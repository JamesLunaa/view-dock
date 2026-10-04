// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 James Luna

package dev.viewdock.android.net

import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.flow.StateFlow

/** A live connection to the host, however its video arrives (WebRTC or the wired stream). */
interface StreamSession {
    val status: StateFlow<String>

    /** Completes once the session is over, whether the host said bye or the link died. */
    val disconnected: CompletableDeferred<Unit>

    fun sendInputEvent(json: String)
    fun close()
}
