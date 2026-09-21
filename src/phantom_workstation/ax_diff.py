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


def extract_node_state(node: Dict[str, Any]) -> Dict[str, Any]:
    """Extracts a canonical dictionary of comparable Accessibility state properties."""
    state: Dict[str, Any] = {}
    for k in STATE_KEYS:
        if k in node:
            val = node[k]
            if isinstance(val, (str, int, float, bool)) or val is None:
                state[k] = val
            elif isinstance(val, dict):
                state[k] = {str(dk): str(dv) for dk, dv in sorted(val.items())}
            elif isinstance(val, list):
                state[k] = [str(item) for item in val]
            else:
                state[k] = str(val)
    return state


def compute_node_hash(node: Dict[str, Any]) -> str:
    """Computes a deterministic, collision-resistant hash for an Accessibility node's state."""
    state = extract_node_state(node)
    serialized = json.dumps(state, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16]


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
                v_prev = prev_state.get(k)
                v_curr = curr_state.get(k)
                if v_prev != v_curr:
                    changes[k] = {"old": v_prev, "new": v_curr}

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
