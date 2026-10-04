// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 James Luna

package dev.viewdock.android.net

import android.app.Application
import android.util.Log
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import dev.viewdock.android.protocol.MessageType
import dev.viewdock.android.protocol.Messages
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * Owns the connection lifecycle and drives [WebRtcClient] once signaling
 * completes. Mirrors the iPad app's `ConnectionManager`: USB is host-initiated
 * through the `adb forward` tunnel (see `host/transport/adb.py`), so this always
 * listens for it in the background; Wi-Fi needs the host's address entered by
 * the user since there is no discovery yet.
 */
class ConnectionManager(application: Application) : AndroidViewModel(application) {
    private val _status = MutableStateFlow("Waiting for host…")
    val status: StateFlow<String> = _status

    private val _session = MutableStateFlow<StreamSession?>(null)
    val session: StateFlow<StreamSession?> = _session

    private val prefs = application.getSharedPreferences("viewdock", 0)
    val savedHostAddress: String get() = prefs.getString(KEY_HOST, "") ?: ""

    private var usbSignaling: UsbSignaling? = null
    private var wifiSignaling: WifiSignaling? = null
    private var usbJob: Job? = null
    private var wifiJob: Job? = null

    fun start() {
        if (usbJob?.isActive == true || _session.value != null) return
        usbJob = viewModelScope.launch { listenForUsb() }
    }

    fun connectOverWifi(hostAddress: String) {
        val address = hostAddress.trim()
        if (address.isEmpty() || wifiJob?.isActive == true) return
        prefs.edit().putString(KEY_HOST, address).apply()
        wifiJob = viewModelScope.launch { connectWifi(address) }
    }

    /** Ends the current session (or attempt) and goes back to listening for USB. */
    fun disconnect() {
        teardown()
        _status.value = "Disconnected"
        start()
    }

    override fun onCleared() = teardown()

    private fun teardown() {
        usbJob?.cancel()
        wifiJob?.cancel()
        _session.value?.close()
        _session.value = null
        usbSignaling?.close()
        usbSignaling = null
        wifiSignaling?.close()
        wifiSignaling = null
    }

    /**
     * Retries on failure rather than giving up after one bad connection — a
     * stray connection to the loopback port (anything that completes the TCP
     * handshake but isn't the host) must not permanently kill USB listening.
     */
    private suspend fun listenForUsb() {
        while (viewModelScope.isActive) {
            val signaling = UsbSignaling()
            usbSignaling = signaling
            try {
                _status.value = "Waiting for USB connection…"
                signaling.waitForHost()
                if (Messages.typeOf(signaling.peekFirstText()) == MessageType.HELLO) {
                    // Wired stream: this connection *is* the session (video
                    // and input both ride it), so it stays open until the
                    // session ends; teardown() then closes it.
                    Log.i(TAG, "Host connected over USB; wired stream")
                    adopt(WiredClient(signaling))
                    return
                }
                Log.i(TAG, "Host connected over USB; negotiating WebRTC")
                negotiate(signaling)
                // WebRTC: the signaling socket has done its job. Leaving the
                // listener open would let a reconnecting host land on this
                // stale server (and then get `1001 going away` when it is
                // torn down), so free the port now; a fresh listener starts
                // when this session ends.
                signaling.close()
                usbSignaling = null
                return
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                Log.e(TAG, "USB session failed", e)
                _status.value = "USB listener retrying after error: ${e.message}"
                signaling.close()
                usbSignaling = null
                delay(1_000)
            }
        }
    }

    private suspend fun connectWifi(address: String) {
        val signaling = WifiSignaling(address)
        wifiSignaling = signaling
        try {
            _status.value = "Connecting to $address…"
            withContext(Dispatchers.IO) { signaling.connect() }
            negotiate(signaling)
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            Log.e(TAG, "Wi-Fi session failed", e)
            signaling.close()
            wifiSignaling = null
            _status.value = "Wi-Fi connect failed: ${e.message}"
        }
    }

    private suspend fun negotiate(channel: SignalingChannel) {
        if (_session.value != null) return // USB and Wi-Fi could race; first one wins.
        val client = WebRtcClient(getApplication())
        _status.value = "Negotiating…"
        try {
            client.negotiate(channel)
        } catch (e: Exception) {
            client.close()
            throw e
        }
        adopt(client)
    }

    /** Publishes a live session and returns to listening once it ends. */
    private fun adopt(session: StreamSession) {
        _session.value = session
        // The host loops back to "waiting for device" when a session ends, so
        // do the same here: drop the dead session and listen again.
        viewModelScope.launch {
            session.disconnected.await()
            Log.i(TAG, "Session ended (${session.status.value})")
            if (_session.value === session) {
                teardown()
                _status.value = "Disconnected — waiting for host…"
                start()
            }
        }
    }

    private companion object {
        const val TAG = "ViewDock"
        const val KEY_HOST = "host_address"
    }
}
