import Foundation

/// RFC 6455 framing, kept free of any networking so it can be unit-tested on its
/// own. `WebSocketServer` does the I/O and feeds frames through here.

enum WebSocketMessage: Equatable {
    case text(String)
    case binary(Data)
}

struct WebSocketFrame {
    var fin: Bool
    var opcode: UInt8
    var payload: Data
}

enum WebSocketFramingError: Error, Equatable {
    case invalidUTF8
    case unexpectedContinuation
    case interleavedDataFrame
    case frameTooLarge
}

enum WebSocketOpcode {
    static let continuation: UInt8 = 0x0
    static let text: UInt8 = 0x1
    static let binary: UInt8 = 0x2
    static let close: UInt8 = 0x8
    static let ping: UInt8 = 0x9
    static let pong: UInt8 = 0xA
}

enum WebSocketFraming {
    /// Builds an unmasked frame (server → client frames are never masked).
    static func encode(opcode: UInt8, payload: Data, fin: Bool = true) -> Data {
        var frame = Data([(fin ? 0x80 : 0x00) | (opcode & 0x0F)])
        frame.append(contentsOf: encodeLength(payload.count))
        frame.append(payload)
        return frame
    }

    static func encodeLength(_ length: Int) -> [UInt8] {
        if length < 126 {
            return [UInt8(length)]
        } else if length <= 0xFFFF {
            return [126, UInt8((length >> 8) & 0xFF), UInt8(length & 0xFF)]
        } else {
            var bytes: [UInt8] = [127]
            for shift in stride(from: 56, through: 0, by: -8) {
                bytes.append(UInt8((length >> shift) & 0xFF))
            }
            return bytes
        }
    }

    /// Far above any real frame (a keyframe at 20 Mbps is a few hundred KB); only
    /// here so a corrupt length can't make us try to buffer gigabytes.
    static let maxPayloadLength = 16 * 1024 * 1024

    /// Decodes one frame from the front of `buffer`, removing it. Returns nil —
    /// consuming nothing — if the buffer doesn't yet hold a whole frame, so it
    /// can be called again as more bytes arrive.
    static func decodeFrame(from buffer: inout Data) throws -> WebSocketFrame? {
        let base = buffer.startIndex
        guard buffer.count >= 2 else { return nil }

        let first = buffer[base]
        let second = buffer[base + 1]
        let fin = (first & 0x80) != 0
        let opcode = first & 0x0F
        let masked = (second & 0x80) != 0
        var length = Int(second & 0x7F)
        var headerLength = 2

        if length == 126 {
            guard buffer.count >= 4 else { return nil }
            length = (Int(buffer[base + 2]) << 8) | Int(buffer[base + 3])
            headerLength = 4
        } else if length == 127 {
            guard buffer.count >= 10 else { return nil }
            var wide: UInt64 = 0
            for offset in 2..<10 {
                wide = (wide << 8) | UInt64(buffer[base + offset])
            }
            guard wide <= UInt64(maxPayloadLength) else { throw WebSocketFramingError.frameTooLarge }
            length = Int(wide)
            headerLength = 10
        }
        guard length <= maxPayloadLength else { throw WebSocketFramingError.frameTooLarge }

        let maskLength = masked ? 4 : 0
        let total = headerLength + maskLength + length
        guard buffer.count >= total else { return nil }

        var payload = [UInt8](buffer[(base + headerLength + maskLength)..<(base + total)])
        if masked {
            let key = [UInt8](buffer[(base + headerLength)..<(base + headerLength + 4)])
            unmask(&payload, key: key)
        }
        buffer.removeFirst(total)
        return WebSocketFrame(fin: fin, opcode: opcode, payload: Data(payload))
    }

    /// Client → server frames are masked; XORs the payload with the 4-byte key in place.
    static func unmask(_ payload: inout [UInt8], key: [UInt8]) {
        guard key.count == 4 else { return }
        payload.withUnsafeMutableBufferPointer { buffer in
            for index in 0..<buffer.count {
                buffer[index] ^= key[index & 3]
            }
        }
    }
}

/// Reassembles fragmented messages. Control frames (close/ping/pong) may arrive
/// in the middle of a fragmented message and are not its business — the caller
/// handles those and only passes data and continuation frames here.
struct WebSocketMessageAssembler {
    private var fragmentOpcode: UInt8?
    private var fragments = Data()

    /// Returns a complete message once its final frame arrives, otherwise nil.
    mutating func accept(_ frame: WebSocketFrame) throws -> WebSocketMessage? {
        switch frame.opcode {
        case WebSocketOpcode.text, WebSocketOpcode.binary:
            guard fragmentOpcode == nil else { throw WebSocketFramingError.interleavedDataFrame }
            if frame.fin {
                return try Self.message(opcode: frame.opcode, payload: frame.payload)
            }
            fragmentOpcode = frame.opcode
            fragments = frame.payload
            return nil
        case WebSocketOpcode.continuation:
            guard let opcode = fragmentOpcode else { throw WebSocketFramingError.unexpectedContinuation }
            fragments.append(frame.payload)
            guard frame.fin else { return nil }
            let message = try Self.message(opcode: opcode, payload: fragments)
            fragmentOpcode = nil
            fragments = Data()
            return message
        default:
            return nil
        }
    }

    private static func message(opcode: UInt8, payload: Data) throws -> WebSocketMessage {
        if opcode == WebSocketOpcode.binary {
            return .binary(payload)
        }
        guard let text = String(data: payload, encoding: .utf8) else {
            throw WebSocketFramingError.invalidUTF8
        }
        return .text(text)
    }
}
