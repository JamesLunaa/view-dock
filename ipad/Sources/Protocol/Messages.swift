import Foundation

/// Swift mirror of `protocol/messages.py` and `protocol/schema/*.json`.
/// See `protocol/PROTOCOL.md` for the full message contract. Keep in sync
/// by hand with the Python side when the protocol changes.
enum ProtocolVersion {
    static let current = "1.0"
}

enum MessageType: String, Codable {
    case hello
    case displayInfo = "display_info"
    case inputEvent = "input_event"
    case stats
    case bye
}

enum Role: String, Codable {
    case host
    case ipad
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
