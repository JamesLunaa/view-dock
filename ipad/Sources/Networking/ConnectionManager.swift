// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 James Luna

import Foundation
import Network

/// Owns the connection lifecycle and drives `WebRTCClient` once signaling
/// completes. Mirrors `host/main.py`'s transport selection: USB is
/// host-initiated through the `iproxy` tunnel (see `host/transport/usb.py`),
/// so this always starts a USB listener in the background; Wi-Fi requires
/// hosts are found by `HostDiscovery` (Bonjour) and offered to the user,
/// and the address can still be typed in.
@MainActor
final class ConnectionManager: ObservableObject {
    @Published private(set) var statusDescription = "Waiting for host…"
    @Published private(set) var webRTCClient: WebRTCClient?
    @Published private(set) var wiredClient: WiredClient?

    private var usbSignaling: UsbSignaling?
    private var wifiSignaling: WifiSignaling?
    private var isListeningForUsb = false

    func start() {
        isListeningForUsb = true
        Task { await listenForUsb() }
    }

    func connectOverWifi(hostAddress: String, port: UInt16 = 8765) {
        Task { await connectWifi(hostAddress: hostAddress, port: port) }
    }

    /// Connects to a host picked from the discovery list.
    func connect(to host: DiscoveredHost) {
        connectOverWifi(hostAddress: host.address, port: host.port)
    }

    func stop() {
        isListeningForUsb = false
        webRTCClient?.close()
        webRTCClient = nil
        wiredClient?.close()
        wiredClient = nil
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

                // Announce wired-stream support; a host that has it answers with
                // its own `hello` and the connection becomes the whole session.
                // Anything else first (an SDP offer) means plain WebRTC.
                try await signaling.announceWiredSupport()
                let first = try await signaling.peekFirstText()
                if decodeMessageType(from: Data(first.utf8)) == .hello {
                    startWiredSession(over: signaling)
                } else {
                    try await negotiate(using: signaling)
                }
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

    private func connectWifi(hostAddress: String, port: UInt16) async {
        do {
            let signaling = WifiSignaling()
            wifiSignaling = signaling
            statusDescription = "Connecting to \(hostAddress)…"
            try await signaling.connect(hostAddress: hostAddress, port: port)
            try await negotiate(using: signaling)
        } catch {
            statusDescription = "Wi-Fi connect failed: \(error.localizedDescription)"
        }
    }

    private func startWiredSession(over signaling: UsbSignaling) {
        guard webRTCClient == nil, wiredClient == nil else { return }
        let client = WiredClient(signaling: signaling)
        client.onFinished = { [weak self] in
            Task { @MainActor in self?.wiredSessionEnded() }
        }
        statusDescription = "Connected over USB"
        wiredClient = client
    }

    /// The host loops back to "waiting for device" when a session ends, so do
    /// the same here: drop the dead session and listen for the next host.
    private func wiredSessionEnded() {
        guard wiredClient != nil else { return }
        wiredClient?.close()
        wiredClient = nil
        usbSignaling?.close()
        usbSignaling = nil
        statusDescription = "Disconnected — waiting for host…"
        guard isListeningForUsb else { return }
        Task { await listenForUsb() }
    }

    private func negotiate(using channel: SignalingChannel) async throws {
        guard webRTCClient == nil, wiredClient == nil else { return } // USB and Wi-Fi could race; first one wins.
        let client = WebRTCClient()
        statusDescription = "Negotiating…"
        try await client.negotiate(using: channel)
        webRTCClient = client
    }
}
