# Phantom Workstation

[![CI](https://github.com/LeonidMajbits/phantom-workstation/actions/workflows/ci.yml/badge.svg)](https://github.com/LeonidMajbits/phantom-workstation/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Platform: macOS](https://img.shields.io/badge/platform-macOS%2013%2B-lightgrey.svg)](README.md)
[![Python: 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](pyproject.toml)

Experimental macOS Virtual-Display Utilities & Accessibility Tree Delta Compressor for Agent Development.

---

## Overview

Modern AI computer-use systems face two core challenges when interacting with desktop operating systems:
1. **Physical Display Disruption**: Operating host UI windows directly can displace user focus, obstruct the primary desktop, and hijack the mouse cursor.
2. **Sensory Token Burden**: Emitting full, redundant Accessibility (AX) hierarchies or DOM dumps on every observation step wastes thousands of context tokens per step.

**Phantom Workstation** provides lightweight, native macOS primitives to address these challenges:
* **Headless Virtual Display**: Spawns an isolated 1920x1080 display space in RAM using CoreGraphics (`CGVirtualDisplay`). Windows can be placed and screenshotted offscreen without disrupting the primary monitor.
* **AX Tree Delta Compressor**: Computes structural and attribute differences across consecutive UI trees. Tracks full accessibility state (`enabled`, `focused`, `selected`, `expanded`, `hidden`, `subrole`, etc.), escapes path segments to prevent hierarchy collisions, and calculates exact token savings.

---

## System Requirements

* macOS 13.0 (Ventura) or later (Apple Silicon or Intel).
* Xcode Command Line Tools (`xcode-select --install`) for compiling the Objective-C virtual display daemon.
* Python 3.9+.

---

## Installation

Clone the repository and install locally:

```bash
git clone https://github.com/LeonidMajbits/phantom-workstation.git
cd phantom-workstation
pip install -e .
```

The virtual display daemon compiles automatically upon first launch via `clang`.

---

## Command Line Interface

### 1. Check Display Status
```bash
phantom-workstation status
```

### 2. Start Virtual Display
```bash
phantom-workstation start --width 1920 --height 1080
```

### 3. Teleport an Application Window
Move any running application window to the virtual display coordinates:
```bash
phantom-workstation teleport "Google Chrome"
```

### 4. Capture Virtual Display
Capture a background screenshot of the virtual display space:
```bash
phantom-workstation capture -o capture.png
```

### 5. Run Demonstration Loop
Run a demonstration harness evaluating virtual display capture and AX diffing:
```bash
phantom-workstation run "Demonstration evaluation" --steps 3 --dry-run
```

### 6. Stop Virtual Display
```bash
phantom-workstation stop
```

---

## Python API

### Virtual Display Lifecycle
```python
from phantom_workstation import start_display, stop_display, get_display_status, capture_display

# Start 1080p virtual display
result = start_display(1920, 1080)
print(result)

# Check status
status = get_display_status()
print(f"Display ID: {status['display_id']} (Ordinal: {status.get('display_index')})")

# Capture frame
capture = capture_display()
print(f"Captured to: {capture['path']}")

# Terminate
stop_display()
```

### AX Tree Delta Compression
```python
from phantom_workstation import compute_ax_diff

prev_tree = {
    "role": "AXApplication",
    "name": "Browser",
    "children": [
        {"role": "AXWindow", "name": "Main", "children": [
            {"role": "AXButton", "name": "Submit", "value": "Initial", "enabled": True}
        ]}
    ]
}

curr_tree = {
    "role": "AXApplication",
    "name": "Browser",
    "children": [
        {"role": "AXWindow", "name": "Main", "children": [
            {"role": "AXButton", "name": "Submit", "value": "Initial", "enabled": False},
            {"role": "AXTextField", "name": "Status", "value": "Ready", "focused": True}
        ]}
    ]
}

diff = compute_ax_diff(prev_tree, curr_tree)
print(f"Token reduction: {diff['token_reduction_pct']}%")
print(f"Added nodes    : {diff['added_count']}")
print(f"Modified nodes : {diff['modified_count']}")
print(f"Detailed changes: {diff['mutations']['modified'][0]['changes']}")
```

---

## Architectural & Security Design

* **Safe AppleScript Parameterization**: Window movement parameters are passed as positional arguments (`on run argv`) via `osascript`, preventing script interpreter injection.
* **Display Ordinal Resolution**: Resolves the CoreGraphics display ID to the 1-based display ordinal expected by macOS `screencapture -D` using CoreGraphics display list queries.
* **Robust Diff Tracking**: Compares and emits deltas for `role`, `subrole`, `name`, `title`, `value`, `enabled`, `focused`, `selected`, `expanded`, `hidden`, `checked`, `frame`, and `help`.
* **Collision-Resistant Pathing**: Encodes path segments using standard percent-encoding, preventing path depth injection and sibling disambiguation collisions.
* **Unmasked Token Accounting**: Accurately measures serialized payload sizes without masking negative compression ratios, flagging `exceeded_raw` when a patch is larger than the raw tree.
* **Process Concurrency & Cache Invalidation**: Daemon startup and teardown use advisory file locks. The native binary automatically recompiles when the Objective-C source file is modified.

---

## Platform & Distribution Notice

* **Private CoreGraphics Framework**: The virtual display subsystem utilizes Apple's internal `CGVirtualDisplay` CoreGraphics interface. This is designed for local automation workflows, developer tooling, and self-hosted AI agent runners.
* **Mac App Store Disclaimer**: Applications bundling this library cannot be submitted to the sandboxed Mac App Store due to Apple's policy prohibiting private APIs. It is intended for open distribution via package managers, CLI tools, and direct installation.

---

## Contributing

Contributions are welcome. Please read [`CONTRIBUTING.md`](CONTRIBUTING.md) for guidelines on development workflows and style standards.

---

## Security

Please report vulnerabilities confidentially via GitHub Security Advisories. See [`SECURITY.md`](SECURITY.md) for details.

---

## Authorship and License

Authorship and AI-assisted development are documented in [`AUTHORS.md`](AUTHORS.md).

Copyright 2026 Leonid Majbits.

Licensed under the [MIT License](LICENSE).
