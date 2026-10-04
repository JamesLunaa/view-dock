package dev.viewdock.android.net

import android.content.Context
import android.util.Log
import dev.viewdock.android.protocol.DisplayInfo
import dev.viewdock.android.protocol.Messages
import dev.viewdock.android.protocol.MessageType
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.suspendCancellableCoroutine
import org.webrtc.DataChannel
import org.webrtc.DefaultVideoDecoderFactory
import org.webrtc.DefaultVideoEncoderFactory
import org.webrtc.EglBase
import org.webrtc.IceCandidate
import org.webrtc.MediaConstraints
import org.webrtc.MediaStream
import org.webrtc.PeerConnection
import org.webrtc.PeerConnectionFactory
import org.webrtc.RtpReceiver
import org.webrtc.RtpTransceiver
import org.webrtc.SdpObserver
import org.webrtc.SessionDescription
import org.webrtc.VideoTrack
import java.nio.ByteBuffer
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException

/**
 * Peer connection to the host: receives the video track and exchanges
 * `control` data channel messages per `protocol/PROTOCOL.md`. The host always
 * creates the offer and the data channel (see `host/streaming/webrtc_session.py`),
 * so this side only ever answers and waits for the channel to arrive.
 */
class WebRtcClient(context: Context) : StreamSession {
    val appContext: Context = context.applicationContext

    val eglBase: EglBase = EglBase.create()

    private val _videoTrack = MutableStateFlow<VideoTrack?>(null)
    val videoTrack: StateFlow<VideoTrack?> = _videoTrack

    private val _displayInfo = MutableStateFlow<DisplayInfo?>(null)
    val displayInfo: StateFlow<DisplayInfo?> = _displayInfo

    private val _status = MutableStateFlow("Negotiating…")
    override val status: StateFlow<String> = _status

    override val disconnected = CompletableDeferred<Unit>()

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private val iceGatheringComplete = CompletableDeferred<Unit>()
    private var controlChannel: DataChannel? = null
    private var disconnectGrace: kotlinx.coroutines.Job? = null

    private val observer = object : PeerConnection.Observer {
        override fun onSignalingChange(state: PeerConnection.SignalingState) {}
        override fun onIceConnectionChange(state: PeerConnection.IceConnectionState) = handleIceState(state)
        override fun onIceConnectionReceivingChange(receiving: Boolean) {}
        override fun onIceGatheringChange(state: PeerConnection.IceGatheringState) {
            if (state == PeerConnection.IceGatheringState.COMPLETE) iceGatheringComplete.complete(Unit)
        }
        override fun onIceCandidate(candidate: IceCandidate) {}
        override fun onIceCandidatesRemoved(candidates: Array<out IceCandidate>) {}
        override fun onAddStream(stream: MediaStream) {}
        override fun onRemoveStream(stream: MediaStream) {}
        override fun onRenegotiationNeeded() {}
        override fun onAddTrack(receiver: RtpReceiver, streams: Array<out MediaStream>) {}

        override fun onTrack(transceiver: RtpTransceiver) {
            Log.i(TAG, "Remote track: ${transceiver.receiver.track()?.kind()}")
            (transceiver.receiver.track() as? VideoTrack)?.let { _videoTrack.value = it }
        }

        override fun onDataChannel(channel: DataChannel) {
            Log.i(TAG, "Data channel '${channel.label()}' arrived")
            controlChannel = channel
            channel.registerObserver(object : DataChannel.Observer {
                override fun onBufferedAmountChange(previousAmount: Long) {}
                override fun onStateChange() {
                    if (channel.state() == DataChannel.State.OPEN) sendInputEvent(Messages.hello())
                }
                override fun onMessage(buffer: DataChannel.Buffer) {
                    val bytes = ByteArray(buffer.data.remaining()).also { buffer.data.get(it) }
                    handleControlMessage(String(bytes, Charsets.UTF_8))
                }
            })
        }
    }

    private val factory: PeerConnectionFactory
    private val peerConnection: PeerConnection

    init {
        initializeOnce(appContext)
        factory = PeerConnectionFactory.builder()
            .setVideoDecoderFactory(DefaultVideoDecoderFactory(eglBase.eglBaseContext))
            .setVideoEncoderFactory(DefaultVideoEncoderFactory(eglBase.eglBaseContext, true, true))
            .createPeerConnectionFactory()

        // No ICE servers: the host and this device share a LAN (or a USB
        // tethering network), so host candidates are all that's needed.
        val config = PeerConnection.RTCConfiguration(emptyList()).apply {
            sdpSemantics = PeerConnection.SdpSemantics.UNIFIED_PLAN
        }
        peerConnection = factory.createPeerConnection(config, observer)
            ?: error("PeerConnectionFactory returned no peer connection")
    }

    suspend fun negotiate(channel: SignalingChannel) {
        val offer = channel.receiveOffer()
        peerConnection.setRemote(SessionDescription(SessionDescription.Type.OFFER, offer.sdp))
        val answer = peerConnection.createAnswerSuspending()
        peerConnection.setLocal(answer)

        // The host does not do trickle ICE: it expects the answer to already
        // carry every candidate.
        if (peerConnection.iceGatheringState() != PeerConnection.IceGatheringState.COMPLETE) {
            iceGatheringComplete.await()
        }
        val local = peerConnection.localDescription ?: error("No local description after setLocalDescription")
        channel.sendAnswer(SdpEnvelope(local.description, "answer"))
        _status.value = "Connected"
    }

    override fun sendInputEvent(json: String) {
        val channel = controlChannel ?: return
        if (channel.state() != DataChannel.State.OPEN) return
        channel.send(DataChannel.Buffer(ByteBuffer.wrap(json.toByteArray(Charsets.UTF_8)), false))
    }

    override fun close() {
        Log.i(TAG, "Closing WebRTC client")
        disconnectGrace?.cancel()
        scope.cancel()
        controlChannel?.close()
        controlChannel = null
        _videoTrack.value = null
        peerConnection.close()
        factory.dispose()
        eglBase.release()
        disconnected.complete(Unit)
    }

    private fun handleControlMessage(raw: String) {
        when (Messages.typeOf(raw)) {
            MessageType.DISPLAY_INFO -> Messages.parseDisplayInfo(raw)?.let { _displayInfo.value = it }
            MessageType.BYE -> {
                Log.i(TAG, "Host said bye: $raw")
                _status.value = "Host disconnected"
                disconnected.complete(Unit)
            }
            else -> Unit // hello needs no reaction; input_event/stats aren't expected inbound.
        }
    }

    private fun handleIceState(state: PeerConnection.IceConnectionState) {
        Log.i(TAG, "ICE connection state: $state")
        _status.value = "ICE: $state"
        when (state) {
            PeerConnection.IceConnectionState.FAILED,
            PeerConnection.IceConnectionState.CLOSED -> disconnected.complete(Unit)
            // DISCONNECTED is often transient (a Wi-Fi blip); only give up if it doesn't recover.
            PeerConnection.IceConnectionState.DISCONNECTED -> {
                disconnectGrace?.cancel()
                disconnectGrace = scope.launch {
                    delay(DISCONNECT_GRACE_MS)
                    disconnected.complete(Unit)
                }
            }
            else -> disconnectGrace?.cancel()
        }
    }

    companion object {
        private const val TAG = "ViewDock"
        private const val DISCONNECT_GRACE_MS = 10_000L
        private var initialized = false

        @Synchronized
        private fun initializeOnce(appContext: Context) {
            if (initialized) return
            PeerConnectionFactory.initialize(
                PeerConnectionFactory.InitializationOptions.builder(appContext).createInitializationOptions(),
            )
            initialized = true
        }
    }
}

private abstract class SdpResult : SdpObserver {
    override fun onCreateSuccess(description: SessionDescription) {}
    override fun onSetSuccess() {}
    override fun onCreateFailure(error: String?) {}
    override fun onSetFailure(error: String?) {}
}

private suspend fun PeerConnection.setRemote(description: SessionDescription) =
    suspendCancellableCoroutine { cont ->
        setRemoteDescription(object : SdpResult() {
            override fun onSetSuccess() = cont.resume(Unit)
            override fun onSetFailure(error: String?) =
                cont.resumeWithException(IllegalStateException("setRemoteDescription failed: $error"))
        }, description)
    }

private suspend fun PeerConnection.setLocal(description: SessionDescription) =
    suspendCancellableCoroutine { cont ->
        setLocalDescription(object : SdpResult() {
            override fun onSetSuccess() = cont.resume(Unit)
            override fun onSetFailure(error: String?) =
                cont.resumeWithException(IllegalStateException("setLocalDescription failed: $error"))
        }, description)
    }

private suspend fun PeerConnection.createAnswerSuspending(): SessionDescription =
    suspendCancellableCoroutine { cont ->
        createAnswer(object : SdpResult() {
            override fun onCreateSuccess(description: SessionDescription) = cont.resume(description)
            override fun onCreateFailure(error: String?) =
                cont.resumeWithException(IllegalStateException("createAnswer failed: $error"))
        }, MediaConstraints())
    }
