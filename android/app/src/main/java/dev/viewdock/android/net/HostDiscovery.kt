// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 James Luna

package dev.viewdock.android.net

import android.content.Context
import android.net.nsd.NsdManager
import android.net.nsd.NsdServiceInfo
import android.util.Log
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow

/**
 * Browses the LAN for view-dock hosts with the platform [NsdManager]. Discovery
 * keeps the Wi-Fi radio busy, so [start] when the connect screen is showing and
 * [stop] as soon as it is not.
 *
 * Only ever touched from the main thread (NSD callbacks arrive on its own
 * thread, so they hop through [post]).
 */
class HostDiscovery(context: Context) {
    private val nsd = context.applicationContext.getSystemService(Context.NSD_SERVICE) as NsdManager
    private val mainHandler = android.os.Handler(android.os.Looper.getMainLooper())

    private val _hosts = MutableStateFlow<List<DiscoveredHost>>(emptyList())
    val hosts: StateFlow<List<DiscoveredHost>> = _hosts

    /** True from [start] until [stop], so the UI can say "Searching…". */
    private val _searching = MutableStateFlow(false)
    val searching: StateFlow<Boolean> = _searching

    private var listener: NsdManager.DiscoveryListener? = null
    private val found = LinkedHashMap<String, DiscoveredHost>()   // by NSD service name
    private val resolveQueue = ArrayDeque<NsdServiceInfo>()
    private var resolving = false

    fun start() {
        if (listener != null) return
        found.clear()
        publish()
        val discovery = object : NsdManager.DiscoveryListener {
            override fun onDiscoveryStarted(serviceType: String) {}
            override fun onServiceFound(service: NsdServiceInfo) = post { enqueue(service) }
            override fun onServiceLost(service: NsdServiceInfo) = post {
                if (found.remove(service.serviceName) != null) publish()
            }
            override fun onDiscoveryStopped(serviceType: String) {}
            override fun onStartDiscoveryFailed(serviceType: String, errorCode: Int) {
                Log.w(TAG, "NSD discovery failed to start: $errorCode")
                post { listener = null; _searching.value = false }
            }
            override fun onStopDiscoveryFailed(serviceType: String, errorCode: Int) {
                Log.w(TAG, "NSD discovery failed to stop: $errorCode")
            }
        }
        listener = discovery
        _searching.value = true
        try {
            nsd.discoverServices(HostRecords.SERVICE_TYPE, NsdManager.PROTOCOL_DNS_SD, discovery)
        } catch (e: Exception) {
            // Discovery is a convenience; the typed address keeps working.
            Log.w(TAG, "NSD discovery unavailable", e)
            listener = null
            _searching.value = false
        }
    }

    fun stop() {
        val active = listener ?: return
        listener = null
        _searching.value = false
        resolveQueue.clear()
        try {
            nsd.stopServiceDiscovery(active)
        } catch (e: IllegalArgumentException) {
            // Already stopped by the system.
        }
        found.clear()
        publish()
    }

    private fun post(block: () -> Unit) {
        mainHandler.post(block)
    }

    // resolveService allows one resolve at a time (FAILURE_ALREADY_ACTIVE otherwise).
    private fun enqueue(service: NsdServiceInfo) {
        if (listener == null) return
        resolveQueue.addLast(service)
        resolveNext()
    }

    @Suppress("DEPRECATION") // registerServiceInfoCallback needs API 34; minSdk is 26.
    private fun resolveNext() {
        if (resolving) return
        val service = resolveQueue.removeFirstOrNull() ?: return
        resolving = true
        nsd.resolveService(service, object : NsdManager.ResolveListener {
            override fun onResolveFailed(info: NsdServiceInfo, errorCode: Int) {
                Log.w(TAG, "Resolving ${info.serviceName} failed: $errorCode")
                post { resolving = false; resolveNext() }
            }

            override fun onServiceResolved(info: NsdServiceInfo) = post {
                resolving = false
                if (listener != null) {
                    toHost(info)?.let { found[info.serviceName] = it; publish() }
                }
                resolveNext()
            }
        })
    }

    private fun toHost(info: NsdServiceInfo): DiscoveredHost? {
        val address = info.host?.hostAddress?.let { HostRecords.preferredAddress(listOf(it)) } ?: return null
        return DiscoveredHost(
            name = HostRecords.txt(info.attributes, HostRecords.KEY_NAME) ?: info.serviceName,
            address = address,
            port = info.port,
            protocolVersion = HostRecords.txt(info.attributes, HostRecords.KEY_PROTOCOL_VERSION),
        )
    }

    private fun publish() {
        _hosts.value = found.values.distinctBy { it.key }.sortedBy { it.title.lowercase() }
    }

    private companion object {
        const val TAG = "HostDiscovery"
    }
}
