package dev.viewdock.android.net

import android.media.MediaCodec
import android.media.MediaFormat
import android.os.Build
import android.util.Log
import android.view.Surface
import kotlin.concurrent.thread

/**
 * Hardware H.264 decoder rendering straight onto a [Surface].
 *
 * The wired stream is baseline profile with no B-frames and carries SPS/PPS
 * in-band on every keyframe (see host/streaming/wired_encoder.py), so no
 * extradata is needed: decoding can start at any keyframe. Output is released
 * to the surface as soon as it is ready — latency matters more than pacing.
 */
class H264Decoder(surface: Surface, width: Int, height: Int) {
    private val codec: MediaCodec = MediaCodec.createDecoderByType(MediaFormat.MIMETYPE_VIDEO_AVC)

    @Volatile
    private var running = true
    private val outputThread: Thread

    init {
        val format = MediaFormat.createVideoFormat(MediaFormat.MIMETYPE_VIDEO_AVC, width, height).apply {
            setInteger(MediaFormat.KEY_MAX_INPUT_SIZE, maxOf(1 shl 20, width * height))
            if (Build.VERSION.SDK_INT >= 30) setInteger(MediaFormat.KEY_LOW_LATENCY, 1)
            setInteger(MediaFormat.KEY_PRIORITY, 0) // real-time
        }
        codec.configure(format, surface, null, 0)
        codec.start()
        outputThread = thread(name = "viewdock-decoder-output", isDaemon = true) { drainOutput() }
    }

    /** Returns false if the decoder had no free input buffer in time (it is falling behind). */
    fun queue(data: ByteArray, offset: Int, ptsUs: Long, keyframe: Boolean): Boolean {
        if (!running) return false
        return try {
            val index = codec.dequeueInputBuffer(INPUT_TIMEOUT_US)
            if (index < 0) return false
            val buffer = codec.getInputBuffer(index) ?: return false
            buffer.clear()
            val length = data.size - offset
            buffer.put(data, offset, length)
            val flags = if (keyframe) MediaCodec.BUFFER_FLAG_KEY_FRAME else 0
            codec.queueInputBuffer(index, 0, length, ptsUs, flags)
            true
        } catch (e: IllegalStateException) {
            Log.w(TAG, "Decoder rejected input", e)
            false
        }
    }

    fun release() {
        running = false
        outputThread.join(500)
        try {
            codec.stop()
        } catch (_: IllegalStateException) {
            // Already stopped or in an error state; release() below still frees it.
        }
        codec.release()
    }

    private fun drainOutput() {
        val info = MediaCodec.BufferInfo()
        while (running) {
            try {
                val index = codec.dequeueOutputBuffer(info, OUTPUT_TIMEOUT_US)
                if (index >= 0) codec.releaseOutputBuffer(index, true)
            } catch (e: IllegalStateException) {
                Log.w(TAG, "Decoder output loop ended", e)
                return
            }
        }
    }

    private companion object {
        const val TAG = "ViewDock"
        const val INPUT_TIMEOUT_US = 50_000L
        const val OUTPUT_TIMEOUT_US = 10_000L
    }
}
