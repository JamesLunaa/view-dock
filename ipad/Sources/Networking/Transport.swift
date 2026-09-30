import Foundation

/// Mirrors `host/transport/`: the same WebRTC session runs over either
/// physical connection, only signaling setup differs per case.
enum Transport {
    case wifi
    case usb
}
