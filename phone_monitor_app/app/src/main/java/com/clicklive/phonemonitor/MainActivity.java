package com.clicklive.phonemonitor;

import android.Manifest;
import android.app.Activity;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.net.wifi.WifiManager;
import android.os.Bundle;
import android.provider.Settings;
import android.text.method.ScrollingMovementMethod;
import android.view.View;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

public class MainActivity extends Activity {
    private TextView status;
    private TextView logs;
    private EditText urlInput;
    private EditText serverInput;
    private EditText actionNoteInput;
    private MonitorLog appLog;
    private QueuePoller poller;
    private final android.os.Handler handler = new android.os.Handler(android.os.Looper.getMainLooper());
    private final Runnable refresh = new Runnable() { @Override public void run() { render(); handler.postDelayed(this, 1000); } };

    @Override protected void onCreate(Bundle bundle) {
        super.onCreate(bundle);
        if (android.os.Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 10);
        appLog = new MonitorLog(this);
        poller = new QueuePoller(this, appLog);
        buildUi();
    }

    @Override protected void onResume() { super.onResume(); handler.post(refresh); }
    @Override protected void onPause() { handler.removeCallbacks(refresh); super.onPause(); }

    private void buildUi() {
        ScrollView scroll = new ScrollView(this);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(24, 24, 24, 24);
        scroll.addView(root);

        TextView title = new TextView(this);
        title.setText("Phone Monitor");
        title.setTextSize(24);
        title.setPadding(0, 0, 0, 12);
        root.addView(title);

        status = new TextView(this);
        status.setTextSize(14);
        status.setPadding(0, 0, 0, 16);
        root.addView(status);

        Button accessibility = button("Open Accessibility Settings");
        accessibility.setOnClickListener(v -> startActivity(new Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS)));
        root.addView(accessibility);

        Button overlay = button("Allow Overlay Permission");
        overlay.setOnClickListener(v -> startActivity(new Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION, Uri.parse("package:" + getPackageName()))));
        root.addView(overlay);

        serverInput = new EditText(this);
        serverInput.setHint("Queue server URL, e.g. http://192.168.1.10:8787");
        serverInput.setText(getPreferences(0).getString("server_url", ""));
        root.addView(serverInput);

        LinearLayout pollRow = new LinearLayout(this);
        pollRow.setOrientation(LinearLayout.HORIZONTAL);
        Button startPoll = button("Start Queue Polling");
        Button futurePoll = button("Future Only");
        Button scanServer = button("Scan Server");
        Button stopPoll = button("Stop");
        pollRow.addView(startPoll); pollRow.addView(futurePoll); pollRow.addView(scanServer); pollRow.addView(stopPoll);
        root.addView(pollRow);
        startPoll.setOnClickListener(v -> { String server = serverInput.getText().toString(); getPreferences(0).edit().putString("server_url", server).apply(); poller.start(server); render(); });
        futurePoll.setOnClickListener(v -> { String server = serverInput.getText().toString(); getPreferences(0).edit().putString("server_url", server).apply(); poller.startFutureOnly(server); render(); });
        scanServer.setOnClickListener(v -> scanServer());
        stopPoll.setOnClickListener(v -> { poller.stop(); render(); });

        actionNoteInput = new EditText(this);
        actionNoteInput.setHint("Action log note, e.g. clicked follow / scrolled / done");
        root.addView(actionNoteInput);

        LinearLayout jobRow = new LinearLayout(this);
        jobRow.setOrientation(LinearLayout.HORIZONTAL);
        Button logAction = button("Log Action");
        Button completeJob = button("Complete & Next");
        jobRow.addView(logAction); jobRow.addView(completeJob);
        root.addView(jobRow);
        logAction.setOnClickListener(v -> logManualAction());
        completeJob.setOnClickListener(v -> { poller.completeActiveJob(actionNoteInput.getText().toString()); actionNoteInput.setText(""); render(); });

        urlInput = new EditText(this);
        urlInput.setHint("tiktok://... or https://...");
        root.addView(urlInput);

        Button deeplink = button("Open Deeplink");
        deeplink.setOnClickListener(v -> serviceCall("deeplink"));
        root.addView(deeplink);

        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.HORIZONTAL);
        Button tap = button("Tap Center");
        Button scrollUp = button("Scroll Up");
        Button scrollDown = button("Scroll Down");
        row.addView(tap); row.addView(scrollUp); row.addView(scrollDown);
        root.addView(row);
        tap.setOnClickListener(v -> serviceCall("tap"));
        scrollUp.setOnClickListener(v -> serviceCall("up"));
        scrollDown.setOnClickListener(v -> serviceCall("down"));

        Button share = button("Share Logs");
        share.setOnClickListener(v -> shareLogs());
        root.addView(share);

        logs = new TextView(this);
        logs.setTextSize(11);
        logs.setMovementMethod(new ScrollingMovementMethod());
        logs.setPadding(0, 16, 0, 0);
        root.addView(logs);

        setContentView(scroll);
    }

    private Button button(String text) {
        Button b = new Button(this);
        b.setText(text);
        return b;
    }

    private void logManualAction() {
        String note = actionNoteInput == null ? "" : actionNoteInput.getText().toString();
        String active = poller == null ? "" : poller.activeJobLabel();
        if (appLog != null) appLog.addRawJson("manual_action", "{\"active_job\":\"" + esc(active) + "\",\"note\":\"" + esc(note) + "\"}");
        Toast.makeText(this, "Action logged", Toast.LENGTH_SHORT).show();
        render();
    }

    private void serviceCall(String action) {
        PhoneMonitorAccessibilityService svc = PhoneMonitorAccessibilityService.instance;
        if (svc == null) { Toast.makeText(this, "Enable Phone Monitor Accessibility Service first", Toast.LENGTH_LONG).show(); return; }
        if ("deeplink".equals(action)) svc.openDeeplink(urlInput.getText().toString());
        else if ("tap".equals(action)) svc.doTap(getResources().getDisplayMetrics().widthPixels / 2, getResources().getDisplayMetrics().heightPixels / 2);
        else if ("up".equals(action)) svc.doSwipe(540, 1450, 540, 650, 450);
        else if ("down".equals(action)) svc.doSwipe(540, 650, 540, 1450, 450);
        render();
    }

    private void scanServer() {
        Toast.makeText(this, "Scanning LAN for Queue server...", Toast.LENGTH_SHORT).show();
        new Thread(() -> {
            String found = findQueueServer();
            handler.post(() -> {
                if (found.isEmpty()) {
                    Toast.makeText(this, "No Queue server found on port 8787/8788", Toast.LENGTH_LONG).show();
                    render();
                    return;
                }
                serverInput.setText(found);
                getPreferences(0).edit().putString("server_url", found).apply();
                poller.start(found);
                Toast.makeText(this, "Connected " + found, Toast.LENGTH_LONG).show();
                render();
            });
        }, "queue-server-scan").start();
    }

    private String findQueueServer() {
        String subnet = wifiSubnet();
        if (subnet.isEmpty()) return "";
        int[] ports = new int[]{8787, 8788};
        for (int port : ports) {
            for (int i = 1; i <= 254; i++) {
                String base = "http://" + subnet + i + ":" + port;
                if (isQueueServer(base)) return base;
            }
        }
        return "";
    }

    private String wifiSubnet() {
        try {
            WifiManager wifi = (WifiManager) getApplicationContext().getSystemService(WIFI_SERVICE);
            int ip = wifi.getConnectionInfo().getIpAddress();
            if (ip == 0) return "";
            return (ip & 0xff) + "." + ((ip >> 8) & 0xff) + "." + ((ip >> 16) & 0xff) + ".";
        } catch (Exception ignored) {
            return "";
        }
    }

    private boolean isQueueServer(String base) {
        try {
            java.net.HttpURLConnection conn = (java.net.HttpURLConnection) new java.net.URL(base + "/api/phone/config").openConnection();
            conn.setConnectTimeout(180);
            conn.setReadTimeout(350);
            return conn.getResponseCode() == 200;
        } catch (Exception ignored) {
            return false;
        }
    }

    private void render() {
        PhoneMonitorAccessibilityService svc = PhoneMonitorAccessibilityService.instance;
        boolean overlay = Settings.canDrawOverlays(this);
        status.setText("Accessibility: " + (svc == null ? "OFF" : "ON") + "\nOverlay: " + (overlay ? "ON" : "OFF") + "\nQueue polling: " + (poller != null && poller.isRunning() ? "ON " + poller.serverUrl() : "OFF") + "\nActive job: " + (poller != null && poller.hasActiveJob() ? poller.activeJobLabel() : "none") + "\nHTTP: http://" + PhoneHttpServer.localIp() + ":8791\nQueue mode opens one link, waits for Complete & Next, then receives next link.");
        String serviceLogs = svc == null ? "" : svc.logs();
        String localLogs = appLog == null ? "" : appLog.all();
        logs.setText(tail((serviceLogs + "\n" + localLogs).trim(), 12000));
    }

    private String tail(String text, int max) { return text == null || text.length() <= max ? (text == null ? "" : text) : text.substring(text.length() - max); }

    private static String esc(String s) { return s == null ? "" : s.replace("\\", "\\\\").replace("\"", "\\\"").replace("\n", " "); }

    private void shareLogs() {
        PhoneMonitorAccessibilityService svc = PhoneMonitorAccessibilityService.instance;
        Intent intent = new Intent(Intent.ACTION_SEND);
        intent.setType("text/plain");
        intent.putExtra(Intent.EXTRA_TEXT, svc == null ? "" : svc.logs());
        startActivity(Intent.createChooser(intent, "Share Phone Monitor logs"));
    }
}
