// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 James Luna

package dev.viewdock.android.ui

import android.content.Context
import android.content.pm.PackageManager
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import dev.viewdock.android.R
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.IOException

/**
 * The icon's blue. The app has no Material theme, so buttons would otherwise default to a dark
 * purple that is hard to read on the black background.
 */
internal val AccentBlue = Color(0xFF7FB2FF)

/** Which page of the About flow is showing; [NONE] is the normal connect screen. */
enum class AboutPage { NONE, ABOUT, LICENSE, THIRD_PARTY }

/**
 * The legal notices screen. Besides being good manners, a GPL program with a
 * user interface has to show its copyright, say there is no warranty, and tell
 * the user how to see the license (GPL-3.0 section 5(d)) — this is that.
 */
@Composable
fun AboutScreen(onBack: () -> Unit, onOpen: (AboutPage) -> Unit) {
    val context = LocalContext.current
    val uriHandler = LocalUriHandler.current
    val version = remember { appVersion(context) }

    Box(Modifier.fillMaxSize().background(Color.Black), contentAlignment = Alignment.TopCenter) {
        Column(
            modifier = Modifier
                .widthIn(max = 640.dp)
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 24.dp, vertical = 12.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            TextButton(onClick = onBack, colors = ButtonDefaults.textButtonColors(contentColor = AccentBlue)) {
                Text(stringResource(R.string.about_back))
            }
            Text(
                stringResource(R.string.about_title),
                color = Color.White,
                fontSize = 22.sp,
                fontWeight = FontWeight.Bold,
            )
            Text(stringResource(R.string.about_version, version), color = Color.Gray)
            Text(LegalInfo.COPYRIGHT, color = Color.White)
            Text(stringResource(R.string.about_free_software), color = Color.LightGray)
            Text(stringResource(R.string.about_no_warranty), color = Color.LightGray)

            OutlinedButton(
                onClick = { onOpen(AboutPage.LICENSE) },
                modifier = Modifier.fillMaxWidth(),
                colors = ButtonDefaults.outlinedButtonColors(contentColor = Color.White),
                border = BorderStroke(1.dp, Color.Gray),
            ) {
                Text(stringResource(R.string.about_license))
            }
            OutlinedButton(
                onClick = { onOpen(AboutPage.THIRD_PARTY) },
                modifier = Modifier.fillMaxWidth(),
                colors = ButtonDefaults.outlinedButtonColors(contentColor = Color.White),
                border = BorderStroke(1.dp, Color.Gray),
            ) {
                Text(stringResource(R.string.about_third_party))
            }
            OutlinedButton(
                onClick = { uriHandler.openUri(LegalInfo.SOURCE_URL) },
                modifier = Modifier.fillMaxWidth(),
                colors = ButtonDefaults.outlinedButtonColors(contentColor = Color.White),
                border = BorderStroke(1.dp, Color.Gray),
            ) {
                Text(stringResource(R.string.about_source))
            }
        }
    }
}

/** A long text asset (the GPL, or the third-party notices) in a scrolling, monospaced view. */
@Composable
fun LegalTextScreen(title: String, assetPath: String, onBack: () -> Unit) {
    val context = LocalContext.current
    val text by produceState<String?>(initialValue = null, assetPath) {
        value = withContext(Dispatchers.IO) {
            try {
                context.assets.open(assetPath).bufferedReader().use { it.readText() }
            } catch (e: IOException) {
                "Could not load $assetPath: ${e.message}"
            }
        }
    }

    Column(Modifier.fillMaxSize().background(Color.Black)) {
        Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(horizontal = 12.dp, vertical = 4.dp)) {
            TextButton(onClick = onBack, colors = ButtonDefaults.textButtonColors(contentColor = AccentBlue)) {
                Text(stringResource(R.string.about_back))
            }
            Text(title, color = Color.White, fontWeight = FontWeight.Bold)
        }
        // One line per row so the 600+ line GPL doesn't have to be laid out as a single giant Text.
        val lines = remember(text) { text?.lines() ?: listOf("Loading…") }
        LazyColumn(Modifier.fillMaxSize().padding(horizontal = 16.dp)) {
            items(lines) { line ->
                Text(
                    // An empty Text has no height; a space keeps blank lines blank.
                    line.ifEmpty { " " },
                    color = Color.LightGray,
                    fontFamily = FontFamily.Monospace,
                    fontSize = 13.sp,
                )
            }
        }
    }
}

private fun appVersion(context: Context): String = try {
    context.packageManager.getPackageInfo(context.packageName, 0).versionName ?: "?"
} catch (_: PackageManager.NameNotFoundException) {
    "?"
}
