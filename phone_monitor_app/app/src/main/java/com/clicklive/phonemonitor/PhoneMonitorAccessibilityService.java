package com.clicklive.phonemonitor;

import android.accessibilityservice.AccessibilityService;
import android.accessibilityservice.GestureDescription;
import android.content.Intent;
import android.graphics.Path;
import android.net.Uri;
import android.os.Handler;
import android.os.Looper;
import android.provider.Settings;
import android.view.Gravity;
import android.view.MotionEvent;
import android.view.View;
import android.view.WindowManager;
import android.view.accessibility.AccessibilityEvent;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.Toast;

public class PhoneMonitorAccessibilityService extends AccessibilityService {
    static PhoneMonitorAccessibilityService instance;
    private MonitorLog log;
    private PhoneHttpServer http;
    private WindowManager windowManager;
    private View overlay;
    private final Handler main = new Handler(Looper.getMainLooper());

    @Override public void onServiceConnected() {
        instance = this;
        log = new MonitorLog(this);
        log.addRawJson("service", "{\"state\":\"connected\"}");
        startHttp();
        showOverlay();
    }

    @Override public void onAccessibilityEvent(AccessibilityEvent event) {
        if (log == null || event == null) return;
        String text = event.getText() == null ? "" : event.getText().toString();
        String json = "{"
                + "\"event\":" + event.getEventType() + ","
                + "\"package\":\"" + esc(String.valueOf(event.getPackageName())) + "\","
                + "\"class\":\"" + esc(String.valueOf(event.getClassName())) + "\","
                + "\"text\":\"" + esc(text) + "\","
                + "\"scrollX\":" + event.getScrollX() + ","
                + "\"scrollY\":" + event.getScrollY()
                + "}";
        log.addRawJson("accessibility_event", json);
    }

    @Override public void onInterrupt() {
        if (log != null) log.addRawJson("service", "{\"state\":\"interrupted\"}");
    }

    @Override public void onDestroy() {
        if (http != null) http.stop();
        hideOverlay();
        instance = null;
        super.onDestroy();
    }

    void doTap(int x, int y) {
        Path path = new Path();
        path.moveTo(x, y);
        GestureDescription gesture = new GestureDescription.Builder()
                .addStroke(new GestureDescription.StrokeDescription(path, 0, 80))
                .build();
        dispatchGesture(gesture, null, null);
        if (log != null) log.addRawJson("tap", "{\"x\":" + x + ",\"y\":" + y + "}");
    }

    void doSwipe(int x1, int y1, int x2, int y2, int durationMs) {
        Path path = new Path();
        path.moveTo(x1, y1);
        path.lineTo(x2, y2);
        GestureDescription gesture = new GestureDescription.Builder()
                .addStroke(new GestureDescription.StrokeDescription(path, 0, Math.max(1, durationMs)))
                .build();
        dispatchGesture(gesture, null, null);
        if (log != null) log.addRawJson("swipe", "{\"x1\":" + x1 + ",\"y1\":" + y1 + ",\"x2\":" + x2 + ",\"y2\":" + y2 + ",\"duration_ms\":" + durationMs + "}");
    }

    void openDeeplink(String url) {
        openDeeplink(url, "", "", "", 0, 0, 0);
    }

    void openDeeplink(String url, String source, String queueId) {
        openDeeplink(url, source, queueId, "", 0, 0, 0);
    }

    void openDeeplink(String url, String source, String queueId, String timeLabel, int clickAfterMs, int clickX, int clickY) {
        if (url == null || url.trim().isEmpty()) return;
        Intent intent = new Intent(Intent.ACTION_VIEW, Uri.parse(url.trim()));
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        startActivity(intent);
        if (log != null) log.addRawJson("deeplink", "{\"url\":\"" + esc(url.trim()) + "\",\"source\":\"" + esc(source) + "\",\"queue_id\":\"" + esc(queueId) + "\",\"time\":\"" + esc(timeLabel) + "\",\"click_after_ms\":" + clickAfterMs + ",\"click_x\":" + clickX + ",\"click_y\":" + clickY + "}");
        if (clickAfterMs > 0 && clickX > 0 && clickY > 0) {
            if (log != null) log.addRawJson("scheduled_tap", "{\"after_ms\":" + clickAfterMs + ",\"x\":" + clickX + ",\"y\":" + clickY + ",\"queue_id\":\"" + esc(queueId) + "\"}");
            main.postDelayed(() -> doTap(clickX, clickY), clickAfterMs);
        }
    }

    String logs() { return log == null ? "" : log.all(); }

    private void startHttp() {
        http = new PhoneHttpServer(8791, new PhoneHttpServer.ActionHandler() {
            @Override public void tap(int x, int y) { main.post(() -> doTap(x, y)); }
            @Override public void swipe(int x1, int y1, int x2, int y2, int durationMs) { main.post(() -> doSwipe(x1, y1, x2, y2, durationMs)); }
            @Override public void deeplink(String url, String source, String queueId, String timeLabel, int clickAfterMs, int clickX, int clickY) { main.post(() -> openDeeplink(url, source, queueId, timeLabel, clickAfterMs, clickX, clickY)); }
            @Override public String logs() { return PhoneMonitorAccessibilityService.this.logs(); }
        });
        http.start();
    }

    private void showOverlay() {
        if (!Settings.canDrawOverlays(this)) return;
        windowManager = (WindowManager) getSystemService(WINDOW_SERVICE);
        LinearLayout panel = new LinearLayout(this);
        panel.setOrientation(LinearLayout.VERTICAL);
        panel.setPadding(8, 8, 8, 8);
        panel.setBackgroundColor(0xcc151922);

        Button mark = button("Log Mark");
        Button up = button("Scroll Up");
        Button down = button("Scroll Down");
        Button back = button("Back");
        panel.addView(mark); panel.addView(up); panel.addView(down); panel.addView(back);
        mark.setOnClickListener(v -> { if (log != null) log.addRawJson("mark", "{\"note\":\"overlay mark\"}"); Toast.makeText(this, "Logged", Toast.LENGTH_SHORT).show(); });
        up.setOnClickListener(v -> doSwipe(540, 1450, 540, 650, 450));
        down.setOnClickListener(v -> doSwipe(540, 650, 540, 1450, 450));
        back.setOnClickListener(v -> performGlobalAction(GLOBAL_ACTION_BACK));

        WindowManager.LayoutParams params = new WindowManager.LayoutParams(
                WindowManager.LayoutParams.WRAP_CONTENT,
                WindowManager.LayoutParams.WRAP_CONTENT,
                WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
                WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE,
                android.graphics.PixelFormat.TRANSLUCENT);
        params.gravity = Gravity.TOP | Gravity.END;
        params.x = 12; params.y = 180;
        panel.setOnTouchListener(new DragTouch(params));
        overlay = panel;
        windowManager.addView(overlay, params);
    }

    private void hideOverlay() {
        if (windowManager != null && overlay != null) windowManager.removeView(overlay);
        overlay = null;
    }

    private Button button(String text) {
        Button b = new Button(this);
        b.setText(text);
        b.setTextSize(12);
        return b;
    }

    private static String esc(String s) { return s == null ? "" : s.replace("\\", "\\\\").replace("\"", "\\\"").replace("\n", " "); }

    private final class DragTouch implements View.OnTouchListener {
        private final WindowManager.LayoutParams params;
        private int startX, startY;
        private float touchX, touchY;
        DragTouch(WindowManager.LayoutParams params) { this.params = params; }
        @Override public boolean onTouch(View v, MotionEvent e) {
            if (e.getAction() == MotionEvent.ACTION_DOWN) { startX = params.x; startY = params.y; touchX = e.getRawX(); touchY = e.getRawY(); return false; }
            if (e.getAction() == MotionEvent.ACTION_MOVE) { params.x = startX - (int)(e.getRawX() - touchX); params.y = startY + (int)(e.getRawY() - touchY); windowManager.updateViewLayout(overlay, params); return true; }
            return false;
        }
    }
}
