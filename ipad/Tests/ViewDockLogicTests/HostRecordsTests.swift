// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 James Luna

import XCTest
@testable import ViewDockLogic

final class HostRecordsTests: XCTestCase {
    func testSameMajorVersionIsCompatibleDifferentMajorIsNot() {
        XCTAssertTrue(HostRecords.isCompatible(hostVersion: "1.2", ours: "1.2"))
        XCTAssertTrue(HostRecords.isCompatible(hostVersion: "1.9", ours: "1.2"))
        XCTAssertFalse(HostRecords.isCompatible(hostVersion: "2.0", ours: "1.2"))
    }

    func testMissingVersionGetsTheBenefitOfTheDoubtButGarbageDoesNot() {
        XCTAssertTrue(HostRecords.isCompatible(hostVersion: nil, ours: "1.2"))
        XCTAssertTrue(HostRecords.isCompatible(hostVersion: "", ours: "1.2"))
        XCTAssertFalse(HostRecords.isCompatible(hostVersion: "banana", ours: "1.2"))
    }

    func testTxtValuesAreReadAndBlankOnesAreAbsent() {
        let record = ["name": "arch-box", "protocol_version": "  "]
        XCTAssertEqual(HostRecords.txt(record, "name"), "arch-box")
        XCTAssertNil(HostRecords.txt(record, "protocol_version"))
        XCTAssertNil(HostRecords.txt(record, "missing"))
    }

    func testTwoHostsWithTheSameNameOnDifferentAddressesHaveDifferentIds() {
        let a = DiscoveredHost(name: "laptop", address: "192.168.1.5", port: 8765, protocolVersion: "1.2")
        let b = DiscoveredHost(name: "laptop", address: "192.168.1.6", port: 8765, protocolVersion: "1.2")
        XCTAssertNotEqual(a.id, b.id)
        XCTAssertTrue(a.isCompatible)
    }

    func testServiceTypeMatchesTheHostAndInfoPlist() {
        // host/transport/discovery.py advertises "_viewdock._tcp.local."; project.yml's NSBonjourServices lists this.
        XCTAssertEqual(HostRecords.serviceType, "_viewdock._tcp")
    }
}
