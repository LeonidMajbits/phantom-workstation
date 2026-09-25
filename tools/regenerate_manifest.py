#!/usr/bin/env python3
"""Regenerates MANIFEST.sha256 for phantom-workstation.

Enforces strict exclusion of runtime, build, and private artifacts.
"""

from __future__ import annotations

import hashlib
import fnmatch
import os
import subprocess
import sys
from pathlib import Path
from typing import List, Set

ROOT = Path(__file__).resolve().parents[1]

EXCLUDED_EXACT_NAMES = {
    "MANIFEST.sha256",
    ".DS_Store",
    "Thumbs.db",
}

EXCLUDED_DIR_PATTERNS = {
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    "build",
    "dist",
    "runs",
    "runtime",
    "*.egg-info",
    ".eggs",
    ".venv",
    "venv",
}

EXCLUDED_FILE_PATTERNS = {
    ".env*",
    "credentials*.json",
    "token*.json",
    "*.pem",
    "*.key",
    "*.pfx",
    "*.pyc",
    "*.pyo",
    "*.pyd",
    "*.so",
    "*.dylib",
    "display_state.json",
    "capture_*.png",
}


def _is_excluded(rel_path: str) -> bool:
    parts = Path(rel_path).parts
    filename = parts[-1]

    if filename in EXCLUDED_EXACT_NAMES:
        return True

    for pattern in EXCLUDED_FILE_PATTERNS:
        if fnmatch.fnmatch(filename, pattern):
            return True

    for part in parts[:-1]:
        for dir_pat in EXCLUDED_DIR_PATTERNS:
            if fnmatch.fnmatch(part, dir_pat):
                return True

    return False


def get_release_files() -> List[str]:
    files: Set[str] = set()

    # 1. Primary: Use Git ls-files with null delimiters to respect tracked inventory and .gitignore
    git_dir = ROOT / ".git"
    if git_dir.exists():
        try:
            # Tracked files only (untracked files must not be accidentally enrolled)
            tracked_res = subprocess.run(
                ["git", "-C", str(ROOT), "ls-files", "-z"],
                capture_output=True,
                check=True,
            )
            for raw in tracked_res.stdout.split(b"\x00"):
                if not raw:
                    continue
                rel = raw.decode("utf-8", errors="replace")
                if not _is_excluded(rel):
                    files.add(rel)

            return sorted(files)
        except Exception as e:
            print(f"Warning: Git command failed ({e}), falling back to filesystem scan.", file=sys.stderr)

    # 2. Fallback: Filesystem scan strictly enforcing exclusions
    for root, dirs, filenames in os.walk(ROOT):
        # Prune excluded directories in-place
        dirs[:] = [
            d for d in dirs
            if not any(fnmatch.fnmatch(d, p) for p in EXCLUDED_DIR_PATTERNS)
        ]
        for f in filenames:
            p = Path(root) / f
            rel = p.relative_to(ROOT).as_posix()
            if not _is_excluded(rel):
                files.add(rel)

    return sorted(files)


def main() -> int:
    files = get_release_files()
    lines = []
    for rel in files:
        p = ROOT / rel
        if not p.is_file():
            continue
        # Verify file does not escape ROOT
        try:
            p.resolve().relative_to(ROOT.resolve())
        except ValueError:
            print(f"Error: Path {rel} escapes package root!", file=sys.stderr)
            return 1
        digest = hashlib.sha256(p.read_bytes()).hexdigest()
        lines.append(f"{digest}  {rel}\n")

    lines.sort(key=lambda x: x.split("  ")[1])
    manifest_path = ROOT / "MANIFEST.sha256"
    manifest_path.write_text("".join(lines), encoding="utf-8")
    print(f"Wrote {len(lines)} file hashes to {manifest_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
