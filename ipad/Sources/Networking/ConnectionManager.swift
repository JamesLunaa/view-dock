import Foundation
import Network

/// Owns the connection lifecycle and drives `WebRTCClient` once signaling
/// completes. Mirrors `host/main.py`'s transport selection: USB is
/// host-initiated through the `iproxy` tunnel (see `host/transport/usb.py`),
/// so this always starts a USB listener in the background; Wi-Fi requires
/// the user to enter the host's address since there's no discovery yet
/// (see TODO/TODO.md).
@MainActor
final class ConnectionManager: ObservableObject {
    @Published private(set) var statusDescription = "Waiting for host…"
    @Published private(set) var webRTCClient: WebRTCClient?

    private var usbSignaling: UsbSignaling?
    private var wifiSignaling: WifiSignaling?

    func start() {
        Task { await listenForUsb() }
    }

    func connectOverWifi(hostAddress: String) {
        Task { await connectWifi(hostAddress: hostAddress) }
    }

    func stop() {
        webRTCClient?.close()
        webRTCClient = nil
        usbSignaling?.close()
        usbSignaling = nil
        wifiSignaling?.close()
        wifiSignaling = nil
    }

    private func listenForUsb() async {
        do {
            let signaling = try UsbSignaling()
            usbSignaling = signaling
            statusDescription = "Waiting for USB connection…"
            try await signaling.waitForHost { [weak self] error in
                Task { @MainActor in
                    self?.statusDescription =
                        "USB listener not ready (\(error.debugDescription)) — check "
                        + "Settings > Privacy & Security > Local Network for ViewDock"
                }
            }
            try await negotiate(using: signaling)
        } catch {
            statusDescription = "USB listener failed: \(error.localizedDescription)"
        }
    }

    private func connectWifi(hostAddress: String) async {
        do {
            let signaling = WifiSignaling()
            wifiSignaling = signaling
            statusDescription = "Connecting to \(hostAddress)…"
            try await signaling.connect(hostAddress: hostAddress)
            try await negotiate(using: signaling)
        } catch {
            statusDescription = "Wi-Fi connect failed: \(error.localizedDescription)"
        }
    }

    private func negotiate(using channel: SignalingChannel) async throws {
        guard webRTCClient == nil else { return } // USB and Wi-Fi could race; first one wins.
        let client = WebRTCClient()
        statusDescription = "Negotiating…"
        try await client.negotiate(using: channel)
        webRTCClient = client
    }
}
