// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 James Luna

import XCTest
@testable import ViewDockLogic

final class WebSocketFramingTests: XCTestCase {
    func testSmallFrameHeader() {
        let frame = WebSocketFraming.encode(opcode: WebSocketOpcode.text, payload: Data("hi".utf8))
        XCTAssertEqual(Array(frame), [0x81, 2, 0x68, 0x69])
    }

    func testMediumAndLargeLengthEncodings() {
        XCTAssertEqual(WebSocketFraming.encodeLength(125), [125])
        XCTAssertEqual(WebSocketFraming.encodeLength(126), [126, 0, 126])
        XCTAssertEqual(WebSocketFraming.encodeLength(0xFFFF), [126, 0xFF, 0xFF])
        XCTAssertEqual(WebSocketFraming.encodeLength(0x10000), [127, 0, 0, 0, 0, 0, 1, 0, 0])
    }

    func testUnmaskIsItsOwnInverse() {
        let original: [UInt8] = Array(0..<37)
        var data = original
        let key: [UInt8] = [0xDE, 0xAD, 0xBE, 0xEF]
        WebSocketFraming.unmask(&data, key: key)
        XCTAssertNotEqual(data, original)
        WebSocketFraming.unmask(&data, key: key)
        XCTAssertEqual(data, original)
    }

    func testUnmaskMatchesTheRFCDefinition() {
        var data: [UInt8] = [0x37, 0xFA, 0x21, 0x3D, 0x7F]
        WebSocketFraming.unmask(&data, key: [0x37, 0xFA, 0x21, 0x3D])
        XCTAssertEqual(data, [0, 0, 0, 0, 0x48]) // 0x7F ^ key[0] (index 4 wraps to 0)
    }

    // MARK: - Decoding frames from a real client

    // Serialized by the Python `websockets` library — the same code the host
    // uses to talk to the app — as masked client frames.
    private static func fixture(_ base64: String) -> Data { Data(base64Encoded: base64)! }
    private static let textHi = fixture("gYKc85hF9Jo=")
    private static let binary300 = fixture("gv4BLJoaKb2aGyu+nh8vupITI7aWFyeyigs7ro4PP6qCAzOmhgc3oro7C56+Pw+asjMDlrY3B5KqKxuOri8fiqIjE4amJxeC2ltr/t5fb/rSU2P21ldn8spLe+7OT3/qwkNz5sZHd+L6e0ve/n9P2vJzQ9b2d0fS6mtbzu5vX8riY1PG5mdXwhqbqz4en686EpOjNhaXpzIKi7suDo+/KgKDsyYGh7ciOruLHj6/jxoys4MWNreHEiqrmw4ur58KIqOTBianlwJa2+t+Xt/velLT43ZW1+dySsv7bk7P/2pCw/NmRsf3Ynr7y15+/89acvPDVnb3x1Jq69tObu/fSmLj072bGCq5nxwutZMQIrGXFCatiwg6qY8MPqWDADKhhwQ2nbs4Cpm/PA6VszACkbc0Bo0=")
    private static let binary70000Header = fixture("gv8AAAAAAAERcAuZJjc=")
    private static let pingAbc = fixture("iYPgEKOsgXLA")
    private static let close1001 = fixture("iIKSqRqJkUA=")

    private static func pattern(_ count: Int) -> Data { Data((0..<count).map { UInt8($0 % 251) }) }

    func testDecodesAMaskedTextFrame() throws {
        var buffer = Self.textHi
        let frame = try XCTUnwrap(WebSocketFraming.decodeFrame(from: &buffer))
        XCTAssertTrue(frame.fin)
        XCTAssertEqual(frame.opcode, WebSocketOpcode.text)
        XCTAssertEqual(frame.payload, Data("hi".utf8))
        XCTAssertTrue(buffer.isEmpty)
    }

    func testDecodesA126FormBinaryFrame() throws {
        var buffer = Self.binary300
        let frame = try XCTUnwrap(WebSocketFraming.decodeFrame(from: &buffer))
        XCTAssertEqual(frame.opcode, WebSocketOpcode.binary)
        XCTAssertEqual(frame.payload, Self.pattern(300))
    }

    /// The 8-byte-length form is what every real video frame uses (they are tens of KB).
    func testDecodesA127FormBinaryFrame() throws {
        // Python's header + masking key, then the payload masked by that key.
        let header = Self.binary70000Header
        let key = [UInt8](header.suffix(4))
        var maskedPayload = [UInt8](Self.pattern(70_000))
        WebSocketFraming.unmask(&maskedPayload, key: key) // XOR is symmetric: this masks it
        var buffer = header + Data(maskedPayload)

        let frame = try XCTUnwrap(WebSocketFraming.decodeFrame(from: &buffer))
        XCTAssertEqual(frame.opcode, WebSocketOpcode.binary)
        XCTAssertEqual(frame.payload.count, 70_000)
        XCTAssertEqual(frame.payload, Self.pattern(70_000))
    }

    func testReturnsNilUntilTheWholeFrameHasArrived() throws {
        let whole = Self.binary300
        var buffer = Data()
        for byte in whole.dropLast() {
            buffer.append(byte)
            XCTAssertNil(try WebSocketFraming.decodeFrame(from: &buffer), "must wait, and consume nothing")
        }
        XCTAssertEqual(buffer.count, whole.count - 1)
        buffer.append(whole.last!)
        XCTAssertNotNil(try WebSocketFraming.decodeFrame(from: &buffer))
    }

    func testDecodesBackToBackFramesFromOneBuffer() throws {
        var buffer = Self.textHi + Self.pingAbc + Self.binary300
        XCTAssertEqual(try XCTUnwrap(WebSocketFraming.decodeFrame(from: &buffer)).opcode, WebSocketOpcode.text)
        let ping = try XCTUnwrap(WebSocketFraming.decodeFrame(from: &buffer))
        XCTAssertEqual(ping.opcode, WebSocketOpcode.ping)
        XCTAssertEqual(ping.payload, Data("abc".utf8))
        XCTAssertEqual(try XCTUnwrap(WebSocketFraming.decodeFrame(from: &buffer)).payload.count, 300)
        XCTAssertNil(try WebSocketFraming.decodeFrame(from: &buffer))
    }

    func testDecodesCloseWithItsStatusCode() throws {
        var buffer = Self.close1001
        let frame = try XCTUnwrap(WebSocketFraming.decodeFrame(from: &buffer))
        XCTAssertEqual(frame.opcode, WebSocketOpcode.close)
        XCTAssertEqual(Array(frame.payload), [0x03, 0xE9]) // 1001 going away
    }

    func testDecodesWhenTheBufferIsASliceWithANonZeroStartIndex() throws {
        let padded = Data([0xEE, 0xEE]) + Self.textHi
        var buffer = padded.dropFirst(2) // startIndex == 2
        let frame = try XCTUnwrap(WebSocketFraming.decodeFrame(from: &buffer))
        XCTAssertEqual(frame.payload, Data("hi".utf8))
    }

    func testAbsurdLengthIsRejectedRatherThanBuffered() {
        // 127-form header claiming a 4 GB payload.
        var buffer = Data([0x82, 0x7F, 0, 0, 0, 1, 0, 0, 0, 0])
        XCTAssertThrowsError(try WebSocketFraming.decodeFrame(from: &buffer)) {
            XCTAssertEqual($0 as? WebSocketFramingError, .frameTooLarge)
        }
    }

    // MARK: - Reassembly

    func testSingleFrameMessagesPassStraightThrough() throws {
        var assembler = WebSocketMessageAssembler()
        XCTAssertEqual(
            try assembler.accept(WebSocketFrame(fin: true, opcode: WebSocketOpcode.text, payload: Data("ok".utf8))),
            .text("ok")
        )
        XCTAssertEqual(
            try assembler.accept(WebSocketFrame(fin: true, opcode: WebSocketOpcode.binary, payload: Data([1, 2]))),
            .binary(Data([1, 2]))
        )
    }

    func testFragmentedMessageIsReassembled() throws {
        var assembler = WebSocketMessageAssembler()
        XCTAssertNil(try assembler.accept(WebSocketFrame(fin: false, opcode: WebSocketOpcode.binary, payload: Data([1, 2]))))
        XCTAssertNil(try assembler.accept(WebSocketFrame(fin: false, opcode: WebSocketOpcode.continuation, payload: Data([3]))))
        XCTAssertEqual(
            try assembler.accept(WebSocketFrame(fin: true, opcode: WebSocketOpcode.continuation, payload: Data([4, 5]))),
            .binary(Data([1, 2, 3, 4, 5]))
        )
        // and it is ready for the next message afterwards
        XCTAssertEqual(
            try assembler.accept(WebSocketFrame(fin: true, opcode: WebSocketOpcode.text, payload: Data("x".utf8))),
            .text("x")
        )
    }

    func testContinuationWithoutAStartIsRejected() {
        var assembler = WebSocketMessageAssembler()
        XCTAssertThrowsError(
            try assembler.accept(WebSocketFrame(fin: true, opcode: WebSocketOpcode.continuation, payload: Data()))
        ) { XCTAssertEqual($0 as? WebSocketFramingError, .unexpectedContinuation) }
    }

    func testNewDataFrameInsideAFragmentedMessageIsRejected() throws {
        var assembler = WebSocketMessageAssembler()
        _ = try assembler.accept(WebSocketFrame(fin: false, opcode: WebSocketOpcode.text, payload: Data("a".utf8)))
        XCTAssertThrowsError(
            try assembler.accept(WebSocketFrame(fin: true, opcode: WebSocketOpcode.text, payload: Data("b".utf8)))
        ) { XCTAssertEqual($0 as? WebSocketFramingError, .interleavedDataFrame) }
    }

    func testInvalidUTF8TextIsRejected() {
        var assembler = WebSocketMessageAssembler()
        XCTAssertThrowsError(
            try assembler.accept(WebSocketFrame(fin: true, opcode: WebSocketOpcode.text, payload: Data([0xFF, 0xFE])))
        ) { XCTAssertEqual($0 as? WebSocketFramingError, .invalidUTF8) }
    }

    func testControlFramesAreLeftToTheCaller() throws {
        var assembler = WebSocketMessageAssembler()
        XCTAssertNil(try assembler.accept(WebSocketFrame(fin: true, opcode: WebSocketOpcode.ping, payload: Data())))
    }
}
