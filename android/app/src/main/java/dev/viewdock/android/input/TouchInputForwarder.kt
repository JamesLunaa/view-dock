// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 James Luna

package dev.viewdock.android.input

import android.view.MotionEvent
import dev.viewdock.android.protocol.InputKind
import dev.viewdock.android.protocol.Messages

/**
 * Turns `MotionEvent`s from the video view into `input_event` messages
 * (protocol/PROTOCOL.md). Coordinates are normalized to [0, 1] relative to the
 * *video content*, not the view: the stream is letterboxed to keep its aspect
 * ratio, and the host maps normalized coordinates onto the virtual display.
 *
 * The protocol is single-pointer, so only the first finger/stylus to touch
 * down is tracked until it lifts; other pointers are ignored. A stylus
 * (`TOOL_TYPE_STYLUS`) is sent as `pencil_*` with pressure, a finger as
 * `touch_*` with pressure 0 — the same convention as the iPad client.
 */
class TouchInputForwarder(
    private val send: (String) -> Unit,
    private val now: () -> Long = System::currentTimeMillis,
) {
    private var trackedPointerId = NO_POINTER

    /** Video frame size in pixels; (0, 0) until the first frame arrives. */
    var videoWidth = 0
    var videoHeight = 0

    fun onTouchEvent(event: MotionEvent, viewWidth: Int, viewHeight: Int): Boolean {
        if (viewWidth <= 0 || viewHeight <= 0) return false

        when (event.actionMasked) {
            MotionEvent.ACTION_DOWN, MotionEvent.ACTION_POINTER_DOWN -> {
                if (trackedPointerId == NO_POINTER) {
                    val index = event.actionIndex
                    trackedPointerId = event.getPointerId(index)
                    emit(event, index, viewWidth, viewHeight, Phase.DOWN)
                }
            }
            MotionEvent.ACTION_MOVE -> {
                val index = event.findPointerIndex(trackedPointerId)
                if (index >= 0) {
                    // A stylus reports at a higher rate than frames are
                    // delivered; the batched samples keep strokes smooth.
                    for (h in 0 until event.historySize) {
                        emitSample(
                            event, index, viewWidth, viewHeight, Phase.MOVE,
                            event.getHistoricalX(index, h), event.getHistoricalY(index, h),
                            event.getHistoricalPressure(index, h),
                        )
                    }
                    emit(event, index, viewWidth, viewHeight, Phase.MOVE)
                }
            }
            MotionEvent.ACTION_UP, MotionEvent.ACTION_POINTER_UP, MotionEvent.ACTION_CANCEL -> {
                val liftedIndex = if (event.actionMasked == MotionEvent.ACTION_POINTER_UP) event.actionIndex else 0
                val tracked = event.actionMasked == MotionEvent.ACTION_CANCEL ||
                    event.getPointerId(liftedIndex) == trackedPointerId
                if (tracked) {
                    val index = event.findPointerIndex(trackedPointerId).takeIf { it >= 0 } ?: liftedIndex
                    emit(event, index, viewWidth, viewHeight, Phase.UP)
                    trackedPointerId = NO_POINTER
                }
            }
            else -> return false
        }
        return true
    }

    /** Releases the tracked pointer without sending anything, e.g. when the view goes away mid-touch. */
    fun reset() {
        trackedPointerId = NO_POINTER
    }

    private fun emit(event: MotionEvent, index: Int, viewWidth: Int, viewHeight: Int, phase: Phase) =
        emitSample(
            event, index, viewWidth, viewHeight, phase,
            event.getX(index), event.getY(index), event.getPressure(index),
        )

    private fun emitSample(
        event: MotionEvent,
        index: Int,
        viewWidth: Int,
        viewHeight: Int,
        phase: Phase,
        x: Float,
        y: Float,
        pressure: Float,
    ) {
        val stylus = event.getToolType(index) == MotionEvent.TOOL_TYPE_STYLUS
        val (nx, ny) = normalize(x, y, viewWidth, viewHeight, videoWidth, videoHeight)
        send(
            Messages.inputEvent(
                kind = kindFor(stylus, phase),
                x = nx,
                y = ny,
                pressure = if (stylus) pressure.toDouble().coerceIn(0.0, 1.0) else 0.0,
                timestampMs = now(),
            ),
        )
    }

    private enum class Phase { DOWN, MOVE, UP }

    companion object {
        private const val NO_POINTER = -1

        private fun kindFor(stylus: Boolean, phase: Phase): InputKind = when (phase) {
            Phase.DOWN -> if (stylus) InputKind.PENCIL_DOWN else InputKind.TOUCH_DOWN
            Phase.MOVE -> if (stylus) InputKind.PENCIL_MOVE else InputKind.TOUCH_MOVE
            Phase.UP -> if (stylus) InputKind.PENCIL_UP else InputKind.TOUCH_UP
        }

        /**
         * Maps a point in the view onto the aspect-fit video rectangle, clamped
         * to [0, 1] (a touch on the letterbox bars lands on the nearest edge).
         * Falls back to the whole view until the video size is known.
         */
        fun normalize(
            x: Float,
            y: Float,
            viewWidth: Int,
            viewHeight: Int,
            videoWidth: Int,
            videoHeight: Int,
        ): Pair<Double, Double> {
            var left = 0.0
            var top = 0.0
            var width = viewWidth.toDouble()
            var height = viewHeight.toDouble()
            if (videoWidth > 0 && videoHeight > 0) {
                val scale = minOf(viewWidth.toDouble() / videoWidth, viewHeight.toDouble() / videoHeight)
                width = videoWidth * scale
                height = videoHeight * scale
                left = (viewWidth - width) / 2
                top = (viewHeight - height) / 2
            }
            return ((x - left) / width).coerceIn(0.0, 1.0) to ((y - top) / height).coerceIn(0.0, 1.0)
        }
    }
}
