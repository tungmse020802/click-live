#!/usr/bin/env python3
import argparse
import json
import logging
import os
import shlex
import shutil
import subprocess
import threading
import time
from copy import deepcopy
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = BASE_DIR / "config.json"
DEFAULT_LOG_PATH = BASE_DIR / "events.log"
DEFAULT_SCRCPY_LOG_PATH = BASE_DIR / "scrcpy.log"
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
    .direct-grid { display:grid; grid-template-columns:1fr auto; gap:10px; align-items:end; }
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
      </div>
    </header>
    <section class="statusbar">
      <div class="stat"><div class="label">ADB</div><div id="adbValue" class="value">Checking</div></div>
      <div class="stat"><div class="label">Device</div><div id="deviceValue" class="value">Checking</div></div>
      <div class="stat"><div class="label">Screen</div><div id="screenValue" class="value">Unknown</div></div>
      <div class="stat"><div class="label">Runner</div><div id="runnerValue" class="value">Idle</div></div>
      <div class="stat"><div class="label">Mirror</div><div id="mirrorValue" class="value">Idle</div></div>
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
          <h2>Raw Config</h2>
          <textarea id="rawConfig"></textarea>
        </section>
      </aside>
      <section class="work">
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
      </section>
    </main>
  </div>
  <script>
    const state = { config:null, status:null, logs:[], streamTimer:null };
    const $ = (id) => document.getElementById(id);
    const els = {
      path:$('configPath'), adb:$('adbValue'), device:$('deviceValue'), screen:$('screenValue'), runner:$('runnerValue'),
      adbPath:$('adbPathInput'), deviceSelect:$('deviceSelect'), deviceList:$('deviceList'), startup:$('startupDelayInput'),
      interval:$('intervalInput'), repeat:$('repeatCountInput'), forever:$('foreverInput'), dryRun:$('dryRunInput'),
      raw:$('rawConfig'), actions:$('actionList'), logs:$('logBox'), screenStage:$('screenStage'), screenImage:$('screenImage'),
      tapInfo:$('tapInfo'), stream:$('streamInput'), streamInterval:$('streamIntervalInput'), deeplink:$('deeplinkInput')
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
      renderDevices();
    }
    function renderLogs() {
      els.logs.textContent = (state.logs || []).map((item) => `[${item.time}] ${item.message}`).join('\n');
      els.logs.scrollTop = els.logs.scrollHeight;
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
      if (els.stream.checked) setTimeout(refreshSnapshot, 700);
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
    $('backBtn').addEventListener('click', () => directKey('BACK').catch((err) => els.tapInfo.textContent = err.message));
    $('homeBtn').addEventListener('click', () => directKey('HOME').catch((err) => els.tapInfo.textContent = err.message));
    $('recentsBtn').addEventListener('click', () => directKey('APP_SWITCH').catch((err) => els.tapInfo.textContent = err.message));
    $('openDeeplinkBtn').addEventListener('click', () => openDeeplink().catch((err) => els.tapInfo.textContent = err.message));
    els.stream.addEventListener('change', () => setStreaming(els.stream.checked));
    els.streamInterval.addEventListener('change', () => { if (els.stream.checked) setStreaming(true); });
    [els.adbPath, els.deviceSelect, els.startup, els.interval, els.repeat, els.forever, els.dryRun].forEach((node) => {
      node.addEventListener('input', () => { syncSettings(); els.raw.value = JSON.stringify(state.config, null, 2); });
      node.addEventListener('change', () => { syncSettings(); els.raw.value = JSON.stringify(state.config, null, 2); });
    });
    $('refreshBtn').addEventListener('click', () => refreshStatus().catch((err) => alert(err.message)));
    $('saveBtn').addEventListener('click', () => saveConfig().catch((err) => alert(err.message)));
    $('runBtn').addEventListener('click', () => runConfig().catch((err) => alert(err.message)));
    $('stopBtn').addEventListener('click', () => stopRun().catch((err) => alert(err.message)));
    (async function init() {
      await loadConfig();
      await refreshStatus();
      renderAll();
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


class AutoClickerApp:
    def __init__(self, config_path: Path) -> None:
        self.config_path = config_path
        self.log = EventLog(DEFAULT_LOG_PATH)
        self.adb = AdbClient(self.log)
        self.runner = Runner(self.adb, self.log)
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

    actions = config.get("actions")
    config["actions"] = actions if isinstance(actions, list) else []
    return config


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
                if parsed.path == "/api/logs.txt":
                    text_response(self, app.log.text(), filename="phone-autoclicker.log")
                    return
                if parsed.path == "/api/screenshot":
                    png_response(self, app.adb.screencap(app.load_config()))
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
