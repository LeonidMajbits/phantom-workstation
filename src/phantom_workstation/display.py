"""Virtual Display Manager for macOS via CoreGraphics CGVirtualDisplay."""

from __future__ import annotations

import contextlib
import ctypes
import datetime
import fcntl
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

    # Invalidate cached binary if source file is newer
    if BIN_PATH.exists() and os.access(BIN_PATH, os.X_OK):
        try:
            if BIN_PATH.stat().st_mtime >= source_path.stat().st_mtime:
                return True
        except Exception:
            pass

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
    res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if res.returncode != 0 and res.stderr:
        print(f"[ERROR] Failed to compile phantom_display: {res.stderr.strip()}", file=sys.stderr)
    return res.returncode == 0


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

        # Guard against PID reuse: ensure command name contains phantom_display
        if "phantom_display" not in comm:
            return False

        return True
    except Exception:
        return False


def resolve_display_ordinal(display_id: int) -> Optional[int]:
    """Resolves the 1-based display ordinal required by screencapture -D from a CGDirectDisplayID."""
    try:
        cg = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
        count = ctypes.c_uint32(0)
        cg.CGGetActiveDisplayList(0, None, ctypes.byref(count))
        if count.value == 0:
            return None
        display_ids = (ctypes.c_uint32 * count.value)()
        cg.CGGetActiveDisplayList(count.value, display_ids, ctypes.byref(count))
        for idx, did in enumerate(display_ids, 1):
            if did == display_id:
                return idx
    except Exception:
        pass
    return None


def get_display_status() -> Dict[str, Any]:
    """Retrieves current virtual display runtime status."""
    if not STATE_PATH.exists():
        return {"active": False, "status": "offline"}

    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        pid = data.get("pid")
        if pid:
            if is_pid_alive(int(pid)):
                data["active"] = True
                data["status"] = "online"
                return data
            else:
                STATE_PATH.unlink(missing_ok=True)
                return {"active": False, "status": "stale_cleaned"}
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

    # Resolve 1-based display ordinal for screencapture -D
    display_ordinal = st.get("display_index")
    if not display_ordinal:
        display_ordinal = resolve_display_ordinal(int(did))

    if not display_ordinal:
        display_ordinal = 1

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
