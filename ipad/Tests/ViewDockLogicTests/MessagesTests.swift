// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 James Luna

import XCTest
@testable import ViewDockLogic

final class MessagesTests: XCTestCase {
    private func json(_ value: some Encodable) throws -> [String: Any] {
        let data = try JSONEncoder().encode(value)
        return try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
    }

    func testHelloAnnouncesTheIPadAtTheCurrentVersion() throws {
        // Same shape the host's wired-hello detection expects.
        let object = try json(HelloMessage(role: .ipad, protocolVersion: ProtocolVersion.current))
        XCTAssertEqual(object["type"] as? String, "hello")
        XCTAssertEqual(object["role"] as? String, "ipad")
        XCTAssertEqual(object["protocol_version"] as? String, "1.2")
        XCTAssertEqual(Set(object.keys), ["type", "role", "protocol_version"])
    }

    func testKeyframeRequestMatchesTheHostSchema() throws {
        // protocol/schema/keyframe_request.json is additionalProperties:false.
        let object = try json(KeyframeRequestMessage())
        XCTAssertEqual(object as? [String: String], ["type": "keyframe_request"])
    }

    func testInputEventHasExactlyTheFieldsTheHostSchemaAllows() throws {
        let event = InputEventMessage(kind: .touchMove, x: 0.25, y: 0.75, pressure: 0, timestampMs: 1_732_999_999_123)
        let object = try json(event)
        XCTAssertEqual(Set(object.keys), ["type", "kind", "x", "y", "pressure", "timestamp_ms"])
        XCTAssertEqual(object["kind"] as? String, "touch_move")
    }

    func testDecodesDisplayInfoFromTheHost() throws {
        let raw = Data(#"{"type":"display_info","width":1180,"height":820,"refresh_hz":60,"orientation":"landscape"}"#.utf8)
        XCTAssertEqual(decodeMessageType(from: raw), .displayInfo)
        let info = try JSONDecoder().decode(DisplayInfoMessage.self, from: raw)
        XCTAssertEqual(info.width, 1180)
        XCTAssertEqual(info.orientation, .landscape)
    }

    func testMessageTypeDetection() {
        XCTAssertEqual(decodeMessageType(from: Data(#"{"type":"hello","role":"host","protocol_version":"1.2"}"#.utf8)), .hello)
        XCTAssertEqual(decodeMessageType(from: Data(#"{"type":"keyframe_request"}"#.utf8)), .keyframeRequest)
        XCTAssertNil(decodeMessageType(from: Data("not json".utf8)))
        XCTAssertNil(decodeMessageType(from: Data(#"{"sdp":"v=0","type":"offer"}"#.utf8))) // an SDP envelope is not a protocol message
    }

    // MARK: - Wired video frames (same bytes as the host and Android tests)

    func testParsesAWiredVideoFrameHeader() throws {
        let frame = Data([0x01, 0x01, 0, 0, 0, 0, 0, 0x0F, 0x42, 0x40, 0x11, 0x22])
        let packet = try XCTUnwrap(parseVideoPacket(from: frame))
        XCTAssertTrue(packet.isKeyframe)
        XCTAssertEqual(packet.presentationTimeMicros, 1_000_000)
        XCTAssertEqual(packet.accessUnit, Data([0x11, 0x22]))
    }

    func testParsingWorksOnADataSliceWithANonZeroStartIndex() throws {
        let backing = Data([0xFF, 0xFF, 0x01, 0x00, 0, 0, 0, 0, 0, 0, 0, 1, 0xAB])
        let packet = try XCTUnwrap(parseVideoPacket(from: backing.dropFirst(2)))
        XCTAssertFalse(packet.isKeyframe)
        XCTAssertEqual(packet.presentationTimeMicros, 1)
        XCTAssertEqual(packet.accessUnit, Data([0xAB]))
    }

    func testMalformedWiredFramesAreIgnored() {
        XCTAssertNil(parseVideoPacket(from: Data([1, 2, 3])))
        XCTAssertNil(parseVideoPacket(from: Data([0x7F] + [UInt8](repeating: 0, count: 11)))) // unknown frame type
    }
}
