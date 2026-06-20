package com.abc.tikclaim

import android.Manifest
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import com.abc.tikclaim.ui.theme.TikClaimTheme

class MainActivity : ComponentActivity() {
    private var serverUrl by mutableStateOf("")
    private var isListening by mutableStateOf(false)
    private var statusText by mutableStateOf("Chưa kết nối")
    private var lastLink by mutableStateOf<String?>(null)

    private val statusReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context?, intent: Intent?) {
            if (intent?.action != TikClaimLinkService.ACTION_STATUS) return
            isListening = intent.getBooleanExtra(TikClaimLinkService.EXTRA_RUNNING, false)
            statusText = intent.getStringExtra(TikClaimLinkService.EXTRA_STATUS) ?: statusText
            intent.getStringExtra(TikClaimLinkService.EXTRA_LAST_LINK)?.let { lastLink = it }
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        serverUrl = TikClaimPrefs.getServerUrl(this)
        isListening = TikClaimPrefs.isServiceEnabled(this)
        lastLink = TikClaimPrefs.getLastLink(this)
        statusText = if (isListening) "Nhận link nền đang bật" else "Chưa kết nối"
        registerStatusReceiver()

        setContent {
            TikClaimTheme {
                Scaffold(modifier = Modifier.fillMaxSize()) { innerPadding ->
                    HomeScreen(
                        serverUrl = serverUrl,
                        isListening = isListening,
                        statusText = statusText,
                        lastLink = lastLink,
                        onServerUrlChange = {
                            serverUrl = it
                            TikClaimPrefs.setServerUrl(this, it)
                        },
                        onListeningChange = { enabled ->
                            if (enabled) startListening() else stopListening("Đã tắt nhận link")
                        },
                        onOpenAccessibility = { openAccessibilitySettings() },
                        modifier = Modifier.padding(innerPadding)
                    )
                }
            }
        }
    }

    override fun onResume() {
        super.onResume()
        isListening = TikClaimPrefs.isServiceEnabled(this)
        lastLink = TikClaimPrefs.getLastLink(this)
    }

    override fun onDestroy() {
        runCatching { unregisterReceiver(statusReceiver) }
        super.onDestroy()
    }

    private fun startListening() {
        val url = TikClaimPrefs.normalizeServerBaseUrl(serverUrl)
        if (url.isBlank()) {
            statusText = "Nhập URL máy chủ trước khi bật"
            return
        }

        isListening = true
        statusText = "Đang bật dịch vụ nền..."
        serverUrl = url
        TikClaimPrefs.setServerUrl(this, url)
        requestNotificationPermissionIfNeeded()
        TikClaimLinkService.start(this)
    }

    private fun stopListening(message: String) {
        TikClaimLinkService.stop(this)
        TikClaimPrefs.setServiceEnabled(this, false)
        isListening = false
        statusText = message
    }

    private fun openAccessibilitySettings() {
        startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS))
    }

    private fun requestNotificationPermissionIfNeeded() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) return
        if (checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED) return
        requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 10)
    }

    private fun registerStatusReceiver() {
        val filter = IntentFilter(TikClaimLinkService.ACTION_STATUS)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            registerReceiver(statusReceiver, filter, RECEIVER_NOT_EXPORTED)
        } else {
            @Suppress("UnspecifiedRegisterReceiverFlag")
            registerReceiver(statusReceiver, filter)
        }
    }
}

@Composable
private fun HomeScreen(
    serverUrl: String,
    isListening: Boolean,
    statusText: String,
    lastLink: String?,
    onServerUrlChange: (String) -> Unit,
    onListeningChange: (Boolean) -> Unit,
    onOpenAccessibility: () -> Unit,
    modifier: Modifier = Modifier
) {
    Column(
        modifier = modifier
            .fillMaxSize()
            .padding(20.dp),
        verticalArrangement = Arrangement.spacedBy(18.dp)
    ) {
        Text(
            text = "TikClaim",
            style = MaterialTheme.typography.headlineMedium,
            fontWeight = FontWeight.Bold
        )

        Text(
            text = "Nhận link bằng long polling trong nền, mở TikTok và tự động click theo vị trí BE gửi.",
            style = MaterialTheme.typography.bodyLarge,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )

        OutlinedTextField(
            value = serverUrl,
            onValueChange = onServerUrlChange,
            modifier = Modifier.fillMaxWidth(),
            label = { Text("URL máy chủ") },
            placeholder = { Text("http://192.168.1.10:8787") },
            singleLine = true,
            enabled = !isListening
        )

        Card(
            colors = CardDefaults.cardColors(
                containerColor = MaterialTheme.colorScheme.surfaceContainer
            ),
            modifier = Modifier.fillMaxWidth()
        ) {
            Column(
                modifier = Modifier.padding(16.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp)
            ) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.SpaceBetween
                ) {
                    Column(modifier = Modifier.weight(1f)) {
                        Text(
                            text = if (isListening) "Đang bật" else "Đang tắt",
                            style = MaterialTheme.typography.titleMedium,
                            fontWeight = FontWeight.SemiBold
                        )
                        Text(
                            text = statusText,
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                    }
                    Spacer(modifier = Modifier.width(12.dp))
                    Switch(
                        checked = isListening,
                        onCheckedChange = onListeningChange
                    )
                }

                Button(
                    onClick = { onListeningChange(!isListening) },
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Text(if (isListening) "Tắt dịch vụ nền" else "Bật dịch vụ nền")
                }

                Button(
                    onClick = onOpenAccessibility,
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Text("Mở cài đặt Trợ năng")
                }
            }
        }

        Spacer(modifier = Modifier.height(4.dp))

        Text(
            text = "Link cuối",
            style = MaterialTheme.typography.titleMedium,
            fontWeight = FontWeight.SemiBold
        )
        Text(
            text = lastLink ?: "Chưa nhận link nào",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )
    }
}

@Preview(showBackground = true)
@Composable
private fun HomeScreenPreview() {
    TikClaimTheme {
        HomeScreen(
            serverUrl = "https://example.com",
            isListening = false,
            statusText = "Chưa kết nối",
            lastLink = null,
            onServerUrlChange = {},
            onListeningChange = {},
            onOpenAccessibility = {}
        )
    }
}
