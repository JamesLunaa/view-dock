import Foundation

/// Splits the wired stream's Annex-B access units into what Apple's decoders
/// want. Foundation-only so it can be tested without any media framework.
///
/// The host sends each frame as one access unit with start codes
/// (`00 00 01` / `00 00 00 01`) between NAL units, and SPS/PPS in-band ahead of
/// every keyframe. `CMVideoFormatDescription` wants the SPS/PPS separately and
/// the slice data as length-prefixed (AVCC) NAL units instead.
enum H264AnnexB {
    struct AccessUnit {
        var sps: Data?
        var pps: Data?
        /// Slice (IDR / non-IDR) and SEI NAL units, without start codes.
        var slices: [Data] = []
        var containsKeyframe = false
    }

    enum NALType {
        static let slice: UInt8 = 1
        static let idrSlice: UInt8 = 5
        static let sei: UInt8 = 6
        static let sps: UInt8 = 7
        static let pps: UInt8 = 8
    }

    /// NAL units in `data`, each without its start code.
    static func nalUnits(in data: Data) -> [Data] {
        let bytes = [UInt8](data)
        let count = bytes.count
        // (offset where the start code begins, offset of the NAL's first byte)
        var starts: [(code: Int, nal: Int)] = []

        bytes.withUnsafeBufferPointer { buffer in
            var index = 0
            while index + 2 < count {
                if buffer[index] == 0, buffer[index + 1] == 0, buffer[index + 2] == 1 {
                    // A zero just before `00 00 01` makes it the 4-byte form; a NAL never ends in 0x00.
                    let codeStart = (index > 0 && buffer[index - 1] == 0) ? index - 1 : index
                    starts.append((codeStart, index + 3))
                    index += 3
                } else {
                    index += 1
                }
            }
        }

        var units: [Data] = []
        for (position, start) in starts.enumerated() {
            let end = position + 1 < starts.count ? starts[position + 1].code : count
            if start.nal < end {
                units.append(Data(bytes[start.nal..<end]))
            }
        }
        return units
    }

    static func parse(_ data: Data) -> AccessUnit {
        var unit = AccessUnit()
        for nal in nalUnits(in: data) {
            guard let header = nal.first else { continue }
            switch header & 0x1F {
            case NALType.sps:
                unit.sps = nal
            case NALType.pps:
                unit.pps = nal
            case NALType.idrSlice:
                unit.containsKeyframe = true
                unit.slices.append(nal)
            case NALType.slice, NALType.sei:
                unit.slices.append(nal)
            default:
                break // access unit delimiters, filler, etc.
            }
        }
        return unit
    }

    /// Concatenates NAL units, each prefixed with its length as a 4-byte big-endian integer.
    static func avcc(from nalUnits: [Data]) -> Data {
        var output = Data()
        output.reserveCapacity(nalUnits.reduce(0) { $0 + $1.count + 4 })
        for nal in nalUnits {
            let length = UInt32(nal.count)
            output.append(UInt8((length >> 24) & 0xFF))
            output.append(UInt8((length >> 16) & 0xFF))
            output.append(UInt8((length >> 8) & 0xFF))
            output.append(UInt8(length & 0xFF))
            output.append(nal)
        }
        return output
    }
}
