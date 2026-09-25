#!/usr/bin/env python3
"""Regenerates MANIFEST.sha256 for phantom-workstation."""

import hashlib
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

IGNORED_DIRS = {
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    "build",
    "dist",
}

IGNORED_FILES = {
    "MANIFEST.sha256",
    ".DS_Store",
}


def get_files():
    # If in a git worktree, use git ls-files to guarantee exact tracking
    try:
        res = subprocess.run(
            ["git", "-C", str(ROOT), "ls-files"],
            capture_output=True,
            text=True,
            check=True,
        )
        tracked = [line.strip() for line in res.stdout.splitlines() if line.strip()]
        file_paths = []
        for rel in tracked:
            p = ROOT / rel
            if p.is_file() and rel not in IGNORED_FILES:
                file_paths.append(rel)
        # Also include uncommitted new files like NOTICE.md, tools/regenerate_manifest.py if not yet tracked
        for root, dirs, files in os.walk(ROOT):
            dirs[:] = [d for d in dirs if d not in IGNORED_DIRS and not d.endswith(".egg-info")]
            for f in files:
                if f in IGNORED_FILES:
                    continue
                p = Path(root) / f
                rel = p.relative_to(ROOT).as_posix()
                if rel not in file_paths:
                    file_paths.append(rel)
        return sorted(file_paths)
    except Exception:
        # Fallback to filesystem walk
        file_paths = []
        for root, dirs, files in os.walk(ROOT):
            dirs[:] = [d for d in dirs if d not in IGNORED_DIRS and not d.endswith(".egg-info")]
            for f in files:
                if f in IGNORED_FILES:
                    continue
                p = Path(root) / f
                rel = p.relative_to(ROOT).as_posix()
                file_paths.append(rel)
        return sorted(file_paths)


def main():
    files = get_files()
    lines = []
    for rel in files:
        p = ROOT / rel
        if not p.is_file():
            continue
        digest = hashlib.sha256(p.read_bytes()).hexdigest()
        lines.append(f"{digest}  {rel}\n")

    lines.sort(key=lambda x: x.split("  ")[1])
    manifest_path = ROOT / "MANIFEST.sha256"
    manifest_path.write_text("".join(lines), encoding="utf-8")
    print(f"Wrote {len(lines)} file hashes to {manifest_path}")


if __name__ == "__main__":
    main()
