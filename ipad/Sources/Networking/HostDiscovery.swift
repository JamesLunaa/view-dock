// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 James Luna

import Foundation
import Network

/// Browses the LAN for view-dock hosts (`_viewdock._tcp`, see `HostRecords`). Browsing
/// keeps the Wi-Fi radio busy, so `start()` when the connect screen appears and
/// `stop()` when it goes away. The first browse triggers the Local Network
/// permission prompt (`NSLocalNetworkUsageDescription` / `NSBonjourServices` in
/// `project.yml`).
@MainActor
final class HostDiscovery: ObservableObject {
    @Published private(set) var hosts: [DiscoveredHost] = []
    @Published private(set) var isSearching = false
    /// Set when browsing cannot run (typically Local Network access is off).
    @Published private(set) var unavailableReason: String?

    private var browser: NWBrowser?
    private var found: [String: DiscoveredHost] = [:]      // by Bonjour service name
    private var resolving: [String: Task<Void, Never>] = [:]

    func start() {
        guard browser == nil else { return }
        unavailableReason = nil
        let browser = NWBrowser(for: .bonjourWithTXTRecord(type: HostRecords.serviceType, domain: nil), using: .tcp)
        browser.stateUpdateHandler = { [weak self] state in
            Task { @MainActor in self?.handle(state: state) }
        }
        browser.browseResultsChangedHandler = { [weak self] _, changes in
            Task { @MainActor in self?.handle(changes: changes) }
        }
        self.browser = browser
        isSearching = true
        browser.start(queue: .main)
    }

    func stop() {
        browser?.cancel()
        browser = nil
        isSearching = false
        resolving.values.forEach { $0.cancel() }
        resolving = [:]
        found = [:]
        publish()
    }

    private func handle(state: NWBrowser.State) {
        switch state {
        case .failed, .waiting:
            // `.waiting` is what a denied Local Network permission looks like.
            unavailableReason = "Host discovery is unavailable — check Settings ▸ Privacy ▸ Local Network."
        case .ready:
            unavailableReason = nil
        default:
            break
        }
    }

    private func handle(changes: Set<NWBrowser.Result.Change>) {
        for change in changes {
            switch change {
            case .added(let result), .changed(old: _, new: let result, flags: _):
                resolve(result)
            case .removed(let result):
                guard let name = Self.serviceName(of: result) else { continue }
                resolving.removeValue(forKey: name)?.cancel()
                if found.removeValue(forKey: name) != nil { publish() }
            default:
                break
            }
        }
    }

    private func resolve(_ result: NWBrowser.Result) {
        guard let name = Self.serviceName(of: result) else { return }
        var txt: [String: String] = [:]
        if case .bonjour(let record) = result.metadata { txt = record.dictionary }
        resolving[name]?.cancel()
        resolving[name] = Task { [weak self] in
            guard let (address, port) = await Self.resolveAddress(of: result.endpoint), !Task.isCancelled else { return }
            guard let self, self.browser != nil else { return }
            self.found[name] = DiscoveredHost(
                name: HostRecords.txt(txt, HostRecords.keyName) ?? name,
                address: address,
                port: port,
                protocolVersion: HostRecords.txt(txt, HostRecords.keyProtocolVersion)
            )
            self.publish()
        }
    }

    private func publish() {
        var seen = Set<String>()
        hosts = found.values
            .filter { seen.insert($0.id).inserted }
            .sorted { $0.name.localizedCaseInsensitiveCompare($1.name) == .orderedAscending }
    }

    private static func serviceName(of result: NWBrowser.Result) -> String? {
        if case .service(let name, _, _, _) = result.endpoint { return name }
        return nil
    }

    /// Opens a TCP connection to the service just long enough to learn which IPv4
    /// address and port it resolved to. The host's WebSocket server drops it
    /// without ever treating it as a client (no handshake is sent).
    private nonisolated static func resolveAddress(of endpoint: NWEndpoint) async -> (String, UInt16)? {
        let parameters = NWParameters.tcp
        (parameters.defaultProtocolStack.internetProtocol as? NWProtocolIP.Options)?.version = .v4
        let connection = NWConnection(to: endpoint, using: parameters)
        let queue = DispatchQueue(label: "viewdock.resolve")
        return await withCheckedContinuation { continuation in
            var finished = false // only touched on `queue`
            func finish(_ value: (String, UInt16)?) {
                guard !finished else { return }
                finished = true
                connection.cancel()
                continuation.resume(returning: value)
            }
            connection.stateUpdateHandler = { state in
                switch state {
                case .ready:
                    if case .hostPort(let host, let port)? = connection.currentPath?.remoteEndpoint,
                       case .ipv4(let address) = host {
                        finish((address.rawValue.map(String.init).joined(separator: "."), port.rawValue))
                    } else {
                        finish(nil)
                    }
                case .failed, .cancelled:
                    finish(nil)
                default:
                    break
                }
            }
            connection.start(queue: queue)
            queue.asyncAfter(deadline: .now() + 5) { finish(nil) }
        }
    }
}
