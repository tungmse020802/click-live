package com.abc.tikclaim

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.graphics.Path
import android.os.Handler
import android.os.Looper
import android.util.Log
import android.view.accessibility.AccessibilityEvent
import java.lang.ref.WeakReference

class TikTokAccessibilityService : AccessibilityService() {
    private val tag = "TikClaimAccessibility"
    private val handler = Handler(Looper.getMainLooper())
    private var tikTokVisible = false

    override fun onServiceConnected() {
        instance = WeakReference(this)
        pendingEvent?.let(::scheduleIfReady)
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        val packageName = event?.packageName?.toString().orEmpty()
        tikTokVisible = packageName in TIKTOK_PACKAGE_SET
        if (tikTokVisible) {
            pendingEvent?.let(::scheduleIfReady)
        }
    }

    override fun onInterrupt() = Unit

    override fun onDestroy() {
        instance?.clear()
        instance = null
        handler.removeCallbacksAndMessages(null)
        super.onDestroy()
    }

    private fun scheduleIfReady(event: SseLinkEvent) {
        if (!tikTokVisible) return
        pendingEvent = null
        handler.removeCallbacksAndMessages(null)
        runInteractionScript(event)
    }

    private fun runInteractionScript(event: SseLinkEvent) {
        val actions = event.actions.ifEmpty {
            listOf(
                ClickAction(
                    x = event.clickX,
                    y = event.clickY,
                    delayMs = event.clickAfterMs,
                )
            )
        }

        Log.i(tag, "Scheduling ${actions.size} TikTok tap(s)")
        actions.forEach { action ->
            handler.postDelayed({
                tap(action.x, action.y, action.durationMs)
            }, action.delayMs.coerceAtMost(MAX_INITIAL_DELAY_MS))
        }
    }

    private fun tap(x: Int, y: Int, durationMs: Long) {
        Log.i(tag, "Dispatching tap x=$x y=$y durationMs=$durationMs")
        val path = Path().apply { moveTo(x.toFloat(), y.toFloat()) }
        dispatchGesture(
            GestureDescription.Builder()
                .addStroke(GestureDescription.StrokeDescription(path, 0L, durationMs))
                .build(),
            null,
            null
        )
    }

    companion object {
        private val TIKTOK_PACKAGE_SET = TIKTOK_PACKAGES.toSet()
        private const val MAX_INITIAL_DELAY_MS = 120_000L

        private var instance: WeakReference<TikTokAccessibilityService>? = null
        private var pendingEvent: SseLinkEvent? = null

        internal fun requestInteraction(event: SseLinkEvent) {
            pendingEvent = event
            instance?.get()?.scheduleIfReady(event)
        }
    }
}
