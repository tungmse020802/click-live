#!/usr/bin/env python3
import argparse
import json
import logging
import os
import io
import shlex
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request
from copy import deepcopy
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = BASE_DIR / "config.json"
DEFAULT_LOG_PATH = BASE_DIR / "events.log"
DEFAULT_SCRCPY_LOG_PATH = BASE_DIR / "scrcpy.log"
DEFAULT_CAPTURE_DIR = BASE_DIR / "captures"
DEFAULT_TEMPLATE_DIR = BASE_DIR / "templates"
LOG_LIMIT = 300

DEFAULT_CONFIG: Dict[str, Any] = {
    "adb_path": "adb",
    "scrcpy_path": "scrcpy",
    "scrcpy_options": "--stay-awake --max-size 1280",
    "device_id": "",
    "dry_run": False,
    "startup_delay_ms": 500,
    "repeat": {
        "count": 1,
        "forever": False,
        "interval_ms": 800,
    },
    "treasure_detection": {
        "enabled": True,
        "after_deeplink": True,
        "load_wait_ms": 1200,
        "retry_count": 3,
        "retry_interval_ms": 700,
        "threshold": 0.78,
        "roi": {"x": 0, "y": 0, "w": 420, "h": 520},
        "template_path": "templates/treasure_box.png",
        "mask_path": "templates/treasure_box_mask.png",
        "tap": True,
    },
    "phone_timing": {
        "clock_offset_ms": 60000,
        "tap_lead_ms": 500,
        "click_x": 540,
        "click_y": 1800,
    },
    "queue_runner": {
        "enabled": False,
        "queue_url": "http://127.0.0.1:8787",
        "poll_interval_ms": 5000,
        "task_duration_ms": 30000,
        "fallback_pick_seconds": 18,
        "deeplink_settle_ms": 1000,
    },
    "actions": [
        {"type": "tap", "x": 500, "y": 1200, "delay_ms": 250},
        {
            "type": "swipe",
            "x1": 500,
            "y1": 1600,
            "x2": 500,
            "y2": 700,
            "duration_ms": 450,
            "delay_ms": 600,
        },
    ],
}

HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Phone Auto Clicker</title>
  <style>
    :root {
      --bg:#f4f6f8; --surface:#fff; --surface-2:#eef2f5; --border:#d3dae2;
      --text:#20242a; --muted:#66707b; --blue:#1d5fd0; --green:#16743a;
      --red:#b42318; --amber:#8a5a00; --dark:#151922;
    }
    * { box-sizing:border-box; }
    body { margin:0; min-height:100vh; background:var(--bg); color:var(--text); font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; letter-spacing:0; }
    button,input,select,textarea { font:inherit; }
    .shell { min-height:100vh; display:grid; grid-template-rows:auto auto 1fr; }
    .topbar { min-height:58px; display:flex; align-items:center; justify-content:space-between; gap:16px; padding:0 18px; background:var(--dark); color:#f9fafb; border-bottom:1px solid #252b36; }
    .brand { display:flex; align-items:baseline; gap:12px; min-width:0; }
    h1 { margin:0; font-size:18px; line-height:1; white-space:nowrap; }
    .brand span { color:#aeb6c3; font-size:12px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
    .toolbar { display:flex; align-items:center; gap:8px; flex-wrap:wrap; }
    .button { min-height:34px; min-width:38px; display:inline-flex; align-items:center; justify-content:center; border:1px solid #394252; background:#263040; color:#f9fafb; border-radius:6px; padding:0 12px; cursor:pointer; }
    .button:hover { background:#30394b; }
    .button.primary { background:var(--blue); border-color:#3170df; }
    .button.danger { background:#4a2530; border-color:#6d3342; }
    .button.light { background:#fff; color:var(--text); border-color:var(--border); }
    .statusbar { display:grid; grid-template-columns:repeat(5,minmax(150px,1fr)); gap:1px; background:var(--border); border-bottom:1px solid var(--border); }
    .stat { min-height:66px; padding:12px 16px; background:var(--surface); display:flex; flex-direction:column; justify-content:center; gap:5px; }
    .label { color:var(--muted); font-size:12px; font-weight:700; text-transform:uppercase; }
    .value { min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-size:14px; font-weight:700; }
    .main { min-height:0; display:grid; grid-template-columns:minmax(340px,420px) minmax(0,1fr); }
    .pane { min-height:0; overflow:auto; padding:16px; background:var(--surface); border-right:1px solid var(--border); }
    .work { min-height:0; overflow:auto; padding:16px; background:#fbfcfd; }
    .section { margin-bottom:18px; }
    .section h2 { margin:0 0 12px; font-size:15px; line-height:1.2; }
    .grid { display:grid; grid-template-columns:1fr 1fr; gap:12px; }
    .field { min-width:0; display:flex; flex-direction:column; gap:6px; }
    .field.full { grid-column:1 / -1; }
    input,select,textarea { width:100%; min-width:0; border:1px solid var(--border); border-radius:6px; background:#fff; color:var(--text); padding:9px 10px; }
    input[type="checkbox"] { width:auto; min-width:16px; }
    textarea { min-height:140px; resize:vertical; line-height:1.4; font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace; font-size:12px; }
    .checkline { min-height:40px; display:inline-flex; align-items:center; gap:8px; color:var(--text); font-size:13px; text-transform:none; }
    .device-list { display:flex; flex-direction:column; gap:8px; }
    .device-row { min-height:34px; display:flex; align-items:center; justify-content:space-between; gap:8px; padding:8px 10px; border:1px solid var(--border); border-radius:6px; background:#fff; }
    .pill { display:inline-flex; align-items:center; height:22px; padding:0 8px; border-radius:999px; border:1px solid #c8d0d9; color:#3a414b; background:#eef1f4; font-size:12px; font-weight:700; white-space:nowrap; }
    .pill.ok { color:var(--green); background:#eaf7ee; border-color:#a8dfba; }
    .pill.bad { color:var(--red); background:#fff0ee; border-color:#f5b6ad; }
    .actions-head { display:flex; align-items:center; justify-content:space-between; gap:8px; margin-bottom:12px; }
    .action-tools { display:flex; align-items:center; gap:8px; flex-wrap:wrap; }
    .action-list { display:flex; flex-direction:column; gap:10px; }
    .action-row { border:1px solid var(--border); border-radius:6px; background:#fff; overflow:hidden; }
    .action-top { min-height:44px; display:flex; align-items:center; justify-content:space-between; gap:10px; padding:8px 10px; background:#eef2f5; border-bottom:1px solid var(--border); }
    .action-title { display:flex; align-items:center; gap:8px; min-width:0; }
    .action-title select { width:130px; }
    .action-buttons { display:flex; align-items:center; gap:6px; }
    .mini { min-height:30px; min-width:32px; padding:0 8px; border:1px solid var(--border); border-radius:6px; background:#fff; color:var(--text); cursor:pointer; }
    .mini:hover { background:#f7f9fb; }
    .mini.danger { color:var(--red); }
    .action-body { display:grid; grid-template-columns:repeat(4,minmax(100px,1fr)); gap:10px; padding:12px; }
    .log { min-height:180px; max-height:280px; overflow:auto; border:1px solid var(--border); border-radius:6px; background:#111827; color:#d1d5db; padding:10px; font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace; font-size:12px; line-height:1.45; white-space:pre-wrap; }
    .screen-layout { display:grid; grid-template-columns:minmax(260px,390px) minmax(260px,1fr); gap:12px; align-items:start; }
    .screen-stage { position:relative; width:100%; min-height:360px; display:flex; align-items:center; justify-content:center; border:1px solid var(--border); border-radius:6px; background:#111827; overflow:hidden; }
    .screen-image { display:none; width:100%; height:auto; max-height:720px; object-fit:contain; cursor:crosshair; }
    .screen-stage.has-image .screen-image { display:block; }
    .screen-empty { padding:18px; color:#d1d5db; text-align:center; font-size:13px; line-height:1.45; }
    .screen-stage.has-image .screen-empty { display:none; }
    .screen-tools { display:flex; align-items:center; gap:8px; flex-wrap:wrap; margin-bottom:10px; }
    .tabs { display:flex; gap:8px; flex-wrap:wrap; margin-bottom:14px; }
    .tab { border:1px solid var(--border); background:#fff; color:var(--text); border-radius:999px; padding:8px 13px; cursor:pointer; font-weight:700; }
    .tab.active { background:var(--dark); color:#fff; border-color:var(--dark); }
    .view { display:none; }
    .view.active { display:block; }
    .capture-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(180px,1fr)); gap:12px; }
    .capture-card { border:1px solid var(--border); border-radius:6px; background:#fff; overflow:hidden; }
    .capture-card img { width:100%; display:block; background:#111827; }
    .capture-meta { padding:8px 10px; color:var(--muted); font-size:12px; line-height:1.35; word-break:break-all; }
    .direct-grid { display:grid; grid-template-columns:1fr auto; gap:10px; align-items:end; }
    .detect-grid { display:grid; grid-template-columns:repeat(4,minmax(80px,1fr)); gap:10px; margin-top:12px; }
    .detect-result { margin-top:10px; padding:10px; border:1px solid var(--border); border-radius:6px; background:#fff; color:var(--muted); font-size:13px; line-height:1.45; white-space:pre-wrap; }
    .tap-info { min-height:28px; display:flex; align-items:center; color:var(--muted); font-size:13px; }
    .small-input { width:92px; }
    @media (max-width:980px) {
      .topbar { align-items:flex-start; flex-direction:column; padding:12px; }
      .statusbar { grid-template-columns:1fr 1fr; }
      .main { grid-template-columns:1fr; }
      .pane { border-right:0; border-bottom:1px solid var(--border); }
      .action-body { grid-template-columns:repeat(2,minmax(0,1fr)); }
      .screen-layout { grid-template-columns:1fr; }
    }
  </style>
</head>
<body>
  <div class="shell">
    <header class="topbar">
      <div class="brand"><h1>Phone Auto Clicker</h1><span id="configPath"></span></div>
      <div class="toolbar">
        <button id="refreshBtn" class="button">Refresh</button>
        <button id="saveBtn" class="button">Save</button>
        <button id="runBtn" class="button primary">Run</button>
        <button id="stopBtn" class="button danger">Stop</button>
        <button id="queueStartBtn" class="button primary">Start Queue</button>
        <button id="queueStopBtn" class="button danger">Stop Queue</button>
      </div>
    </header>
    <section class="statusbar">
      <div class="stat"><div class="label">ADB</div><div id="adbValue" class="value">Checking</div></div>
      <div class="stat"><div class="label">Device</div><div id="deviceValue" class="value">Checking</div></div>
      <div class="stat"><div class="label">Screen</div><div id="screenValue" class="value">Unknown</div></div>
      <div class="stat"><div class="label">Runner</div><div id="runnerValue" class="value">Idle</div></div>
      <div class="stat"><div class="label">Queue</div><div id="queueValue" class="value">Idle</div></div>
    </section>
    <main class="main">
      <aside class="pane">
        <section class="section">
          <h2>Connection</h2>
          <div class="grid">
            <div class="field full"><label class="label" for="adbPathInput">ADB path</label><input id="adbPathInput" autocomplete="off"></div>
            <div class="field full"><label class="label" for="scrcpyPathInput">scrcpy path</label><input id="scrcpyPathInput" autocomplete="off"></div>
            <div class="field full"><label class="label" for="scrcpyOptionsInput">scrcpy options</label><input id="scrcpyOptionsInput" autocomplete="off" placeholder="--stay-awake --max-size 1280"></div>
            <div class="field full"><label class="label" for="deviceSelect">Device</label><select id="deviceSelect"></select></div>
            <div class="field full"><div id="deviceList" class="device-list"></div></div>
          </div>
        </section>
        <section class="section">
          <h2>Run Config</h2>
          <div class="grid">
            <div class="field"><label class="label" for="startupDelayInput">Start delay ms</label><input id="startupDelayInput" type="number" min="0" step="50"></div>
            <div class="field"><label class="label" for="intervalInput">Loop interval ms</label><input id="intervalInput" type="number" min="0" step="50"></div>
            <div class="field"><label class="label" for="repeatCountInput">Repeat count</label><input id="repeatCountInput" type="number" min="1" step="1"></div>
            <div class="field"><label class="checkline"><input id="foreverInput" type="checkbox"> Repeat forever</label></div>
            <div class="field full"><label class="checkline"><input id="dryRunInput" type="checkbox"> Dry run</label></div>
          </div>
        </section>
        <section class="section">
          <h2>Phone Timing</h2>
          <div class="grid">
            <div class="field full"><label class="label" for="clockOffsetInput">Clock offset ms <small style="font-weight:400;text-transform:none;">(phone nhanh hơn = dương, ví dụ +60000 = nhanh 1 phút)</small></label><input id="clockOffsetInput" type="number" step="100"></div>
            <div class="field"><label class="label" for="tapLeadInput">Tap lead ms <small style="font-weight:400;text-transform:none;">(bấm sớm hơn)</small></label><input id="tapLeadInput" type="number" min="0" step="50"></div>
            <div class="field"><label class="label" for="tapClickXInput">Click X</label><input id="tapClickXInput" type="number" min="0" step="1"></div>
            <div class="field"><label class="label" for="tapClickYInput">Click Y</label><input id="tapClickYInput" type="number" min="0" step="1"></div>
          </div>
        </section>
        <section class="section">
          <h2>Queue Runner</h2>
          <div class="grid">
            <div class="field full"><label class="checkline"><input id="queueEnabledInput" type="checkbox"> Auto-pull queue on start</label></div>
            <div class="field full"><label class="label" for="queueUrlInput">Queue UI URL</label><input id="queueUrlInput" type="text" autocomplete="off" placeholder="http://127.0.0.1:8787"></div>
            <div class="field"><label class="label" for="pollIntervalInput">Poll interval ms</label><input id="pollIntervalInput" type="number" min="500" step="500"></div>
            <div class="field"><label class="label" for="taskDurationInput">Task duration ms <small style="font-weight:400;text-transform:none;">(30000 = 30s)</small></label><input id="taskDurationInput" type="number" min="1000" step="1000"></div>
            <div class="field"><label class="label" for="fallbackPickInput">Fallback pick s <small style="font-weight:400;text-transform:none;">(10–20s)</small></label><input id="fallbackPickInput" type="number" min="1" step="1"></div>
            <div class="field"><label class="label" for="deeplinkSettleInput">Deeplink settle ms</label><input id="deeplinkSettleInput" type="number" min="0" step="100"></div>
            <div id="queueStatus" style="grid-column:1/-1;padding:8px 10px;border:1px solid var(--border);border-radius:6px;background:#f7f9fb;font-size:12px;color:var(--muted);">Queue idle</div>
          </div>
        </section>
        <section class="section">
          <h2>Raw Config</h2>
          <textarea id="rawConfig"></textarea>
        </section>
      </aside>
      <section class="work">
        <div class="tabs">
          <button id="controlTab" class="tab active" data-view="controlView">Điều khiển</button>
          <button id="capturesTab" class="tab" data-view="capturesView">Màn hình đã capture</button>
        </div>
        <div id="controlView" class="view active">
        <section class="section">
          <div class="actions-head">
            <h2>Live Control</h2>
            <div class="action-tools">
              <button id="snapshotBtn" class="button light">Snapshot</button>
              <button id="backBtn" class="button light">Back</button>
              <button id="homeBtn" class="button light">Home</button>
              <button id="recentsBtn" class="button light">Recents</button>
              <button id="openMirrorBtn" class="button light">Open Smooth Mirror</button>
              <button id="closeMirrorBtn" class="button light">Close Mirror</button>
              <button id="downloadLogsBtn" class="button light">Download Logs</button>
            </div>
          </div>
          <div class="screen-layout">
            <div>
              <div class="screen-tools">
                <label class="checkline"><input id="streamInput" type="checkbox"> Stream</label>
                <label class="label" for="streamIntervalInput">Interval</label>
                <input id="streamIntervalInput" class="small-input" type="number" min="300" step="100" value="1000">
              </div>
              <div id="screenStage" class="screen-stage">
                <img id="screenImage" class="screen-image" alt="Phone screen">
                <div id="screenEmpty" class="screen-empty">No screenshot yet. Connect ADB, then press Snapshot or enable Stream.</div>
              </div>
              <div id="tapInfo" class="tap-info">Click the screenshot to tap that coordinate.</div>
            </div>
            <div class="section">
              <h2>Open Deeplink</h2>
              <div class="direct-grid">
                <div class="field"><label class="label" for="deeplinkInput">URL</label><input id="deeplinkInput" autocomplete="off" placeholder="tiktok://... or https://..."></div>
                <button id="openDeeplinkBtn" class="button primary">Open</button>
              </div>
              <h2 style="margin-top:18px;">Treasure Detect</h2>
              <label class="checkline"><input id="detectEnabledInput" type="checkbox"> Detect + tap after deeplink</label>
              <div class="detect-grid">
                <div class="field"><label class="label" for="detectWaitInput">Load wait ms</label><input id="detectWaitInput" type="number" min="0" step="100"></div>
                <div class="field"><label class="label" for="detectRetryInput">Retries</label><input id="detectRetryInput" type="number" min="1" step="1"></div>
                <div class="field"><label class="label" for="detectIntervalInput">Retry ms</label><input id="detectIntervalInput" type="number" min="0" step="100"></div>
                <div class="field"><label class="label" for="detectThresholdInput">Threshold</label><input id="detectThresholdInput" type="number" min="0" max="1" step="0.01"></div>
                <div class="field"><label class="label" for="roiXInput">ROI X</label><input id="roiXInput" type="number" min="0" step="1"></div>
                <div class="field"><label class="label" for="roiYInput">ROI Y</label><input id="roiYInput" type="number" min="0" step="1"></div>
                <div class="field"><label class="label" for="roiWInput">ROI W</label><input id="roiWInput" type="number" min="1" step="1"></div>
                <div class="field"><label class="label" for="roiHInput">ROI H</label><input id="roiHInput" type="number" min="1" step="1"></div>
                <div class="field full"><label class="label" for="templatePathInput">Template path</label><input id="templatePathInput" autocomplete="off" placeholder="templates/treasure_box.png"></div>
              </div>
              <div class="action-tools" style="margin-top:10px;"><button id="testDetectBtn" class="button light">Test detect now</button></div>
              <div id="detectResult" class="detect-result">Template: phone_autoclicker/templates/treasure_box.png. Mask optional: treasure_box_mask.png.</div>
            </div>
          </div>
        </section>
        <div class="actions-head">
          <h2>Actions</h2>
          <div class="action-tools">
            <button class="button light" data-add="tap">Tap</button>
            <button class="button light" data-add="swipe">Swipe</button>
            <button class="button light" data-add="wait">Wait</button>
            <button class="button light" data-add="key">Key</button>
            <button class="button light" data-add="text">Text</button>
            <button class="button light" data-add="deeplink">Deeplink</button>
          </div>
        </div>
        <div id="actionList" class="action-list"></div>
        <section class="section" style="margin-top:18px;">
          <h2>Logs</h2>
          <div id="logBox" class="log"></div>
        </section>
        </div>
        <div id="capturesView" class="view">
          <section class="section">
            <div class="actions-head">
              <h2>Saved Captures</h2>
              <div class="action-tools">
                <button id="captureNowBtn" class="button primary">Capture now</button>
                <button id="refreshCapturesBtn" class="button light">Refresh Captures</button>
              </div>
            </div>
            <div id="captureList" class="capture-grid"></div>
          </section>
        </div>
      </section>
    </main>
  </div>
  <script>
    const state = { config:null, status:null, logs:[], captures:[], streamTimer:null };
    const $ = (id) => document.getElementById(id);
    const els = {
      path:$('configPath'), adb:$('adbValue'), device:$('deviceValue'), screen:$('screenValue'), runner:$('runnerValue'), queue:$('queueValue'),
      adbPath:$('adbPathInput'), deviceSelect:$('deviceSelect'), deviceList:$('deviceList'), startup:$('startupDelayInput'),
      interval:$('intervalInput'), repeat:$('repeatCountInput'), forever:$('foreverInput'), dryRun:$('dryRunInput'),
      raw:$('rawConfig'), actions:$('actionList'), logs:$('logBox'), screenStage:$('screenStage'), screenImage:$('screenImage'),
      tapInfo:$('tapInfo'), stream:$('streamInput'), streamInterval:$('streamIntervalInput'), deeplink:$('deeplinkInput'),
      captureList:$('captureList'), detectEnabled:$('detectEnabledInput'), detectWait:$('detectWaitInput'), detectRetry:$('detectRetryInput'), detectInterval:$('detectIntervalInput'), detectThreshold:$('detectThresholdInput'), roiX:$('roiXInput'), roiY:$('roiYInput'), roiW:$('roiWInput'), roiH:$('roiHInput'), templatePath:$('templatePathInput'), detectResult:$('detectResult'),
      clockOffset:$('clockOffsetInput'), tapLead:$('tapLeadInput'), tapClickX:$('tapClickXInput'), tapClickY:$('tapClickYInput'),
      queueEnabled:$('queueEnabledInput'), queueUrl:$('queueUrlInput'), pollInterval:$('pollIntervalInput'), taskDuration:$('taskDurationInput'), fallbackPick:$('fallbackPickInput'), deeplinkSettle:$('deeplinkSettleInput'), queueStatus:$('queueStatus')
    };
    function esc(value) { return String(value ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#039;'); }
    function numberValue(value, fallback=0) { const n = Number(value); return Number.isFinite(n) ? n : fallback; }
    function defaultAction(type) {
      if (type === 'tap') return { type:'tap', x:500, y:1200, delay_ms:250 };
      if (type === 'swipe') return { type:'swipe', x1:500, y1:1600, x2:500, y2:700, duration_ms:450, delay_ms:600 };
      if (type === 'wait') return { type:'wait', ms:1000 };
      if (type === 'key') return { type:'key', key:'BACK', delay_ms:250 };
      if (type === 'text') return { type:'text', text:'hello', delay_ms:250 };
      if (type === 'deeplink') return { type:'deeplink', url:'https://example.com', delay_ms:800 };
      return { type:'tap', x:500, y:1200, delay_ms:250 };
    }
    function syncSettings() {
      if (!state.config) return;
      state.config.adb_path = els.adbPath.value.trim() || 'adb';
      state.config.device_id = els.deviceSelect.value || '';
      state.config.startup_delay_ms = numberValue(els.startup.value, 0);
      state.config.dry_run = els.dryRun.checked;
      state.config.repeat = state.config.repeat || {};
      state.config.repeat.count = Math.max(1, numberValue(els.repeat.value, 1));
      state.config.repeat.forever = els.forever.checked;
      state.config.repeat.interval_ms = numberValue(els.interval.value, 0);
      state.config.treasure_detection = state.config.treasure_detection || {};
      const td = state.config.treasure_detection;
      td.enabled = Boolean(els.detectEnabled?.checked);
      td.after_deeplink = td.enabled;
      td.load_wait_ms = numberValue(els.detectWait?.value, 1200);
      td.retry_count = Math.max(1, numberValue(els.detectRetry?.value, 3));
      td.retry_interval_ms = numberValue(els.detectInterval?.value, 700);
      td.threshold = Number(els.detectThreshold?.value || 0.78);
      td.template_path = els.templatePath?.value.trim() || "templates/treasure_box.png";
      td.roi = { x:numberValue(els.roiX?.value, 0), y:numberValue(els.roiY?.value, 0), w:Math.max(1, numberValue(els.roiW?.value, 420)), h:Math.max(1, numberValue(els.roiH?.value, 520)) };
      td.tap = true;
      state.config.phone_timing = state.config.phone_timing || {};
      const pt = state.config.phone_timing;
      pt.clock_offset_ms = Number(els.clockOffset?.value ?? 60000);
      pt.tap_lead_ms = Math.max(0, numberValue(els.tapLead?.value, 500));
      pt.click_x = Math.max(0, numberValue(els.tapClickX?.value, 540));
      pt.click_y = Math.max(0, numberValue(els.tapClickY?.value, 1800));
      state.config.queue_runner = state.config.queue_runner || {};
      const qr = state.config.queue_runner;
      qr.enabled = Boolean(els.queueEnabled?.checked);
      qr.queue_url = (els.queueUrl?.value || 'http://127.0.0.1:8787').trim().replace(/\/$/, '');
      qr.poll_interval_ms = Math.max(500, numberValue(els.pollInterval?.value, 5000));
      qr.task_duration_ms = Math.max(1000, numberValue(els.taskDuration?.value, 30000));
      qr.fallback_pick_seconds = Math.max(1, numberValue(els.fallbackPick?.value, 18));
      qr.deeplink_settle_ms = Math.max(0, numberValue(els.deeplinkSettle?.value, 1000));
    }
    function renderSettings() {
      const cfg = state.config; if (!cfg) return;
      els.path.textContent = state.config_path || '';
      els.adbPath.value = cfg.adb_path || 'adb';
      els.startup.value = cfg.startup_delay_ms ?? 0;
      els.interval.value = cfg.repeat?.interval_ms ?? 0;
      els.repeat.value = cfg.repeat?.count ?? 1;
      els.forever.checked = Boolean(cfg.repeat?.forever);
      els.dryRun.checked = Boolean(cfg.dry_run);
      const td = cfg.treasure_detection || {};
      if (els.detectEnabled) els.detectEnabled.checked = Boolean(td.enabled);
      if (els.detectWait) els.detectWait.value = td.load_wait_ms ?? 1200;
      if (els.detectRetry) els.detectRetry.value = td.retry_count ?? 3;
      if (els.detectInterval) els.detectInterval.value = td.retry_interval_ms ?? 700;
      if (els.detectThreshold) els.detectThreshold.value = td.threshold ?? 0.78;
      if (els.templatePath) els.templatePath.value = td.template_path || "templates/treasure_box.png";
      const roi = td.roi || {};
      if (els.roiX) els.roiX.value = roi.x ?? 0;
      if (els.roiY) els.roiY.value = roi.y ?? 0;
      if (els.roiW) els.roiW.value = roi.w ?? 420;
      if (els.roiH) els.roiH.value = roi.h ?? 520;
      const pt = cfg.phone_timing || {};
      if (els.clockOffset) els.clockOffset.value = pt.clock_offset_ms ?? 60000;
      if (els.tapLead) els.tapLead.value = pt.tap_lead_ms ?? 500;
      if (els.tapClickX) els.tapClickX.value = pt.click_x ?? 540;
      if (els.tapClickY) els.tapClickY.value = pt.click_y ?? 1800;
      const qr = cfg.queue_runner || {};
      if (els.queueEnabled) els.queueEnabled.checked = Boolean(qr.enabled);
      if (els.queueUrl) els.queueUrl.value = qr.queue_url || 'http://127.0.0.1:8787';
      if (els.pollInterval) els.pollInterval.value = qr.poll_interval_ms ?? 5000;
      if (els.taskDuration) els.taskDuration.value = qr.task_duration_ms ?? 30000;
      if (els.fallbackPick) els.fallbackPick.value = qr.fallback_pick_seconds ?? 18;
      if (els.deeplinkSettle) els.deeplinkSettle.value = qr.deeplink_settle_ms ?? 1000;
      renderDevices();
      els.raw.value = JSON.stringify(cfg, null, 2);
    }
    function renderDevices() {
      const cfg = state.config || {};
      const devices = state.status?.devices || [];
      const active = cfg.device_id || devices.find((item) => item.state === 'device')?.serial || '';
      const options = ['<option value="">Auto select</option>'].concat(devices.map((item) => `<option value="${esc(item.serial)}">${esc(item.serial)} (${esc(item.state)})</option>`));
      els.deviceSelect.innerHTML = options.join('');
      els.deviceSelect.value = active;
      if (active) cfg.device_id = active;
      if (!devices.length) {
        els.deviceList.innerHTML = '<div class="device-row"><span>No ADB device</span><span class="pill bad">offline</span></div>';
        return;
      }
      els.deviceList.innerHTML = devices.map((item) => `<div class="device-row"><span>${esc(item.serial)}</span><span class="pill ${item.state === 'device' ? 'ok' : 'bad'}">${esc(item.state)}</span></div>`).join('');
    }
    function field(action,index,name,label,type='number') {
      const value = action[name] ?? '';
      return `<div class="field"><label class="label">${label}</label><input data-index="${index}" data-field="${name}" type="${type}" value="${esc(value)}"></div>`;
    }
    function renderAction(action,index) {
      const type = action.type || 'tap';
      let body = '';
      if (type === 'tap') body = field(action,index,'x','X') + field(action,index,'y','Y') + field(action,index,'delay_ms','Delay ms');
      else if (type === 'swipe') body = field(action,index,'x1','X1') + field(action,index,'y1','Y1') + field(action,index,'x2','X2') + field(action,index,'y2','Y2') + field(action,index,'duration_ms','Duration ms') + field(action,index,'delay_ms','Delay ms');
      else if (type === 'wait') body = field(action,index,'ms','Wait ms');
      else if (type === 'key') body = field(action,index,'key','Key','text') + field(action,index,'delay_ms','Delay ms');
      else if (type === 'text') body = field(action,index,'text','Text','text') + field(action,index,'delay_ms','Delay ms');
      else if (type === 'deeplink') body = field(action,index,'url','URL','text') + field(action,index,'delay_ms','Delay ms');
      return `<div class="action-row" data-index="${index}">
        <div class="action-top">
          <div class="action-title">
            <span class="pill">${index + 1}</span>
            <select data-index="${index}" data-field="type">
              ${['tap','swipe','wait','key','text','deeplink'].map((item) => `<option value="${item}" ${item === type ? 'selected' : ''}>${item}</option>`).join('')}
            </select>
          </div>
          <div class="action-buttons">
            <button class="mini" data-move="up" data-index="${index}">Up</button>
            <button class="mini" data-move="down" data-index="${index}">Down</button>
            <button class="mini danger" data-delete="${index}">Delete</button>
          </div>
        </div>
        <div class="action-body">${body}</div>
      </div>`;
    }
    function renderActions() {
      const actions = state.config?.actions || [];
      els.actions.innerHTML = actions.map(renderAction).join('');
    }
    function renderStatus() {
      const s = state.status || {};
      els.adb.textContent = s.adb_available ? s.adb_path : 'ADB not found';
      els.device.textContent = s.active_device || 'No device';
      els.screen.textContent = s.screen_size || 'Unknown';
      els.runner.textContent = s.runner?.running ? 'Running' : 'Idle';
      const qr = s.queue_runner || {};
      if (els.queue) els.queue.textContent = qr.running ? `Running #${qr.last_job_id || '?'}` : 'Idle';
      if (els.queueStatus) {
        const jobPart = qr.last_job_id ? ` | job #${qr.last_job_id}` : '';
        els.queueStatus.textContent = qr.running
          ? `Running${jobPart} | ${qr.last_status || ''}`
          : `Idle | ${qr.last_status || 'stopped'}${jobPart}`;
      }
      renderDevices();
    }
    function renderLogs() {
      els.logs.textContent = (state.logs || []).map((item) => `[${item.time}] ${item.message}`).join('\n');
      els.logs.scrollTop = els.logs.scrollHeight;
    }
    function renderCaptures() {
      const captures = state.captures || [];
      if (!captures.length) {
        els.captureList.innerHTML = '<div class="screen-empty" style="background:#111827;border-radius:6px;">Chưa có ảnh capture. Mở deeplink hoặc bấm Capture now để lưu ảnh.</div>';
        return;
      }
      els.captureList.innerHTML = captures.map((item) => `<a class="capture-card" href="${esc(item.url)}" target="_blank" rel="noreferrer">
        <img src="${esc(item.url)}" alt="${esc(item.filename)}" loading="lazy">
        <div class="capture-meta"><strong>${esc(item.created_at)}</strong><br>${esc(item.filename)}<br>${esc(item.size)} bytes</div>
      </a>`).join('');
    }
    function renderAll() { renderSettings(); renderActions(); renderStatus(); renderLogs(); }
    async function api(path, options={}) {
      const res = await fetch(path, options);
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
      return data;
    }
    async function loadConfig() {
      const data = await api('/api/config');
      state.config = data.config;
      state.config_path = data.path;
    }
    async function refreshStatus() {
      state.status = await api('/api/status');
      state.logs = (await api('/api/logs')).logs;
      renderStatus();
      renderLogs();
    }
    async function refreshCaptures() {
      state.captures = (await api('/api/captures')).captures;
      renderCaptures();
    }
    function renderDetectResult(result) {
      if (!els.detectResult) return;
      if (!result) { els.detectResult.textContent = "No result"; return; }
      const d = result.detection || result;
      els.detectResult.textContent = JSON.stringify(d, null, 2);
    }
    async function testTreasureDetect() {
      syncSettings();
      const data = await api('/api/treasure/detect', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({ config:state.config, tap:false, source:'test' }) });
      renderDetectResult(data);
      await refreshCaptures().catch(() => {});
      await refreshSnapshot().catch(() => {});
    }
    async function saveCapture(source='manual') {
      syncSettings();
      const data = await api('/api/capture', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({ config:state.config, source }) });
      state.captures = data.captures || state.captures;
      renderCaptures();
      els.tapInfo.textContent = `Saved capture ${data.capture?.filename || ''}`;
      return data.capture;
    }
    async function saveConfig() {
      syncSettings();
      try { state.config = JSON.parse(els.raw.value); } catch {}
      const data = await api('/api/config', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({ config:state.config }) });
      state.config = data.config;
      renderAll();
    }
    async function runConfig() {
      syncSettings();
      const data = await api('/api/run', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({ config:state.config }) });
      state.status = data.status;
      renderStatus();
      await refreshStatus();
    }
    async function stopRun() {
      await api('/api/stop', { method:'POST', headers:{'Content-Type':'application/json'}, body:'{}' });
      await refreshStatus();
    }
    async function refreshSnapshot() {
      if (state.snapshotLoading) return;
      state.snapshotLoading = true;
      try {
        const res = await fetch('/api/screenshot?_=' + Date.now(), { cache:'no-store' });
        if (!res.ok) {
          let message = `Screenshot failed: HTTP ${res.status}`;
          try { message = (await res.json()).error || message; } catch {}
          throw new Error(message);
        }
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const oldUrl = els.screenImage.dataset.url;
        els.screenImage.onload = () => {
          if (oldUrl) URL.revokeObjectURL(oldUrl);
          els.screenImage.dataset.url = url;
          els.screenStage.classList.add('has-image');
          els.tapInfo.textContent = `Screenshot ${els.screenImage.naturalWidth}x${els.screenImage.naturalHeight}. Click image to tap.`;
        };
        els.screenImage.src = url;
      } catch (err) {
        els.tapInfo.textContent = err.message;
        if (!els.screenImage.src) els.screenStage.classList.remove('has-image');
      } finally {
        state.snapshotLoading = false;
      }
    }
    function setStreaming(enabled) {
      if (state.streamTimer) {
        clearInterval(state.streamTimer);
        state.streamTimer = null;
      }
      if (!enabled) return;
      const interval = Math.max(300, numberValue(els.streamInterval.value, 1000));
      refreshSnapshot();
      state.streamTimer = setInterval(() => refreshSnapshot(), interval);
    }
    async function directTap(x, y) {
      syncSettings();
      await api('/api/tap', {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({ config:state.config, x, y })
      });
      els.tapInfo.textContent = `Tapped ${x}, ${y}`;
      await refreshStatus();
    }
    async function directKey(key) {
      syncSettings();
      await api('/api/key', {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({ config:state.config, key })
      });
      await refreshStatus();
    }
    async function openDeeplink() {
      syncSettings();
      await api('/api/deeplink', {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({ config:state.config, url:els.deeplink.value.trim() })
      });
      await refreshStatus();
      setTimeout(() => {
        const td = state.config?.treasure_detection || {};
        const work = td.enabled && td.after_deeplink ? api('/api/treasure/detect', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({ config:state.config, tap:true, source:'deeplink' }) }) : saveCapture('deeplink');
        work.then((data) => { renderDetectResult(data); return refreshCaptures(); }).then(() => refreshSnapshot()).catch((err) => els.tapInfo.textContent = err.message);
      }, 1000);
    }
    document.querySelectorAll('[data-add]').forEach((button) => button.addEventListener('click', () => {
      syncSettings();
      state.config.actions = state.config.actions || [];
      state.config.actions.push(defaultAction(button.dataset.add));
      renderActions();
      els.raw.value = JSON.stringify(state.config, null, 2);
    }));
    els.screenImage.addEventListener('click', async (event) => {
      if (!els.screenImage.naturalWidth || !els.screenImage.naturalHeight) return;
      const rect = els.screenImage.getBoundingClientRect();
      const x = Math.max(0, Math.min(els.screenImage.naturalWidth - 1, Math.round((event.clientX - rect.left) * els.screenImage.naturalWidth / rect.width)));
      const y = Math.max(0, Math.min(els.screenImage.naturalHeight - 1, Math.round((event.clientY - rect.top) * els.screenImage.naturalHeight / rect.height)));
      await directTap(x, y);
    });
    els.actions.addEventListener('input', (event) => {
      const target = event.target;
      const index = Number(target.dataset.index);
      const fieldName = target.dataset.field;
      if (!fieldName || !state.config?.actions?.[index]) return;
      const action = state.config.actions[index];
      if (fieldName === 'type') {
        state.config.actions[index] = defaultAction(target.value);
        renderActions();
      } else {
        action[fieldName] = target.type === 'number' ? numberValue(target.value, 0) : target.value;
      }
      els.raw.value = JSON.stringify(state.config, null, 2);
    });
    els.actions.addEventListener('click', (event) => {
      const del = event.target.dataset.delete;
      const move = event.target.dataset.move;
      const index = Number(event.target.dataset.index);
      const actions = state.config?.actions || [];
      if (del !== undefined) actions.splice(Number(del), 1);
      if (move === 'up' && index > 0) [actions[index - 1], actions[index]] = [actions[index], actions[index - 1]];
      if (move === 'down' && index < actions.length - 1) [actions[index + 1], actions[index]] = [actions[index], actions[index + 1]];
      renderActions();
      els.raw.value = JSON.stringify(state.config, null, 2);
    });
    $('snapshotBtn').addEventListener('click', () => refreshSnapshot().catch((err) => els.tapInfo.textContent = err.message));
    $('downloadLogsBtn').addEventListener('click', () => { window.location.href = '/api/logs.txt'; });
    $('captureNowBtn').addEventListener('click', () => saveCapture('manual').catch((err) => els.tapInfo.textContent = err.message));
    $('testDetectBtn').addEventListener('click', () => testTreasureDetect().catch((err) => els.detectResult.textContent = err.message));
    $('refreshCapturesBtn').addEventListener('click', () => refreshCaptures().catch((err) => els.tapInfo.textContent = err.message));
    document.querySelectorAll('[data-view]').forEach((button) => button.addEventListener('click', () => {
      document.querySelectorAll('.tab').forEach((tab) => tab.classList.toggle('active', tab === button));
      document.querySelectorAll('.view').forEach((view) => view.classList.toggle('active', view.id === button.dataset.view));
      if (button.dataset.view === 'capturesView') refreshCaptures().catch((err) => els.tapInfo.textContent = err.message);
    }));
    $('backBtn').addEventListener('click', () => directKey('BACK').catch((err) => els.tapInfo.textContent = err.message));
    $('homeBtn').addEventListener('click', () => directKey('HOME').catch((err) => els.tapInfo.textContent = err.message));
    $('recentsBtn').addEventListener('click', () => directKey('APP_SWITCH').catch((err) => els.tapInfo.textContent = err.message));
    $('openDeeplinkBtn').addEventListener('click', () => openDeeplink().catch((err) => els.tapInfo.textContent = err.message));
    els.stream.addEventListener('change', () => setStreaming(els.stream.checked));
    els.streamInterval.addEventListener('change', () => { if (els.stream.checked) setStreaming(true); });
    [els.adbPath, els.deviceSelect, els.startup, els.interval, els.repeat, els.forever, els.dryRun, els.detectEnabled, els.detectWait, els.detectRetry, els.detectInterval, els.detectThreshold, els.roiX, els.roiY, els.roiW, els.roiH, els.templatePath, els.clockOffset, els.tapLead, els.tapClickX, els.tapClickY, els.queueEnabled, els.queueUrl, els.pollInterval, els.taskDuration, els.fallbackPick, els.deeplinkSettle].filter(Boolean).forEach((node) => {
      node.addEventListener('input', () => { syncSettings(); els.raw.value = JSON.stringify(state.config, null, 2); });
      node.addEventListener('change', () => { syncSettings(); els.raw.value = JSON.stringify(state.config, null, 2); });
    });
    $('refreshBtn').addEventListener('click', () => refreshStatus().catch((err) => alert(err.message)));
    $('saveBtn').addEventListener('click', () => saveConfig().catch((err) => alert(err.message)));
    $('runBtn').addEventListener('click', () => runConfig().catch((err) => alert(err.message)));
    $('stopBtn').addEventListener('click', () => stopRun().catch((err) => alert(err.message)));
    async function startQueueRunner() {
      syncSettings();
      const data = await api('/api/queue/start', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({ config:state.config }) });
      state.status = data.status;
      renderStatus();
    }
    async function stopQueueRunner() {
      await api('/api/queue/stop', { method:'POST', headers:{'Content-Type':'application/json'}, body:'{}' });
      await refreshStatus();
    }
    $('queueStartBtn').addEventListener('click', () => startQueueRunner().catch((err) => alert(err.message)));
    $('queueStopBtn').addEventListener('click', () => stopQueueRunner().catch((err) => alert(err.message)));
    (async function init() {
      await loadConfig();
      await refreshStatus();
      await refreshCaptures().catch(() => {});
      renderAll();
      renderCaptures();
      refreshSnapshot().catch(() => {});
      setInterval(() => refreshStatus().catch(() => {}), 1500);
    })().catch((err) => alert(err.message));
  </script>
</body>
</html>
"""


def now_label() -> str:
    return datetime.now().strftime("%H:%M:%S")


class EventLog:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._items: List[Dict[str, str]] = []

    def add(self, message: str) -> None:
        item = {"time": now_label(), "message": message}
        with self._lock:
            self._items.append(item)
            del self._items[:-LOG_LIMIT]
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as file:
                file.write(f"[{item['time']}] {item['message']}\n")

    def snapshot(self) -> List[Dict[str, str]]:
        with self._lock:
            return list(self._items)

    def text(self) -> str:
        if not self.path.exists():
            return ""
        return self.path.read_text(encoding="utf-8")


class AdbError(RuntimeError):
    pass


class AdbClient:
    def __init__(self, log: EventLog) -> None:
        self.log = log

    def resolve_adb(self, config: Dict[str, Any]) -> Optional[str]:
        adb_path = str(config.get("adb_path") or "adb").strip() or "adb"
        if "/" in adb_path:
            return adb_path if Path(adb_path).exists() else None
        return shutil.which(adb_path)

    def adb_available(self, config: Dict[str, Any]) -> bool:
        return self.resolve_adb(config) is not None

    def devices(self, config: Dict[str, Any]) -> List[Dict[str, str]]:
        adb_path = self.resolve_adb(config)
        if not adb_path:
            return []
        try:
            result = subprocess.run(
                [adb_path, "devices", "-l"],
                text=True,
                capture_output=True,
                timeout=8,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return []

        devices: List[Dict[str, str]] = []
        for line in result.stdout.splitlines()[1:]:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            serial = parts[0]
            state = parts[1] if len(parts) > 1 else "unknown"
            devices.append({"serial": serial, "state": state, "details": " ".join(parts[2:])})
        return devices

    def active_device(self, config: Dict[str, Any]) -> Optional[str]:
        requested = str(config.get("device_id") or "").strip()
        if requested:
            return requested
        for device in self.devices(config):
            if device.get("state") == "device":
                return device.get("serial")
        return None

    def adb_command(
        self,
        config: Dict[str, Any],
        args: List[Any],
        timeout: int = 10,
        binary: bool = False,
    ) -> Any:
        adb_path = self.resolve_adb(config)
        if not adb_path:
            raise AdbError("ADB not found. Install android-platform-tools and refresh.")

        command = [adb_path]
        device_id = self.active_device(config)
        if device_id:
            command += ["-s", device_id]
        command += [str(value) for value in args]

        if bool(config.get("dry_run")):
            self.log.add("DRY RUN: " + " ".join(command))
            return b"" if binary else ""

        result = subprocess.run(command, capture_output=True, timeout=timeout, check=False)
        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace")
            stdout = result.stdout.decode("utf-8", errors="replace")
            error = (stderr or stdout or "ADB command failed").strip()
            raise AdbError(error)
        if binary:
            return result.stdout
        return result.stdout.decode("utf-8", errors="replace").strip()

    def shell(self, config: Dict[str, Any], args: List[Any], timeout: int = 10) -> str:
        return self.adb_command(config, ["shell"] + args, timeout=timeout, binary=False)

    def screencap(self, config: Dict[str, Any]) -> bytes:
        data = self.adb_command(
            config,
            ["exec-out", "screencap", "-p"],
            timeout=15,
            binary=True,
        )
        if not data:
            raise AdbError("Screenshot is empty")
        return data

    def open_deeplink(self, config: Dict[str, Any], url: str) -> str:
        url = url.strip()
        if not url:
            raise AdbError("Deeplink URL is empty")
        self.log.add(f"open deeplink {url}")
        return self.shell(
            config,
            ["am", "start", "-a", "android.intent.action.VIEW", "-d", url],
            timeout=10,
        )

    def screen_size(self, config: Dict[str, Any]) -> Optional[str]:
        try:
            output = self.shell(config, ["wm", "size"], timeout=5)
        except Exception:
            return None
        for line in output.splitlines():
            if "size:" in line:
                return line.split(":", 1)[1].strip()
        return None


class Runner:
    def __init__(self, adb: AdbClient, log: EventLog) -> None:
        self.adb = adb
        self.log = log
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._started_at: Optional[float] = None

    def status(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "running": self._running,
                "started_at": self._started_at,
                "stop_requested": self._stop.is_set(),
            }

    def start(self, config: Dict[str, Any]) -> None:
        with self._lock:
            if self._running:
                raise RuntimeError("Runner is already running")
            self._stop.clear()
            self._running = True
            self._started_at = time.time()
            self._thread = threading.Thread(target=self._run, args=(deepcopy(config),), daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self.log.add("Stop requested")

    def _run(self, config: Dict[str, Any]) -> None:
        try:
            self._run_sequence(config)
        except Exception as exc:
            self.log.add(f"ERROR: {exc}")
        finally:
            with self._lock:
                self._running = False
                self._started_at = None
            self.log.add("Runner idle")

    def _run_sequence(self, config: Dict[str, Any]) -> None:
        actions = config.get("actions") or []
        repeat = config.get("repeat") or {}
        count = int(repeat.get("count") or 1)
        forever = bool(repeat.get("forever"))
        interval_ms = int(repeat.get("interval_ms") or 0)
        startup_delay_ms = int(config.get("startup_delay_ms") or 0)

        if not actions:
            raise RuntimeError("No actions configured")

        if startup_delay_ms > 0:
            self.log.add(f"Start delay {startup_delay_ms}ms")
            if self._stop.wait(startup_delay_ms / 1000):
                return

        loop_index = 0
        while not self._stop.is_set() and (forever or loop_index < count):
            loop_index += 1
            self.log.add(f"Loop {loop_index} started")
            for index, action in enumerate(actions, start=1):
                if self._stop.is_set():
                    break
                self._execute_action(config, action, index)
            if self._stop.is_set():
                break
            if (forever or loop_index < count) and interval_ms > 0:
                self.log.add(f"Loop interval {interval_ms}ms")
                self._stop.wait(interval_ms / 1000)
        self.log.add("Run finished")

    def _execute_action(self, config: Dict[str, Any], action: Dict[str, Any], index: int) -> None:
        action_type = str(action.get("type") or "tap").lower()
        if action_type == "tap":
            x = int(action.get("x"))
            y = int(action.get("y"))
            self.log.add(f"#{index} tap x={x} y={y}")
            self.adb.shell(config, ["input", "tap", x, y])
            self._delay(action)
            return

        if action_type == "swipe":
            x1 = int(action.get("x1"))
            y1 = int(action.get("y1"))
            x2 = int(action.get("x2"))
            y2 = int(action.get("y2"))
            duration_ms = int(action.get("duration_ms") or 300)
            self.log.add(f"#{index} swipe {x1},{y1} -> {x2},{y2} {duration_ms}ms")
            self.adb.shell(config, ["input", "swipe", x1, y1, x2, y2, duration_ms])
            self._delay(action)
            return

        if action_type == "wait":
            wait_ms = int(action.get("ms") or 0)
            self.log.add(f"#{index} wait {wait_ms}ms")
            self._wait_ms(wait_ms)
            return

        if action_type == "key":
            key = str(action.get("key") or "BACK").strip()
            self.log.add(f"#{index} key {key}")
            self.adb.shell(config, ["input", "keyevent", key])
            self._delay(action)
            return

        if action_type == "text":
            text = str(action.get("text") or "").replace(" ", "%s")
            self.log.add(f"#{index} text length={len(text)}")
            self.adb.shell(config, ["input", "text", text])
            self._delay(action)
            return

        if action_type == "deeplink":
            url = str(action.get("url") or "").strip()
            self.log.add(f"#{index} deeplink {url}")
            self.adb.open_deeplink(config, url)
            self._delay(action)
            return

        raise RuntimeError(f"Unsupported action type: {action_type}")

    def _delay(self, action: Dict[str, Any]) -> None:
        self._wait_ms(int(action.get("delay_ms") or 0))

    def _wait_ms(self, wait_ms: int) -> None:
        if wait_ms > 0:
            self._stop.wait(wait_ms / 1000)


class QueueRunner:
    """Auto pulls jobs from queue_ui, opens deeplink, schedules a precise tap at the
    target wall-clock time and loops. Tries to pick a job whose remaining countdown
    is between (deeplink_settle_ms + tap_lead_ms) and `task_duration_ms`.
    """

    def __init__(self, adb: "AdbClient", log: "EventLog", app: "AutoClickerApp") -> None:
        self.adb = adb
        self.log = log
        self.app = app
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._started_at: Optional[float] = None
        self._last_job_id: int = 0
        self._last_status: str = "idle"

    def status(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "running": self._running,
                "started_at": self._started_at,
                "last_job_id": self._last_job_id,
                "last_status": self._last_status,
            }

    def start(self, config: Dict[str, Any]) -> None:
        with self._lock:
            if self._running:
                raise RuntimeError("Queue runner is already running")
            self._stop.clear()
            self._running = True
            self._started_at = time.time()
            self._last_status = "started"
            self._thread = threading.Thread(target=self._run, args=(deepcopy(config),), daemon=True)
            self._thread.start()
        self.log.add("queue runner started")

    def stop(self) -> None:
        self._stop.set()
        self.log.add("queue runner stop requested")

    def _set_status(self, status: str, job_id: Optional[int] = None) -> None:
        with self._lock:
            self._last_status = status
            if job_id is not None:
                self._last_job_id = job_id

    def _run(self, config: Dict[str, Any]) -> None:
        try:
            self._loop(config)
        except Exception as exc:
            self.log.add(f"queue runner error: {exc}")
        finally:
            with self._lock:
                self._running = False
                self._started_at = None
                self._last_status = "stopped"
            self.log.add("queue runner idle")

    def _loop(self, config: Dict[str, Any]) -> None:
        seen_ids: set = set()
        while not self._stop.is_set():
            cfg = self.app.load_config()
            qr = cfg.get("queue_runner") or {}
            pt = cfg.get("phone_timing") or {}
            queue_url = str(qr.get("queue_url") or "").strip().rstrip("/")
            poll_interval_ms = max(500, int(qr.get("poll_interval_ms") or 5000))
            task_duration_ms = max(1000, int(qr.get("task_duration_ms") or 30000))
            fallback_pick_seconds = max(1, int(qr.get("fallback_pick_seconds") or 18))
            deeplink_settle_ms = max(0, int(qr.get("deeplink_settle_ms") or 1000))
            tap_lead_ms = max(0, int(pt.get("tap_lead_ms") or 0))
            clock_offset_ms = int(pt.get("clock_offset_ms") or 0)
            click_x = max(0, int(pt.get("click_x") or 540))
            click_y = max(0, int(pt.get("click_y") or 1800))

            if not queue_url:
                self._set_status("queue_url empty")
                self.log.add("queue runner: queue_url empty, waiting")
                if self._stop.wait(poll_interval_ms / 1000):
                    return
                continue

            try:
                items = self._fetch_pending(queue_url)
            except Exception as exc:
                self._set_status(f"fetch error: {exc}")
                self.log.add(f"queue fetch error: {exc}")
                if self._stop.wait(poll_interval_ms / 1000):
                    return
                continue

            picked = self._pick_job(
                items,
                seen_ids=seen_ids,
                deeplink_settle_ms=deeplink_settle_ms,
                tap_lead_ms=tap_lead_ms,
                clock_offset_ms=clock_offset_ms,
                task_duration_ms=task_duration_ms,
                fallback_pick_seconds=fallback_pick_seconds,
            )
            if not picked:
                self._set_status("no candidate")
                if self._stop.wait(poll_interval_ms / 1000):
                    return
                continue

            job, target_at = picked
            job_id = int(job.get("id") or 0)
            url = str(job.get("url") or "").strip()
            if not url or job_id == 0:
                seen_ids.add(job_id)
                continue

            seen_ids.add(job_id)
            self._set_status(f"opening #{job_id}", job_id=job_id)
            self.log.add(f"queue picked #{job_id} url={url} target_at={target_at}")

            try:
                self._execute_job(cfg, job_id, url, target_at, click_x, click_y, deeplink_settle_ms, tap_lead_ms)
            except Exception as exc:
                self._set_status(f"job error: {exc}", job_id=job_id)
                self.log.add(f"queue job #{job_id} error: {exc}")
                if self._stop.wait(poll_interval_ms / 1000):
                    return
                continue

            self._set_status(f"done #{job_id}", job_id=job_id)
            try:
                self._mark_done(queue_url, job_id, "auto-clicker tap completed")
            except Exception as exc:
                self.log.add(f"queue mark-done #{job_id} error: {exc}")

    def _fetch_pending(self, queue_url: str) -> List[Dict[str, Any]]:
        url = f"{queue_url}/api/queue?limit=50&statuses=pending&_={int(time.time() * 1000)}"
        request = urllib.request.Request(url, headers={"Accept": "application/json", "Cache-Control": "no-store"})
        with urllib.request.urlopen(request, timeout=8) as response:
            data = json.loads(response.read().decode("utf-8"))
        return data.get("items") or []

    def _mark_done(self, queue_url: str, job_id: int, note: str) -> None:
        url = f"{queue_url}/api/queue/mark-done"
        body = json.dumps({"job_id": job_id, "note": note}).encode("utf-8")
        request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(request, timeout=8) as response:
            response.read()

    def _pick_job(
        self,
        items: List[Dict[str, Any]],
        seen_ids: set,
        deeplink_settle_ms: int,
        tap_lead_ms: int,
        clock_offset_ms: int,
        task_duration_ms: int,
        fallback_pick_seconds: int,
    ) -> Optional[Tuple[Dict[str, Any], Optional[float]]]:
        """Pick the first pending job with countdown that fits the task window
        (`min_remaining_ms < remaining < task_duration_ms`). If none fits, pick
        the smallest-countdown job whose remaining > min_remaining_ms.
        """
        min_remaining_ms = deeplink_settle_ms + tap_lead_ms + 500
        now = time.time()
        candidates: List[Tuple[Dict[str, Any], Optional[float], int]] = []
        for item in items:
            try:
                job_id = int(item.get("id") or 0)
            except (TypeError, ValueError):
                continue
            if job_id == 0 or job_id in seen_ids:
                continue
            url = _extract_link(item)
            if not url:
                continue
            target_at, remaining_ms = self._target_for_item(item, now=now, clock_offset_ms=clock_offset_ms)
            if remaining_ms is None:
                # No timing info: usable as a fallback only.
                candidates.append((self._make_runtime_job(item, url), None, fallback_pick_seconds * 1000))
                continue
            if remaining_ms < min_remaining_ms:
                continue
            candidates.append((self._make_runtime_job(item, url), target_at, remaining_ms))

        if not candidates:
            return None

        in_window = [c for c in candidates if c[2] <= task_duration_ms]
        if in_window:
            in_window.sort(key=lambda c: c[2])
            job, target_at, _ = in_window[0]
            return job, target_at

        candidates.sort(key=lambda c: c[2])
        job, target_at, _ = candidates[0]
        return job, target_at

    def _target_for_item(
        self,
        item: Dict[str, Any],
        now: float,
        clock_offset_ms: int,
    ) -> Tuple[Optional[float], Optional[int]]:
        target_label = _extract_target_hhmmss(item)
        if target_label:
            target_at = _resolve_target_time(target_label, now=now)
            if target_at is not None:
                target_at_with_offset = target_at - (clock_offset_ms / 1000)
                remaining_ms = int(round((target_at_with_offset - now) * 1000))
                return target_at_with_offset, remaining_ms
        click_after_ms = _extract_click_after_ms(item)
        if click_after_ms > 0:
            target_at = now + (click_after_ms / 1000)
            return target_at, click_after_ms
        return None, None

    def _make_runtime_job(self, item: Dict[str, Any], url: str) -> Dict[str, Any]:
        return {"id": int(item.get("id") or 0), "url": url, "raw": item}

    def _execute_job(
        self,
        cfg: Dict[str, Any],
        job_id: int,
        url: str,
        target_at: Optional[float],
        click_x: int,
        click_y: int,
        deeplink_settle_ms: int,
        tap_lead_ms: int,
    ) -> None:
        self.log.add(f"queue #{job_id} open deeplink {url}")
        self.adb.open_deeplink(cfg, url)
        if deeplink_settle_ms > 0:
            if self._stop.wait(deeplink_settle_ms / 1000):
                return

        if target_at is not None:
            tap_at = target_at - (tap_lead_ms / 1000)
            wait_seconds = tap_at - time.time()
            if wait_seconds > 0:
                self.log.add(f"queue #{job_id} sleep {wait_seconds:.2f}s before tap")
                if self._stop.wait(wait_seconds):
                    return

        self.log.add(f"queue #{job_id} tap {click_x},{click_y}")
        self.adb.shell(cfg, ["input", "tap", click_x, click_y])

        try:
            data = self.adb.screencap(cfg)
            self.app.save_capture_bytes(data, f"queue-{job_id}", {"queue_job_id": job_id, "url": url})
        except Exception as exc:
            self.log.add(f"queue #{job_id} capture failed: {exc}")


def _extract_link(item: Dict[str, Any]) -> str:
    import re as _re
    payload = item.get("payload") or {}
    message = item.get("message") or {}
    candidates = [
        payload.get("url"), payload.get("link"), payload.get("deeplink"),
        payload.get("deep_link"), payload.get("live_url"), payload.get("room_url"),
        message.get("text"),
    ]
    for value in candidates:
        match = _re.search(r"(?:https?://|tiktok://)[^\s<>'\"]+", str(value or ""), _re.I)
        if match:
            return match.group(0)
    return ""


def _extract_target_hhmmss(item: Dict[str, Any]) -> str:
    import re as _re
    payload = item.get("payload") or {}
    message = item.get("message") or {}
    candidates = [
        payload.get("target_time_hhmmss"),
        payload.get("TIME"), payload.get("time"), payload.get("Time"),
        message.get("text"),
    ]
    for value in candidates:
        text = str(value or "")
        match = _re.search(r"-\s*(\d{1,2}):(\d{2}):(\d{2})", text)
        if match:
            return f"{match.group(1)}:{match.group(2)}:{match.group(3)}"
    return ""


def _extract_click_after_ms(item: Dict[str, Any]) -> int:
    import re as _re
    payload = item.get("payload") or {}
    message = item.get("message") or {}
    if isinstance(payload.get("click_after_ms"), (int, float)):
        return int(payload["click_after_ms"])
    candidates = [payload.get("TIME"), payload.get("time"), message.get("text")]
    for value in candidates:
        text = str(value or "")
        match = _re.search(r"(\d{1,2}):(\d{2})\s*s", text, _re.I)
        if match:
            return (int(match.group(1)) * 60 + int(match.group(2))) * 1000
        match = _re.search(r"(\d+(?:\.\d+)?)\s*s", text, _re.I)
        if match:
            return int(float(match.group(1)) * 1000)
    return 0


def _resolve_target_time(hhmmss: str, now: float) -> Optional[float]:
    """Convert a `HH:MM:SS` label (where HH may be 24+, meaning past midnight) to
    an absolute epoch time near `now`. Picks the closest occurrence (today or
    tomorrow) within ±12h of `now`.
    """
    parts = hhmmss.split(":")
    if len(parts) != 3:
        return None
    try:
        hours = int(parts[0])
        minutes = int(parts[1])
        seconds = int(parts[2])
    except ValueError:
        return None
    day_offset, hh = divmod(hours, 24)
    now_dt = datetime.fromtimestamp(now)
    base = now_dt.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=day_offset)
    candidate = base.replace(hour=hh, minute=minutes, second=seconds)
    best = candidate
    best_delta = abs((candidate.timestamp() - now))
    for shift in (-1, 1):
        alt = candidate + timedelta(days=shift)
        delta = abs(alt.timestamp() - now)
        if delta < best_delta:
            best = alt
            best_delta = delta
    return best.timestamp()


class AutoClickerApp:
    def __init__(self, config_path: Path) -> None:
        self.config_path = config_path
        self.log = EventLog(DEFAULT_LOG_PATH)
        self.adb = AdbClient(self.log)
        self.runner = Runner(self.adb, self.log)
        self.queue_runner: "QueueRunner" = QueueRunner(self.adb, self.log, self)
        self._config_lock = threading.Lock()

    def load_config(self) -> Dict[str, Any]:
        with self._config_lock:
            if not self.config_path.exists():
                return deepcopy(DEFAULT_CONFIG)
            with self.config_path.open(encoding="utf-8") as file:
                return normalize_config(json.load(file))

    def save_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        normalized = normalize_config(config)
        with self._config_lock:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self.config_path.with_suffix(self.config_path.suffix + ".tmp")
            tmp_path.write_text(
                json.dumps(normalized, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            tmp_path.replace(self.config_path)
        self.log.add(f"Config saved {self.config_path}")
        return normalized

    def save_capture_bytes(self, data: bytes, source: str = "manual", metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        DEFAULT_CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
        safe_source = "".join(ch if ch.isalnum() or ch in ("-", "_") else "-" for ch in source)[:32] or "manual"
        filename = f"{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}-{safe_source}.png"
        path = DEFAULT_CAPTURE_DIR / filename
        path.write_bytes(data)
        info = capture_info(path)
        if metadata is not None:
            meta_path = path.with_suffix(".json")
            meta_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            info["metadata_url"] = f"/captures/{meta_path.name}"
        self.log.add(f"capture saved {path.name}")
        return info

    def save_capture(self, config: Dict[str, Any], source: str = "manual") -> Dict[str, Any]:
        return self.save_capture_bytes(self.adb.screencap(config), source)

    def detect_treasure(self, config: Dict[str, Any], tap: bool = True, source: str = "treasure") -> Dict[str, Any]:
        td = treasure_config(config)
        if td["load_wait_ms"] > 0:
            time.sleep(td["load_wait_ms"] / 1000)
        last: Dict[str, Any] = {}
        capture: Optional[Dict[str, Any]] = None
        for attempt in range(1, td["retry_count"] + 1):
            data = self.adb.screencap(config)
            detection = detect_treasure_in_png(data, td)
            detection["attempt"] = attempt
            last = detection
            capture = self.save_capture_bytes(data, source, {"treasure_detection": detection})
            if detection.get("found"):
                tap_point = detection.get("tap") or {}
                if tap and td.get("tap", True):
                    x = int(tap_point.get("x"))
                    y = int(tap_point.get("y"))
                    self.log.add(f"treasure found score={detection.get('score')} tap {x},{y}")
                    self.adb.shell(config, ["input", "tap", x, y])
                    detection["tapped"] = True
                return {"ok": True, "detection": detection, "capture": capture, "captures": self.captures()}
            self.log.add(f"treasure not found attempt={attempt} score={detection.get('score')}")
            if attempt < td["retry_count"] and td["retry_interval_ms"] > 0:
                time.sleep(td["retry_interval_ms"] / 1000)
        return {"ok": True, "detection": last, "capture": capture, "captures": self.captures()}

    def captures(self) -> List[Dict[str, Any]]:
        DEFAULT_CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
        return [capture_info(path) for path in sorted(DEFAULT_CAPTURE_DIR.glob("*.png"), key=lambda item: item.stat().st_mtime, reverse=True)]

    def status(self, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        config = config or self.load_config()
        adb_path = self.adb.resolve_adb(config)
        active_device = self.adb.active_device(config) if adb_path else None
        return {
            "adb_available": adb_path is not None,
            "adb_path": adb_path or str(config.get("adb_path") or "adb"),
            "devices": self.adb.devices(config),
            "active_device": active_device,
            "screen_size": self.adb.screen_size(config) if active_device else None,
            "runner": self.runner.status(),
            "queue_runner": self.queue_runner.status(),
        }


def treasure_config(config: Dict[str, Any]) -> Dict[str, Any]:
    raw = config.get("treasure_detection") if isinstance(config.get("treasure_detection"), dict) else {}
    roi = raw.get("roi") if isinstance(raw.get("roi"), dict) else {}
    template_path = resolve_local_path(str(raw.get("template_path") or "templates/treasure_box.png"))
    mask_raw = str(raw.get("mask_path") or "templates/treasure_box_mask.png")
    mask_path = resolve_local_path(mask_raw) if mask_raw else None
    return {
        "enabled": bool(raw.get("enabled", True)),
        "after_deeplink": bool(raw.get("after_deeplink", True)),
        "load_wait_ms": non_negative_int(raw.get("load_wait_ms"), 1200),
        "retry_count": max(1, non_negative_int(raw.get("retry_count"), 3)),
        "retry_interval_ms": non_negative_int(raw.get("retry_interval_ms"), 700),
        "threshold": float(raw.get("threshold", 0.78)),
        "roi": {
            "x": non_negative_int(roi.get("x"), 0),
            "y": non_negative_int(roi.get("y"), 0),
            "w": max(1, non_negative_int(roi.get("w"), 420)),
            "h": max(1, non_negative_int(roi.get("h"), 520)),
        },
        "template_path": template_path,
        "mask_path": mask_path,
        "tap": bool(raw.get("tap", True)),
    }


def resolve_local_path(value: str) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    return BASE_DIR / path


def detect_treasure_in_png(data: bytes, td: Dict[str, Any]) -> Dict[str, Any]:
    try:
        import cv2  # type: ignore
        import numpy as np  # type: ignore
    except ImportError as exc:
        raise RuntimeError("Treasure detection needs opencv-python and numpy. Run: pip install opencv-python numpy") from exc

    template_path: Path = td["template_path"]
    if not template_path.exists():
        raise RuntimeError(f"Treasure template not found: {template_path}")

    image_array = np.frombuffer(data, dtype=np.uint8)
    image = cv2.imdecode(image_array, cv2.IMREAD_COLOR)
    if image is None:
        raise RuntimeError("Could not decode screenshot")
    template = cv2.imread(str(template_path), cv2.IMREAD_COLOR)
    if template is None:
        raise RuntimeError(f"Could not read template: {template_path}")

    height, width = image.shape[:2]
    roi_cfg = td["roi"]
    rx = min(int(roi_cfg["x"]), width - 1)
    ry = min(int(roi_cfg["y"]), height - 1)
    rw = min(int(roi_cfg["w"]), width - rx)
    rh = min(int(roi_cfg["h"]), height - ry)
    roi = image[ry:ry + rh, rx:rx + rw]
    th, tw = template.shape[:2]
    if rw < tw or rh < th:
        return {"found": False, "reason": "template_larger_than_roi", "screen": {"w": width, "h": height}, "roi": roi_cfg, "template": {"w": tw, "h": th}}

    mask = None
    mask_path = td.get("mask_path")
    if mask_path and Path(mask_path).exists():
        mask = cv2.imread(str(mask_path), cv2.IMREAD_GRAYSCALE)
        if mask is not None and mask.shape[:2] != (th, tw):
            mask = cv2.resize(mask, (tw, th), interpolation=cv2.INTER_NEAREST)

    method = cv2.TM_CCORR_NORMED if mask is not None else cv2.TM_CCOEFF_NORMED
    result = cv2.matchTemplate(roi, template, method, mask=mask) if mask is not None else cv2.matchTemplate(roi, template, method)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)
    score = float(max_val)
    x = rx + int(max_loc[0])
    y = ry + int(max_loc[1])
    box = {"x": x, "y": y, "w": tw, "h": th}
    tap = {"x": x + tw // 2, "y": y + th // 2}
    found = score >= float(td["threshold"])
    return {"found": found, "score": round(score, 4), "threshold": td["threshold"], "screen": {"w": width, "h": height}, "roi": {"x": rx, "y": ry, "w": rw, "h": rh}, "box": box, "tap": tap, "template": str(template_path), "mask": str(mask_path) if mask_path and Path(mask_path).exists() else None}


def capture_info(path: Path) -> Dict[str, Any]:
    stat = path.stat()
    return {
        "filename": path.name,
        "url": f"/captures/{path.name}",
        "size": stat.st_size,
        "created_at": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
    }


def normalize_config(raw: Dict[str, Any]) -> Dict[str, Any]:
    config = deepcopy(DEFAULT_CONFIG)
    if isinstance(raw, dict):
        config.update(raw)
    config["adb_path"] = str(config.get("adb_path") or "adb").strip() or "adb"
    config["device_id"] = str(config.get("device_id") or "").strip()
    config["dry_run"] = bool(config.get("dry_run"))
    config["startup_delay_ms"] = non_negative_int(config.get("startup_delay_ms"), 0)

    repeat = config.get("repeat") if isinstance(config.get("repeat"), dict) else {}
    config["repeat"] = {
        "count": max(1, non_negative_int(repeat.get("count"), 1)),
        "forever": bool(repeat.get("forever")),
        "interval_ms": non_negative_int(repeat.get("interval_ms"), 0),
    }

    td = config.get("treasure_detection") if isinstance(config.get("treasure_detection"), dict) else {}
    roi = td.get("roi") if isinstance(td.get("roi"), dict) else {}
    config["treasure_detection"] = {
        "enabled": bool(td.get("enabled", True)),
        "after_deeplink": bool(td.get("after_deeplink", True)),
        "load_wait_ms": non_negative_int(td.get("load_wait_ms"), 1200),
        "retry_count": max(1, non_negative_int(td.get("retry_count"), 3)),
        "retry_interval_ms": non_negative_int(td.get("retry_interval_ms"), 700),
        "threshold": float(td.get("threshold", 0.78)),
        "roi": {"x": non_negative_int(roi.get("x"), 0), "y": non_negative_int(roi.get("y"), 0), "w": max(1, non_negative_int(roi.get("w"), 420)), "h": max(1, non_negative_int(roi.get("h"), 520))},
        "template_path": str(td.get("template_path") or "templates/treasure_box.png"),
        "mask_path": str(td.get("mask_path") or "templates/treasure_box_mask.png"),
        "tap": bool(td.get("tap", True)),
    }

    pt = config.get("phone_timing") if isinstance(config.get("phone_timing"), dict) else {}
    config["phone_timing"] = {
        "clock_offset_ms": int_value(pt.get("clock_offset_ms"), 60000),
        "tap_lead_ms": non_negative_int(pt.get("tap_lead_ms"), 500),
        "click_x": non_negative_int(pt.get("click_x"), 540),
        "click_y": non_negative_int(pt.get("click_y"), 1800),
    }

    qr = config.get("queue_runner") if isinstance(config.get("queue_runner"), dict) else {}
    config["queue_runner"] = {
        "enabled": bool(qr.get("enabled", False)),
        "queue_url": str(qr.get("queue_url") or "http://127.0.0.1:8787").strip().rstrip("/"),
        "poll_interval_ms": max(500, non_negative_int(qr.get("poll_interval_ms"), 5000)),
        "task_duration_ms": max(1000, non_negative_int(qr.get("task_duration_ms"), 30000)),
        "fallback_pick_seconds": max(1, non_negative_int(qr.get("fallback_pick_seconds"), 18)),
        "deeplink_settle_ms": non_negative_int(qr.get("deeplink_settle_ms"), 1000),
    }

    actions = config.get("actions")
    config["actions"] = actions if isinstance(actions, list) else []
    return config


def int_value(value: Any, default: int) -> int:
    """Like non_negative_int but allows negative values (used for clock offsets)."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def non_negative_int(value: Any, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(0, number)


def json_response(handler: BaseHTTPRequestHandler, payload: Dict[str, Any], status: int = 200) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


def html_response(handler: BaseHTTPRequestHandler, html: str) -> None:
    body = html.encode("utf-8")
    handler.send_response(200)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


def text_response(
    handler: BaseHTTPRequestHandler,
    text: str,
    filename: Optional[str] = None,
) -> None:
    body = text.encode("utf-8")
    handler.send_response(200)
    handler.send_header("Content-Type", "text/plain; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    if filename:
        handler.send_header("Content-Disposition", f'attachment; filename="{filename}"')
    handler.end_headers()
    handler.wfile.write(body)

def binary_response(handler: BaseHTTPRequestHandler, body: bytes, content_type: str) -> None:
    handler.send_response(200)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store, no-cache, max-age=0")
    handler.end_headers()
    handler.wfile.write(body)


def png_response(handler: BaseHTTPRequestHandler, body: bytes) -> None:
    handler.send_response(200)
    handler.send_header("Content-Type", "image/png")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store, no-cache, max-age=0")
    handler.end_headers()
    handler.wfile.write(body)

def read_json(handler: BaseHTTPRequestHandler) -> Dict[str, Any]:
    length = int(handler.headers.get("Content-Length") or 0)
    if length <= 0:
        return {}
    data = handler.rfile.read(length)
    return json.loads(data.decode("utf-8"))


def make_handler(app: AutoClickerApp):
    class PhoneAutoClickerHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            try:
                if parsed.path == "/":
                    html_response(self, HTML)
                    return
                if parsed.path == "/api/config":
                    json_response(self, {"path": str(app.config_path), "config": app.load_config()})
                    return
                if parsed.path == "/api/status":
                    json_response(self, app.status())
                    return
                if parsed.path == "/api/logs":
                    json_response(self, {"logs": app.log.snapshot()})
                    return
                if parsed.path == "/api/captures":
                    json_response(self, {"captures": app.captures()})
                    return
                if parsed.path == "/api/logs.txt":
                    text_response(self, app.log.text(), filename="phone-autoclicker.log")
                    return
                if parsed.path == "/api/screenshot":
                    png_response(self, app.adb.screencap(app.load_config()))
                    return
                if parsed.path.startswith("/captures/"):
                    filename = Path(parsed.path).name
                    path = DEFAULT_CAPTURE_DIR / filename
                    if not path.exists() or path.suffix.lower() not in (".png", ".json"):
                        json_response(self, {"error": "Capture not found"}, status=404)
                        return
                    if path.suffix.lower() == ".json":
                        text_response(self, path.read_text(encoding="utf-8"))
                    else:
                        binary_response(self, path.read_bytes(), "image/png")
                    return
                json_response(self, {"error": "Not found"}, status=404)
            except Exception as exc:
                json_response(self, {"error": str(exc)}, status=500)

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            try:
                payload = read_json(self)
                if parsed.path == "/api/config":
                    config = app.save_config(payload.get("config", payload))
                    json_response(self, {"path": str(app.config_path), "config": config})
                    return
                if parsed.path == "/api/run":
                    config = normalize_config(payload.get("config", payload) or app.load_config())
                    app.runner.start(config)
                    app.log.add("Runner started")
                    json_response(self, {"status": app.status(config)})
                    return
                if parsed.path == "/api/stop":
                    app.runner.stop()
                    json_response(self, {"status": app.status()})
                    return
                if parsed.path == "/api/tap":
                    config = normalize_config(payload.get("config") or app.load_config())
                    x = int(payload.get("x"))
                    y = int(payload.get("y"))
                    app.log.add(f"direct tap x={x} y={y}")
                    app.adb.shell(config, ["input", "tap", x, y])
                    json_response(self, {"ok": True, "status": app.status(config)})
                    return
                if parsed.path == "/api/key":
                    config = normalize_config(payload.get("config") or app.load_config())
                    key = str(payload.get("key") or "BACK").strip()
                    app.log.add(f"direct key {key}")
                    app.adb.shell(config, ["input", "keyevent", key])
                    json_response(self, {"ok": True, "status": app.status(config)})
                    return
                if parsed.path == "/api/deeplink":
                    config = normalize_config(payload.get("config") or app.load_config())
                    output = app.adb.open_deeplink(config, str(payload.get("url") or ""))
                    json_response(self, {"ok": True, "output": output, "status": app.status(config)})
                    return
                if parsed.path == "/api/capture":
                    config = normalize_config(payload.get("config") or app.load_config())
                    capture = app.save_capture(config, str(payload.get("source") or "manual"))
                    json_response(self, {"ok": True, "capture": capture, "captures": app.captures()})
                    return
                if parsed.path == "/api/treasure/detect":
                    config = normalize_config(payload.get("config") or app.load_config())
                    result = app.detect_treasure(config, bool(payload.get("tap", True)), str(payload.get("source") or "treasure"))
                    json_response(self, result)
                    return
                if parsed.path == "/api/queue/start":
                    config = normalize_config(payload.get("config", payload) or app.load_config())
                    app.save_config(config)
                    app.queue_runner.start(config)
                    json_response(self, {"ok": True, "status": app.status(config)})
                    return
                if parsed.path == "/api/queue/stop":
                    app.queue_runner.stop()
                    json_response(self, {"ok": True, "status": app.status()})
                    return
                json_response(self, {"error": "Not found"}, status=404)
            except RuntimeError as exc:
                json_response(self, {"error": str(exc)}, status=409)
            except Exception as exc:
                json_response(self, {"error": str(exc)}, status=500)

        def log_message(self, format: str, *args: Any) -> None:
            logging.getLogger("http").debug(format, *args)

    return PhoneAutoClickerHandler


def setup_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def main() -> None:
    parser = argparse.ArgumentParser(description="Phone auto clicker over Android ADB")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8790)
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    args = parser.parse_args()

    setup_logging()
    app = AutoClickerApp(Path(args.config).expanduser().resolve())
    if not app.config_path.exists():
        app.save_config(DEFAULT_CONFIG)

    server = ThreadingHTTPServer((args.host, args.port), make_handler(app))
    url = f"http://{args.host}:{args.port}"
    logging.info("Phone Auto Clicker running at %s", url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logging.info("Stopping")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
