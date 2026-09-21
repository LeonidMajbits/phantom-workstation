"""CLI Entrypoint for Phantom Workstation."""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

from .display import (
    capture_display,
    get_display_status,
    start_display,
    stop_display,
    teleport_window,
)
from .workstation import PhantomWorkstation


def cmd_status(_: argparse.Namespace) -> int:
    st = get_display_status()
    print("\nVirtual Display Status")
    print("---------------------------------")
    print(f"Active      : {st.get('active', False)}")
    print(f"Status      : {st.get('status', 'offline')}")
    if st.get("active"):
        print(f"Display ID  : {st.get('display_id')}")
        print(f"Ordinal     : {st.get('display_index', 'auto')}")
        print(f"Resolution  : {st.get('width')}x{st.get('height')}")
        print(f"Coordinates : ({st.get('origin_x')}, {st.get('origin_y')})")
        print(f"Daemon PID  : {st.get('pid')}")
    print("---------------------------------\n")
    return 0


def cmd_start(args: argparse.Namespace) -> int:
    res = start_display(args.width, args.height)
    if res.get("ok"):
        print(f"[OK] Virtual display online ({args.width}x{args.height})")
        return 0
    print(f"[ERROR] Failed to start display: {res.get('error')}", file=sys.stderr)
    return 1


def cmd_stop(_: argparse.Namespace) -> int:
    res = stop_display()
    if res.get("ok"):
        print("[OK] Virtual display terminated")
        return 0
    print(f"[ERROR] Failed to stop display: {res.get('error')}", file=sys.stderr)
    return 1


def cmd_capture(args: argparse.Namespace) -> int:
    out = pathlib.Path(args.output) if args.output else None
    res = capture_display(out)
    if res.get("ok"):
        print(f"[OK] Screen captured to: {res.get('path')} ({res.get('size_bytes')} bytes)")
        return 0
    print(f"[ERROR] Capture failed: {res.get('error')}", file=sys.stderr)
    return 1


def cmd_teleport(args: argparse.Namespace) -> int:
    res = teleport_window(args.app)
    if res.get("ok"):
        coords = res.get("coordinates", [])
        print(f"[OK] Window '{args.app}' teleported to virtual display coordinates: {coords}")
        return 0
    print(f"[ERROR] Teleport failed: {res.get('error')}", file=sys.stderr)
    return 1


def cmd_run(args: argparse.Namespace) -> int:
    station = PhantomWorkstation(
        objective=args.objective,
        max_steps=args.steps,
        dry_run=args.dry_run,
    )
    res = station.run_loop()
    return 0 if res.get("ok") else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="phantom-workstation",
        description="Phantom Workstation: Experimental macOS Virtual-Display Utilities & AX Tree Delta Compressor",
    )
    subparsers = parser.add_subparsers(dest="command")
    parser.set_defaults(func=cmd_status)

    subparsers.add_parser("status", help="Check virtual display status").set_defaults(func=cmd_status)

    start_p = subparsers.add_parser("start", help="Start virtual display daemon")
    start_p.add_argument("--width", type=int, default=1920, help="Display width")
    start_p.add_argument("--height", type=int, default=1080, help="Display height")
    start_p.set_defaults(func=cmd_start)

    subparsers.add_parser("stop", help="Stop virtual display daemon").set_defaults(func=cmd_stop)

    cap_p = subparsers.add_parser("capture", help="Capture screenshot of virtual display")
    cap_p.add_argument("-o", "--output", help="Output PNG path")
    cap_p.set_defaults(func=cmd_capture)

    tele_p = subparsers.add_parser("teleport", help="Teleport an application window to the virtual display")
    tele_p.add_argument("app", help="Application name, e.g. 'Google Chrome' or 'Calculator'")
    tele_p.set_defaults(func=cmd_teleport)

    run_p = subparsers.add_parser("run", help="Run demonstration benchmark loop on virtual display")
    run_p.add_argument("objective", help="Mission objective description")
    run_p.add_argument("--steps", type=int, default=3, help="Max execution steps")
    run_p.add_argument("--dry-run", action="store_true", help="Simulate actuation without live actions")
    run_p.set_defaults(func=cmd_run)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
