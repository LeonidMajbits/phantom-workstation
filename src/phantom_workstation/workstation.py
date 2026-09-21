"""Synthetic Demonstration and Benchmark Harness for macOS Phantom Workstation.

Simulates observation and actuation steps on the virtual display space
to evaluate AX tree delta compression and verify the headless lifecycle.
"""

from __future__ import annotations

import datetime
import json
import os
import pathlib
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional

from .ax_diff import compute_ax_diff
from .display import capture_display, get_display_status, start_display


class PhantomWorkstation:
    """Demonstration and benchmark runner showcasing virtual display lifecycle and AX diff compression.

    Note: This is an evaluation and demonstration harness using synthetic UI state trees
    to verify compression ratios and virtual display capture without claiming full autonomous agency.
    """

    def __init__(
        self,
        objective: str,
        initial_url: str = "https://example.com",
        max_steps: int = 5,
        dry_run: bool = False,
        headless: bool = False,
        keep_open: bool = True,
        runs_dir: Optional[pathlib.Path] = None,
    ):
        self.objective = objective
        self.initial_url = initial_url
        self.max_steps = max_steps
        self.dry_run = dry_run
        self.headless = headless
        self.keep_open = keep_open

        if runs_dir is None:
            self.runs_dir = pathlib.Path.cwd() / "runs"
        else:
            self.runs_dir = runs_dir

        now = datetime.datetime.now(datetime.timezone.utc)
        random_suffix = os.urandom(4).hex()
        self.run_id = f"demo_{now.strftime('%Y%m%d_%H%M%S_%f')}_{random_suffix}"
        self.run_dir = self.runs_dir / self.run_id
        self.run_dir.mkdir(parents=True, exist_ok=True)

        self.step = 0
        self.prev_tree: Optional[Dict[str, Any]] = None
        self.ticks: List[Dict[str, Any]] = []
        self.total_tokens_full = 0
        self.total_tokens_diff = 0
        self.failed_captures: List[Dict[str, Any]] = []

    def initialize_display(self) -> bool:
        st = get_display_status()
        if not st.get("active"):
            print("[INFO] Virtual display offline. Spawning CGVirtualDisplay (1920x1080)...")
            res = start_display(1920, 1080)
            if not res.get("ok"):
                print(f"[ERROR] Failed to start virtual display: {res.get('error')}", file=sys.stderr)
                return False
            st = get_display_status()

        ox = st.get("origin_x", 1728)
        oy = st.get("origin_y", 0)
        did = st.get("display_id", "Unknown")
        didx = st.get("display_index", "Unknown")
        print(f"[OK] Virtual Display Active [ID: {did}, Ordinal: {didx}] at (x:{ox}, y:{oy}) 1920x1080")
        return True

    def run_loop(self) -> Dict[str, Any]:
        """Runs the demonstration observation and actuation evaluation loop."""
        print("=" * 65)
        print("PHANTOM WORKSTATION: DEMONSTRATION & BENCHMARK HARNESS")
        print(f"Objective   : {self.objective}")
        print(f"Mode        : {'DRY-RUN' if self.dry_run else 'LIVE'}")
        print(f"Run Ledger  : {self.run_dir}")
        print("=" * 65 + "\n")

        if not self.dry_run and not self.initialize_display():
            return {"ok": False, "status": "FAILED", "error": "Display initialization failed"}

        start_time = time.time()

        for s in range(1, self.max_steps + 1):
            self.step = s
            print(f"--- [Step {s}/{self.max_steps}] ---")

            # 1. Capture step
            step_img = self.run_dir / f"step_{s:03d}.png"
            capture_ok = True
            capture_err = None

            if not self.dry_run:
                cap_res = capture_display(step_img)
                if not cap_res.get("ok") or not step_img.exists() or step_img.stat().st_size == 0:
                    capture_ok = False
                    capture_err = cap_res.get("error", "Empty or missing screenshot file")
                    print(f"[WARN] Step {s} capture failed: {capture_err}", file=sys.stderr)
                    self.failed_captures.append({"step": s, "error": capture_err})
                else:
                    print(f"[CAPTURE] Frame saved: {step_img.name} ({step_img.stat().st_size} bytes)")
            else:
                step_img.touch()
                print(f"[DRY-RUN] Simulated screen capture: {step_img.name}")

            # 2. Demonstration AX tree state transition
            sample_curr_tree = {
                "role": "AXApplication",
                "name": "PhantomWorkstationDemo",
                "children": [
                    {
                        "role": "AXWindow",
                        "name": "Evaluation Window",
                        "children": [
                            {"role": "AXButton", "name": "Proceed", "value": f"State_{s}", "enabled": True},
                            {"role": "AXTextField", "name": "Input", "value": f"Value_{s}", "focused": (s % 2 == 1)},
                        ],
                    }
                ],
            }

            diff_result = compute_ax_diff(self.prev_tree, sample_curr_tree)
            raw_tok = diff_result["raw_tokens_est"]
            patch_tok = diff_result["patch_tokens_est"]
            saved_pct = diff_result["token_reduction_pct"]

            self.total_tokens_full += raw_tok
            self.total_tokens_diff += patch_tok

            print(f"[DIFF] Tokens: {raw_tok} -> {patch_tok} ({saved_pct}% reduction)")
            mut = diff_result["mutations"]
            print(f"       Mutations: +{len(mut.get('added', []))} added, ~{len(mut.get('modified', []))} modified, -{len(mut.get('removed', []))} removed")

            # 3. Demonstration Actuation
            action = "INSPECT" if s < self.max_steps else "CONCLUDE"
            print(f"[ACTION] Synthetic Actuation: {action}")

            self.ticks.append({
                "step": s,
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "action": action,
                "capture_ok": capture_ok,
                "capture_error": capture_err,
                "tokens": {
                    "full_tree": raw_tok,
                    "diff_patch": patch_tok,
                    "reduction_pct": saved_pct,
                },
                "screenshot": str(step_img.name),
            })

            self.prev_tree = sample_curr_tree
            print()

        elapsed = round(time.time() - start_time, 2)
        total_saved_pct = round((1.0 - (self.total_tokens_diff / max(1, self.total_tokens_full))) * 100.0, 1)

        # Write mission report
        report_path = self.run_dir / "MISSION_REPORT.md"
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(f"# Phantom Workstation Demonstration Report: {self.run_id}\n\n")
            f.write(f"- Objective: {self.objective}\n")
            f.write(f"- Steps Completed: {self.step}\n")
            f.write(f"- Elapsed Time: {elapsed}s\n")
            f.write(f"- Full Tokens: {self.total_tokens_full}\n")
            f.write(f"- Diff Tokens: {self.total_tokens_diff}\n")
            f.write(f"- Overall Reduction: {total_saved_pct}%\n")
            f.write(f"- Capture Failures: {len(self.failed_captures)}\n\n")
            f.write("## Execution Ticks\n")
            for t in self.ticks:
                f.write(f"### Step {t['step']}: {t['action']}\n")
                cap_detail = "OK" if t["capture_ok"] else f"FAILED ({t.get('capture_error')})"
                f.write(f"- Capture: {cap_detail}\n")
                f.write(f"- Reduction: {t['tokens']['reduction_pct']}%\n")
                f.write(f"- Screenshot: `{t['screenshot']}`\n\n")

        is_degraded = bool(self.failed_captures)
        status = "DEGRADED" if is_degraded else "COMPLETED"

        print("=" * 65)
        print(f"DEMONSTRATION RUN {status}")
        print(f"Duration         : {elapsed}s across {self.step} steps")
        print(f"Total Tokens     : {self.total_tokens_full} -> {self.total_tokens_diff} ({total_saved_pct}% saved)")
        if self.failed_captures:
            print(f"Capture Failures : {len(self.failed_captures)}")
        print(f"Report           : {report_path}")
        print("=" * 65 + "\n")

        return {
            "ok": not is_degraded,
            "status": status,
            "run_id": self.run_id,
            "steps_completed": self.step,
            "duration_seconds": elapsed,
            "failed_captures": self.failed_captures,
            "tokens": {
                "total_full_tree": self.total_tokens_full,
                "total_diff_patch": self.total_tokens_diff,
                "overall_reduction_pct": total_saved_pct,
            },
            "report_path": str(report_path),
        }
