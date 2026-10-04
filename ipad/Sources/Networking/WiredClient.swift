// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 James Luna

import AVFoundation
import Foundation

/// A wired session: the USB tunnel's WebSocket carries the whole thing —
/// control messages as text, H.264 video as binary frames (protocol/PROTOCOL.md,
/// "Wired stream"). No WebRTC, so it needs no Wi-Fi and no shared network.
///
/// Decoding and display are handed to `AVSampleBufferDisplayLayer`, which owns
/// the hardware decoder. The layer lives here rather than in the SwiftUI view,
/// so the stream keeps being consumed (and stays decodable) if the view is
/// rebuilt.
final class WiredClient: ObservableObject {
    @Published private(set) var displayInfo: DisplayInfoMessage?
    @Published private(set) var statusDescription = "Connected over USB"

    let displayLayer = AVSampleBufferDisplayLayer()

    /// Called on the main thread once, when the session ends (host stopped, cable pulled, …).
    var onFinished: (() -> Void)?

    private let signaling: UsbSignaling
    private let factory = H264SampleBufferFactory()
    private var readTask: Task<Void, Never>?
    private var sendTask: Task<Void, Never>?
    private var sendContinuation: AsyncStream<String>.Continuation?
    private var finished = false

    // Only touched from the read loop.
    private var waitingForKeyframe = true
    private var lastKeyframeRequest = Date.distantPast

    init(signaling: UsbSignaling) {
        self.signaling = signaling
        displayLayer.videoGravity = .resizeAspect
        displayLayer.backgroundColor = CGColor(gray: 0, alpha: 1)

        // Outgoing messages go through one queue so they leave in the order they
        // were produced — touch-down, moves and touch-up must not be reordered.
        let (stream, continuation) = AsyncStream.makeStream(of: String.self)
        sendContinuation = continuation
        sendTask = Task.detached { [signaling] in
            for await text in stream {
                try? await signaling.sendText(text)
            }
        }
        readTask = Task.detached { [weak self] in
            await self?.readLoop()
        }
    }

    deinit {
        readTask?.cancel()
        sendTask?.cancel()
    }

    func sendInputEvent(_ event: InputEventMessage) {
        guard let data = try? JSONEncoder().encode(event) else { return }
        sendContinuation?.yield(String(decoding: data, as: UTF8.self))
    }

    func close() {
        readTask?.cancel()
        sendContinuation?.finish()
        signaling.close()
        displayLayer.flushAndRemoveImage()
    }

    // MARK: - Reading

    private func readLoop() async {
        do {
            while !Task.isCancelled {
                switch try await signaling.receiveMessage() {
                case .text(let text):
                    handleControl(text)
                case .binary(let data):
                    handleVideo(data)
                }
            }
        } catch {
            finish("Host disconnected")
        }
    }

    private func handleControl(_ text: String) {
        let data = Data(text.utf8)
        switch decodeMessageType(from: data) {
        case .displayInfo:
            if let info = try? JSONDecoder().decode(DisplayInfoMessage.self, from: data) {
                DispatchQueue.main.async { self.displayInfo = info }
            }
        case .bye:
            finish("Host disconnected")
        default:
            break // hello needs no reaction; the rest isn't expected inbound.
        }
    }

    private func handleVideo(_ data: Data) {
        guard let packet = parseVideoPacket(from: data) else { return }

        // The layer can fail (e.g. after the app was backgrounded); recovery is
        // to flush it and start again from the next keyframe.
        if displayLayer.status == .failed || displayLayer.requiresFlushToResumeDecoding {
            displayLayer.flush()
            waitingForKeyframe = true
        }
        if waitingForKeyframe {
            guard packet.isKeyframe else {
                requestKeyframe()
                return
            }
        }

        let unit = H264AnnexB.parse(packet.accessUnit)
        guard let sample = factory.makeSampleBuffer(from: unit, presentationTimeMicros: packet.presentationTimeMicros)
        else {
            waitingForKeyframe = true
            requestKeyframe()
            return
        }
        waitingForKeyframe = false
        displayLayer.enqueue(sample)
    }

    /// Decoding can only begin at a keyframe; ask for one, at most once a second.
    private func requestKeyframe() {
        guard Date().timeIntervalSince(lastKeyframeRequest) > 1 else { return }
        lastKeyframeRequest = Date()
        guard let data = try? JSONEncoder().encode(KeyframeRequestMessage()) else { return }
        sendContinuation?.yield(String(decoding: data, as: UTF8.self))
    }

    private func finish(_ reason: String) {
        DispatchQueue.main.async {
            guard !self.finished else { return }
            self.finished = true
            self.statusDescription = reason
            self.onFinished?()
        }
    }
}
