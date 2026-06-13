package com.abc.tikclaim

import android.util.Log
import okhttp3.ConnectionPool
import okhttp3.Call
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

internal data class LongPollingResult(
    val jobId: Int,
    val event: SseLinkEvent,
)

internal class LongPollingLinkClient {
    private val tag = "TikClaimPolling"
    private val client = OkHttpClient.Builder()
        .connectionPool(ConnectionPool(0, 1, TimeUnit.SECONDS))
        .readTimeout(35, TimeUnit.SECONDS)
        .build()
    private val executor = Executors.newSingleThreadExecutor()
    @Volatile private var running = false
    @Volatile private var runToken = 0
    @Volatile private var currentCall: Call? = null

    fun start(
        baseUrl: String,
        afterId: Int,
        onOpen: () -> Unit,
        onLink: (LongPollingResult) -> Unit,
        onError: (String) -> Unit,
    ) {
        stop()
        val token = nextRunToken()
        running = true
        executor.execute {
            var lastId = afterId.coerceAtLeast(0)
            onOpen()
            Log.i(tag, "Long polling started baseUrl=$baseUrl afterId=$lastId")
            while (running && token == runToken) {
                try {
                    val result = fetchNextJob(baseUrl, lastId, token)
                    if (result != null) {
                        lastId = result.jobId
                        onLink(result)
                    }
                } catch (exc: Exception) {
                    Log.e(tag, "Long polling failed: ${exc.message}", exc)
                    onError(exc.message ?: "Lỗi long polling")
                    sleep(2_000L)
                }
            }
        }
    }

    fun stop() {
        running = false
        nextRunToken()
        currentCall?.cancel()
        currentCall = null
    }

    @Synchronized
    private fun nextRunToken(): Int {
        runToken += 1
        return runToken
    }

    private fun fetchNextJob(baseUrl: String, afterId: Int, token: Int): LongPollingResult? {
        val url = "$baseUrl/api/phone/next-job".toHttpUrlOrNull()
            ?.newBuilder()
            ?.addQueryParameter("after_id", afterId.toString())
            ?.addQueryParameter("wait", "25")
            ?.addQueryParameter("limit", "50")
            ?.build()
            ?: throw IllegalArgumentException("URL long polling không hợp lệ: $baseUrl")

        val request = Request.Builder()
            .url(url)
            .header("Connection", "close")
            .build()
        val call = client.newCall(request)
        currentCall = call
        call.execute().use { response ->
            if (!running || token != runToken) return null
            if (!response.isSuccessful) {
                throw IllegalStateException("HTTP ${response.code}")
            }
            val body = response.body?.string().orEmpty()
            val job = JSONObject(body).optJSONObject("job") ?: return null
            val jobId = job.optInt("id", 0)
            val event = parseJob(job) ?: return null
            return LongPollingResult(jobId = jobId, event = event)
        }
    }

    private fun parseJob(job: JSONObject): SseLinkEvent? {
        val payload = job.optJSONObject("payload")
        val url = job.optString("url")
            .ifBlank { job.optString("link") }
            .ifBlank { payload?.optString("url").orEmpty() }
            .ifBlank { payload?.optString("link").orEmpty() }
        if (!url.isSupportedLink()) return null

        val defaultDelayMs = job.optLong("click_after_ms", 0L).coerceAtLeast(0L)
        val defaultX = job.optInt("click_x", 540).coerceAtLeast(1)
        val defaultY = job.optInt("click_y", 1800).coerceAtLeast(1)
        val actions = parseActions(job, payload, defaultX, defaultY, defaultDelayMs)
        return SseLinkEvent(
            url = url,
            clickAfterMs = defaultDelayMs,
            clickX = defaultX,
            clickY = defaultY,
            actions = actions,
        )
    }

    private fun parseActions(
        job: JSONObject,
        payload: JSONObject?,
        defaultX: Int,
        defaultY: Int,
        defaultDelayMs: Long,
    ): List<ClickAction> {
        val actionArray = job.optJSONArray("actions")
            ?: job.optJSONArray("clicks")
            ?: payload?.optJSONArray("actions")
            ?: payload?.optJSONArray("clicks")
        val actions = actionArray?.let(::parseActionArray).orEmpty()
        if (actions.isNotEmpty()) return actions

        val afterOpenClick = job.optJSONObject("after_open_click")
            ?: payload?.optJSONObject("after_open_click")
        if (afterOpenClick != null) {
            val x = afterOpenClick.optInt("x", 0)
            val y = afterOpenClick.optInt("y", 0)
            if (x > 0 && y > 0) {
                return listOf(
                    ClickAction(
                        x = x,
                        y = y,
                        delayMs = afterOpenClick.optLong("delay_ms", afterOpenClick.optLong("after_ms", 0L))
                            .coerceAtLeast(0L),
                        durationMs = afterOpenClick.optLong("duration_ms", 80L)
                            .coerceIn(40L, 1_500L),
                    )
                )
            }
        }

        return listOf(ClickAction(x = defaultX, y = defaultY, delayMs = defaultDelayMs))
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
                durationMs = action.optLong("duration_ms", 80L).coerceIn(40L, 1_500L),
            )
        }
        return result
    }

    private fun sleep(delayMs: Long) {
        try {
            Thread.sleep(delayMs)
        } catch (_: InterruptedException) {
            Thread.currentThread().interrupt()
        }
    }

    private fun String.isSupportedLink(): Boolean {
        return startsWith("http://") || startsWith("https://") || startsWith("tiktok://")
    }
}
