// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 James Luna

import CoreMedia
import Foundation

/// Turns the wired stream's access units into `CMSampleBuffer`s that
/// `AVSampleBufferDisplayLayer` can decode and show directly (no
/// `VTDecompressionSession` needed).
///
/// The format description (built from the SPS/PPS) is created on the first
/// keyframe and replaced only if the parameter sets change, so delta frames —
/// which carry none — reuse it.
final class H264SampleBufferFactory {
    private var formatDescription: CMVideoFormatDescription?
    private var currentSPS: Data?
    private var currentPPS: Data?

    /// Returns nil if the access unit can't be shown yet, e.g. a delta frame
    /// arriving before any keyframe has supplied the parameter sets.
    func makeSampleBuffer(from unit: H264AnnexB.AccessUnit, presentationTimeMicros: UInt64) -> CMSampleBuffer? {
        if let sps = unit.sps, let pps = unit.pps, sps != currentSPS || pps != currentPPS {
            guard let description = Self.makeFormatDescription(sps: sps, pps: pps) else { return nil }
            formatDescription = description
            currentSPS = sps
            currentPPS = pps
        }
        guard let formatDescription, !unit.slices.isEmpty else { return nil }

        let avcc = H264AnnexB.avcc(from: unit.slices)

        var blockBuffer: CMBlockBuffer?
        var status = CMBlockBufferCreateWithMemoryBlock(
            allocator: kCFAllocatorDefault,
            memoryBlock: nil,
            blockLength: avcc.count,
            blockAllocator: kCFAllocatorDefault,
            customBlockSource: nil,
            offsetToData: 0,
            dataLength: avcc.count,
            flags: kCMBlockBufferAssureMemoryNowFlag,
            blockBufferOut: &blockBuffer
        )
        guard status == kCMBlockBufferNoErr, let blockBuffer else { return nil }

        status = avcc.withUnsafeBytes { bytes in
            CMBlockBufferReplaceDataBytes(
                with: bytes.baseAddress!,
                blockBuffer: blockBuffer,
                offsetIntoDestination: 0,
                dataLength: avcc.count
            )
        }
        guard status == kCMBlockBufferNoErr else { return nil }

        var timing = CMSampleTimingInfo(
            duration: .invalid,
            presentationTimeStamp: CMTime(value: CMTimeValue(presentationTimeMicros), timescale: 1_000_000),
            decodeTimeStamp: .invalid
        )
        var sampleSize = avcc.count
        var sampleBuffer: CMSampleBuffer?
        status = CMSampleBufferCreateReady(
            allocator: kCFAllocatorDefault,
            dataBuffer: blockBuffer,
            formatDescription: formatDescription,
            sampleCount: 1,
            sampleTimingEntryCount: 1,
            sampleTimingArray: &timing,
            sampleSizeEntryCount: 1,
            sampleSizeArray: &sampleSize,
            sampleBufferOut: &sampleBuffer
        )
        guard status == noErr, let sampleBuffer else { return nil }

        Self.markForImmediateDisplay(sampleBuffer, isKeyframe: unit.containsKeyframe)
        return sampleBuffer
    }

    /// Latency matters more than smooth pacing for a desktop: show every frame
    /// the moment it is decoded rather than waiting for its timestamp.
    private static func markForImmediateDisplay(_ sampleBuffer: CMSampleBuffer, isKeyframe: Bool) {
        guard let attachments = CMSampleBufferGetSampleAttachmentsArray(sampleBuffer, createIfNecessary: true),
              CFArrayGetCount(attachments) > 0
        else { return }
        let dictionary = unsafeBitCast(CFArrayGetValueAtIndex(attachments, 0), to: CFMutableDictionary.self)
        CFDictionarySetValue(
            dictionary,
            Unmanaged.passUnretained(kCMSampleAttachmentKey_DisplayImmediately).toOpaque(),
            Unmanaged.passUnretained(kCFBooleanTrue).toOpaque()
        )
        if !isKeyframe {
            CFDictionarySetValue(
                dictionary,
                Unmanaged.passUnretained(kCMSampleAttachmentKey_NotSync).toOpaque(),
                Unmanaged.passUnretained(kCFBooleanTrue).toOpaque()
            )
        }
    }

    private static func makeFormatDescription(sps: Data, pps: Data) -> CMVideoFormatDescription? {
        var description: CMFormatDescription?
        let status = sps.withUnsafeBytes { (spsBytes: UnsafeRawBufferPointer) -> OSStatus in
            pps.withUnsafeBytes { (ppsBytes: UnsafeRawBufferPointer) -> OSStatus in
                guard let spsBase = spsBytes.bindMemory(to: UInt8.self).baseAddress,
                      let ppsBase = ppsBytes.bindMemory(to: UInt8.self).baseAddress
                else { return -1 }
                let pointers: [UnsafePointer<UInt8>] = [spsBase, ppsBase]
                let sizes: [Int] = [sps.count, pps.count]
                return CMVideoFormatDescriptionCreateFromH264ParameterSets(
                    allocator: kCFAllocatorDefault,
                    parameterSetCount: 2,
                    parameterSetPointers: pointers,
                    parameterSetSizes: sizes,
                    nalUnitHeaderLength: 4,
                    formatDescriptionOut: &description
                )
            }
        }
        return status == noErr ? description : nil
    }
}
