// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 James Luna

import Foundation

/// A view-dock host found on the LAN over Bonjour (`_viewdock._tcp`, advertised by
/// `host/transport/discovery.py`). Anyone on the network can advertise this service,
/// so a hit is a suggestion, never proof of trust.
struct DiscoveredHost: Equatable, Identifiable {
    let name: String
    let address: String
    let port: UInt16
    let protocolVersion: String?

    /// Two hosts with the same hostname on different addresses must not collide in a list.
    var id: String { "\(name)@\(address):\(port)" }

    var isCompatible: Bool { HostRecords.isCompatible(hostVersion: protocolVersion) }
}

enum HostRecords {
    static let serviceType = "_viewdock._tcp"
    static let keyProtocolVersion = "protocol_version"
    static let keyName = "name"

    /// Reads a TXT value written by the host; absent or blank means nil.
    static func txt(_ record: [String: String], _ key: String) -> String? {
        guard let value = record[key], !value.trimmingCharacters(in: .whitespaces).isEmpty else { return nil }
        return value
    }

    /// A host is usable when its protocol major version matches ours (see
    /// `protocol/PROTOCOL.md`, "Versioning"). A host that does not say is given the
    /// benefit of the doubt, since the hello handshake rejects it anyway.
    static func isCompatible(hostVersion: String?, ours: String = ProtocolVersion.current) -> Bool {
        guard let hostVersion, !hostVersion.isEmpty else { return true }
        guard let theirs = major(hostVersion) else { return false }
        return theirs == major(ours)
    }

    private static func major(_ version: String) -> Int? {
        Int(version.split(separator: ".").first.map(String.init)?.trimmingCharacters(in: .whitespaces) ?? "")
    }
}
