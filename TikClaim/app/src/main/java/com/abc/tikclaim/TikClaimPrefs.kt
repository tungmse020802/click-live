package com.abc.tikclaim

import android.content.Context

internal val TIKTOK_PACKAGES = listOf(
    "com.zhiliaoapp.musically",
    "com.ss.android.ugc.trill",
    "com.zhiliaoapp.musically.go",
)

internal object TikClaimPrefs {
    private const val PREFS_NAME = "tikclaim"
    private const val KEY_SERVER_URL = "server_url"
    private const val KEY_LAST_LINK = "last_link"
    private const val KEY_LAST_JOB_ID = "last_job_id"
    private const val KEY_SERVICE_ENABLED = "service_enabled"

    fun getServerUrl(context: Context): String {
        val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        return prefs.getString(KEY_SERVER_URL, null) ?: normalizeServerBaseUrl(BuildConfig.DEFAULT_SERVER_URL)
    }

    fun setServerUrl(context: Context, url: String) {
        context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            .edit()
            .putString(KEY_SERVER_URL, url)
            .apply()
    }

    fun getLastLink(context: Context): String? {
        return context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            .getString(KEY_LAST_LINK, null)
    }

    fun setLastLink(context: Context, link: String) {
        context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            .edit()
            .putString(KEY_LAST_LINK, link)
            .apply()
    }

    fun getLastJobId(context: Context): Int {
        return context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            .getInt(KEY_LAST_JOB_ID, 0)
    }

    fun setLastJobId(context: Context, jobId: Int) {
        context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            .edit()
            .putInt(KEY_LAST_JOB_ID, jobId.coerceAtLeast(0))
            .apply()
    }

    fun isServiceEnabled(context: Context): Boolean {
        return context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            .getBoolean(KEY_SERVICE_ENABLED, false)
    }

    fun setServiceEnabled(context: Context, enabled: Boolean) {
        context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            .edit()
            .putBoolean(KEY_SERVICE_ENABLED, enabled)
            .apply()
    }

    fun normalizeServerBaseUrl(rawUrl: String): String {
        val trimmed = rawUrl.trim()
        if (trimmed.isBlank()) return ""
        return trimmed
            .substringBefore("/events")
            .substringBefore("/api/phone/next-job")
            .trimEnd('/')
    }
}
