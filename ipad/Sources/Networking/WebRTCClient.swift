import Foundation
import WebRTC

/// Peer connection to the host: receives the video track and exchanges
/// `control` data channel messages per `protocol/PROTOCOL.md`. The host
/// always creates the offer and the data channel (see
/// `host/streaming/webrtc_session.py`), so this side only ever answers and
/// waits for the channel to arrive via `didOpen`.
@MainActor
final class WebRTCClient: NSObject, ObservableObject {
    @Published private(set) var remoteVideoTrack: RTCVideoTrack?
    @Published private(set) var displayInfo: DisplayInfoMessage?
    @Published private(set) var statusDescription = "Negotiating…"

    private let peerConnection: RTCPeerConnection
    private var controlChannel: RTCDataChannel?
    private var iceGatheringContinuation: CheckedContinuation<Void, Never>?

    override init() {
        let factory = RTCPeerConnectionFactory()
        let config = RTCConfiguration()
        let constraints = RTCMediaConstraints(mandatoryConstraints: nil, optionalConstraints: nil)
        // Force-unwrap is safe here: RTCPeerConnectionFactory only returns
        // nil for an invalid RTCConfiguration, and `config` above is default.
        self.peerConnection = factory.peerConnection(with: config, constraints: constraints, delegate: nil)!
        super.init()
        self.peerConnection.delegate = self
    }

    func negotiate(using channel: SignalingChannel) async throws {
        let offer = try await channel.receiveOffer()
        try await peerConnection.setRemoteDescription(RTCSessionDescription(type: .offer, sdp: offer.sdp))

        let constraints = RTCMediaConstraints(mandatoryConstraints: nil, optionalConstraints: nil)
        let answer = try await peerConnection.answer(for: constraints)
        try await peerConnection.setLocalDescription(answer)

        await waitForIceGatheringComplete()

        guard let local = peerConnection.localDescription else {
            throw SignalingError.unexpectedMessage
        }
        try await channel.sendAnswer(SDPEnvelope(sdp: local.sdp, type: "answer"))
        statusDescription = "Connected"
    }

    func sendInputEvent(_ event: InputEventMessage) {
        guard let controlChannel, controlChannel.readyState == .open,
              let data = try? JSONEncoder().encode(event)
        else { return }
        controlChannel.sendData(RTCDataBuffer(data: data, isBinary: false))
    }

    func close() {
        controlChannel = nil
        peerConnection.close()
    }

    private func waitForIceGatheringComplete() async {
        if peerConnection.iceGatheringState == .complete { return }
        await withCheckedContinuation { continuation in
            self.iceGatheringContinuation = continuation
        }
    }

    private func handleControlMessage(_ data: Data) {
        guard let type = decodeMessageType(from: data) else { return }
        switch type {
        case .hello:
            break // Host identifies itself; nothing to react to yet.
        case .displayInfo:
            if let message = try? JSONDecoder().decode(DisplayInfoMessage.self, from: data) {
                displayInfo = message
            }
        case .bye:
            statusDescription = "Host disconnected"
            close()
        case .inputEvent, .stats, .keyframeRequest:
            break // Not expected inbound on this side.
        }
    }
}

extension WebRTCClient: RTCPeerConnectionDelegate {
    nonisolated func peerConnection(_ peerConnection: RTCPeerConnection, didChange stateChanged: RTCSignalingState) {}

    nonisolated func peerConnection(_ peerConnection: RTCPeerConnection, didAdd stream: RTCMediaStream) {
        let track = stream.videoTracks.first
        Task { @MainActor in self.remoteVideoTrack = track }
    }

    nonisolated func peerConnection(_ peerConnection: RTCPeerConnection, didRemove stream: RTCMediaStream) {
        Task { @MainActor in self.remoteVideoTrack = nil }
    }

    nonisolated func peerConnectionShouldNegotiate(_ peerConnection: RTCPeerConnection) {}

    nonisolated func peerConnection(_ peerConnection: RTCPeerConnection, didChange newState: RTCIceConnectionState) {
        Task { @MainActor in self.statusDescription = "ICE: \(newState.description)" }
    }

    nonisolated func peerConnection(_ peerConnection: RTCPeerConnection, didChange newState: RTCIceGatheringState) {
        guard newState == .complete else { return }
        Task { @MainActor in
            self.iceGatheringContinuation?.resume()
            self.iceGatheringContinuation = nil
        }
    }

    nonisolated func peerConnection(_ peerConnection: RTCPeerConnection, didGenerate candidate: RTCIceCandidate) {}
    nonisolated func peerConnection(_ peerConnection: RTCPeerConnection, didRemove candidates: [RTCIceCandidate]) {}

    nonisolated func peerConnection(_ peerConnection: RTCPeerConnection, didOpen dataChannel: RTCDataChannel) {
        Task { @MainActor in
            self.controlChannel = dataChannel
            dataChannel.delegate = self
        }
    }
}

extension WebRTCClient: RTCDataChannelDelegate {
    nonisolated func dataChannelDidChangeState(_ dataChannel: RTCDataChannel) {}

    nonisolated func dataChannel(_ dataChannel: RTCDataChannel, didReceiveMessageWith buffer: RTCDataBuffer) {
        let data = buffer.data
        Task { @MainActor in self.handleControlMessage(data) }
    }
}
