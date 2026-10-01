#!/usr/bin/env bash
# Forces a real GPU display connector "connected" at the kernel/DRM level, so
# a virtual display can be attached to it with nothing physically plugged in.
#
# Why this is needed (and why `xrandr` alone isn't enough): a desktop's own
# display manager — KDE's kscreen, for one — decides what counts as a real
# screen from the kernel's DRM connector state, not from XRandR. Forcing a
# mode purely at the XRandR level gets you a capturable region, but the
# desktop won't place windows on it, so you can't drag anything there. Once
# the connector is forced at the DRM level, it becomes a real monitor as far
# as the whole stack is concerned.
#
# NOT persistent: debugfs resets on reboot, so re-run this after each boot.
# For a permanent setup, add `video=<CONNECTOR>:e` to the kernel command line
# instead (e.g. video=HDMI-A-1:e) — see host/README.md.
#
# Usage:
#   ./host/scripts/force-connector.sh                      # defaults to HDMI-A-1
#   ./host/scripts/force-connector.sh DP-1
#   ./host/scripts/force-connector.sh HDMI-A-1 unspecified  # undo: back to normal
#                                                            # kernel auto-detection
#
# Don't use "off" to undo — that's a DIFFERENT force state (permanently
# FORCED DISCONNECTED), not "no force". Found live: this was still a sharp
# edge even with this script around — a real monitor plugged into a
# connector left forced "on" from an earlier view-dock session showed "No
# signal", because the forced state was overriding the physical cable's own
# hotplug/EDID detection. "unspecified" is what actually restores it.
#
# Note the DRM connector name ("HDMI-A-1") differs from the XRandR output
# name ("HDMI-1") for the same physical port.

set -euo pipefail

CONNECTOR="${1:-HDMI-A-1}"
STATE="${2:-on}"

# /sys/kernel/debug isn't traversable without root, so even resolving the
# path has to happen under sudo — a plain glob here silently matches nothing.
echo "Locating connector '${CONNECTOR}' (sudo password may be required)..."
FORCE_PATH="$(sudo sh -c "ls -d /sys/kernel/debug/dri/*/'${CONNECTOR}'/force 2>/dev/null | head -1")"

if [ -z "${FORCE_PATH}" ]; then
    echo "No DRM connector '${CONNECTOR}' found. Available connectors:" >&2
    # maxdepth 3: .../dri/<card>/<connector>/force is 3 levels below dri/.
    sudo find /sys/kernel/debug/dri -maxdepth 3 -name force -printf '%h\n' 2>/dev/null \
        | sed 's|.*/|  |' >&2 || true
    exit 1
fi
echo "Setting ${FORCE_PATH} = ${STATE} (sudo password may be required)..."
echo "${STATE}" | sudo tee "${FORCE_PATH}" >/dev/null

echo "Current state: $(sudo cat "${FORCE_PATH}")"
echo
echo "XRandR now reports:"
xrandr --query | grep -E '^\S+ (dis)?connected' || true
