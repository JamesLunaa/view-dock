#!/usr/bin/env bash
# Launcher for the host GUI (host/gui/), meant to be run via the .desktop
# entry (scripts/install-desktop-entry.sh installs it), not directly — it
# hardcodes nothing user-specific itself, but `python -m host.gui` needs to
# run with the repo root as the working directory to resolve the `host`
# package, which a desktop launcher won't do on its own.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/../.."
exec env DISPLAY="${DISPLAY:-:0}" .venv/bin/python -m host.gui
