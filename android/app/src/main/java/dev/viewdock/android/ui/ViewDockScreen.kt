// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 James Luna

package dev.viewdock.android.ui

import android.annotation.SuppressLint
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import dev.viewdock.android.R
import dev.viewdock.android.input.TouchInputForwarder
import dev.viewdock.android.net.ConnectionManager
import dev.viewdock.android.net.WebRtcClient
import dev.viewdock.android.net.WiredClient
import android.view.SurfaceHolder
import android.view.SurfaceView
import org.webrtc.RendererCommon
import org.webrtc.SurfaceViewRenderer

@Composable
fun ViewDockScreen(connection: ConnectionManager) {
    val session by connection.session.collectAsState()
    val status by connection.status.collectAsState()
    var page by rememberSaveable { mutableStateOf(AboutPage.NONE) }

    Box(Modifier.fillMaxSize().background(Color.Black)) {
        val active = session
        if (active != null) {
            BackHandler { connection.disconnect() }
            when (active) {
                is WebRtcClient -> ConnectedScreen(active)
                is WiredClient -> WiredScreen(active)
                else -> Unit
            }
        } else {
            when (page) {
                AboutPage.NONE -> {
                    ConnectScreen(
                        status = status,
                        initialHost = connection.savedHostAddress,
                        onConnect = connection::connectOverWifi,
                    )
                    // In the corner, not in the centered column: the screen is landscape-only and
                    // that column is already close to a phone's height.
                    TextButton(
                        onClick = { page = AboutPage.ABOUT },
                        modifier = Modifier.align(Alignment.TopEnd).padding(8.dp),
                        colors = ButtonDefaults.textButtonColors(contentColor = AccentBlue),
                    ) { Text(stringResource(R.string.about_open)) }
                }
                AboutPage.ABOUT -> AboutScreen(onBack = { page = AboutPage.NONE }, onOpen = { page = it })
                AboutPage.LICENSE -> LegalTextScreen(
                    title = stringResource(R.string.about_license),
                    assetPath = LegalInfo.LICENSE_ASSET,
                    onBack = { page = AboutPage.ABOUT },
                )
                AboutPage.THIRD_PARTY -> LegalTextScreen(
                    title = stringResource(R.string.about_third_party),
                    assetPath = LegalInfo.NOTICES_ASSET,
                    onBack = { page = AboutPage.ABOUT },
                )
            }
            BackHandler(enabled = page != AboutPage.NONE) {
                page = if (page == AboutPage.ABOUT) AboutPage.NONE else AboutPage.ABOUT
            }
        }
    }
}

@Composable
private fun ConnectScreen(status: String, initialHost: String, onConnect: (String) -> Unit) {
    var host by remember { mutableStateOf(initialHost) }
    Column(
        modifier = Modifier.fillMaxSize().padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp, Alignment.CenterVertically),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text(status, color = Color.White)
        OutlinedTextField(
            value = host,
            onValueChange = { host = it },
            label = { Text("Host IP address") },
            singleLine = true,
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri),
            modifier = Modifier.widthIn(max = 320.dp),
        )
        Button(onClick = { onConnect(host) }, enabled = host.isNotBlank()) {
            Text("Connect over Wi-Fi")
        }
        Text(
            "Or plug in the USB cable (USB debugging on) and start the host.",
            color = Color.Gray,
        )
    }
}

/** Full-screen video render + touch/stylus capture once negotiation with the host has completed. */
@SuppressLint("ClickableViewAccessibility")
@Composable
private fun ConnectedScreen(client: WebRtcClient) {
    val track by client.videoTrack.collectAsState()
    val displayInfo by client.displayInfo.collectAsState()
    val forwarder = remember(client) { TouchInputForwarder(send = client::sendInputEvent) }

    // The host's display_info is the fallback video size until the renderer
    // reports a real frame size (it can arrive first).
    LaunchedEffect(displayInfo) {
        displayInfo?.let {
            if (forwarder.videoWidth == 0) {
                forwarder.videoWidth = it.width
                forwarder.videoHeight = it.height
            }
        }
    }

    val renderer = remember(client) { SurfaceViewRenderer(client.appContext) }

    DisposableEffect(renderer) {
        renderer.init(
            client.eglBase.eglBaseContext,
            object : RendererCommon.RendererEvents {
                override fun onFirstFrameRendered() {}
                override fun onFrameResolutionChanged(width: Int, height: Int, rotation: Int) {
                    // Rotation is 0 for the host's capture; swap if it ever isn't.
                    val rotated = rotation % 180 != 0
                    forwarder.videoWidth = if (rotated) height else width
                    forwarder.videoHeight = if (rotated) width else height
                }
            },
        )
        renderer.setScalingType(RendererCommon.ScalingType.SCALE_ASPECT_FIT)
        renderer.setEnableHardwareScaler(true)
        renderer.setOnTouchListener { view, event ->
            forwarder.onTouchEvent(event, view.width, view.height)
        }
        onDispose {
            forwarder.reset()
            renderer.release()
        }
    }

    DisposableEffect(track, renderer) {
        val current = track
        current?.addSink(renderer)
        onDispose { current?.removeSink(renderer) }
    }

    AndroidView(factory = { renderer }, modifier = Modifier.fillMaxSize())
}

/**
 * Wired stream: the decoder renders straight onto this `SurfaceView`, sized to
 * the host display's aspect ratio so touch coordinates map 1:1 onto the video.
 */
@SuppressLint("ClickableViewAccessibility")
@Composable
private fun WiredScreen(client: WiredClient) {
    val displayInfo by client.displayInfo.collectAsState()
    val forwarder = remember(client) { TouchInputForwarder(send = client::sendInputEvent) }
    val aspect = displayInfo?.let { it.width.toFloat() / it.height } ?: (16f / 9f)

    DisposableEffect(client) { onDispose { forwarder.reset() } }

    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        AndroidView(
            factory = { context ->
                SurfaceView(context).apply {
                    holder.addCallback(object : SurfaceHolder.Callback {
                        override fun surfaceCreated(holder: SurfaceHolder) = client.attachSurface(holder.surface)
                        override fun surfaceChanged(holder: SurfaceHolder, format: Int, width: Int, height: Int) {}
                        override fun surfaceDestroyed(holder: SurfaceHolder) = client.detachSurface()
                    })
                    setOnTouchListener { view, event -> forwarder.onTouchEvent(event, view.width, view.height) }
                }
            },
            modifier = Modifier.aspectRatio(aspect),
        )
    }
}
