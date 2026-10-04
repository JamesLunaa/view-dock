#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Luna

# Installs an application-menu launcher for the host GUI — "an app icon
# where we can launch this without doing the CLI stuff". Templates
# gui/viewdock-host.desktop.in with this checkout's absolute path (the
# launcher has to be an absolute path; there's no installed package to
# resolve it another way) and drops it where KDE's app menu picks it up
# automatically, no root needed.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
APPS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"

mkdir -p "$APPS_DIR"
chmod +x "$REPO_DIR/host/scripts/launch-gui.sh"
sed "s|__REPO_DIR__|$REPO_DIR|g" "$REPO_DIR/host/gui/viewdock-host.desktop.in" \
    > "$APPS_DIR/viewdock-host.desktop"

command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$APPS_DIR" || true

echo "Installed: $APPS_DIR/viewdock-host.desktop"
echo "It should now show up as \"view-dock Host\" in your application launcher."
