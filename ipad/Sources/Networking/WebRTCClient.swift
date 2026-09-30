import Foundation
import WebRTC

/// Peer connection to the host: receives the video track and exchanges
/// `control` data channel messages per `protocol/PROTOCOL.md`.
final class WebRTCClient: NSObject {
    private let peerConnection: RTCPeerConnection
    private var controlChannel: RTCDataChannel?

    override init() {
        let factory = RTCPeerConnectionFactory()
        let config = RTCConfiguration()
        let constraints = RTCMediaConstraints(
            mandatoryConstraints: nil,
            optionalConstraints: nil
        )
        // Force-unwrap is safe here: RTCPeerConnectionFactory only returns
        // nil for an invalid RTCConfiguration, and `config` above is default.
        self.peerConnection = factory.peerConnection(
            with: config,
            constraints: constraints,
            delegate: nil
        )!
        super.init()
        self.peerConnection.delegate = self
    }

    func close() {
        peerConnection.close()
    }

    // TODO: offer/answer exchange via ConnectionManager's signaling
    // connection, ICE candidate handling, and wiring the remote video track
    // to a renderable view for ContentView.
}

extension WebRTCClient: RTCPeerConnectionDelegate {
    func peerConnection(_ peerConnection: RTCPeerConnection, didChange stateChanged: RTCSignalingState) {}
    func peerConnection(_ peerConnection: RTCPeerConnection, didAdd stream: RTCMediaStream) {}
    func peerConnection(_ peerConnection: RTCPeerConnection, didRemove stream: RTCMediaStream) {}
    func peerConnectionShouldNegotiate(_ peerConnection: RTCPeerConnection) {}
    func peerConnection(_ peerConnection: RTCPeerConnection, didChange newState: RTCIceConnectionState) {}
    func peerConnection(_ peerConnection: RTCPeerConnection, didChange newState: RTCIceGatheringState) {}
    func peerConnection(_ peerConnection: RTCPeerConnection, didGenerate candidate: RTCIceCandidate) {}
    func peerConnection(_ peerConnection: RTCPeerConnection, didRemove candidates: [RTCIceCandidate]) {}
    func peerConnection(_ peerConnection: RTCPeerConnection, didOpen dataChannel: RTCDataChannel) {
        controlChannel = dataChannel
        // TODO: send `hello`, then dispatch incoming messages by
        // MessageType (see Protocol/Messages.swift).
    }
}
