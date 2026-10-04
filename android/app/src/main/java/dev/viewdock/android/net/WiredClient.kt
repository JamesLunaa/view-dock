package dev.viewdock.android.net

import android.util.Log
import android.view.Surface
import dev.viewdock.android.protocol.DisplayInfo
import dev.viewdock.android.protocol.MessageType
import dev.viewdock.android.protocol.Messages
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch

/**
 * A wired session: the USB tunnel's WebSocket carries the whole thing — control
 * messages as text, H.264 video as binary frames (protocol/PROTOCOL.md, "Wired
 * stream"). No WebRTC, so it needs no Wi-Fi and no shared network.
 *
 * The decoder only exists while the UI has a [Surface]; it is rebuilt on each
 * attach and every (re)build asks the host for a keyframe, since decoding can
 * only begin at one.
 */
class WiredClient(private val link: UsbSignaling) : StreamSession {
    private val _status = MutableStateFlow("Connected over USB")
    override val status: StateFlow<String> = _status

    override val disconnected = CompletableDeferred<Unit>()

    private val _displayInfo = MutableStateFlow<DisplayInfo?>(null)
    val displayInfo: StateFlow<DisplayInfo?> = _displayInfo

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private val lock = Any()
    private var surface: Surface? = null
    private var decoder: H264Decoder? = null
    private var waitingForKeyframe = true

    init {
        scope.launch { readLoop() }
    }

    fun attachSurface(newSurface: Surface) = synchronized(lock) {
        surface = newSurface
        rebuildDecoder()
    }

    fun detachSurface() = synchronized(lock) {
        surface = null
        decoder?.release()
        decoder = null
    }

    override fun sendInputEvent(json: String) {
        try {
            link.sendText(json)
        } catch (_: SignalingClosedException) {
            // The link is going away; the read loop reports it.
        }
    }

    override fun close() {
        Log.i(TAG, "Closing wired client")
        scope.cancel()
        detachSurface()
        link.close()
        disconnected.complete(Unit)
    }

    private fun rebuildDecoder() {
        val info = _displayInfo.value
        val target = surface
        decoder?.release()
        decoder = null
        if (info == null || target == null) return // retried when the other half arrives
        try {
            decoder = H264Decoder(target, info.width, info.height)
        } catch (e: Exception) {
            Log.e(TAG, "Could not start the H.264 decoder", e)
            end("Decoder error: ${e.message}")
            return
        }
        waitingForKeyframe = true
        requestKeyframe()
    }

    private fun requestKeyframe() {
        try {
            link.sendText(Messages.keyframeRequest())
        } catch (_: SignalingClosedException) {
        }
    }

    private suspend fun readLoop() {
        try {
            while (true) {
                when (val message = link.receive()) {
                    is UsbSignaling.Incoming.Text -> handleControl(message.text)
                    is UsbSignaling.Incoming.Binary -> handleVideo(message.bytes)
                }
            }
        } catch (e: kotlinx.coroutines.CancellationException) {
            throw e
        } catch (e: Exception) {
            // A closed channel is the normal way a session ends (host stopped or unplugged).
            Log.i(TAG, "Wired link ended: ${e.message ?: e.javaClass.simpleName}")
            end("Host disconnected")
        }
    }

    private fun handleControl(raw: String) {
        when (Messages.typeOf(raw)) {
            MessageType.DISPLAY_INFO -> Messages.parseDisplayInfo(raw)?.let {
                _displayInfo.value = it
                synchronized(lock) { rebuildDecoder() }
            }
            MessageType.BYE -> {
                Log.i(TAG, "Host said bye: $raw")
                end("Host disconnected")
            }
            else -> Unit // hello needs no reaction; the rest isn't expected inbound.
        }
    }

    private fun handleVideo(frame: ByteArray) {
        val packet = Messages.parseVideoPacket(frame) ?: return
        synchronized(lock) {
            val current = decoder ?: return // no surface yet; the keyframe request covers the gap
            if (waitingForKeyframe && !packet.keyframe) return
            if (current.queue(packet.data, packet.offset, packet.ptsUs, packet.keyframe)) {
                waitingForKeyframe = false
            } else {
                // Dropping a delta frame corrupts everything until the next keyframe.
                waitingForKeyframe = true
                requestKeyframe()
            }
        }
    }

    private fun end(reason: String) {
        _status.value = reason
        disconnected.complete(Unit)
    }

    private companion object {
        const val TAG = "ViewDock"
    }
}
