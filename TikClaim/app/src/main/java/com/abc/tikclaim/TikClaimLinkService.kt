package com.abc.tikclaim

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.util.Log
import androidx.core.app.NotificationCompat

class TikClaimLinkService : Service() {
    private val tag = "TikClaimService"
    private val handler = Handler(Looper.getMainLooper())
    private val pollingClient = LongPollingLinkClient()
    private var shouldRun = false

    override fun onCreate() {
        super.onCreate()
        createNotificationChannel()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_STOP -> stopService()
            else -> startListening()
        }
        return START_STICKY
    }

    override fun onDestroy() {
        shouldRun = false
        handler.removeCallbacksAndMessages(null)
        pollingClient.stop()
        sendStatus(false, "Đã tắt nhận link nền")
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    private fun startListening() {
        val baseUrl = TikClaimPrefs.normalizeServerBaseUrl(TikClaimPrefs.getServerUrl(this))
        if (baseUrl.isBlank()) {
            sendStatus(false, "Nhập URL máy chủ trước khi bật")
            stopSelf()
            return
        }

        TikClaimPrefs.setServerUrl(this, baseUrl)
        TikClaimPrefs.setServiceEnabled(this, true)
        shouldRun = true
        startForeground(NOTIFICATION_ID, notification("Đang kết nối long polling"))
        Log.i(tag, "Starting long polling service baseUrl=$baseUrl")

        pollingClient.start(
            baseUrl = baseUrl,
            afterId = TikClaimPrefs.getLastJobId(this),
            onOpen = {
                sendStatus(true, "Đang nhận link bằng long polling")
                notifyStatus("Đang nhận link")
            },
            onLink = { result ->
                val event = result.event
                Log.i(tag, "Received link ${event.url} actions=${event.actions.size}")
                TikClaimPrefs.setLastJobId(this, result.jobId)
                TikClaimPrefs.setLastLink(this, event.url)
                sendStatus(true, "Đã nhận link, đang mở TikTok", event.url)
                notifyStatus("Mở link TikTok")
                openTikTokLink(event.url)
                TikTokAccessibilityService.requestInteraction(event)
            },
            onError = { message ->
                Log.e(tag, "Long polling error: $message")
                sendStatus(false, message)
                notifyStatus(message)
            }
        )
    }

    private fun stopService() {
        shouldRun = false
        handler.removeCallbacksAndMessages(null)
        TikClaimPrefs.setServiceEnabled(this, false)
        pollingClient.stop()
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    private fun openTikTokLink(link: String) {
        val uri = Uri.parse(link)
        Log.i(tag, "Opening TikTok link $link")
        for (packageName in TIKTOK_PACKAGES) {
            val tikTokIntent = Intent(Intent.ACTION_VIEW, uri).apply {
                setPackage(packageName)
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            }
            try {
                startActivity(tikTokIntent)
                return
            } catch (_: ActivityNotFoundException) {
                // Try the next known TikTok package.
            }
        }

        val browserIntent = Intent(Intent.ACTION_VIEW, uri).apply {
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        startActivity(browserIntent)
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val channel = NotificationChannel(
            CHANNEL_ID,
            "TikClaim nhận link",
            NotificationManager.IMPORTANCE_LOW
        )
        getSystemService(NotificationManager::class.java).createNotificationChannel(channel)
    }

    private fun notifyStatus(message: String) {
        val manager = getSystemService(NotificationManager::class.java)
        manager.notify(NOTIFICATION_ID, notification(message))
    }

    private fun notification(message: String): Notification {
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.stat_sys_download_done)
            .setContentTitle("TikClaim")
            .setContentText(message)
            .setOngoing(true)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .build()
    }

    private fun sendStatus(running: Boolean, status: String, lastLink: String? = null) {
        sendBroadcast(Intent(ACTION_STATUS).apply {
            setPackage(packageName)
            putExtra(EXTRA_RUNNING, running)
            putExtra(EXTRA_STATUS, status)
            if (lastLink != null) putExtra(EXTRA_LAST_LINK, lastLink)
        })
    }

    companion object {
        const val ACTION_START = "com.abc.tikclaim.action.START"
        const val ACTION_STOP = "com.abc.tikclaim.action.STOP"
        const val ACTION_STATUS = "com.abc.tikclaim.action.STATUS"
        const val EXTRA_RUNNING = "running"
        const val EXTRA_STATUS = "status"
        const val EXTRA_LAST_LINK = "last_link"

        private const val CHANNEL_ID = "tikclaim_sse"
        private const val NOTIFICATION_ID = 1001

        fun start(context: Context) {
            val intent = Intent(context, TikClaimLinkService::class.java).setAction(ACTION_START)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                context.startForegroundService(intent)
            } else {
                context.startService(intent)
            }
        }

        fun stop(context: Context) {
            context.startService(Intent(context, TikClaimLinkService::class.java).setAction(ACTION_STOP))
        }
    }
}
