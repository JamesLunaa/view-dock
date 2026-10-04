# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Luna

"""Forces a spare GPU connector "connected" at the DRM level, in-process.

Python counterpart of `host/scripts/force-connector.sh`, so starting the host
(CLI, TUI or tray) doesn't need a separate manual step after every boot. The
write goes to debugfs, which needs root: this tries passwordless `sudo -n`
first, then `pkexec` (a graphical polkit prompt, which works from the tray
app and doesn't fight the TUI for the terminal).
"""

import logging
import re
import subprocess

logger = logging.getLogger(__name__)

_HDMI_RE = re.compile(r"^HDMI-(\d+)$")

# Takes a force state, then DRM connector-name candidates, and applies the state
# to the first candidate that exists. The glob has to be expanded as root — debugfs isn't traversable
# otherwise — hence a single privileged shell rather than a Python-side lookup.
_FORCE_SCRIPT = (
    'state="$1"; shift; '
    'for c in "$@"; do '
    "for f in /sys/kernel/debug/dri/*/$c/force; do "
    '[ -e "$f" ] && echo "$state" > "$f" && echo "$c" && exit 0; '
    "done; done; exit 1"
)


def drm_candidates(xrandr_name: str) -> list[str]:
    """DRM connector names that may correspond to an XRandR output name.

    They differ for HDMI (`HDMI-1` in XRandR is `HDMI-A-1` in DRM); DP/eDP
    names match as-is.
    """
    candidates = [xrandr_name]
    match = _HDMI_RE.match(xrandr_name)
    if match:
        candidates.insert(0, f"HDMI-A-{match.group(1)}")
    return candidates


def _set_force(xrandr_name: str, state: str, timeout: float) -> str | None:
    command = ["sh", "-c", _FORCE_SCRIPT, "sh", state, *drm_candidates(xrandr_name)]
    for escalate in (["sudo", "-n"], ["pkexec"]):
        try:
            result = subprocess.run(
                [*escalate, *command], capture_output=True, text=True, timeout=timeout
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
        if result.returncode == 0:
            changed = result.stdout.strip()
            logger.info("Set DRM connector %s force=%s (via %s).", changed, state, escalate[0])
            return changed
    logger.warning(
        "Could not set force=%s for %s; run scripts/force-connector.sh manually.", state, xrandr_name
    )
    return None


def force_connector(xrandr_name: str, timeout: float = 120.0) -> str | None:
    """Forces the connector behind `xrandr_name` on. Returns the DRM name that
    was forced, or None if it couldn't be (no privileges, no such connector)."""
    return _set_force(xrandr_name, "on", timeout)


def unforce_connector(xrandr_name: str, timeout: float = 120.0) -> str | None:
    """Returns the connector to normal kernel detection (`unspecified`, not
    `off` — see force-connector.sh), so a real monitor on it works again."""
    return _set_force(xrandr_name, "unspecified", timeout)
