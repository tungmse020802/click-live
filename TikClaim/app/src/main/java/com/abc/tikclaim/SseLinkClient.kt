package com.abc.tikclaim

import android.util.Log
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.sse.EventSource
import okhttp3.sse.EventSourceListener
import okhttp3.sse.EventSources
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.TimeUnit

internal data class ClickAction(
    val x: Int,
    val y: Int,
    val delayMs: Long = 0L,
    val durationMs: Long = 80L,
)

internal data class SseLinkEvent(
    val url: String,
    val clickAfterMs: Long = 0L,
    val clickX: Int = 540,
    val clickY: Int = 1800,
    val actions: List<ClickAction> = emptyList(),
)

internal class SseLinkClient {
    private val tag = "TikClaimSse"
    private val client = OkHttpClient.Builder()
        .readTimeout(0, TimeUnit.MILLISECONDS)
        .build()
    private var eventSource: EventSource? = null

    fun start(
        url: String,
        onOpen: () -> Unit,
        onLink: (SseLinkEvent) -> Unit,
        onError: (String) -> Unit,
        onClosed: () -> Unit
    ) {
        stop()

        val request = Request.Builder()
            .url(url)
            .header("Accept", "text/event-stream")
            .build()

        eventSource = EventSources.createFactory(client).newEventSource(
            request,
            object : EventSourceListener() {
                override fun onOpen(eventSource: EventSource, response: Response) {
                    Log.i(tag, "SSE opened HTTP ${response.code}")
                    onOpen()
                }

                override fun onEvent(
                    eventSource: EventSource,
                    id: String?,
                    type: String?,
                    data: String
                ) {
                    Log.i(tag, "SSE event type=$type id=$id data=$data")
                    val event = extractEvent(data)
                    if (event == null) {
                        Log.w(tag, "SSE event ignored: no supported link")
                    } else {
                        onLink(event)
                    }
                }

                override fun onFailure(
                    eventSource: EventSource,
                    t: Throwable?,
                    response: Response?
                ) {
                    val code = response?.code?.let { "HTTP $it: " }.orEmpty()
                    Log.e(tag, "SSE failure ${code}${t?.message ?: "unknown"}", t)
                    onError("${code}${t?.message ?: "Lỗi kết nối SSE"}")
                }

                override fun onClosed(eventSource: EventSource) {
                    Log.i(tag, "SSE closed")
                    onClosed()
                }
            }
        )
    }

    fun stop() {
        eventSource?.cancel()
        eventSource = null
    }

    private fun extractEvent(data: String): SseLinkEvent? {
        val trimmed = data.trim()
        if (trimmed.isSupportedLink()) return SseLinkEvent(url = trimmed)

        runCatching {
            val json = JSONObject(trimmed)
            val job = json.optJSONObject("job")
            val payload = job?.optJSONObject("payload")
            val url = json.optString("url")
                .ifBlank { json.optString("link") }
                .ifBlank { job?.optString("url").orEmpty() }
                .ifBlank { job?.optString("link").orEmpty() }
                .ifBlank { payload?.optString("url").orEmpty() }
                .ifBlank { payload?.optString("link").orEmpty() }

            if (!url.isSupportedLink()) return@runCatching null

            val firstClickDelayMs = (job?.optLong("click_after_ms")
                ?: json.optLong("click_after_ms", 0L)).coerceAtLeast(0L)
            val firstClickX = (job?.optInt("click_x")
                ?: json.optInt("click_x", 540)).coerceAtLeast(1)
            val firstClickY = (job?.optInt("click_y")
                ?: json.optInt("click_y", 1800)).coerceAtLeast(1)

            SseLinkEvent(
                url = url,
                clickAfterMs = firstClickDelayMs,
                clickX = firstClickX,
                clickY = firstClickY,
                actions = parseActions(json, job, payload, firstClickX, firstClickY, firstClickDelayMs),
            )
        }.getOrNull()?.let { return it }

        return Regex("""(?:https?://|tiktok://)\S+""")
            .find(trimmed)
            ?.value
            ?.let { SseLinkEvent(url = it) }
    }

    private fun String.isSupportedLink(): Boolean {
        return startsWith("http://") || startsWith("https://") || startsWith("tiktok://")
    }

    private fun parseActions(
        json: JSONObject,
        job: JSONObject?,
        payload: JSONObject?,
        defaultX: Int,
        defaultY: Int,
        defaultDelayMs: Long,
    ): List<ClickAction> {
        val candidates = listOfNotNull(
            json.optJSONArray("actions"),
            json.optJSONArray("clicks"),
            job?.optJSONArray("actions"),
            job?.optJSONArray("clicks"),
            payload?.optJSONArray("actions"),
            payload?.optJSONArray("clicks"),
        )

        val parsedActions = candidates.firstOrNull()
            ?.let(::parseActionArray)
            .orEmpty()

        if (parsedActions.isNotEmpty()) return parsedActions

        val afterOpenClick = parseAfterOpenClick(json, job, payload)
        if (afterOpenClick != null) return listOf(afterOpenClick)

        return listOf(
            ClickAction(
                x = defaultX,
                y = defaultY,
                delayMs = defaultDelayMs,
            )
        )
    }

    private fun parseActionArray(actions: JSONArray): List<ClickAction> {
        val result = mutableListOf<ClickAction>()
        for (index in 0 until actions.length()) {
            val action = actions.optJSONObject(index) ?: continue
            val type = action.optString("type", "tap")
            if (type.isNotBlank() && type != "tap" && type != "click") continue

            val x = action.optInt("x", 0)
            val y = action.optInt("y", 0)
            if (x <= 0 || y <= 0) continue

            result += ClickAction(
                x = x,
                y = y,
                delayMs = action.optLong("delay_ms", action.optLong("after_ms", 0L))
                    .coerceAtLeast(0L),
                durationMs = action.optLong("duration_ms", 80L)
                    .coerceIn(40L, 1_500L),
            )
        }
        return result
    }

    private fun parseAfterOpenClick(json: JSONObject, job: JSONObject?, payload: JSONObject?): ClickAction? {
        val source = job?.optJSONObject("after_open_click")
            ?: json.optJSONObject("after_open_click")
            ?: payload?.optJSONObject("after_open_click")
            ?: return null
        val x = source.optInt("x", 0)
        val y = source.optInt("y", 0)
        if (x <= 0 || y <= 0) return null
        return ClickAction(
            x = x,
            y = y,
            delayMs = source.optLong("delay_ms", source.optLong("after_ms", 0L))
                .coerceAtLeast(0L),
            durationMs = source.optLong("duration_ms", 80L)
                .coerceIn(40L, 1_500L),
        )
    }
}
