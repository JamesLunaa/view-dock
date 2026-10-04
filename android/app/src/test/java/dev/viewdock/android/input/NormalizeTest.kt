package dev.viewdock.android.input

import org.junit.Assert.assertEquals
import org.junit.Test

class NormalizeTest {
    private fun n(x: Float, y: Float, vw: Int, vh: Int, fw: Int, fh: Int) =
        TouchInputForwarder.normalize(x, y, vw, vh, fw, fh)

    @Test
    fun matchingAspectMapsLinearly() {
        val (x, y) = n(500f, 250f, 1000, 500, 1600, 800)
        assertEquals(0.5, x, 1e-9)
        assertEquals(0.5, y, 1e-9)
    }

    @Test
    fun letterboxedVideoIsMeasuredAgainstTheVideoRectNotTheView() {
        // 2000x1000 view showing a 4:3 video: 1333.3px wide, centered (bars of ~333px).
        val (centerX, _) = n(1000f, 500f, 2000, 1000, 1600, 1200)
        assertEquals(0.5, centerX, 1e-9)
        val (leftEdgeX, _) = n((2000 - 1333.333f) / 2, 500f, 2000, 1000, 1600, 1200)
        assertEquals(0.0, leftEdgeX, 1e-3)
    }

    @Test
    fun touchOnLetterboxBarClampsToEdge() {
        val (x, _) = n(10f, 500f, 2000, 1000, 1600, 1200)
        assertEquals(0.0, x, 1e-9)
        val (xr, _) = n(1990f, 500f, 2000, 1000, 1600, 1200)
        assertEquals(1.0, xr, 1e-9)
    }

    @Test
    fun unknownVideoSizeFallsBackToWholeView() {
        val (x, y) = n(250f, 100f, 1000, 400, 0, 0)
        assertEquals(0.25, x, 1e-9)
        assertEquals(0.25, y, 1e-9)
    }
}
