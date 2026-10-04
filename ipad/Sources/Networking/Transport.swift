// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 James Luna

import Foundation

/// Mirrors `host/transport/`: the same WebRTC session runs over either
/// physical connection, only signaling setup differs per case.
enum Transport {
    case wifi
    case usb
}
