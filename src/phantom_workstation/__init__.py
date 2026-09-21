"""Phantom Workstation: Experimental macOS Virtual-Display Utilities & AX Tree Delta Compressor.

Provides lightweight native macOS utilities for managing offscreen virtual display spaces
and token-efficient Accessibility tree delta compression for local agent development.
"""

__version__ = "0.1.0"
__author__ = "The Phantom Workstation Authors"

from .ax_diff import compute_ax_diff, flatten_tree
from .display import (
    get_display_status,
    start_display,
    stop_display,
    capture_display,
    teleport_window,
)
from .workstation import PhantomWorkstation

__all__ = [
    "compute_ax_diff",
    "flatten_tree",
    "get_display_status",
    "start_display",
    "stop_display",
    "capture_display",
    "teleport_window",
    "PhantomWorkstation",
]
