// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 James Luna

import CryptoKit
import Foundation
import Network

/// Minimal RFC 6455 WebSocket server for the USB transport: the host connects
/// through the tunnel, then either bootstraps WebRTC signaling over it (one SDP
/// offer in, one answer out — see `SignalingChannel.swift`) or, for the wired
/// stream, carries the whole session on it (see `WiredClient.swift`). `iproxy <local_port> <device_port>` on the host
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
    /// the WebSocket handshake. `onWaiting` fires (possibly repeatedly,
    /// without resolving the wait) whenever the listener can't bind yet —
    /// in practice this is almost always a not-yet-granted Local Network
    /// permission, which otherwise looks identical to "no host connected
    /// yet" from the caller's point of view.
    func acceptConnection(onWaiting: ((NWError) -> Void)? = nil) async throws {
        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
            // `newConnectionHandler` and `stateUpdateHandler` are both
            // `@Sendable` closures that could in principle run concurrently,
            // so the "resume at most once" guard needs its own locking
            // rather than a plain captured var.
            let resumeOnce = OnceFlag()
            listener.newConnectionHandler = { [weak self] newConnection in
                guard let self, resumeOnce.trySet() else { return }
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
                switch state {
                case .waiting(let error):
                    onWaiting?(error)
                case .failed(let error):
                    guard resumeOnce.trySet() else { return }
                    continuation.resume(throwing: ServerError.listenerFailed(error))
                default:
                    break
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

    // MARK: - Framing
    //
    // The wire format itself lives in `WebSocketFraming.swift` (and is unit
    // tested there); this is just the I/O around it.

    private var assembler = WebSocketMessageAssembler()

    func sendText(_ text: String) async throws {
        try await write(WebSocketFraming.encode(opcode: WebSocketOpcode.text, payload: Data(text.utf8)))
    }

    /// The next complete text or binary message from the client. Pings are
    /// answered here and fragmented messages are reassembled, so callers only
    /// ever see whole messages.
    func receiveMessage() async throws -> WebSocketMessage {
        while true {
            let frame = try await readFrame()
            switch frame.opcode {
            case WebSocketOpcode.close:
                throw ServerError.connectionClosed
            case WebSocketOpcode.ping:
                try await write(WebSocketFraming.encode(opcode: WebSocketOpcode.pong, payload: frame.payload))
            case WebSocketOpcode.pong:
                continue
            default:
                if let message = try assembler.accept(frame) {
                    return message
                }
            }
        }
    }

    func receiveText() async throws -> String {
        guard case .text(let text) = try await receiveMessage() else {
            throw ServerError.unexpectedFrame
        }
        return text
    }

    private func readFrame() async throws -> WebSocketFrame {
        while true {
            if let frame = try WebSocketFraming.decodeFrame(from: &buffer) {
                return frame
            }
            try await fillBuffer()
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

/// Thread-safe "fire exactly once" latch, for guarding a continuation that
/// could otherwise be resumed from two different `@Sendable` callbacks.
private final class OnceFlag: @unchecked Sendable {
    private let lock = NSLock()
    private var fired = false

    /// Returns `true` for the first caller only; `false` for every call after.
    func trySet() -> Bool {
        lock.lock()
        defer { lock.unlock() }
        guard !fired else { return false }
        fired = true
        return true
    }
}
