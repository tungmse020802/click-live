package com.clicklive.phonemonitor;

import android.content.Context;
import android.content.Intent;
import android.net.Uri;
import android.os.Handler;
import android.os.Looper;

import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.OutputStream;
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;

final class QueuePoller {
    private final Context context;
    private final MonitorLog log;
    private final Handler main = new Handler(Looper.getMainLooper());
    private volatile boolean running;
    private Thread thread;
    private String serverUrl = "";
    private long lastJobId = 0;
    private volatile long activeJobId = 0;
    private volatile String activeJobUrl = "";
    private volatile long afterId = 0;

    QueuePoller(Context context, MonitorLog log) {
        this.context = context.getApplicationContext();
        this.log = log;
    }

    boolean isRunning() { return running; }
    boolean hasActiveJob() { return activeJobId > 0; }
    String activeJobLabel() { return activeJobId > 0 ? ("#" + activeJobId + " " + activeJobUrl) : ""; }
    String serverUrl() { return serverUrl; }

    void start(String url) {
        serverUrl = normalize(url);
        if (serverUrl.isEmpty() || running) return;
        running = true;
        thread = new Thread(this::loop, "phone-queue-poller");
        thread.setDaemon(true);
        thread.start();
        log.addRawJson("poller", "{\"state\":\"started\",\"server\":\"" + esc(serverUrl) + "\",\"after_id\":" + afterId + "}");
    }

    void startFutureOnly(String url) {
        serverUrl = normalize(url);
        if (serverUrl.isEmpty()) return;
        new Thread(() -> {
            try {
                afterId = fetchLatestQueueId();
                log.addRawJson("future_only", "{\"after_id\":" + afterId + ",\"server\":\"" + esc(serverUrl) + "\"}");
            } catch (Exception exc) {
                log.addRawJson("future_only_error", "{\"error\":\"" + esc(exc.toString()) + "\"}");
            }
            if (!running) start(serverUrl);
        }, "phone-future-baseline").start();
    }

    void completeActiveJob(String note) {
        long jobId = activeJobId;
        if (jobId <= 0) {
            log.addRawJson("complete_ignored", "{\"reason\":\"no_active_job\"}");
            return;
        }
        log.addRawJson("job_completed_local", "{\"job_id\":" + jobId + ",\"note\":\"" + esc(note) + "\"}");
        ack(jobId, "completed", note == null ? "" : note);
        activeJobId = 0;
        activeJobUrl = "";
    }

    void stop() {
        running = false;
        log.addRawJson("poller", "{\"state\":\"stopped\"}");
    }

    private void loop() {
        while (running) {
            try {
                if (activeJobId > 0) {
                    Thread.sleep(1000);
                    continue;
                }
                pollOnce();
                Thread.sleep(300);
            } catch (InterruptedException ignored) {
                return;
            } catch (Exception exc) {
                log.addRawJson("poll_error", "{\"error\":\"" + esc(exc.toString()) + "\"}");
                try { Thread.sleep(3000); } catch (InterruptedException ignored) { return; }
            }
        }
    }

    private void pollOnce() throws Exception {
        String text = get(serverUrl + "/api/phone/next-job?wait=25&after_id=" + afterId + "&device_id=" + Uri.encode(android.os.Build.MODEL));
        JSONObject root = new JSONObject(text);
        JSONObject job = root.optJSONObject("job");
        if (job == null) return;
        long jobId = job.optLong("id", 0);
        if (jobId > 0 && jobId == lastJobId) return;
        lastJobId = jobId;
        activeJobId = jobId;
        activeJobUrl = job.optString("url", "");
        handleJob(job);
    }

    private long fetchLatestQueueId() throws Exception {
        String text = get(serverUrl + "/api/queue?limit=1&_=" + System.currentTimeMillis());
        JSONObject root = new JSONObject(text);
        return root.optLong("latest_id", 0);
    }

    private void handleJob(JSONObject job) {
        long jobId = job.optLong("id", 0);
        String url = job.optString("url", "");
        String time = job.optString("time", "");
        int delay = job.optInt("click_after_ms", 0);
        int x = job.optInt("click_x", 0);
        int y = job.optInt("click_y", 0);
        log.addRawJson("queue_job", "{\"job_id\":" + jobId + ",\"url\":\"" + esc(url) + "\",\"time\":\"" + esc(time) + "\",\"click_after_ms\":" + delay + ",\"click_x\":" + x + ",\"click_y\":" + y + "}");
        main.post(() -> {
            openUrl(url);
            PhoneMonitorAccessibilityService svc = PhoneMonitorAccessibilityService.instance;
            if (svc != null && delay > 0 && x > 0 && y > 0) {
                svc.openDeeplink(url, "queue-poller", String.valueOf(jobId), time, delay, x, y);
            } else if (delay > 0) {
                log.addRawJson("manual_click_required", "{\"job_id\":" + jobId + ",\"after_ms\":" + delay + ",\"x\":" + x + ",\"y\":" + y + "}");
            }
        });
        ack(jobId, "opened_waiting_complete", "");
    }

    private void openUrl(String value) {
        if (value == null || value.trim().isEmpty()) return;
        Intent intent = new Intent(Intent.ACTION_VIEW, Uri.parse(value.trim()));
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        context.startActivity(intent);
    }

    private void ack(long jobId, String status, String error) {
        new Thread(() -> {
            try {
                JSONObject body = new JSONObject();
                body.put("job_id", jobId);
                body.put("status", status);
                body.put("device_id", android.os.Build.MODEL);
                body.put("error", error == null ? "" : error);
                postJson(serverUrl + "/api/phone/job-result", body.toString());
            } catch (Exception exc) {
                log.addRawJson("ack_error", "{\"error\":\"" + esc(exc.toString()) + "\"}");
            }
        }, "phone-queue-ack").start();
    }

    private static String get(String value) throws Exception {
        HttpURLConnection conn = (HttpURLConnection) new URL(value).openConnection();
        conn.setConnectTimeout(5000);
        conn.setReadTimeout(32000);
        try (BufferedReader reader = new BufferedReader(new InputStreamReader(conn.getInputStream(), StandardCharsets.UTF_8))) {
            StringBuilder out = new StringBuilder();
            String line;
            while ((line = reader.readLine()) != null) out.append(line);
            return out.toString();
        }
    }

    private static void postJson(String value, String body) throws Exception {
        HttpURLConnection conn = (HttpURLConnection) new URL(value).openConnection();
        conn.setRequestMethod("POST");
        conn.setRequestProperty("Content-Type", "application/json; charset=utf-8");
        conn.setDoOutput(true);
        byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
        try (OutputStream out = conn.getOutputStream()) { out.write(bytes); }
        conn.getInputStream().close();
    }

    private static String normalize(String value) {
        String text = value == null ? "" : value.trim();
        while (text.endsWith("/")) text = text.substring(0, text.length() - 1);
        return text;
    }

    private static String esc(String s) { return s == null ? "" : s.replace("\\", "\\\\").replace("\"", "\\\"").replace("\n", " "); }
}
