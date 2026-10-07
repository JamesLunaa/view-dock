// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 James Luna

package dev.viewdock.android.net

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class HostRecordsTest {
    @Test
    fun sameMajorVersionIsCompatibleDifferentMajorIsNot() {
        assertTrue(HostRecords.isCompatible("1.2", ours = "1.2"))
        assertTrue(HostRecords.isCompatible("1.9", ours = "1.2"))
        assertFalse(HostRecords.isCompatible("2.0", ours = "1.2"))
    }

    @Test
    fun missingVersionIsGivenTheBenefitOfTheDoubtButGarbageIsNot() {
        assertTrue(HostRecords.isCompatible(null, ours = "1.2"))
        assertTrue(HostRecords.isCompatible("", ours = "1.2"))
        assertFalse(HostRecords.isCompatible("banana", ours = "1.2"))
    }

    @Test
    fun txtValuesAreDecodedAndEmptyOnesAreAbsent() {
        val attributes = mapOf<String, ByteArray?>(
            "name" to "arch-box".toByteArray(),
            "protocol_version" to ByteArray(0),
            "flag" to null,
        )
        assertEquals("arch-box", HostRecords.txt(attributes, "name"))
        assertNull(HostRecords.txt(attributes, "protocol_version"))
        assertNull(HostRecords.txt(attributes, "flag"))
        assertNull(HostRecords.txt(attributes, "missing"))
    }

    @Test
    fun prefersAnIpv4AddressAndSkipsScopedIpv6() {
        assertEquals("192.168.1.5", HostRecords.preferredAddress(listOf("fe80::1%wlan0", "192.168.1.5")))
        assertNull(HostRecords.preferredAddress(listOf("fe80::1%wlan0")))
    }

    @Test
    fun twoHostsWithTheSameNameOnDifferentAddressesHaveDifferentKeys() {
        val a = DiscoveredHost("laptop", "192.168.1.5", 8765, "1.2")
        val b = DiscoveredHost("laptop", "192.168.1.6", 8765, "1.2")
        assertNotEquals(a.key, b.key)
        assertEquals("192.168.1.5", DiscoveredHost("", "192.168.1.5", 8765, null).title)
    }
}
