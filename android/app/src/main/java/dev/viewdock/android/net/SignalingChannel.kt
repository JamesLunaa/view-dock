package dev.viewdock.android.net

import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.channels.Channel
import org.java_websocket.WebSocket
import org.java_websocket.client.WebSocketClient
import org.java_websocket.handshake.ClientHandshake
import org.java_websocket.handshake.ServerHandshake
import org.java_websocket.server.WebSocketServer
import org.json.JSONObject
import java.net.InetAddress
import java.net.InetSocketAddress
import java.net.URI
import java.nio.ByteBuffer

/**
 * Bootstrap channel used only to exchange the WebRTC SDP offer/answer pair
 * before the real peer connection takes over. Mirrors `host/transport/base.py`'s
 * `send_signal`/`receive_signal`; the host always sends the offer first (see
 * `host/streaming/webrtc_session.py`), so this side only ever answers.
 */
interface SignalingChannel {
    suspend fun receiveOffer(): SdpEnvelope
    fun sendAnswer(answer: SdpEnvelope)
    fun close()
}

data class SdpEnvelope(val sdp: String, val type: String) {
    fun toJson(): String = JSONObject().put("sdp", sdp).put("type", type).toString()

    companion object {
        fun fromJson(raw: String): SdpEnvelope {
            val json = JSONObject(raw)
            return SdpEnvelope(json.getString("sdp"), json.getString("type"))
        }
    }
}

class SignalingClosedException(message: String) : Exception(message)

/**
 * Wi-Fi: the host runs the signaling server (`host/transport/wifi.py`) and this
 * connects to it directly, given the host's address on the LAN.
 */
class WifiSignaling(private val hostAddress: String, private val port: Int = 8765) : SignalingChannel {
    private val incoming = Channel<String>(Channel.UNLIMITED)
    private var socket: WebSocketClient? = null

    /** Blocking — call from an IO dispatcher. */
    fun connect(timeoutMs: Long = 8_000) {
        val client = object : WebSocketClient(URI("ws://$hostAddress:$port")) {
            override fun onOpen(handshake: ServerHandshake) {}
            override fun onMessage(message: String) {
                incoming.trySend(message)
            }
            override fun onClose(code: Int, reason: String?, remote: Boolean) {
                incoming.close(SignalingClosedException("Host closed the signaling connection"))
            }
            override fun onError(ex: Exception) {
                incoming.close(ex)
            }
        }
        client.connectionLostTimeout = 0
        socket = client
        if (!client.connectBlocking(timeoutMs, java.util.concurrent.TimeUnit.MILLISECONDS)) {
            client.close()
            throw SignalingClosedException("Could not reach $hostAddress:$port")
        }
    }

    override suspend fun receiveOffer(): SdpEnvelope = SdpEnvelope.fromJson(incoming.receive())

    override fun sendAnswer(answer: SdpEnvelope) {
        socket?.send(answer.toJson()) ?: throw SignalingClosedException("Not connected")
    }

    override fun close() {
        socket?.close()
        socket = null
        incoming.close()
    }
}

/**
 * USB: this app must be the listener — `adb forward tcp:N tcp:N` on the host
 * relays connections to a port *on this device*, so for USB the host connects
 * through the tunnel as a client (see `host/transport/adb.py`). Bound to
 * loopback only: adb delivers the forwarded connection locally, so nothing on
 * the LAN can reach this listener.
 */
class UsbSignaling(private val port: Int = 8766) : SignalingChannel {
    /** What the host sent: text for control messages / SDP, binary for wired video frames. */
    sealed interface Incoming {
        class Text(val text: String) : Incoming
        class Binary(val bytes: ByteArray) : Incoming
    }

    private val incoming = Channel<Incoming>(Channel.UNLIMITED)

    // A message already read to decide which kind of session this is.
    private var pending: Incoming? = null
    private val hostConnected = CompletableDeferred<Unit>()

    @Volatile
    private var hostSocket: WebSocket? = null

    private val server = object : WebSocketServer(
        InetSocketAddress(InetAddress.getByAddress(byteArrayOf(127, 0, 0, 1)), port),
    ) {
        override fun onStart() {}

        override fun onOpen(conn: WebSocket, handshake: ClientHandshake) {
            // One host at a time; the first connection wins.
            if (hostSocket != null) {
                conn.close()
                return
            }
            hostSocket = conn
            hostConnected.complete(Unit)
        }

        override fun onMessage(conn: WebSocket, message: String) {
            if (conn === hostSocket) incoming.trySend(Incoming.Text(message))
        }

        override fun onMessage(conn: WebSocket, message: ByteBuffer) {
            if (conn !== hostSocket) return
            val bytes = ByteArray(message.remaining())
            message.get(bytes)
            incoming.trySend(Incoming.Binary(bytes))
        }

        override fun onClose(conn: WebSocket, code: Int, reason: String?, remote: Boolean) {
            if (conn === hostSocket) {
                hostSocket = null
                incoming.close(SignalingClosedException("Host closed the signaling connection"))
            }
        }

        override fun onError(conn: WebSocket?, ex: Exception) {
            // A null `conn` means the listener itself failed (e.g. the port is
            // still held by a previous run), not one client connection.
            if (conn == null) hostConnected.completeExceptionally(ex)
            incoming.close(ex)
        }
    }

    init {
        server.isReuseAddr = true
        server.connectionLostTimeout = 0
    }

    /** Starts listening and suspends until the host connects through the tunnel. */
    suspend fun waitForHost() {
        server.start()
        hostConnected.await()
    }

    /** The next message from the host, in order. */
    suspend fun receive(): Incoming = pending?.also { pending = null } ?: incoming.receive()

    /**
     * Reads the host's first message and keeps it for the next [receive] /
     * [receiveOffer], so the caller can decide what kind of session this is
     * (a wired `hello`, or a WebRTC SDP offer) without consuming it.
     */
    suspend fun peekFirstText(): String {
        val first = receive()
        pending = first
        return (first as? Incoming.Text)?.text ?: throw SignalingClosedException("Host opened with a binary frame")
    }

    fun sendText(text: String) {
        (hostSocket ?: throw SignalingClosedException("Host not connected")).send(text)
    }

    override suspend fun receiveOffer(): SdpEnvelope =
        SdpEnvelope.fromJson((receive() as? Incoming.Text)?.text ?: throw SignalingClosedException("Expected an SDP offer"))

    override fun sendAnswer(answer: SdpEnvelope) = sendText(answer.toJson())

    override fun close() {
        incoming.close()
        try {
            server.stop(500)
        } catch (_: Exception) {
            // Already stopped, or never started.
        }
    }
}
