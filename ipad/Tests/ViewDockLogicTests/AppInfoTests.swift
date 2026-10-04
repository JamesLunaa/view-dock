// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 James Luna

import XCTest
@testable import ViewDockLogic

final class AppInfoTests: XCTestCase {
    func testVersionIncludesTheBuildNumberWhenItDiffers() {
        let info: [String: Any] = ["CFBundleShortVersionString": "2.0.0", "CFBundleVersion": "7"]
        XCTAssertEqual(AppInfo.versionDescription(from: info), "Version 2.0.0 (7)")
    }

    func testVersionOmitsTheBuildNumberWhenItMatches() {
        let info: [String: Any] = ["CFBundleShortVersionString": "2.0.0", "CFBundleVersion": "2.0.0"]
        XCTAssertEqual(AppInfo.versionDescription(from: info), "Version 2.0.0")
    }

    func testVersionWithoutABuildNumber() {
        XCTAssertEqual(AppInfo.versionDescription(from: ["CFBundleShortVersionString": "2.0.0"]), "Version 2.0.0")
    }

    func testVersionIsUnknownWhenThePlistHasNone() {
        XCTAssertEqual(AppInfo.versionDescription(from: nil), "Version unknown")
        XCTAssertEqual(AppInfo.versionDescription(from: [:]), "Version unknown")
        XCTAssertEqual(AppInfo.versionDescription(from: ["CFBundleVersion": "7"]), "Version unknown")
    }

    func testTheCreditAndSourceLink() {
        XCTAssertEqual(AppInfo.copyright, "Copyright (C) 2026 James Luna")
        XCTAssertEqual(AppInfo.sourceURL.absoluteString, "https://github.com/JamesLunaa/view-dock")
    }

    func testTheNoticesTheGPLRequiresAreStated() {
        XCTAssertTrue(AppInfo.freeSoftwareNotice.contains("GNU General Public License"))
        XCTAssertTrue(AppInfo.freeSoftwareNotice.contains("version 3"))
        XCTAssertTrue(AppInfo.noWarrantyNotice.contains("ABSOLUTELY NO WARRANTY"))
    }

    // MARK: - The files actually bundled into the app

    /// `ipad/Resources/Legal/<name>.txt`, located relative to this test file.
    private func bundled(_ name: String) throws -> String {
        let root = URL(fileURLWithPath: #filePath)   // …/ipad/Tests/ViewDockLogicTests/AppInfoTests.swift
            .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        return try String(contentsOf: root.appendingPathComponent("Resources/\(AppInfo.legalSubdirectory)/\(name).txt"), encoding: .utf8)
    }

    func testTheFullGPLIsBundled() throws {
        let gpl = try bundled(AppInfo.licenseResource)
        XCTAssertTrue(gpl.contains("GNU GENERAL PUBLIC LICENSE"))
        XCTAssertTrue(gpl.contains("Version 3, 29 June 2007"))
    }

    func testTheBundledNoticesCarryTheCreditTheNoWarrantyStatementAndTheWebRTCLicense() throws {
        let notices = try bundled(AppInfo.noticesResource)
        XCTAssertTrue(notices.contains(AppInfo.copyright))
        XCTAssertTrue(notices.contains("ABSOLUTELY NO WARRANTY"))
        XCTAssertTrue(notices.contains(AppInfo.sourceURL.absoluteString))
        // BSD requires its copyright notice to travel with the binary.
        XCTAssertTrue(notices.contains("Copyright (c) 2011, The WebRTC project authors"))
        // The iPad app doesn't contain the Android-only libraries.
        XCTAssertFalse(notices.contains("Java-WebSocket"))
    }
}
