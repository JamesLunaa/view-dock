// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 James Luna

import Foundation

/// Swift mirror of `protocol/messages.py` and `protocol/schema/*.json`.
/// See `protocol/PROTOCOL.md` for the full message contract. Keep in sync
/// by hand with the Python side when the protocol changes.
enum ProtocolVersion {
    static let current = "1.2"
}

enum MessageType: String, Codable {
    case hello
    case displayInfo = "display_info"
    case inputEvent = "input_event"
    case stats
    case bye
    case keyframeRequest = "keyframe_request"
}

enum Role: String, Codable {
    case host
    case ipad
    case android
}

enum InputKind: String, Codable {
    case touchDown = "touch_down"
    case touchMove = "touch_move"
    case touchUp = "touch_up"
    case pencilDown = "pencil_down"
    case pencilMove = "pencil_move"
    case pencilUp = "pencil_up"
}

enum Orientation: String, Codable {
    case landscape
    case portrait
}

enum ByeReason: String, Codable {
    case userDisconnected = "user_disconnected"
    case error
    case shutdown
}

struct HelloMessage: Codable {
    let type = MessageType.hello
    let role: Role
    let protocolVersion: String

    enum CodingKeys: String, CodingKey {
        case type, role
        case protocolVersion = "protocol_version"
    }
}

struct DisplayInfoMessage: Codable {
    let type = MessageType.displayInfo
    let width: Int
    let height: Int
    let refreshHz: Double
    let orientation: Orientation

    enum CodingKeys: String, CodingKey {
        case type, width, height, orientation
        case refreshHz = "refresh_hz"
    }
}

struct InputEventMessage: Codable {
    let type = MessageType.inputEvent
    let kind: InputKind
    let x: Double
    let y: Double
    let pressure: Double
    let timestampMs: Int64

    enum CodingKeys: String, CodingKey {
        case type, kind, x, y, pressure
        case timestampMs = "timestamp_ms"
    }
}

struct StatsMessage: Codable {
    let type = MessageType.stats
    let rttMs: Double
    let bitrateKbps: Double
    let fps: Double

    enum CodingKeys: String, CodingKey {
        case type
        case rttMs = "rtt_ms"
        case bitrateKbps = "bitrate_kbps"
        case fps
    }
}

struct ByeMessage: Codable {
    let type = MessageType.bye
    let reason: ByeReason

    enum CodingKeys: String, CodingKey {
        case type, reason
    }
}

/// Asks the host to make its next video frame a keyframe. Only used on the wired
/// stream, where decoding can only begin at one (WebRTC has PLI for this).
struct KeyframeRequestMessage: Codable {
    let type = MessageType.keyframeRequest

    enum CodingKeys: String, CodingKey {
        case type
    }
}

/// Binary frames on a wired stream; layout in protocol/PROTOCOL.md ("Wired
/// stream"): type(1) + flags(1) + pts in microseconds (8, big-endian) + one
/// H.264 access unit in Annex-B form.
enum WiredFrame {
    static let video: UInt8 = 0x01
    static let flagKeyframe: UInt8 = 0x01
    static let videoHeaderSize = 10
}

struct VideoPacket {
    let isKeyframe: Bool
    let presentationTimeMicros: UInt64
    let accessUnit: Data
}

/// Returns nil for anything that isn't a well-formed video frame, so unknown
/// frame types are ignored rather than fatal.
func parseVideoPacket(from frame: Data) -> VideoPacket? {
    guard frame.count >= WiredFrame.videoHeaderSize, frame[frame.startIndex] == WiredFrame.video else {
        return nil
    }
    let base = frame.startIndex
    var pts: UInt64 = 0
    for offset in 2..<10 {
        pts = (pts << 8) | UInt64(frame[base + offset])
    }
    return VideoPacket(
        isKeyframe: frame[base + 1] & WiredFrame.flagKeyframe != 0,
        presentationTimeMicros: pts,
        accessUnit: frame.subdata(in: (base + WiredFrame.videoHeaderSize)..<frame.endIndex)
    )
}

/// Just enough to read `type` off an incoming control-channel message before
/// decoding it into its concrete struct.
private struct MessageEnvelope: Decodable {
    let type: MessageType
}

func decodeMessageType(from data: Data) -> MessageType? {
    try? JSONDecoder().decode(MessageEnvelope.self, from: data).type
}
