import CryptoKit
import Foundation
import Network

/// Minimal RFC 6455 WebSocket server, used only for the USB transport's
/// bootstrap signaling (one SDP offer in, one answer out — see
/// `SignalingChannel.swift`). `iproxy <local_port> <device_port>` on the host
/// relays connections to a port *this device* must be listening on, so for
/// USB the iPad is the WebSocket server and the host connects through the
/// tunnel as a client (see `host/transport/usb.py`).
final class WebSocketServer {
    enum ServerError: Error {
        case listenerFailed(Error)
        case handshakeFailed
        case connectionClosed
        case unexpectedFrame
    }

    private let listener: NWListener
    private var connection: NWConnection?
    private var buffer = Data()

    init(port: UInt16) throws {
        guard let nwPort = NWEndpoint.Port(rawValue: port) else {
            throw ServerError.listenerFailed(NSError(domain: "WebSocketServer", code: 0))
        }
        self.listener = try NWListener(using: .tcp, on: nwPort)
    }

    /// Starts listening and suspends until the first client has completed
    /// the WebSocket handshake.
    func acceptConnection() async throws {
        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
            var resumed = false
            listener.newConnectionHandler = { [weak self] newConnection in
                guard let self, !resumed else { return }
                resumed = true
                self.connection = newConnection
                newConnection.start(queue: .main)
                Task {
                    do {
                        try await self.performHandshake()
                        continuation.resume()
                    } catch {
                        continuation.resume(throwing: error)
                    }
                }
            }
            listener.stateUpdateHandler = { state in
                guard !resumed else { return }
                if case .failed(let error) = state {
                    resumed = true
                    continuation.resume(throwing: ServerError.listenerFailed(error))
                }
            }
            listener.start(queue: .main)
        }
    }

    func close() {
        connection?.cancel()
        connection = nil
        listener.cancel()
    }

    // MARK: - Handshake

    private func performHandshake() async throws {
        let headerData = try await readUntil(delimiter: Data("\r\n\r\n".utf8))
        guard let headerText = String(data: headerData, encoding: .utf8),
              let key = Self.headerValue(named: "Sec-WebSocket-Key", in: headerText)
        else {
            throw ServerError.handshakeFailed
        }

        let response = "HTTP/1.1 101 Switching Protocols\r\n"
            + "Upgrade: websocket\r\n"
            + "Connection: Upgrade\r\n"
            + "Sec-WebSocket-Accept: \(Self.acceptKey(for: key))\r\n\r\n"
        try await write(Data(response.utf8))
    }

    private static func headerValue(named name: String, in headerText: String) -> String? {
        for line in headerText.split(separator: "\r\n") {
            let parts = line.split(separator: ":", maxSplits: 1)
            guard parts.count == 2,
                  parts[0].trimmingCharacters(in: .whitespaces).caseInsensitiveCompare(name) == .orderedSame
            else { continue }
            return parts[1].trimmingCharacters(in: .whitespaces)
        }
        return nil
    }

    private static func acceptKey(for key: String) -> String {
        let magic = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
        let digest = Insecure.SHA1.hash(data: Data((key + magic).utf8))
        return Data(digest).base64EncodedString()
    }

    // MARK: - Framing (text frames only — all we ever send is JSON)

    func sendText(_ text: String) async throws {
        let payload = Data(text.utf8)
        var frame = Data([0x81]) // FIN + text opcode
        frame.append(contentsOf: Self.encodeLength(payload.count))
        frame.append(payload)
        try await write(frame)
    }

    func receiveText() async throws -> String {
        let header = try await readExactly(2)
        let opcode = header[header.startIndex] & 0x0F
        let masked = (header[header.startIndex + 1] & 0x80) != 0
        var length = Int(header[header.startIndex + 1] & 0x7F)

        if length == 126 {
            let extended = try await readExactly(2)
            length = extended.reduce(0) { ($0 << 8) | Int($1) }
        } else if length == 127 {
            let extended = try await readExactly(8)
            length = extended.reduce(0) { ($0 << 8) | Int($1) }
        }

        var maskKey: [UInt8] = []
        if masked {
            maskKey = Array(try await readExactly(4))
        }

        var payload = Array(try await readExactly(length))
        if masked {
            for i in 0..<payload.count {
                payload[i] ^= maskKey[i % 4]
            }
        }

        if opcode == 0x8 {
            throw ServerError.connectionClosed
        }
        guard opcode == 0x1, let text = String(bytes: payload, encoding: .utf8) else {
            throw ServerError.unexpectedFrame
        }
        return text
    }

    private static func encodeLength(_ length: Int) -> [UInt8] {
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

    // MARK: - Raw I/O

    private func write(_ data: Data) async throws {
        guard let connection else { throw ServerError.connectionClosed }
        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
            connection.send(content: data, completion: .contentProcessed { error in
                if let error {
                    continuation.resume(throwing: error)
                } else {
                    continuation.resume()
                }
            })
        }
    }

    private func readExactly(_ count: Int) async throws -> Data {
        while buffer.count < count {
            try await fillBuffer()
        }
        let result = buffer.prefix(count)
        buffer.removeFirst(count)
        return result
    }

    private func readUntil(delimiter: Data) async throws -> Data {
        while true {
            if let range = buffer.range(of: delimiter) {
                let result = buffer.prefix(upTo: range.lowerBound)
                buffer.removeSubrange(buffer.startIndex..<range.upperBound)
                return result
            }
            try await fillBuffer()
        }
    }

    private func fillBuffer() async throws {
        guard let connection else { throw ServerError.connectionClosed }
        let chunk: Data = try await withCheckedThrowingContinuation { continuation in
            connection.receive(minimumIncompleteLength: 1, maximumLength: 65536) { data, _, isComplete, error in
                if let error {
                    continuation.resume(throwing: error)
                } else if let data, !data.isEmpty {
                    continuation.resume(returning: data)
                } else if isComplete {
                    continuation.resume(throwing: ServerError.connectionClosed)
                } else {
                    continuation.resume(returning: Data())
                }
            }
        }
        buffer.append(chunk)
    }
}
