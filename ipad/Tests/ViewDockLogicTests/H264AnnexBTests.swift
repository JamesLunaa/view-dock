// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 James Luna

import XCTest
@testable import ViewDockLogic

final class H264AnnexBTests: XCTestCase {
    private func bytes(_ values: [UInt8]) -> Data { Data(values) }

    func testSplitsThreeAndFourByteStartCodes() {
        let stream = bytes([0, 0, 0, 1, 0x67, 0xAA, 0, 0, 1, 0x68, 0xBB, 0xCC, 0, 0, 0, 1, 0x65, 0xDD])
        let units = H264AnnexB.nalUnits(in: stream)
        XCTAssertEqual(units, [bytes([0x67, 0xAA]), bytes([0x68, 0xBB, 0xCC]), bytes([0x65, 0xDD])])
    }

    func testNoStartCodeYieldsNothing() {
        XCTAssertTrue(H264AnnexB.nalUnits(in: bytes([1, 2, 3, 4])).isEmpty)
        XCTAssertTrue(H264AnnexB.nalUnits(in: Data()).isEmpty)
    }

    func testParseSortsParameterSetsFromSlices() {
        let stream = bytes([0, 0, 0, 1, 0x67, 1, 0, 0, 0, 1, 0x68, 2, 0, 0, 1, 0x06, 3, 0, 0, 1, 0x65, 4, 5])
        let unit = H264AnnexB.parse(stream)
        XCTAssertEqual(unit.sps, bytes([0x67, 1]))
        XCTAssertEqual(unit.pps, bytes([0x68, 2]))
        XCTAssertEqual(unit.slices, [bytes([0x06, 3]), bytes([0x65, 4, 5])]) // SEI and IDR, in order
        XCTAssertTrue(unit.containsKeyframe)
    }

    func testDeltaFrameIsNotAKeyframeAndAccessUnitDelimitersAreDropped() {
        let stream = bytes([0, 0, 0, 1, 0x09, 0xF0, 0, 0, 0, 1, 0x41, 9, 9])
        let unit = H264AnnexB.parse(stream)
        XCTAssertNil(unit.sps)
        XCTAssertFalse(unit.containsKeyframe)
        XCTAssertEqual(unit.slices, [bytes([0x41, 9, 9])])
    }

    func testAvccPrefixesEachUnitWithItsBigEndianLength() {
        let output = H264AnnexB.avcc(from: [bytes([0x65, 1, 2]), Data(repeating: 7, count: 300)])
        XCTAssertEqual(Array(output.prefix(7)), [0, 0, 0, 3, 0x65, 1, 2])
        // 300 = 0x012C
        XCTAssertEqual(Array(output[7..<11]), [0, 0, 1, 0x2C])
        XCTAssertEqual(output.count, 4 + 3 + 4 + 300)
    }

    // MARK: - Real encoder output

    // Produced by the host's own encoder (host/streaming/wired_encoder.py, libx264,
    // baseline, zerolatency) for a 64x64 frame: a keyframe, then a delta frame.
    private static let realKeyframeBase64 =
        "AAAAAWdCwDTaEJoQAAADABAAAAMDyPGDKgAAAAFozjyAAAABBgX//6jcRem95tlIt5Ys2CDZI+7veDI2NCAtIGNvcmUgMTY1IC0g" +
        "SC4yNjQvTVBFRy00IEFWQyBjb2RlYyAtIENvcHlsZWZ0IDIwMDMtMjAyNSAtIGh0dHA6Ly93d3cudmlkZW9sYW4ub3JnL3gyNjQu" +
        "aHRtbCAtIG9wdGlvbnM6IGNhYmFjPTAgcmVmPTEgZGVibG9jaz0xOjA6MCBhbmFseXNlPTB4MToweDExMSBtZT1oZXggc3VibWU9" +
        "MiBwc3k9MSBwc3lfcmQ9MS4wMDowLjAwIG1peGVkX3JlZj0wIG1lX3JhbmdlPTE2IGNocm9tYV9tZT0xIHRyZWxsaXM9MCA4eDhk" +
        "Y3Q9MCBjcW09MCBkZWFkem9uZT0yMSwxMSBmYXN0X3Bza2lwPTEgY2hyb21hX3FwX29mZnNldD0wIHRocmVhZHM9MSBsb29rYWhl" +
        "YWRfdGhyZWFkcz0xIHNsaWNlZF90aHJlYWRzPTAgbnI9MCBkZWNpbWF0ZT0xIGludGVybGFjZWQ9MCBibHVyYXlfY29tcGF0PTAg" +
        "Y29uc3RyYWluZWRfaW50cmE9MCBiZnJhbWVzPTAgd2VpZ2h0cD0wIGtleWludD0zMDAga2V5aW50X21pbj0zMCBzY2VuZWN1dD00" +
        "MCBpbnRyYV9yZWZyZXNoPTAgcmNfbG9va2FoZWFkPTAgcmM9Y2JyIG1idHJlZT0wIGJpdHJhdGU9MjAwMDAgcmF0ZXRvbD0xLjAg" +
        "cWNvbXA9MC42MCBxcG1pbj0wIHFwbWF4PTY5IHFwc3RlcD00IHZidl9tYXhyYXRlPTIwMDAwIHZidl9idWZzaXplPTEwMDAwIG5h" +
        "bF9ocmQ9bm9uZSBmaWxsZXI9MCBpcF9yYXRpbz0xLjQwIGFxPTE6MS4wMACAAAABZYiEBb//8QGDCKAAJa/gAIAAIDTgCgLoAPgm" +
        "YISRFMTObRLFbw9AkgACAmAIhtFpxkN6yUk/wAAQDAABAPAAn4NCpVgz/XVitsdfJ4AYAEAsezoNkLs21MxLz8EgIACO9wQARWs4" +
        "ADgQBSMAjZTf5/aOr34AFgID4E15HIll7Z/O/+/+57BDvwYcWAxVAGuWs6224yKbPe4AQCHuFgoTo6aAryLhebf94AAIPYAUAHgk" +
        "oENbG0W0T0U8iSRPAABAmAAUAAQQxy9qdAjZ7Mxt+7YOXwAAQMgABAOADVgfItGJZAvUzHbw84QAAgJAoGHQDgTKPGYYSf0ESP/v" +
        "GMAAQaiQOGRBlR1VrL62eUNd9AAgAIBYgUEUzcr91njGT8EAIARQJCCjr8AACAYBzZYbA1Rm/O4U4CYBDDjBWTIL2e44JMCQIoIG" +
        "ycy7KkZkmH/AKAIESNvzHbtUh+9SRMn+JgXxQYcFeAACAkAAUAxUy5sO7DzjNXoguoXgBgFQABAA+hDGKxbajT0w/U7wAAQNQABA" +
        "QKAAEBwngmLB25tWrfCmcfAABARAAEAcsHAoPOVfqU5HO6tV9vgACADgFeDbRSklBUWbs/BrXPAABAoAAcgN8BsIrlAvznH7Qps3" +
        "AAAgAAOcVqALgKOyNwScT/eAACAuOEjEmAW2ERIRrhZQalUIAAyBIkJQAAgdAACA74YOIIYkuxMt45PoAXobLm4HTsvx/+gaQAFe" +
        "dxIJ+GlPrp8f/4CgAOOBH5hhmAZmq79xIRrQIFl/AABAoAAEBIABJML7KE94R5p2eYwf/AABAuAAEBgGgo37IDSUZI91h4RKvgAA" +
        "gVgACD6g8AA0HSSciFtPC5JF9L8AAEC8AAQLABiYo5ZGIf02WOiVkti8AAEDAAGDQUTRCUpWNySltiFVneGwAjwKEmTDVKhzRWyY" +
        "eAACAkAAIFIeFyFAnxEGRCU7duJA8AAEDUAAQGwPQOo2UeLjKxMkIWPgAAgAAAMBxLADlIVJL2/srqtQYsfgAAQagABAxAYDlThA" +
        "tK8xMte8H3uAABAaGAVoWLHxQOI7cuM1dO/+8EBihTQsoVSaR85P1JX4AAIF4AcAUtHADeDFREVpHNom8GHB4EL0f5wJLyNcZIJI" +
        "dPAOgFAXoOHh4qZqHjAf4CvwAAIEwAAgDAIfFtYO2a+a+6Tb4IAAQAwABAFAaDwQAAgMAACCQFT0xioCCVdCt1VGbN/7ABAIIhqr" +
        "zDL5LaO/2gMBMNGchWzJNDSL/3AAQ4onXfspjPs1E21gkUACgemy30Xug//3OAEIeBT9bt8eU0mQthgAQAQZ5jq54mvVnf/tADBy" +
        "RJHJFHt39+5RYa4jowAbUNddddde"

    private static let realDeltaBase64 =
        "AAAAAUGaIBf5v/42gwigACQH4ACAACBaAAIBAAIPhG5O9hy2DJWLpJJHhBOAt1cBTxEy71C9gmd/AABBfAAEEYAJJgQ7te0FmBUg" +
        "MwBKneAACAwAIAASCCjdQtPzyCkEq3iLgQAEd7ggJSk4ADgAcYA29RgJfHNuaXfAAsAAQA0Awbf0YqkMEql3/9N/rZRFgh3wAAIJ" +
        "gAAgYgAXsMEX4m2EVisva+TPvMAAQTBwFBVoF2Fp8kbmtk9CbvAABAYAAcA0OghgSbZgJvQwI9TDe8AAQAAgKAAkGwM1UZiYynpZ" +
        "hiIjcqngAAghgACBQAcGBL+ZUuQy1Nj0l183IEODEShKejNQIitoZf/3gAAg6AMAAIBpcoLAnjv9e+7VjOrZfAABACBDQH7MifRC" +
        "8UWoJm5SEAAICYAAgyAUAEQgABACABgs/8AEApL2h4TaKrKaW6rngCI4iw4UvmvrptrxwFAAEBMAGfCQKXLi7bzT9cl0AAEAEVY7" +
        "EJ/8VoV1h/0TPifN9wXxosOCPAABARAGAEUG9kv6Hyg4ZGI7SeAABAZAAEINoACgDxWfTUhMk4S8sZP/3gAAg3gACCIIAxTg9YjG" +
        "DR3dpf734AAIMoAAgFABbhEGW7AXQrFrMlv9jgAgDtAClhZahEvBGtaSjV/94AMUCAIhdnT57cMGr3i+Vs3AAGDAA6WE0QiKlNHn" +
        "L29K3ADiAAU4AAQNyIz45K1c7oCcEoEcIAAuDTHgBAFaDaRW1dEvfZ4l4ABgg9DbhssfWEcsauICgACAAC0lxR9Bk5n12m+gEUJC" +
        "gk1kl6GS93/TVMXmZsLoBP/AABA9AAwKDGKn73IqMxE0lqZG8AAEAQAAQKQFviS90+BJ+kt7VJvTeAABAGAGAAEBACPxkpNGtLbB" +
        "QWxXgAMAESCywBEJccyf47SEOou8AACA0AAIFlgACAIDIhT0a9xX+Bx/U7wAAQKAABAaAAWRAfdIDPk3IclvjIq8AAED0BAABAM0" +
        "BbEaPnpVc0f/WvvfgAAgEAAYSkgzlWYf4vR4ARKfgAAgmgACBMAAWAoPmgiUbpFJmXRblSvAABAjBjWig6W2fBiTKW4l6dPgAAgC" +
        "gp4VJgNUFiwuVi5y3p3gAAglgACA8AAIAofEHiTgxaYn+LKTZngAAhygACATwBDIfLWpOH5zSv6Rr98AACAqAA4FgTLbYDsS1K1V" +
        "FkSf/9wAAIHYDgALAjqEsnKyxcCCfM3t4AAIBIOB4njFyksQ5CqbcYsQQAAgMgACB6LDAQABIGCv6hgGG0S7dZhQjgk/aAACAAYA" +
        "vJtiQBpBDbxp3AAIIlAqlhK10pukud6AACAGoYspleACS9I0SftAABAGAAoJRP3GSX9at5XcLiMAAQMwAENXoOG9bFPiaDQEGeA/" +
        "ZP/ioU1nyzfcAAGINGb7L6tV9nFl2U7Ehz+N40AxgA51Dn8/n8/n8/g="

    func testParsesARealKeyframeFromTheHostEncoder() throws {
        let data = try XCTUnwrap(Data(base64Encoded: Self.realKeyframeBase64))
        let unit = H264AnnexB.parse(data)

        let sps = try XCTUnwrap(unit.sps)
        let pps = try XCTUnwrap(unit.pps)
        XCTAssertEqual(sps[0] & 0x1F, H264AnnexB.NALType.sps)
        XCTAssertEqual(pps[0] & 0x1F, H264AnnexB.NALType.pps)
        XCTAssertTrue(unit.containsKeyframe, "a real keyframe must contain an IDR slice")
        XCTAssertFalse(unit.slices.isEmpty)

        // Conversion must account for every slice byte (4-byte length prefix each).
        let avcc = H264AnnexB.avcc(from: unit.slices)
        XCTAssertEqual(avcc.count, unit.slices.reduce(0) { $0 + $1.count + 4 })
    }

    func testParsesARealDeltaFrameWithoutParameterSets() throws {
        let data = try XCTUnwrap(Data(base64Encoded: Self.realDeltaBase64))
        let unit = H264AnnexB.parse(data)
        XCTAssertNil(unit.sps)
        XCTAssertNil(unit.pps)
        XCTAssertFalse(unit.containsKeyframe)
        XCTAssertEqual(unit.slices.count, 1)
    }
}
