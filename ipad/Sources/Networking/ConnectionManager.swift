import Foundation

/// Owns the connection lifecycle: waits for the host to reach the iPad over
/// either transport (the iPad side doesn't distinguish Wi-Fi from USB — the
/// usbmuxd tunnel on the host side makes USB look like a plain socket
/// connection to this app, see `host/transport/usb.py`) and drives
/// `WebRTCClient` once a signaling connection is established.
@MainActor
final class ConnectionManager: ObservableObject {
    @Published private(set) var statusDescription = "Waiting for host…"

    private var webRTCClient: WebRTCClient?

    func start() {
        // TODO: start a signaling listener (e.g. WebSocket server) that the
        // host connects to directly (Wi-Fi) or through the usbmuxd tunnel
        // (USB), then hand the connection to WebRTCClient.
    }

    func stop() {
        webRTCClient?.close()
        webRTCClient = nil
    }
}
