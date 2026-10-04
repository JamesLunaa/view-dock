package dev.viewdock.android.protocol

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class MessagesTest {
    @Test
    fun helloIdentifiesAsAndroidAtCurrentVersion() {
        val json = JSONObject(Messages.hello())
        assertEquals("hello", json.getString("type"))
        assertEquals("android", json.getString("role"))
        assertEquals(ProtocolVersion.CURRENT, json.getString("protocol_version"))
    }

    @Test
    fun inputEventHasExactlyTheFieldsTheHostSchemaAllows() {
        // protocol/schema/input_event.json is additionalProperties:false.
        val json = JSONObject(Messages.inputEvent(InputKind.PENCIL_MOVE, 0.25, 0.75, 0.5, 1732999999123L))
        assertEquals(
            setOf("type", "kind", "x", "y", "pressure", "timestamp_ms"),
            json.keys().asSequence().toSet(),
        )
        assertEquals("pencil_move", json.getString("kind"))
        assertEquals(1732999999123L, json.getLong("timestamp_ms"))
    }

    @Test
    fun parsesDisplayInfoFromHost() {
        val raw = """{"type":"display_info","width":1600,"height":720,"refresh_hz":60,"orientation":"landscape"}"""
        val info = Messages.parseDisplayInfo(raw)!!
        assertEquals(1600, info.width)
        assertEquals(720, info.height)
        assertEquals("landscape", info.orientation)
    }

    @Test
    fun malformedInputIsIgnoredNotThrown() {
        assertNull(Messages.typeOf("not json"))
        assertNull(Messages.parseDisplayInfo("""{"type":"display_info"}"""))
        assertTrue(Messages.typeOf("""{"type":"bye","reason":"shutdown"}""") == MessageType.BYE)
    }

    @Test
    fun parsesAWiredVideoFrameHeader() {
        // Same bytes the host's pack_video_frame() builds: type, flags, 8-byte big-endian pts.
        val frame = byteArrayOf(0x01, 0x01, 0, 0, 0, 0, 0, 0x0F, 0x42, 0x40, 0x11, 0x22)
        val packet = Messages.parseVideoPacket(frame)!!
        assertTrue(packet.keyframe)
        assertEquals(1_000_000L, packet.ptsUs)
        assertEquals(WiredFrame.VIDEO_HEADER_SIZE, packet.offset)
        assertEquals(0x11, packet.data[packet.offset].toInt())
    }

    @Test
    fun deltaFramesAreNotKeyframes() {
        val frame = ByteArray(12).also { it[0] = 0x01 }
        assertTrue(!Messages.parseVideoPacket(frame)!!.keyframe)
    }

    @Test
    fun malformedWiredFramesAreIgnored() {
        assertNull(Messages.parseVideoPacket(ByteArray(3)))
        assertNull(Messages.parseVideoPacket(ByteArray(12).also { it[0] = 0x7F })) // unknown frame type
    }

    @Test
    fun keyframeRequestMatchesTheHostSchema() {
        assertEquals(setOf("type"), JSONObject(Messages.keyframeRequest()).keys().asSequence().toSet())
        assertEquals("keyframe_request", JSONObject(Messages.keyframeRequest()).getString("type"))
    }
}
