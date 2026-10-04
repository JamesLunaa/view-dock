// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 James Luna

import Foundation
import Network

/// Bootstrap channel used only to exchange the WebRTC SDP offer/answer pair
/// before the real `RTCPeerConnection` takes over. Mirrors
/// `host/transport/base.py`'s `send_signal`/`receive_signal`, but from the
/// iPad's perspective the host always sends the offer first (see
/// `host/streaming/webrtc_session.py`), so this only needs the one
/// offer-in/answer-out shape.
protocol SignalingChannel {
    func receiveOffer() async throws -> SDPEnvelope
    func sendAnswer(_ answer: SDPEnvelope) async throws
    func close()
}

struct SDPEnvelope: Codable {
    let sdp: String
    let type: String
}

enum SignalingError: Error {
    case invalidHostAddress
    case unexpectedMessage
}

/// Wi-Fi: the host runs the signaling server (`host/transport/wifi.py`) and
/// this connects to it directly, given the host's address on the LAN.
final class WifiSignaling: SignalingChannel {
    private var task: URLSessionWebSocketTask?

    func connect(hostAddress: String, port: UInt16 = 8765) async throws {
        guard let url = URL(string: "ws://\(hostAddress):\(port)") else {
            throw SignalingError.invalidHostAddress
        }
        let task = URLSession.shared.webSocketTask(with: url)
        task.resume()
        self.task = task
    }

    func receiveOffer() async throws -> SDPEnvelope {
        guard let task else { throw SignalingError.unexpectedMessage }
        let message = try await task.receive()
        return try Self.decode(message)
    }

    func sendAnswer(_ answer: SDPEnvelope) async throws {
        guard let task else { throw SignalingError.unexpectedMessage }
        let data = try JSONEncoder().encode(answer)
        try await task.send(.string(String(decoding: data, as: UTF8.self)))
    }

    func close() {
        task?.cancel(with: .normalClosure, reason: nil)
        task = nil
    }

    private static func decode(_ message: URLSessionWebSocketTask.Message) throws -> SDPEnvelope {
        switch message {
        case .string(let text):
            return try JSONDecoder().decode(SDPEnvelope.self, from: Data(text.utf8))
        case .data(let data):
            return try JSONDecoder().decode(SDPEnvelope.self, from: data)
        @unknown default:
            throw SignalingError.unexpectedMessage
        }
    }
}

/// USB: the iPad must be the listener here (see `WebSocketServer.swift` for
/// why) — the host connects through the `iproxy` tunnel as a client.
///
/// The same connection can carry either flow. The app announces itself with a
/// `hello` the moment the host connects; a host that understands the wired
/// stream answers with its own `hello` and the connection becomes the whole
/// session, otherwise the first thing sent is a WebRTC SDP offer.
final class UsbSignaling: SignalingChannel {
    private let server: WebSocketServer
    /// A message already read to decide which flow this is.
    private var pendingText: String?

    init(port: UInt16 = 8766) throws {
        server = try WebSocketServer(port: port)
    }

    /// Suspends until the host connects through the USB tunnel. `onWaiting`
    /// reports why the listener isn't bound yet — see
    /// `WebSocketServer.acceptConnection(onWaiting:)`.
    func waitForHost(onWaiting: ((NWError) -> Void)? = nil) async throws {
        try await server.acceptConnection(onWaiting: onWaiting)
    }

    /// Tells the host this build can take the wired stream. Must be sent right
    /// after the connection opens: the host waits only about a second for it
    /// before assuming an older, WebRTC-only build.
    func announceWiredSupport() async throws {
        let hello = HelloMessage(role: .ipad, protocolVersion: ProtocolVersion.current)
        let data = try JSONEncoder().encode(hello)
        try await server.sendText(String(decoding: data, as: UTF8.self))
    }

    /// Reads the host's first message and keeps it for the next read, so the
    /// caller can decide what kind of session this is without consuming it.
    func peekFirstText() async throws -> String {
        let text = try await server.receiveText()
        pendingText = text
        return text
    }

    func receiveMessage() async throws -> WebSocketMessage {
        if let text = pendingText {
            pendingText = nil
            return .text(text)
        }
        return try await server.receiveMessage()
    }

    func sendText(_ text: String) async throws {
        try await server.sendText(text)
    }

    func receiveOffer() async throws -> SDPEnvelope {
        let text: String
        if let pending = pendingText {
            pendingText = nil
            text = pending
        } else {
            text = try await server.receiveText()
        }
        return try JSONDecoder().decode(SDPEnvelope.self, from: Data(text.utf8))
    }

    func sendAnswer(_ answer: SDPEnvelope) async throws {
        let data = try JSONEncoder().encode(answer)
        try await server.sendText(String(decoding: data, as: UTF8.self))
    }

    func close() {
        server.close()
    }
}
