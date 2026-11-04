#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Luna

# Builds the iPad app with xtool and installs it on the plugged-in iPad.
#
# With a free Apple ID the app has to be reinstalled every 7 days, and the first
# `xtool dev` of the week often fails with "There are no current IOS devices on this
# team": that run registers the iPad with Apple, and a second run installs. This
# script retries once in that case.
#
# Set SWIFT_TOOLCHAIN to the toolchain's `usr/bin` if `swift` isn't on your PATH.
set -u

cd "$(dirname "$0")" || exit 1
PATH="$HOME/.local/bin:${SWIFT_TOOLCHAIN:+$SWIFT_TOOLCHAIN:}$PATH"
export PATH

log="$(mktemp)"
trap 'rm -f "$log"' EXIT

for attempt in 1 2; do
    xtool dev 2>&1 | tee "$log"
    if ! grep -q "Error:" "$log"; then
        exit 0
    fi
    if [ "$attempt" = 1 ] && grep -q "no current IOS devices on this team" "$log"; then
        echo "The iPad was just registered with Apple; trying again..." >&2
        continue
    fi
    exit 1
done
exit 1
