// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 James Luna

package dev.viewdock.android

import android.os.Bundle
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.viewModels
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import dev.viewdock.android.net.ConnectionManager
import dev.viewdock.android.ui.ViewDockScreen

class MainActivity : ComponentActivity() {
    private val connection: ConnectionManager by viewModels()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        // The display is the product: draw edge to edge, hide the system
        // bars, and don't let the screen sleep mid-session.
        WindowCompat.setDecorFitsSystemWindows(window, false)
        WindowInsetsControllerCompat(window, window.decorView).apply {
            hide(WindowInsetsCompat.Type.systemBars())
            systemBarsBehavior = WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
        }
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)

        connection.start()
        setContent { ViewDockScreen(connection) }
    }
}
