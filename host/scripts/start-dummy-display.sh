#!/usr/bin/env bash
# Starts a second, isolated X server (display :1) running the dummy driver,
# for view-dock's virtual display — separate from your normal desktop
# session (:0), which is left completely untouched.
#
# Usage:
#   ./host/scripts/start-dummy-display.sh
#   DISPLAY=:1 VIEWDOCK_DISPLAY_WIDTH=1024 VIEWDOCK_DISPLAY_HEIGHT=768 \
#       python -m host.main
#
# Requires xorg-server + xf86-video-dummy (pacman -S xorg-server xf86-video-dummy).
# Starting an X server needs root (Xorg.wrap only allows console users, which
# a script invoked from a non-interactive shell usually isn't) — this uses
# `sudo` and will prompt for your password.
#
# Known limitation: input injected by host/input/injector.py goes to
# whichever session currently holds VT/input focus, which in this two-VT
# setup is your REAL desktop, not this isolated display. This setup is for
# getting real desktop *content* onto the iPad; touch control on that
# content isn't wired up yet — see TODO/TODO.md.

set -euo pipefail

DISPLAY_NUM="${1:-1}"
CONFIG_PATH="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/xorg/dummy.conf"
LOG_PATH="/tmp/viewdock-xorg-dummy-${DISPLAY_NUM}.log"

if xdpyinfo -display ":${DISPLAY_NUM}" >/dev/null 2>&1; then
    echo "X server already running on :${DISPLAY_NUM}"
else
    echo "Starting Xorg :${DISPLAY_NUM} with ${CONFIG_PATH} (sudo password may be required)..."
    sudo Xorg ":${DISPLAY_NUM}" -config "${CONFIG_PATH}" -noreset -logfile "${LOG_PATH}" &

    for _ in $(seq 1 50); do
        if DISPLAY=":${DISPLAY_NUM}" xrandr --query >/dev/null 2>&1; then
            break
        fi
        sleep 0.2
    done

    if ! DISPLAY=":${DISPLAY_NUM}" xrandr --query >/dev/null 2>&1; then
        echo "Xorg :${DISPLAY_NUM} did not come up — check ${LOG_PATH}" >&2
        exit 1
    fi
fi

# The dummy driver auto-connects DUMMY0 with a default mode. Disabling it
# reclaims the ~4MB shared framebuffer budget for whichever DUMMY output
# host/displayserver/x11.py ends up using — see the note in xorg/dummy.conf.
DISPLAY=":${DISPLAY_NUM}" xrandr --output DUMMY0 --off >/dev/null 2>&1 || true

echo "Ready. Run the host against this display with, e.g.:"
echo "  DISPLAY=:${DISPLAY_NUM} VIEWDOCK_DISPLAY_WIDTH=1024 VIEWDOCK_DISPLAY_HEIGHT=768 python -m host.main"
