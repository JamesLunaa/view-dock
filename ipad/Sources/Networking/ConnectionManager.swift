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
    private var isListeningForUsb = false

    func start() {
        isListeningForUsb = true
        Task { await listenForUsb() }
    }

    func connectOverWifi(hostAddress: String) {
        Task { await connectWifi(hostAddress: hostAddress) }
    }

    func stop() {
        isListeningForUsb = false
        webRTCClient?.close()
        webRTCClient = nil
        usbSignaling?.close()
        usbSignaling = nil
        wifiSignaling?.close()
        wifiSignaling = nil
    }

    /// Retries on failure rather than giving up after one bad connection
    /// attempt — a single malformed/stray connection (not even necessarily
    /// from the real host; anything that completes the TCP handshake but
    /// fails ours) would otherwise permanently kill USB listening until the
    /// app is relaunched, while the UI kept showing "Waiting for host…" with
    /// no indication anything had gone wrong. Hit this firsthand debugging
    /// against a `curl` probe that wasn't a real WebSocket handshake.
    private func listenForUsb() async {
        while isListeningForUsb {
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
                guard isListeningForUsb else { return }
                try await negotiate(using: signaling)
                return
            } catch {
                guard isListeningForUsb else { return }
                statusDescription = "USB listener retrying after error: \(error.localizedDescription)"
                usbSignaling?.close()
                usbSignaling = nil
                try? await Task.sleep(for: .seconds(1))
            }
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
