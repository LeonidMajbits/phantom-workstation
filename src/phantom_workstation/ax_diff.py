"""Accessibility Tree Diff Engine: Token-Efficient UI Delta Compressor."""

from __future__ import annotations

import hashlib
import json
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple

STATE_KEYS = (
    "role",
    "subrole",
    "name",
    "title",
    "value",
    "enabled",
    "focused",
    "selected",
    "expanded",
    "hidden",
    "checked",
    "frame",
    "help",
)


def _estimate_tokens(obj: Any) -> int:
    """Estimates token count safely using JSON byte-length divided by 4 heuristic."""
    try:
        serialized = json.dumps(obj, separators=(",", ":"))
        return max(1, len(serialized) // 4)
    except Exception:
        return max(1, len(str(obj)) // 4)


def _canonicalize_value(val: Any) -> Any:
    """Recursively canonicalizes nested state structures, preserving types and deterministic key order."""
    if val is None or isinstance(val, (bool, int, float, str)):
        return val
    if isinstance(val, (list, tuple)):
        return [_canonicalize_value(item) for item in val]
    if isinstance(val, dict):
        return {str(k): _canonicalize_value(v) for k, v in sorted(val.items())}
    return str(val)


def extract_node_state(node: Dict[str, Any]) -> Dict[str, Any]:
    """Extracts a canonical dictionary of defined Accessibility state properties."""
    state: Dict[str, Any] = {}
    for k in STATE_KEYS:
        if k in node:
            state[k] = _canonicalize_value(node[k])
    return state


def compute_node_hash(node: Dict[str, Any]) -> str:
    """Computes a deterministic, collision-resistant hash for an Accessibility node's state."""
    state = extract_node_state(node)
    serialized = json.dumps(state, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16]


_MISSING = object()


def _values_differ(v1: Any, v2: Any) -> bool:
    """Checks whether two canonical values differ, taking into account scalar types
    (bool vs int/float, int vs float) and presence (_MISSING vs None).
    """
    if v1 is _MISSING or v2 is _MISSING:
        return v1 is not v2
    if v1 is None or v2 is None:
        return v1 is not v2
    # In Python, bool is a subclass of int (True == 1, False == 0).
    # We must treat bool vs non-bool as different.
    if isinstance(v1, bool) or isinstance(v2, bool):
        if type(v1) is not type(v2):
            return True
        return v1 != v2
    # Distinguish int vs float (e.g., 1 vs 1.0)
    if (isinstance(v1, int) and isinstance(v2, float)) or (isinstance(v1, float) and isinstance(v2, int)):
        return True
    if isinstance(v1, (list, tuple)) and isinstance(v2, (list, tuple)):
        if len(v1) != len(v2):
            return True
        return any(_values_differ(x1, x2) for x1, x2 in zip(v1, v2))
    if isinstance(v1, (list, tuple)) or isinstance(v2, (list, tuple)):
        return True
    if isinstance(v1, dict) and isinstance(v2, dict):
        if set(v1.keys()) != set(v2.keys()):
            return True
        return any(_values_differ(v1[k], v2[k]) for k in v1)
    if isinstance(v1, dict) or isinstance(v2, dict):
        return True
    return v1 != v2


def _escape_path_component(component: str) -> str:
    """Escapes special characters in a path segment, preventing hierarchy and delimiter collisions."""
    # Preserves ':' for standard role:name readability while escaping '/' and '#'
    return urllib.parse.quote(str(component), safe=":")


def flatten_tree(root: Optional[Dict[str, Any]], path: str = "", visited: Optional[set] = None) -> Dict[str, Dict[str, Any]]:
    """Flattens an accessibility hierarchy into a stable, path-indexed dictionary of nodes.

    Uses escaped semantic identifiers (identifier, role:name) rather than volatile array indices
    to ensure that inserting or reordering siblings does not invalidate existing node paths.
    Safe against nulls, malformed children, circular references, and delimiter collisions.
    """
    if not isinstance(root, dict):
        return {}

    if visited is None:
        visited = set()

    role = str(root.get("role", "node"))
    name = str(root.get("name", ""))
    raw_identifier = str(root.get("identifier") or (f"{role}:{name}" if name else role))
    escaped_identifier = _escape_path_component(raw_identifier)
    current_path = f"{path}/{escaped_identifier}" if path else f"/{escaped_identifier}"
    return _flatten_node(root, current_path, visited)


def _flatten_node(node: Dict[str, Any], path: str, visited: set) -> Dict[str, Dict[str, Any]]:
    nodes: Dict[str, Dict[str, Any]] = {}
    node_id = id(node)
    if node_id in visited:
        return nodes
    visited.add(node_id)

    node_copy = dict(node)
    node_copy["_path"] = path
    node_copy["_hash"] = compute_node_hash(node)
    raw_children = node_copy.pop("children", [])
    children = raw_children if isinstance(raw_children, list) else []
    nodes[path] = node_copy

    seen_keys: Dict[str, int] = {}
    for child in children:
        if not isinstance(child, dict):
            continue
        c_role = str(child.get("role", "node"))
        c_name = str(child.get("name", ""))
        c_raw = str(child.get("identifier") or (f"{c_role}:{c_name}" if c_name else c_role))
        c_escaped = _escape_path_component(c_raw)
        seen_keys[c_escaped] = seen_keys.get(c_escaped, 0) + 1
        disambiguated = c_escaped if seen_keys[c_escaped] == 1 else f"{c_escaped}#{seen_keys[c_escaped]}"
        child_path = f"{path}/{disambiguated}"
        nodes.update(_flatten_node(child, child_path, visited))

    return nodes


def compute_ax_diff(prev_tree: Optional[Dict[str, Any]], curr_tree: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Computes the mutation patch between two consecutive accessibility trees.

    Calculates added, removed, and modified nodes with full property-level delta tracking,
    reporting exact token metrics and highlighting expansions when patches exceed raw trees.
    """
    if not isinstance(curr_tree, dict):
        return {
            "mode": "empty_or_invalid",
            "added_count": 0,
            "removed_count": 0,
            "modified_count": 0,
            "unchanged_count": 0,
            "token_reduction_pct": 0.0,
            "raw_tokens_est": 0,
            "patch_tokens_est": 0,
            "exceeded_raw": False,
            "mutations": {"added": [], "removed": [], "modified": []},
        }

    if not isinstance(prev_tree, dict):
        flat_curr = flatten_tree(curr_tree)
        raw_token_est = _estimate_tokens(curr_tree)
        patch = {
            "added": list(flat_curr.values()),
            "removed": [],
            "modified": [],
        }
        patch_token_est = _estimate_tokens(patch)
        reduction = round((1.0 - (patch_token_est / max(1, raw_token_est))) * 100.0, 1)
        return {
            "mode": "full_initial",
            "added_count": len(flat_curr),
            "removed_count": 0,
            "modified_count": 0,
            "unchanged_count": 0,
            "token_reduction_pct": reduction,
            "raw_tokens_est": raw_token_est,
            "patch_tokens_est": patch_token_est,
            "exceeded_raw": patch_token_est > raw_token_est,
            "mutations": patch,
        }

    flat_prev = flatten_tree(prev_tree)
    flat_curr = flatten_tree(curr_tree)

    prev_paths = set(flat_prev.keys())
    curr_paths = set(flat_curr.keys())

    added_paths = curr_paths - prev_paths
    removed_paths = prev_paths - curr_paths
    common_paths = curr_paths & prev_paths

    modified_nodes = []
    unchanged_count = 0

    for p in sorted(common_paths):
        n_prev = flat_prev[p]
        n_curr = flat_curr[p]
        if n_prev["_hash"] != n_curr["_hash"]:
            prev_state = extract_node_state(n_prev)
            curr_state = extract_node_state(n_curr)
            all_keys = set(prev_state.keys()) | set(curr_state.keys())
            changes: Dict[str, Dict[str, Any]] = {}
            for k in sorted(all_keys):
                v_prev = prev_state.get(k, _MISSING)
                v_curr = curr_state.get(k, _MISSING)
                if _values_differ(v_prev, v_curr):
                    change_item: Dict[str, Any] = {
                        "old": None if v_prev is _MISSING else v_prev,
                        "new": None if v_curr is _MISSING else v_curr,
                    }
                    if v_prev is _MISSING:
                        change_item["old_present"] = False
                    if v_curr is _MISSING:
                        change_item["new_present"] = False
                    changes[k] = change_item

            if not changes:
                changes["_state_mutation"] = {
                    "old": n_prev.get("_hash"),
                    "new": n_curr.get("_hash"),
                }

            modified_nodes.append({
                "path": p,
                "role": n_curr.get("role"),
                "name": n_curr.get("name"),
                "changes": changes,
                "old_value": n_prev.get("value"),
                "new_value": n_curr.get("value"),
                "frame": n_curr.get("frame"),
            })
        else:
            unchanged_count += 1

    added_nodes = [flat_curr[p] for p in sorted(added_paths)]
    removed_nodes = [
        {"path": p, "role": flat_prev[p].get("role"), "name": flat_prev[p].get("name")}
        for p in sorted(removed_paths)
    ]

    patch = {
        "added": added_nodes,
        "removed": removed_nodes,
        "modified": modified_nodes,
    }

    raw_token_est = _estimate_tokens(curr_tree)
    patch_token_est = _estimate_tokens(patch)

    reduction = round((1.0 - (patch_token_est / max(1, raw_token_est))) * 100.0, 1)

    return {
        "mode": "delta_patch",
        "added_count": len(added_nodes),
        "removed_count": len(removed_nodes),
        "modified_count": len(modified_nodes),
        "unchanged_count": unchanged_count,
        "token_reduction_pct": reduction,
        "raw_tokens_est": raw_token_est,
        "patch_tokens_est": patch_token_est,
        "exceeded_raw": patch_token_est > raw_token_est,
        "mutations": patch,
    }
