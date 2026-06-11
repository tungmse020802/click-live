package com.clicklive.phonemonitor;

import android.content.Context;
import android.os.Handler;
import android.os.Looper;
import android.util.Log;

import java.io.BufferedReader;
import java.io.BufferedWriter;
import java.io.File;
import java.io.IOException;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.io.OutputStreamWriter;
import java.net.Inet4Address;
import java.net.InetAddress;
import java.net.NetworkInterface;
import java.net.ServerSocket;
import java.net.Socket;
import java.net.URLDecoder;
import java.nio.charset.StandardCharsets;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Enumeration;
import java.util.Locale;

final class MonitorLog {
    private static final int MAX_MEMORY = 500;
    private final File file;
    private final StringBuilder memory = new StringBuilder();
    private final SimpleDateFormat fmt = new SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss.SSSZ", Locale.US);

    MonitorLog(Context context) {
        file = new File(context.getFilesDir(), "phone-monitor.jsonl");
    }

    synchronized void add(String type, String body) {
        String safe = body == null ? "" : body.replace("\\", "\\\\").replace("\"", "\\\"").replace("\n", " ");
        String line = "{\"ts\":\"" + fmt.format(new Date()) + "\",\"type\":\"" + type + "\",\"data\":" + safe + "}";
        appendLine(line);
    }

    synchronized void addRawJson(String type, String jsonObject) {
        String line = "{\"ts\":\"" + fmt.format(new Date()) + "\",\"type\":\"" + type + "\",\"data\":" + (jsonObject == null || jsonObject.isEmpty() ? "{}" : jsonObject) + "}";
        appendLine(line);
    }

    private void appendLine(String line) {
        try (BufferedWriter writer = new BufferedWriter(new OutputStreamWriter(new java.io.FileOutputStream(file, true), StandardCharsets.UTF_8))) {
            writer.write(line);
            writer.newLine();
        } catch (IOException exc) {
            Log.e("PhoneMonitor", "log write failed", exc);
        }
        memory.append(line).append('\n');
        String[] lines = memory.toString().split("\n");
        if (lines.length > MAX_MEMORY) {
            memory.setLength(0);
            for (int i = Math.max(0, lines.length - MAX_MEMORY); i < lines.length; i++) memory.append(lines[i]).append('\n');
        }
    }

    synchronized String tail() { return memory.toString(); }
    synchronized String all() {
        try { return new String(java.nio.file.Files.readAllBytes(file.toPath()), StandardCharsets.UTF_8); }
        catch (Exception ignored) { return tail(); }
    }
    File file() { return file; }
}

final class PhoneHttpServer {
    interface ActionHandler {
        void tap(int x, int y);
        void swipe(int x1, int y1, int x2, int y2, int durationMs);
        void deeplink(String url, String source, String queueId, String timeLabel, int clickAfterMs, int clickX, int clickY);
        String logs();
    }

    private final int port;
    private final ActionHandler handler;
    private volatile boolean running;
    private ServerSocket serverSocket;
    private Thread thread;

    PhoneHttpServer(int port, ActionHandler handler) {
        this.port = port;
        this.handler = handler;
    }

    void start() {
        if (running) return;
        running = true;
        thread = new Thread(() -> {
            try (ServerSocket server = new ServerSocket(port)) {
                serverSocket = server;
                while (running) handle(server.accept());
            } catch (IOException exc) {
                if (running) Log.e("PhoneMonitor", "http server failed", exc);
            }
        }, "phone-monitor-http");
        thread.setDaemon(true);
        thread.start();
    }

    void stop() {
        running = false;
        try { if (serverSocket != null) serverSocket.close(); } catch (IOException ignored) {}
    }

    private void handle(Socket socket) {
        new Thread(() -> {
            try (Socket s = socket) {
                BufferedReader reader = new BufferedReader(new InputStreamReader(s.getInputStream(), StandardCharsets.UTF_8));
                String first = reader.readLine();
                if (first == null) return;
                int length = 0;
                String line;
                while ((line = reader.readLine()) != null && !line.isEmpty()) {
                    String lower = line.toLowerCase(Locale.US);
                    if (lower.startsWith("content-length:")) length = Integer.parseInt(line.substring(15).trim());
                }
                char[] chars = new char[Math.max(0, length)];
                if (length > 0) reader.read(chars);
                String body = new String(chars);
                String[] parts = first.split(" ");
                String method = parts.length > 0 ? parts[0] : "GET";
                String path = parts.length > 1 ? parts[1] : "/";
                route(s.getOutputStream(), method, path, body);
            } catch (Exception exc) {
                Log.e("PhoneMonitor", "http request failed", exc);
            }
        }, "phone-monitor-http-client").start();
    }

    private void route(OutputStream out, String method, String path, String body) throws IOException {
        if ("GET".equals(method) && path.startsWith("/logs")) { text(out, 200, handler.logs()); return; }
        if ("GET".equals(method) && path.equals("/")) { text(out, 200, "Phone Monitor OK\nPOST /actions/tap x= y=\nPOST /actions/swipe x1= y1= x2= y2= duration_ms=\nPOST /actions/deeplink url=\nGET /logs\n"); return; }
        if ("POST".equals(method) && path.equals("/actions/tap")) { Params p = Params.parse(body); handler.tap(p.i("x", 0), p.i("y", 0)); json(out, 200, "{\"ok\":true}"); return; }
        if ("POST".equals(method) && path.equals("/actions/swipe")) { Params p = Params.parse(body); handler.swipe(p.i("x1",0), p.i("y1",0), p.i("x2",0), p.i("y2",0), p.i("duration_ms",350)); json(out, 200, "{\"ok\":true}"); return; }
        if ("POST".equals(method) && path.equals("/actions/deeplink")) { Params p = Params.parse(body); handler.deeplink(p.s("url", ""), p.s("source", ""), p.s("queue_id", ""), p.s("time", ""), p.i("click_after_ms", 0), p.i("click_x", 0), p.i("click_y", 0)); json(out, 200, "{\"ok\":true}"); return; }
        json(out, 404, "{\"error\":\"not found\"}");
    }

    private void json(OutputStream out, int status, String body) throws IOException { respond(out, status, "application/json; charset=utf-8", body); }
    private void text(OutputStream out, int status, String body) throws IOException { respond(out, status, "text/plain; charset=utf-8", body); }
    private void respond(OutputStream out, int status, String type, String body) throws IOException {
        byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
        out.write(("HTTP/1.1 " + status + " OK\r\nContent-Type: " + type + "\r\nContent-Length: " + bytes.length + "\r\nAccess-Control-Allow-Origin: *\r\nConnection: close\r\n\r\n").getBytes(StandardCharsets.UTF_8));
        out.write(bytes);
    }

    static String localIp() {
        try {
            Enumeration<NetworkInterface> interfaces = NetworkInterface.getNetworkInterfaces();
            while (interfaces.hasMoreElements()) {
                NetworkInterface ni = interfaces.nextElement();
                Enumeration<InetAddress> addresses = ni.getInetAddresses();
                while (addresses.hasMoreElements()) {
                    InetAddress address = addresses.nextElement();
                    if (!address.isLoopbackAddress() && address instanceof Inet4Address) return address.getHostAddress();
                }
            }
        } catch (Exception ignored) {}
        return "0.0.0.0";
    }

    static final class Params {
        private final java.util.Map<String,String> map = new java.util.HashMap<>();
        static Params parse(String body) {
            Params p = new Params();
            if (body == null) return p;
            for (String part : body.split("&")) {
                int eq = part.indexOf('=');
                if (eq > 0) {
                    try { p.map.put(URLDecoder.decode(part.substring(0, eq), "UTF-8"), URLDecoder.decode(part.substring(eq + 1), "UTF-8")); } catch (Exception ignored) {}
                }
            }
            return p;
        }
        int i(String key, int def) { try { return Integer.parseInt(map.get(key)); } catch (Exception ignored) { return def; } }
        String s(String key, String def) { String value = map.get(key); return value == null ? def : value; }
    }
}
