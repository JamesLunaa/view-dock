package dev.viewdock.android.protocol

import org.json.JSONException
import org.json.JSONObject

/**
 * Kotlin mirror of `protocol/messages.py` and the JSON schemas under `protocol/schema/`. See
 * `protocol/PROTOCOL.md` for the full message contract. Keep in sync by hand
 * with the Python side when the protocol changes.
 */
object ProtocolVersion {
    const val CURRENT = "1.2"
}

object MessageType {
    const val HELLO = "hello"
    const val DISPLAY_INFO = "display_info"
    const val INPUT_EVENT = "input_event"
    const val STATS = "stats"
    const val BYE = "bye"
    const val KEYFRAME_REQUEST = "keyframe_request"
}

object Role {
    const val ANDROID = "android"
}

enum class InputKind(val wire: String) {
    TOUCH_DOWN("touch_down"),
    TOUCH_MOVE("touch_move"),
    TOUCH_UP("touch_up"),
    PENCIL_DOWN("pencil_down"),
    PENCIL_MOVE("pencil_move"),
    PENCIL_UP("pencil_up"),
}

enum class ByeReason(val wire: String) {
    USER_DISCONNECTED("user_disconnected"),
    ERROR("error"),
    SHUTDOWN("shutdown"),
}

/** Binary frames on a wired stream; layout in protocol/PROTOCOL.md ("Wired stream"). */
object WiredFrame {
    const val VIDEO = 0x01
    const val FLAG_KEYFRAME = 0x01
    const val VIDEO_HEADER_SIZE = 10 // type(1) + flags(1) + pts_us(8, big-endian)
}

/** One H.264 access unit: `data[offset until data.size]` is the Annex-B payload. */
class VideoPacket(val keyframe: Boolean, val ptsUs: Long, val data: ByteArray, val offset: Int)

data class DisplayInfo(
    val width: Int,
    val height: Int,
    val refreshHz: Double,
    val orientation: String,
)

object Messages {
    fun hello(): String = JSONObject()
        .put("type", MessageType.HELLO)
        .put("role", Role.ANDROID)
        .put("protocol_version", ProtocolVersion.CURRENT)
        .toString()

    /** `x`/`y`/`pressure` must already be clamped to [0, 1] — the host's schema rejects anything outside. */
    fun inputEvent(kind: InputKind, x: Double, y: Double, pressure: Double, timestampMs: Long): String =
        JSONObject()
            .put("type", MessageType.INPUT_EVENT)
            .put("kind", kind.wire)
            .put("x", x)
            .put("y", y)
            .put("pressure", pressure)
            .put("timestamp_ms", timestampMs)
            .toString()

    fun bye(reason: ByeReason): String = JSONObject()
        .put("type", MessageType.BYE)
        .put("reason", reason.wire)
        .toString()

    fun keyframeRequest(): String = JSONObject().put("type", MessageType.KEYFRAME_REQUEST).toString()

    /** Returns null for anything that isn't a well-formed video frame (unknown types are ignored, not fatal). */
    fun parseVideoPacket(frame: ByteArray): VideoPacket? {
        if (frame.size < WiredFrame.VIDEO_HEADER_SIZE || frame[0].toInt() != WiredFrame.VIDEO) return null
        val ptsUs = java.nio.ByteBuffer.wrap(frame, 2, 8).order(java.nio.ByteOrder.BIG_ENDIAN).long
        return VideoPacket(
            keyframe = frame[1].toInt() and WiredFrame.FLAG_KEYFRAME != 0,
            ptsUs = ptsUs,
            data = frame,
            offset = WiredFrame.VIDEO_HEADER_SIZE,
        )
    }

    /** Just enough to route an incoming control message before parsing it fully. */
    fun typeOf(raw: String): String? = try {
        JSONObject(raw).optString("type").ifEmpty { null }
    } catch (_: JSONException) {
        null
    }

    fun parseDisplayInfo(raw: String): DisplayInfo? = try {
        val json = JSONObject(raw)
        DisplayInfo(
            width = json.getInt("width"),
            height = json.getInt("height"),
            refreshHz = json.getDouble("refresh_hz"),
            orientation = json.getString("orientation"),
        )
    } catch (_: JSONException) {
        null
    }
}
