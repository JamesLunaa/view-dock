#!/usr/bin/env bash
# Launches a command with QT_SCALE_FACTOR/GDK_SCALE set to match the host's
# VIEWDOCK_DISPLAY_SCALE, for an app you're opening fresh onto the virtual
# display rather than dragging over from the built-in screen.
#
# Why this exists: X11 has no per-output DPI — every app on the X server
# draws at the same density regardless of which output it ends up on. Normal
# usage (dragging an existing window over) inherits whatever density that
# window's toolkit already picked for the built-in screen, which happens to
# be correct at the default VIEWDOCK_DISPLAY_SCALE=1 (the virtual display
# runs at the iPad's logical point size, so no translation is needed). If
# instead you run the host with VIEWDOCK_DISPLAY_SCALE=2, the virtual display
# captures at the iPad's *physical* pixel size (sharper), but an app that
# doesn't know about the extra pixels will render tiny in the corner of that
# bigger canvas — this script tells Qt/GTK toolkits to draw at the matching
# density so a freshly-launched app looks correctly sized.
#
# What this does NOT do: move the app's window onto the virtual display, or
# help a window dragged over from the built-in screen — that window already
# has its own toolkit scale baked in from whichever screen it started on,
# and nothing retroactively changes that. This only helps an app you are
# about to launch directly for use on the scaled virtual display.
#
# Usage:
#   ./host/scripts/launch-on-virtual-display.sh <scale> <command> [args...]
#
# <scale> should match whatever VIEWDOCK_DISPLAY_SCALE the host is running
# with (2 for the iPad's native 2x-retina pixel density). After launching,
# drag the window over to the virtual display as usual.
#
# Example:
#   # host side, in one terminal:
#   VIEWDOCK_DISPLAY_SCALE=2 python -m host.main
#   # then, to open a sharp fresh window for it:
#   ./host/scripts/launch-on-virtual-display.sh 2 kate

set -euo pipefail

if [ "$#" -lt 2 ]; then
    echo "Usage: $0 <scale> <command> [args...]" >&2
    exit 1
fi

SCALE="$1"
shift

if ! [[ "${SCALE}" =~ ^[0-9]+$ ]] || [ "${SCALE}" -lt 1 ]; then
    echo "<scale> must be a positive integer (got '${SCALE}')" >&2
    exit 1
fi

export QT_SCALE_FACTOR="${SCALE}"
export GDK_SCALE="${SCALE}"
exec "$@"
