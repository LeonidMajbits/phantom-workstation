#!/usr/bin/env python3
"""Strict Hygiene and Integrity Check for Phantom Workstation Standalone Package.

Enforces:
1. Zero Emojis: Fails if any Unicode emoji / pictograph character exists.
2. Zero Private Paths & Emails: Fails if any local machine path, user, host, or personal email is found.
3. Zero Brand Mentions: Strictly prohibits internal or unapproved corporate brands.
4. Zero Secrets: Fails if any credential file or embedded secret pattern is detected.
5. Manifest Integrity: Verifies 100% hash matching and exact set equality with MANIFEST.sha256.
6. Test Verification: Executes test suite and confirms 100% pass rate.
"""

from __future__ import annotations

import getpass
import hashlib
import fnmatch
import os
import pathlib
import platform
import re
import subprocess
import sys
from typing import Dict, List, Set, Tuple

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

STATIC_PRIVACY_PATTERNS = [
    (re.compile(r"/Users/[a-zA-Z0-9._-]+/"), "Local Mac user home path"),
    (re.compile(r"\b[A-Za-z0-9._%+-]+@(?:gmail|yahoo|hotmail|outlook|icloud)\.com\b", re.IGNORECASE), "Personal email address"),
    (re.compile(r"\bfree[\s_-]*life[\s_-]*ai\b", re.IGNORECASE), "Prohibited brand mention"),
    (re.compile(r"\bfreelife\b", re.IGNORECASE), "Prohibited brand mention"),
]

SECRET_CONTENT_PATTERNS = [
    (re.compile(r"-----BEGIN (?:[A-Z0-9_-]+ )?PRIVATE KEY-----"), "Private Key Header"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "AWS Access Key"),
    (re.compile(r"\bghp_[0-9a-zA-Z]{36}\b"), "GitHub Personal Access Token"),
    (re.compile(r"\bsk-[a-zA-Z0-9]{32,}\b"), "API Secret Key"),
]

IGNORED_DIR_NAMES = {
    ".git",
    ".venv",
    "venv",
    "env",
    "test_env",
    "build",
    "dist",
    "__pycache__",
    ".eggs",
    ".pytest_cache",
    ".mypy_cache",
    "runs",
    "runtime",
}

SCANNABLE_EXTS = {
    ".py", ".m", ".md", ".toml", ".json", ".yaml", ".yml", ".sh", ".txt", ".gitignore",
    ".csv", ".tsv", ".rst", ".ini", ".cfg"
}


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
    dynamic_regex = re.compile("|".join(DYNAMIC_PRIVATE_PATTERNS), re.IGNORECASE)
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
                        # Dynamic pattern check
                        match = dynamic_regex.search(line)
                        if match:
                            violations.append((str(rel_path), idx, line.strip(), f"Dynamic pattern: {match.group(0)}"))
                            continue
                        # Static privacy / brand / email check
                        for pat, desc in STATIC_PRIVACY_PATTERNS:
                            m = pat.search(line)
                            if m:
                                violations.append((str(rel_path), idx, line.strip(), f"{desc} ({m.group(0)})"))
                                break
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


def check_manifest() -> Tuple[bool, List[str]]:
    manifest_path = PKG_ROOT / "MANIFEST.sha256"
    if not manifest_path.exists():
        return False, ["MANIFEST.sha256 does not exist"]

    errors = []
    manifested: Dict[str, str] = {}
    for line_no, raw_line in enumerate(manifest_path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("  ", 1)
        if len(parts) != 2:
            errors.append(f"Invalid format in MANIFEST.sha256 line {line_no}: {line}")
            continue
        expected_hash, rel = parts[0], parts[1]
        manifested[rel] = expected_hash
        p = PKG_ROOT / rel
        if not p.is_file():
            errors.append(f"Manifested file missing on disk: {rel}")
            continue
        actual_hash = hashlib.sha256(p.read_bytes()).hexdigest()
        if actual_hash != expected_hash:
            errors.append(f"Digest mismatch for {rel}: expected {expected_hash}, got {actual_hash}")

    # Check unmanifested release files using regenerate_manifest's file discovery
    try:
        sys.path.insert(0, str(PKG_ROOT / "tools"))
        import regenerate_manifest
        release_files = set(regenerate_manifest.get_release_files())
        manifested_files = set(manifested.keys())
        unmanifested = release_files - manifested_files
        extra_manifested = manifested_files - release_files
        for u in sorted(unmanifested):
            errors.append(f"Unmanifested release file: {u}")
        for e in sorted(extra_manifested):
            errors.append(f"Manifest references non-release file: {e}")
    except Exception as exc:
        errors.append(f"Could not verify release inventory: {exc}")

    return (len(errors) == 0), errors


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
    print("[CHECK 1/5] Scanning for emojis and non-standard pictographs...")
    emoji_hits = check_emojis()
    if emoji_hits:
        print("[FAIL] Emoji characters detected:")
        for path, line_no, content in emoji_hits:
            print(f"  - {path}:{line_no} -> {content}")
        failed = True
    else:
        print("[PASS] Zero emojis found across all package files.")

    # 2. Private Path & Identity Audit
    print("\n[CHECK 2/5] Scanning for private paths, personal emails, and brand mentions...")
    path_hits = check_private_paths()
    if path_hits:
        print("[FAIL] Private path or identity traces detected:")
        for path, line_no, content, matched in path_hits:
            print(f"  - {path}:{line_no} (matched: '{matched}') -> {content}")
        failed = True
    else:
        print("[PASS] Zero private paths, emails, or prohibited brands found.")

    # 3. Secret & Credential Audit
    print("\n[CHECK 3/5] Scanning for secret files, keys, and embedded credentials...")
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

    # 4. Manifest Integrity Audit
    print("\n[CHECK 4/5] Verifying MANIFEST.sha256 digest integrity and set equality...")
    manifest_ok, manifest_errs = check_manifest()
    if not manifest_ok:
        print("[FAIL] Manifest verification errors:")
        for err in manifest_errs:
            print(f"  - {err}")
        failed = True
    else:
        print("[PASS] MANIFEST.sha256 verified 100% matched against on-disk files.")

    # 5. Unit Test Verification
    print("\n[CHECK 5/5] Running package unit test suite...")
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

    print("[RESULT] HYGIENE CHECK PASSED: Codebase passes style, privacy, secret, manifest, and test checks.")
    print("=" * 70 + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
