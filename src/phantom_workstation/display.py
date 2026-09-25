"""Virtual Display Manager for macOS via CoreGraphics CGVirtualDisplay."""

from __future__ import annotations

import contextlib
import ctypes
import datetime
import fcntl
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import time
from typing import Any, Dict, Optional

CACHE_DIR = pathlib.Path.home() / ".cache" / "phantom_workstation"
BIN_PATH = CACHE_DIR / "bin" / "phantom_display"
STATE_PATH = CACHE_DIR / "display_state.json"
LOCK_PATH = CACHE_DIR / "display.lock"


@contextlib.contextmanager
def display_lock(timeout: float = 5.0):
    """Acquires an exclusive advisory file lock for virtual display lifecycle mutations."""
    ensure_paths()
    with open(LOCK_PATH, "a+", encoding="utf-8") as f:
        start_time = time.time()
        while True:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except (BlockingIOError, OSError):
                if time.time() - start_time > timeout:
                    raise TimeoutError(f"Could not acquire virtual display lock within {timeout}s")
                time.sleep(0.05)
        try:
            yield
        finally:
            try:
                fcntl.flock(f, fcntl.LOCK_UN)
            except Exception:
                pass


def get_source_path() -> Optional[pathlib.Path]:
    """Resolves phantom_display.m from bundled package data or repository root."""
    # 1. Check inside installed package directory (src/phantom_workstation/c_src)
    pkg_src = pathlib.Path(__file__).resolve().parent / "c_src" / "phantom_display.m"
    if pkg_src.exists():
        return pkg_src

    # 2. Check repository root (c_src/phantom_display.m)
    repo_src = pathlib.Path(__file__).resolve().parent.parent.parent / "c_src" / "phantom_display.m"
    if repo_src.exists():
        return repo_src

    return None


def ensure_paths() -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    BIN_PATH.parent.mkdir(parents=True, exist_ok=True)


def ensure_compiled() -> bool:
    """Compiles the Objective-C CGVirtualDisplay daemon if missing or if source was updated."""
    source_path = get_source_path()
    if not source_path or not source_path.exists():
        return False

    hash_path = BIN_PATH.with_suffix(".sha256")
    try:
        source_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()
    except Exception:
        source_hash = ""

    # Invalidate cached binary if missing, unexecutable, or source hash does not match
    if BIN_PATH.exists() and os.access(BIN_PATH, os.X_OK) and hash_path.exists():
        try:
            cached_hash = hash_path.read_text(encoding="utf-8").strip()
            if cached_hash and cached_hash == source_hash:
                return True
        except Exception:
            pass

    # Check if clang is available before attempting compilation
    if not shutil.which("clang"):
        print(
            "[ERROR] clang was not found. Install Xcode Command Line Tools with: xcode-select --install",
            file=sys.stderr,
        )
        return False

    ensure_paths()
    cmd = [
        "clang",
        "-fobjc-arc",
        "-fmodules",
        "-O2",
        "-framework", "Foundation",
        "-framework", "CoreGraphics",
        "-framework", "AppKit",
        str(source_path),
        "-o", str(BIN_PATH),
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if res.returncode != 0 and res.stderr:
            print(f"[ERROR] Failed to compile phantom_display: {res.stderr.strip()}", file=sys.stderr)
        if res.returncode == 0:
            try:
                BIN_PATH.chmod(0o755)
                if source_hash:
                    hash_path.write_text(source_hash, encoding="utf-8")
            except Exception:
                pass
            return True
        return False
    except FileNotFoundError:
        print(
            "[ERROR] clang was not found. Install Xcode Command Line Tools with: xcode-select --install",
            file=sys.stderr,
        )
        return False


def is_pid_alive(pid: int) -> bool:
    """Checks whether a process is genuinely alive, filtering out zombies and PID reuse."""
    try:
        res = subprocess.run(
            ["ps", "-o", "stat=,comm=", "-p", str(pid)],
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode != 0 or not res.stdout.strip():
            return False
        parts = res.stdout.strip().split(None, 1)
        stat = parts[0]
        comm = parts[1] if len(parts) > 1 else ""

        # Zombie processes (Z) are dead and awaiting reap
        if "Z" in stat:
            return False

        # Guard against PID reuse: ensure command basename matches phantom_display exactly
        comm_base = pathlib.Path(comm.strip()).name
        if comm_base != "phantom_display":
            return False

        return True
    except Exception:
        return False


def resolve_display_ordinal(display_id: int) -> Optional[int]:
    """Resolves the 1-based display ordinal required by screencapture -D from a CGDirectDisplayID."""
    try:
        cg = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
        count = ctypes.c_uint32(0)
        err1 = cg.CGGetActiveDisplayList(0, None, ctypes.byref(count))
        if err1 != 0 or count.value == 0:
            return None
        max_displays = count.value
        display_ids = (ctypes.c_uint32 * max_displays)()
        active_count = ctypes.c_uint32(0)
        err2 = cg.CGGetActiveDisplayList(max_displays, display_ids, ctypes.byref(active_count))
        if err2 != 0:
            return None
        valid_count = min(active_count.value, max_displays)
        for idx in range(valid_count):
            if display_ids[idx] == display_id:
                return idx + 1
    except Exception:
        pass
    return None


def get_display_status() -> Dict[str, Any]:
    """Retrieves current virtual display runtime status non-destructively."""
    if not STATE_PATH.exists():
        return {"active": False, "status": "offline"}

    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        pid = data.get("pid")
        if pid and is_pid_alive(int(pid)):
            data["active"] = True
            data["status"] = "online"
            return data
        else:
            return {"active": False, "status": "offline"}
    except Exception:
        pass
    return {"active": False, "status": "offline"}


def start_display(width: int = 1920, height: int = 1080) -> Dict[str, Any]:
    """Starts the virtual display daemon in the background with concurrency locking."""
    ensure_paths()
    with display_lock():
        status = get_display_status()
        if status.get("active"):
            return {"ok": True, "already_running": True, "details": status}

        # Stale state is safely unlinked under lifecycle lock before starting new daemon
        STATE_PATH.unlink(missing_ok=True)

        if not ensure_compiled():
            return {"ok": False, "error": "Failed to compile phantom_display binary"}

        env = os.environ.copy()
        env["PHANTOM_STATE_PATH"] = str(STATE_PATH)

        proc = subprocess.Popen(
            [str(BIN_PATH), "daemon", str(width), str(height)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
            start_new_session=True,
        )

        for _ in range(30):
            time.sleep(0.1)
            st = get_display_status()
            if st.get("active"):
                return {"ok": True, "details": st}

        # Timed out waiting for display initialization: reap child process cleanly
        try:
            proc.terminate()
            proc.wait(timeout=2.0)
        except Exception:
            try:
                proc.kill()
                proc.wait(timeout=1.0)
            except Exception:
                pass

        return {"ok": False, "error": "Timed out waiting for virtual display to initialize"}


def stop_display() -> Dict[str, Any]:
    """Terminates the virtual display daemon with concurrency locking."""
    with display_lock():
        status = get_display_status()
        if not status.get("active"):
            STATE_PATH.unlink(missing_ok=True)
            return {"ok": True, "already_stopped": True}

        pid = status.get("pid")
        if pid:
            try:
                os.kill(pid, 15)  # SIGTERM
                for _ in range(20):
                    time.sleep(0.1)
                    st = get_display_status()
                    if not st.get("active"):
                        break
                else:
                    # Force kill if process failed to terminate after 2 seconds
                    try:
                        os.kill(pid, 9)  # SIGKILL
                        time.sleep(0.2)
                    except ProcessLookupError:
                        pass
            except ProcessLookupError:
                pass

        STATE_PATH.unlink(missing_ok=True)
        return {"ok": True, "stopped_pid": pid}


def capture_display(output_path: Optional[pathlib.Path] = None) -> Dict[str, Any]:
    """Captures a screenshot of the virtual display space using screencapture."""
    st = get_display_status()
    if not st.get("active"):
        return {"ok": False, "error": "Virtual display is offline"}

    did = st.get("display_id")
    if not did:
        return {"ok": False, "error": "No display ID found"}

    # Always dynamically resolve the live 1-based display ordinal for screencapture -D.
    # Never trust a stale cached display_index or fall back to primary display 1.
    display_ordinal = resolve_display_ordinal(int(did))

    # Fail closed: never silently capture primary monitor if virtual display ordinal cannot be resolved
    if not display_ordinal or display_ordinal <= 0:
        return {
            "ok": False,
            "error": f"Could not resolve 1-based display ordinal for CG display ID {did}",
            "display_id": did,
        }

    if output_path is None:
        ensure_paths()
        ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
        output_path = CACHE_DIR / f"capture_{ts}.png"

    output_path.parent.mkdir(parents=True, exist_ok=True)

    screencap_bin = shutil.which("screencapture") or "/usr/sbin/screencapture"
    cmd = [screencap_bin, "-x", "-D", str(display_ordinal), str(output_path)]
    res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if res.returncode != 0:
        return {"ok": False, "error": f"screencapture failed: {res.stderr.strip()}"}

    if not output_path.exists() or output_path.stat().st_size == 0:
        return {"ok": False, "error": f"screencapture produced an empty or missing file at {output_path}"}

    return {
        "ok": True,
        "path": str(output_path),
        "size_bytes": output_path.stat().st_size,
        "display_id": did,
        "display_ordinal": display_ordinal,
    }


def teleport_window(app_name: str, window_index: int = 1) -> Dict[str, Any]:
    """Teleports a macOS window to the virtual display coordinates via AppleScript.

    Uses positional CLI parameters via 'on run argv' to prevent interpreter injection.
    """
    st = get_display_status()
    if not st.get("active"):
        return {"ok": False, "error": "Virtual display is offline"}

    ox = int(st.get("origin_x", 1728)) + 50
    oy = int(st.get("origin_y", 0)) + 50

    script = """on run argv
    set targetApp to item 1 of argv
    set winIndex to (item 2 of argv) as integer
    set posX to (item 3 of argv) as integer
    set posY to (item 4 of argv) as integer
    tell application "System Events"
        if exists process targetApp then
            tell process targetApp
                if (count of windows) >= winIndex then
                    set position of window winIndex to {posX, posY}
                    return "OK"
                else
                    return "NO_WINDOW"
                end if
            end tell
        else
            return "NO_PROCESS"
        end if
    end tell
end run
"""
    cmd = ["osascript", "-", str(app_name), str(window_index), str(ox), str(oy)]
    res = subprocess.run(cmd, input=script, capture_output=True, text=True, check=False)
    out = res.stdout.strip()
    if out == "OK":
        return {"ok": True, "app": app_name, "coordinates": [ox, oy]}
    return {"ok": False, "error": f"Teleport failed: {out or res.stderr.strip()}"}
