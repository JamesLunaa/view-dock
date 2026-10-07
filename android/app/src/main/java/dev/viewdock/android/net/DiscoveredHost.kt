// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 James Luna

package dev.viewdock.android.net

import dev.viewdock.android.protocol.ProtocolVersion

/**
 * A view-dock host found on the LAN over mDNS (`_viewdock._tcp`, advertised by
 * `host/transport/discovery.py`). Anyone on the network can advertise this
 * service, so a hit is a suggestion, never proof of trust.
 */
data class DiscoveredHost(
    val name: String,
    val address: String,
    val port: Int,
    val protocolVersion: String?,
) {
    /** Two hosts with the same hostname on different addresses must not collide in a list. */
    val key: String get() = "$name@$address:$port"

    val compatible: Boolean get() = HostRecords.isCompatible(protocolVersion)

    /** What the picker shows: the host's own name, falling back to its address. */
    val title: String get() = name.ifBlank { address }
}

object HostRecords {
    const val SERVICE_TYPE = "_viewdock._tcp"
    const val KEY_PROTOCOL_VERSION = "protocol_version"
    const val KEY_NAME = "name"

    /** Reads a TXT attribute written by the host; absent or empty means null. */
    fun txt(attributes: Map<String, ByteArray?>, key: String): String? =
        attributes[key]?.toString(Charsets.UTF_8)?.takeIf { it.isNotBlank() }

    /**
     * A host is usable when its protocol major version matches ours (see
     * `protocol/PROTOCOL.md`, "Versioning"). A host that does not say is given
     * the benefit of the doubt, as the hello handshake rejects it anyway.
     */
    fun isCompatible(hostVersion: String?, ours: String = ProtocolVersion.CURRENT): Boolean {
        val theirs = major(hostVersion) ?: return hostVersion.isNullOrBlank()
        return theirs == major(ours)
    }

    private fun major(version: String?): Int? = version?.substringBefore('.')?.trim()?.toIntOrNull()

    /** IPv4 only: the host advertises IPv4, and a bare or link-local IPv6 address does not fit the `ws://host:port` URL. */
    fun preferredAddress(addresses: List<String>): String? =
        addresses.firstOrNull { it.count { c -> c == '.' } == 3 && !it.contains(':') }
}
