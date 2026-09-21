#!/usr/bin/env python3
"""Strict Hygiene and Integrity Check for Phantom Workstation Standalone Package.

Enforces:
1. Zero Emojis: Fails if any Unicode emoji / pictograph character exists.
2. Zero Private Paths: Fails if any local username, machine name, or private path is found.
3. Zero Secrets: Fails if any credential file or embedded secret pattern is detected.
4. Test Verification: Executes test suite and confirms 100% pass rate.
"""

from __future__ import annotations

import getpass
import os
import pathlib
import platform
import re
import subprocess
import sys
from typing import List, Tuple

PKG_ROOT = pathlib.Path(__file__).resolve().parent.parent

# Emoji detection regex range covering standard Unicode emoji and symbols
EMOJI_PATTERN = re.compile(
    r"[\U0001F300-\U0001FAFF"  # Symbols, pictographs, transport, supplemental
    r"\U00002600-\U000027BF"  # Misc symbols and dingbats
    r"\U0001F1E6-\U0001F1FF"  # Flags
    r"]",
    re.UNICODE,
)

CURRENT_USER = getpass.getuser()
CURRENT_HOST = platform.node()
USER_HOME = str(pathlib.Path.home())

CI_SYSTEM_USERS = {"runner", "root", "ubuntu", "builder", "circleci", "gitlab-runner", "user", "admin"}

DYNAMIC_PRIVATE_PATTERNS = [
    r"CloudStorage",
    r"GoogleDrive",
]

if CURRENT_USER.lower() not in CI_SYSTEM_USERS and len(CURRENT_USER) > 2:
    DYNAMIC_PRIVATE_PATTERNS.append(rf"\b{re.escape(CURRENT_USER)}\b")

if USER_HOME and not any(h in USER_HOME for h in ["/runner", "/root", "/home/ubuntu"]):
    DYNAMIC_PRIVATE_PATTERNS.append(re.escape(USER_HOME))

if CURRENT_HOST and not any(h in CURRENT_HOST.lower() for h in ["github", "runner", "hosted", "fv-az"]):
    DYNAMIC_PRIVATE_PATTERNS.append(re.escape(CURRENT_HOST))

SECRET_CONTENT_PATTERNS = [
    (re.compile(r"-----BEGIN (?:[A-Z0-9_-]+ )?PRIVATE KEY-----"), "Private Key Header"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "AWS Access Key"),
    (re.compile(r"\bghp_[0-9a-zA-Z]{36}\b"), "GitHub Personal Access Token"),
    (re.compile(r"\bsk-[a-zA-Z0-9]{32,}\b"), "API Secret Key"),
]

IGNORED_DIR_NAMES = {".git", ".venv", "venv", "env", "test_env", "build", "dist", "__pycache__", ".eggs", ".pytest_cache"}
SCANNABLE_EXTS = {".py", ".m", ".md", ".toml", ".json", ".yaml", ".yml", ".sh", ".txt", ".gitignore"}


def should_ignore_dir(d: str) -> bool:
    if d in IGNORED_DIR_NAMES:
        return True
    if d.endswith(".egg-info") or d.startswith(".venv") or d.startswith("venv_") or d.startswith("test_env"):
        return True
    return False


def check_emojis() -> List[Tuple[str, int, str]]:
    violations = []
    for root, dirs, files in os.walk(PKG_ROOT):
        dirs[:] = [d for d in dirs if not should_ignore_dir(d)]
        for f in files:
            if any(f.endswith(ext) for ext in SCANNABLE_EXTS):
                file_path = pathlib.Path(root) / f
                rel_path = file_path.relative_to(PKG_ROOT)
                if f == "audit_package.py":
                    continue
                try:
                    lines = file_path.read_text(encoding="utf-8").splitlines()
                    for idx, line in enumerate(lines, 1):
                        match = EMOJI_PATTERN.search(line)
                        if match:
                            violations.append((str(rel_path), idx, line.strip()))
                except Exception:
                    pass
    return violations


def check_private_paths() -> List[Tuple[str, int, str, str]]:
    violations = []
    combined_regex = re.compile("|".join(DYNAMIC_PRIVATE_PATTERNS), re.IGNORECASE)
    for root, dirs, files in os.walk(PKG_ROOT):
        dirs[:] = [d for d in dirs if not should_ignore_dir(d)]
        for f in files:
            if any(f.endswith(ext) for ext in SCANNABLE_EXTS):
                file_path = pathlib.Path(root) / f
                rel_path = file_path.relative_to(PKG_ROOT)
                if f == "audit_package.py":
                    continue
                try:
                    lines = file_path.read_text(encoding="utf-8").splitlines()
                    for idx, line in enumerate(lines, 1):
                        match = combined_regex.search(line)
                        if match:
                            violations.append((str(rel_path), idx, line.strip(), match.group(0)))
                except Exception:
                    pass
    return violations


def check_secrets() -> Tuple[List[str], List[Tuple[str, int, str]]]:
    secret_files = []
    content_matches = []
    for root, dirs, files in os.walk(PKG_ROOT):
        dirs[:] = [d for d in dirs if not should_ignore_dir(d)]
        for f in files:
            file_path = pathlib.Path(root) / f
            rel_path = str(file_path.relative_to(PKG_ROOT))

            # 1. Secret filename check
            if f.startswith(".env") or f.endswith((".key", ".pem", ".pfx")):
                secret_files.append(rel_path)

            # 2. Secret file content check
            if f == "audit_package.py":
                continue
            if any(f.endswith(ext) for ext in SCANNABLE_EXTS):
                try:
                    lines = file_path.read_text(encoding="utf-8").splitlines()
                    for idx, line in enumerate(lines, 1):
                        for pat, desc in SECRET_CONTENT_PATTERNS:
                            if pat.search(line):
                                content_matches.append((rel_path, idx, desc))
                except Exception:
                    pass

    return secret_files, content_matches


def run_unit_tests() -> bool:
    env = os.environ.copy()
    src_dir = str(PKG_ROOT / "src")
    existing_pp = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{src_dir}:{existing_pp}" if existing_pp else src_dir
    cmd = [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", "."]
    res = subprocess.run(cmd, cwd=str(PKG_ROOT), env=env, capture_output=True, text=True, check=False)
    print(res.stdout)
    if res.stderr:
        print(res.stderr, file=sys.stderr)
    return res.returncode == 0


def main() -> int:
    print("=" * 70)
    print("PHANTOM WORKSTATION: PRE-RELEASE HYGIENE & INTEGRITY CHECK")
    print("Package Root: " + str(PKG_ROOT))
    print("=" * 70 + "\n")

    failed = False

    # 1. Emoji Audit
    print("[CHECK 1/4] Scanning for emojis and non-standard pictographs...")
    emoji_hits = check_emojis()
    if emoji_hits:
        print("[FAIL] Emoji characters detected:")
        for path, line_no, content in emoji_hits:
            print(f"  - {path}:{line_no} -> {content}")
        failed = True
    else:
        print("[PASS] Zero emojis found across all package files.")

    # 2. Private Path & Identity Audit
    print("\n[CHECK 2/4] Scanning for private paths, usernames, and hostnames...")
    path_hits = check_private_paths()
    if path_hits:
        print("[FAIL] Private path or identity traces detected:")
        for path, line_no, content, matched in path_hits:
            print(f"  - {path}:{line_no} (matched: '{matched}') -> {content}")
        failed = True
    else:
        print("[PASS] Zero private paths or usernames found.")

    # 3. Secret & Credential Audit
    print("\n[CHECK 3/4] Scanning for secret files, keys, and embedded credentials...")
    secret_files, content_matches = check_secrets()
    if secret_files or content_matches:
        print("[FAIL] Secret files or patterns detected:")
        for sf in secret_files:
            print(f"  - File: {sf}")
        for path, line_no, desc in content_matches:
            print(f"  - Content: {path}:{line_no} matches {desc}")
        failed = True
    else:
        print("[PASS] Zero secret files or credential patterns detected.")

    # 4. Unit Test Verification
    print("\n[CHECK 4/4] Running package unit test suite...")
    test_ok = run_unit_tests()
    if not test_ok:
        print("[FAIL] Unit tests failed.")
        failed = True
    else:
        print("[PASS] All package unit tests passed.")

    print("\n" + "=" * 70)
    if failed:
        print("[RESULT] HYGIENE CHECK FAILED: Fix the issues above before proceeding.")
        print("=" * 70 + "\n")
        return 1

    print("[RESULT] HYGIENE CHECK PASSED: Codebase passes style, privacy, secret, and test checks.")
    print("=" * 70 + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
