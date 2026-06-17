import json
import logging
import re
import shutil
import socket
import subprocess
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

from config import QueueUiConfig, load_queue_ui_config
from db import ChatDatabase, QueueJob


logger = logging.getLogger(__name__)

PHONE_SCREENSHOT_DIR = Path(__file__).resolve().parent / "data" / "phone_screenshots"
PHONE_SCREENSHOT_MAX_BYTES = 15 * 1024 * 1024


HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Message Queue Monitor</title>
  <style>
    :root {
      --bg: #f5f6f8;
      --surface: #ffffff;
      --surface-2: #eef1f4;
      --border: #d7dce2;
      --text: #20242a;
      --muted: #66707b;
      --blue: #1d5fd0;
      --green: #17803d;
      --amber: #9a6500;
      --red: #b42318;
      --purple: #7149a8;
      --shadow: 0 1px 2px rgba(20, 28, 38, 0.08);
    }

    * { box-sizing: border-box; }

    body {
      margin: 0;
      min-height: 100vh;
      background: var(--bg);
      color: var(--text);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      letter-spacing: 0;
    }

    button, input, select {
      font: inherit;
    }

    .shell {
      min-height: 100vh;
      display: grid;
      grid-template-rows: auto auto 1fr;
    }

    .topbar {
      height: 58px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      padding: 0 20px;
      background: #151922;
      color: #f9fafb;
      border-bottom: 1px solid #252b36;
    }

    .brand {
      display: flex;
      align-items: baseline;
      gap: 12px;
      min-width: 0;
    }

    .brand h1 {
      margin: 0;
      font-size: 18px;
      font-weight: 700;
      line-height: 1;
      white-space: nowrap;
    }

    .brand span {
      color: #aeb6c3;
      font-size: 12px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .toolbar {
      display: flex;
      align-items: center;
      gap: 8px;
      min-width: 0;
    }

    .control {
      height: 34px;
      border: 1px solid #323948;
      background: #202634;
      color: #f9fafb;
      border-radius: 6px;
      padding: 0 10px;
      min-width: 0;
    }

    .button {
      height: 34px;
      min-width: 38px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      border: 1px solid #394252;
      background: #263040;
      color: #f9fafb;
      border-radius: 6px;
      cursor: pointer;
    }

    .button:hover {
      background: #30394b;
    }

    .checkbox {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      height: 34px;
      padding: 0 10px;
      color: #d8dde6;
      font-size: 13px;
      white-space: nowrap;
    }

    .live-status {
      height: 34px;
      display: inline-flex;
      align-items: center;
      max-width: 280px;
      padding: 0 10px;
      border: 1px solid #323948;
      background: #1b2130;
      color: #b8c0cc;
      border-radius: 6px;
      font-size: 12px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .stats {
      display: grid;
      grid-template-columns: repeat(8, minmax(110px, 1fr));
      gap: 1px;
      background: var(--border);
      border-bottom: 1px solid var(--border);
    }

    .stat {
      min-height: 70px;
      padding: 12px 16px;
      background: var(--surface);
      display: flex;
      flex-direction: column;
      justify-content: center;
      gap: 5px;
    }

    .stat .label {
      color: var(--muted);
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0;
    }

    .stat .value {
      font-size: 22px;
      font-weight: 700;
      line-height: 1;
    }

    .main {
      min-height: 0;
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(340px, 420px);
      gap: 0;
    }

    .table-wrap {
      min-height: 0;
      overflow: auto;
      border-right: 1px solid var(--border);
      background: var(--surface);
    }

    table {
      width: 100%;
      border-collapse: collapse;
      table-layout: fixed;
      font-size: 13px;
    }

    thead th {
      position: sticky;
      top: 0;
      z-index: 1;
      height: 38px;
      padding: 0 10px;
      background: #e8ebef;
      border-bottom: 1px solid var(--border);
      color: #3a414b;
      text-align: left;
      font-weight: 700;
      white-space: nowrap;
    }

    tbody td {
      height: 44px;
      padding: 7px 10px;
      border-bottom: 1px solid #edf0f3;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      vertical-align: middle;
    }

    tbody tr {
      cursor: pointer;
    }

    tbody tr:hover {
      background: #f7f9fb;
    }

    tbody tr.selected {
      background: #edf4ff;
      box-shadow: inset 3px 0 0 var(--blue);
    }

    .col-id { width: 76px; }
    .col-status { width: 118px; }
    .col-priority { width: 82px; }
    .col-room { width: 170px; }
    .col-attempts { width: 96px; }
    .col-created { width: 152px; }
    .col-message { width: auto; }

    .badge {
      display: inline-flex;
      align-items: center;
      height: 24px;
      max-width: 100%;
      padding: 0 8px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 700;
      border: 1px solid transparent;
      text-transform: uppercase;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .pending { color: var(--amber); background: #fff7e6; border-color: #f3d18b; }
    .processing { color: var(--blue); background: #eef5ff; border-color: #a9c8ff; }
    .done { color: var(--green); background: #eaf7ee; border-color: #a8dfba; }
    .dead, .failed { color: var(--red); background: #fff0ee; border-color: #f5b6ad; }
    .filtered { color: var(--muted); background: #eef1f4; border-color: #c8d0d9; }
    .system { color: var(--purple); background: #f4effc; border-color: #d7c4f3; }

    .detail {
      min-height: 0;
      overflow: auto;
      background: #fbfcfd;
      padding: 16px;
    }

    .detail h2 {
      margin: 0 0 12px;
      font-size: 16px;
      line-height: 1.2;
    }

    .kv {
      display: grid;
      grid-template-columns: 112px minmax(0, 1fr);
      gap: 8px 10px;
      padding: 12px 0;
      border-top: 1px solid var(--border);
      font-size: 13px;
    }

    .kv .key {
      color: var(--muted);
    }

    .kv .value {
      min-width: 0;
      overflow-wrap: anywhere;
    }

    .message-box, pre {
      width: 100%;
      margin: 8px 0 0;
      padding: 12px;
      border: 1px solid var(--border);
      border-radius: 8px;
      background: var(--surface);
      box-shadow: var(--shadow);
      color: var(--text);
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      font-size: 13px;
      line-height: 1.45;
    }

    .detail-actions {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin: 0 0 12px;
    }

    .detail-actions .button {
      width: auto;
      min-width: 120px;
      padding: 0 12px;
      background: var(--blue);
      border-color: #3170df;
    }

    .detail-actions .button.secondary {
      background: #fff;
      color: var(--text);
      border-color: var(--border);
    }

    .context-menu {
      position: fixed;
      z-index: 50;
      min-width: 210px;
      display: none;
      padding: 6px;
      border: 1px solid var(--border);
      border-radius: 8px;
      background: #fff;
      box-shadow: 0 12px 32px rgba(20,28,38,.22);
    }

    .context-menu.open { display: block; }

    .context-menu button {
      width: 100%;
      min-height: 34px;
      display: block;
      border: 0;
      border-radius: 6px;
      background: #fff;
      color: var(--text);
      text-align: left;
      padding: 0 10px;
      cursor: pointer;
    }

    .context-menu button:hover { background: #eef5ff; }

    .context-menu .muted-line {
      padding: 6px 10px;
      color: var(--muted);
      font-size: 12px;
      border-top: 1px solid #edf0f3;
      margin-top: 4px;
    }

    .empty {
      padding: 28px;
      color: var(--muted);
      text-align: center;
    }

    .muted {
      color: var(--muted);
    }

    @media (max-width: 960px) {
      .topbar {
        height: auto;
        min-height: 58px;
        align-items: flex-start;
        flex-direction: column;
        padding: 12px;
      }

      .toolbar {
        width: 100%;
        flex-wrap: wrap;
      }

      .control {
        flex: 1 1 130px;
      }

      .stats {
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }

      .main {
        grid-template-columns: 1fr;
      }

      .table-wrap {
        max-height: 55vh;
        border-right: 0;
        border-bottom: 1px solid var(--border);
      }

      .detail {
        max-height: none;
      }
    }
  </style>
</head>
<body>
  <div class="shell">
    <header class="topbar">
      <div class="brand">
        <h1>Queue Monitor</h1>
        <span id="dbPath"></span>
      </div>
      <div class="toolbar">
        <select id="statusFilter" class="control" aria-label="Status">
          <option value="">All status</option>
          <option value="pending">Pending</option>
          <option value="processing">Processing</option>
          <option value="done">Done</option>
          <option value="dead,failed">Dead/Failed</option>
        </select>
        <select id="limitFilter" class="control" aria-label="Limit">
          <option value="25">25</option>
          <option value="50">50</option>
          <option value="100" selected>100</option>
          <option value="200">200</option>
        </select>
        <label class="checkbox"><input id="autoRefresh" type="checkbox" checked> Auto</label>
        <button id="reloadBtn" class="button" title="Reload" aria-label="Reload">R</button>
        <button id="filtersBtn" class="button" title="Filters" aria-label="Filters">Filters</button>
        <button id="phoneBtn" class="button" title="Phone Monitor" aria-label="Phone Monitor">Phone</button>
        <button id="nextPhoneBtn" class="button primary" title="Send newest pending job to phone" aria-label="Next queue message">Next queue message</button>
        <span id="liveStatus" class="live-status">Starting...</span>
      </div>
    </header>

    <section class="stats" id="stats"></section>

    <main class="main">
      <section class="table-wrap">
        <table>
          <thead>
            <tr>
              <th class="col-id">ID</th>
              <th class="col-status">Status</th>
              <th class="col-priority">Priority</th>
              <th class="col-room">Room</th>
              <th class="col-attempts">Attempts</th>
              <th class="col-created">Created</th>
              <th class="col-message">Message</th>
            </tr>
          </thead>
          <tbody id="queueRows"></tbody>
        </table>
        <div id="emptyState" class="empty" hidden>No queue items</div>
      </section>

      <aside class="detail" id="detail">
        <h2>Job Detail</h2>
        <div class="muted">No row selected</div>
      </aside>
    </main>
    <div id="contextMenu" class="context-menu" role="menu">
      <button id="ctxOpenPhoneBtn">Open link on phone</button>
      <button id="ctxOpenAdbBtn">Run with USB/ADB</button>
      <button id="ctxPhonePageBtn">Phone Monitor</button>
      <div id="ctxHint" class="muted-line">Right-click a queue row</div>
    </div>
  </div>

  <script>
    const state = {
      items: [],
      selectedId: null,
      timer: null,
      refreshSeconds: 1,
      controller: null
    };

    const els = {
      dbPath: document.getElementById('dbPath'),
      stats: document.getElementById('stats'),
      rows: document.getElementById('queueRows'),
      detail: document.getElementById('detail'),
      empty: document.getElementById('emptyState'),
      status: document.getElementById('statusFilter'),
      limit: document.getElementById('limitFilter'),
      auto: document.getElementById('autoRefresh'),
      reload: document.getElementById('reloadBtn'),
      liveStatus: document.getElementById('liveStatus'),
      contextMenu: document.getElementById('contextMenu'),
      ctxHint: document.getElementById('ctxHint')
    };

    function esc(value) {
      return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
    }

    function timeText(value) {
      if (!value) return '';
      return new Date(value * 1000).toLocaleString();
    }

    function shortText(value, size = 140) {
      const text = String(value ?? '').replace(/\s+/g, ' ').trim();
      return text.length > size ? text.slice(0, size - 3) + '...' : text;
    }

    function badge(status) {
      return `<span class="badge ${esc(status)}">${esc(status)}</span>`;
    }

    async function loadQueue() {
      if (state.controller) state.controller.abort();
      state.controller = new AbortController();

      const params = new URLSearchParams();
      params.set('limit', els.limit.value);
      params.set('_', String(Date.now()));
      if (els.status.value) params.set('statuses', els.status.value);

      const res = await fetch('/api/queue?' + params.toString(), {
        cache: 'no-store',
        signal: state.controller.signal
      });
      if (!res.ok) throw new Error('HTTP ' + res.status);
      const data = await res.json();
      state.items = data.items || [];
      state.refreshSeconds = data.refresh_seconds || 2;
      if (data.limit && String(data.limit) !== els.limit.value) {
        els.limit.value = String(data.limit);
      }
      els.dbPath.textContent = data.db_path || '';
      renderStats(data.stats || {}, data);
      renderRows();
      renderDetail();
      renderLiveStatus(data);
    }

    function renderStats(stats, data) {
      const order = ['pending', 'processing', 'done', 'dead', 'failed', 'total', 'latest', 'refresh'];
      const total = Object.values(stats).reduce((sum, value) => sum + Number(value || 0), 0);
      const latest = data.latest_id || state.items[0]?.id || 0;
      const merged = {...stats, total, latest, refresh: `${state.refreshSeconds}s`};
      els.stats.innerHTML = order.map((key) => `
        <div class="stat">
          <div class="label">${esc(key)}</div>
          <div class="value">${key === 'refresh' ? esc(merged[key]) : Number(merged[key] || 0).toLocaleString()}</div>
        </div>
      `).join('');
    }

    function renderLiveStatus(data) {
      const generated = data.generated_at ? new Date(data.generated_at) : new Date();
      const latest = data.latest_id || state.items[0]?.id || 0;
      els.liveStatus.textContent = `Updated ${generated.toLocaleTimeString()} | latest #${latest} | ${state.items.length} rows`;
    }

    function renderRows() {
      els.empty.hidden = state.items.length !== 0;
      els.rows.innerHTML = state.items.map((item) => {
        const selected = item.id === state.selectedId ? 'selected' : '';
        const room = item.room && (item.room.title || item.room.chat_id);
        return `
          <tr class="${selected}" data-id="${item.id}">
            <td class="col-id">#${item.id}</td>
            <td class="col-status">${badge(item.status)}</td>
            <td class="col-priority">${item.priority}</td>
            <td class="col-room" title="${esc(room)}">${esc(room)}</td>
            <td class="col-attempts">${item.attempts}/${item.max_attempts}</td>
            <td class="col-created">${esc(timeText(item.created_at))}</td>
            <td class="col-message" title="${esc(item.message?.text)}">${esc(shortText(item.message?.text))}</td>
          </tr>
        `;
      }).join('');

      els.rows.querySelectorAll('tr').forEach((row) => {
        row.addEventListener('click', () => {
          state.selectedId = Number(row.dataset.id);
          renderRows();
          renderDetail();
        });
        row.addEventListener('contextmenu', (event) => {
          event.preventDefault();
          state.selectedId = Number(row.dataset.id);
          renderRows();
          renderDetail();
          showContextMenu(event.clientX, event.clientY);
        });
      });

      if (state.selectedId && !state.items.some((item) => item.id === state.selectedId)) {
        state.selectedId = state.items[0]?.id || null;
      }
    }

    function findLink(item) {
      const payload = item?.payload || {};
      const message = item?.message || {};
      const candidates = [
        payload.url, payload.link, payload.deeplink, payload.deep_link, payload.live_url, payload.room_url,
        message.text
      ];
      for (const value of candidates) {
        const text = String(value || '');
        const match = text.match(/(?:https?:\/\/|tiktok:\/\/)[^\s<>'\"]+/i);
        if (match) return match[0];
      }
      return '';
    }

    function parseTimeDelayMs(value) {
      const text = String(value || '').trim();
      if (!text) return 0;
      let match = text.match(/(\d{1,2}):(\d{2})\s*s?/i);
      if (match) return (Number(match[1]) * 60 + Number(match[2])) * 1000;
      match = text.match(/(\d+(?:\.\d+)?)\s*s/i);
      if (match) return Math.round(Number(match[1]) * 1000);
      return 0;
    }

    function findTimeMeta(item) {
      const payload = item?.payload || {};
      const message = item?.message || {};
      const candidates = [payload.TIME, payload.time, payload.Time, payload.click_time, payload.open_time, message.text];
      for (const value of candidates) {
        const text = String(value || '');
        const match = text.match(/TIME\s*[:：]\s*([^\n\r]+)/i) || text.match(/(\d{1,2}:\d{2}\s*s?\s*-\s*\d{1,2}:\d{2}:\d{2})/i) || text.match(/(\d{1,2}:\d{2}\s*s?)/i);
        if (match) {
          const label = match[1].trim();
          return { label, click_after_ms: parseTimeDelayMs(label) };
        }
      }
      return { label:'', click_after_ms:0 };
    }

    function phoneClickPoint() {
      return {
        x: Number(localStorage.getItem('phoneClickX') || 540),
        y: Number(localStorage.getItem('phoneClickY') || 1800)
      };
    }

    async function sendNewestToPhone() {
      if (!state.items.length) await loadQueue();
      const pending = state.items.filter((item) => item.status === 'pending').sort((a,b) => Number(b.id || 0) - Number(a.id || 0));
      const item = pending[0];
      if (!item) {
        els.liveStatus.textContent = 'No pending queue message';
        return;
      }
      state.selectedId = item.id;
      renderRows();
      renderDetail();
      await sendSelectedToPhone();
      els.liveStatus.textContent = `Sent newest pending job #${item.id} to phone`;
    }

    async function sendSelectedToPhone() {
      const item = state.items.find((value) => value.id === state.selectedId);
      if (!item) return;
      const link = findLink(item);
      if (!link) {
        els.liveStatus.textContent = `Job #${item.id} has no link/deeplink`;
        return;
      }
      const base = (localStorage.getItem('phoneMonitorBaseUrl') || '').replace(/\/$/, '');
      if (!base) {
        localStorage.setItem('pendingQueueLink', link);
        localStorage.setItem('pendingQueueJobId', String(item.id));
        const timeMeta = findTimeMeta(item);
        localStorage.setItem('pendingQueueTime', timeMeta.label);
        localStorage.setItem('pendingQueueClickAfterMs', String(timeMeta.click_after_ms));
        window.location.href = '/phone-monitor';
        return;
      }
      const point = phoneClickPoint();
      const timeMeta = findTimeMeta(item);
      const body = new URLSearchParams({ url: link, source: 'queue', queue_id: String(item.id), time: timeMeta.label, click_after_ms: String(timeMeta.click_after_ms), click_x: String(point.x), click_y: String(point.y) });
      const res = await fetch(base + '/actions/deeplink', { method:'POST', headers:{'Content-Type':'application/x-www-form-urlencoded'}, body });
      const text = await res.text();
      if (!res.ok) throw new Error(text || `HTTP ${res.status}`);
      els.liveStatus.textContent = `Sent job #${item.id} link to phone`;
    }

    async function sendSelectedToAdb() {
      const item = state.items.find((value) => value.id === state.selectedId);
      if (!item) return;
      const link = findLink(item);
      if (!link) {
        els.liveStatus.textContent = `Job #${item.id} has no link/deeplink`;
        return;
      }
      const timeMeta = findTimeMeta(item);
      const point = phoneClickPoint();
      const res = await fetch('/api/phone/adb-open', {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({ url:link, queue_id:item.id, click_after_ms:timeMeta.click_after_ms, click_x:point.x, click_y:point.y })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
      els.liveStatus.textContent = `ADB opened job #${item.id} on ${data.device || 'phone'}`;
    }

    function showContextMenu(x, y) {
      const item = state.items.find((value) => value.id === state.selectedId);
      const link = findLink(item);
      els.ctxHint.textContent = item ? `Job #${item.id}${link ? '' : ' | no link detected'}` : 'No job selected';
      els.contextMenu.style.left = `${Math.min(x, window.innerWidth - 230)}px`;
      els.contextMenu.style.top = `${Math.min(y, window.innerHeight - 150)}px`;
      els.contextMenu.classList.add('open');
    }

    function hideContextMenu() {
      els.contextMenu.classList.remove('open');
    }

    function renderDetail() {
      const item = state.items.find((value) => value.id === state.selectedId);
      if (!item) {
        els.detail.innerHTML = '<h2>Job Detail</h2><div class="muted">No row selected</div>';
        return;
      }

      const room = item.room || {};
      const user = item.user || {};
      const message = item.message || {};
      const link = findLink(item);
      const timeMeta = findTimeMeta(item);
      els.detail.innerHTML = `
        <h2>Job #${item.id}</h2>
        <div class="detail-actions">
          <button id="sendPhoneBtn" class="button" ${link ? '' : 'disabled'}>Open on phone</button>
          <button id="phonePageBtn" class="button secondary">Phone Monitor</button>
        </div>
        <div class="kv">
          <div class="key">Link</div><div class="value">${link ? `<a href="${esc(link)}" target="_blank" rel="noopener">${esc(link)}</a>` : '<span class="muted">No link detected</span>'}</div>
          <div class="key">TIME</div><div class="value">${timeMeta.label ? `${esc(timeMeta.label)} | click after ${(timeMeta.click_after_ms / 1000).toFixed(0)}s` : '<span class="muted">No TIME detected</span>'}</div>
          <div class="key">Status</div><div class="value">${badge(item.status)} ${item.lease_expired ? '<span class="badge dead">expired</span>' : ''}</div>
          <div class="key">Priority</div><div class="value">${item.priority}</div>
          <div class="key">Attempts</div><div class="value">${item.attempts}/${item.max_attempts}</div>
          <div class="key">Locked By</div><div class="value">${esc(item.locked_by || '')}</div>
          <div class="key">Created</div><div class="value">${esc(timeText(item.created_at))}</div>
          <div class="key">Updated</div><div class="value">${esc(timeText(item.updated_at))}</div>
          <div class="key">Available</div><div class="value">${esc(timeText(item.available_at))}</div>
        </div>
        <div class="kv">
          <div class="key">Room</div><div class="value">${esc(room.title || room.chat_id || '')}</div>
          <div class="key">Platform</div><div class="value">${esc(room.platform || '')}</div>
          <div class="key">Chat ID</div><div class="value">${esc(room.chat_id || '')}</div>
          <div class="key">User</div><div class="value">${esc(user.username || user.platform_user_id || '')}</div>
          <div class="key">Message ID</div><div class="value">${esc(message.platform_message_id || message.id || '')}</div>
        </div>
        <div class="kv">
          <div class="key">Message</div>
          <div class="value"><div class="message-box">${esc(message.text || '')}</div></div>
          <div class="key">Payload</div>
          <div class="value"><pre>${esc(JSON.stringify(item.payload || {}, null, 2))}</pre></div>
          <div class="key">Error</div>
          <div class="value">${esc(item.last_error || '')}</div>
        </div>
      `;
      document.getElementById('sendPhoneBtn')?.addEventListener('click', () => sendSelectedToPhone().catch((err) => { els.liveStatus.textContent = `Phone error: ${err.message}`; }));
      document.getElementById('phonePageBtn')?.addEventListener('click', () => { window.location.href = '/phone-monitor'; });
    }

    function bindContextMenu() {
      document.getElementById('ctxOpenPhoneBtn').addEventListener('click', () => {
        hideContextMenu();
        sendSelectedToPhone().catch((err) => { els.liveStatus.textContent = `Phone error: ${err.message}`; });
      });
      document.getElementById('ctxOpenAdbBtn').addEventListener('click', () => {
        hideContextMenu();
        sendSelectedToAdb().catch((err) => { els.liveStatus.textContent = `ADB error: ${err.message}`; });
      });
      document.getElementById('ctxPhonePageBtn').addEventListener('click', () => { window.location.href = '/phone-monitor'; });
      document.addEventListener('click', hideContextMenu);
      window.addEventListener('blur', hideContextMenu);
      window.addEventListener('resize', hideContextMenu);
    }

    function schedule() {
      clearInterval(state.timer);
      if (els.auto.checked) {
        state.timer = setInterval(() => {
          loadQueue().catch((err) => {
            if (err.name !== 'AbortError') {
              els.liveStatus.textContent = `Error: ${err.message}`;
            }
          });
        }, state.refreshSeconds * 1000);
      }
    }

    els.reload.addEventListener('click', () => loadQueue().catch((err) => {
      if (err.name !== 'AbortError') {
        els.liveStatus.textContent = `Error: ${err.message}`;
      }
    }));
    document.getElementById('filtersBtn').addEventListener('click', () => {
      window.location.href = '/filters';
    });
    document.getElementById('phoneBtn').addEventListener('click', () => {
      window.location.href = '/phone-monitor';
    });
    document.getElementById('nextPhoneBtn').addEventListener('click', () => {
      sendNewestToPhone().catch((err) => { els.liveStatus.textContent = `Next error: ${err.message}`; });
    });
    els.auto.addEventListener('change', schedule);
    els.status.addEventListener('change', loadQueue);
    els.limit.addEventListener('change', loadQueue);

    bindContextMenu();
    loadQueue().then(schedule).catch((err) => {
      els.detail.innerHTML = `<h2>Job Detail</h2><div class="message-box">${esc(err.message)}</div>`;
    });
  </script>
</body>
</html>
"""


FILTERS_HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Message Filters</title>
  <style>
    :root { --bg:#f5f6f8; --surface:#fff; --border:#d7dce2; --text:#20242a; --muted:#66707b; --blue:#1d5fd0; --green:#17803d; --red:#b42318; }
    * { box-sizing: border-box; }
    body { margin:0; min-height:100vh; background:var(--bg); color:var(--text); font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; letter-spacing:0; }
    button,input,textarea { font:inherit; }
    .shell { min-height:100vh; display:grid; grid-template-rows:auto 1fr; }
    .topbar { min-height:58px; display:flex; align-items:center; justify-content:space-between; gap:16px; padding:0 20px; background:#151922; color:#f9fafb; border-bottom:1px solid #252b36; }
    .brand { display:flex; align-items:baseline; gap:12px; min-width:0; }
    h1 { margin:0; font-size:18px; line-height:1; }
    .brand span { color:#aeb6c3; font-size:12px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
    .toolbar { display:flex; align-items:center; gap:8px; flex-wrap:wrap; }
    .button { height:34px; min-width:38px; display:inline-flex; align-items:center; justify-content:center; border:1px solid #394252; background:#263040; color:#f9fafb; border-radius:6px; padding:0 12px; cursor:pointer; }
    .button:hover { background:#30394b; }
    .button.primary { background:var(--blue); border-color:#3170df; }
    .button.danger { background:#4a2530; border-color:#6d3342; }
    .main { min-height:0; display:grid; grid-template-columns:340px minmax(0,1fr); background:var(--surface); }
    .list-pane { min-height:0; overflow:auto; border-right:1px solid var(--border); background:#fbfcfd; }
    .list-head { position:sticky; top:0; z-index:1; display:flex; gap:8px; padding:12px; border-bottom:1px solid var(--border); background:#eef1f4; }
    .filter-list { margin:0; padding:0; list-style:none; }
    .filter-row { display:grid; grid-template-columns:minmax(0,1fr) auto; gap:8px; padding:12px; border-bottom:1px solid #edf0f3; cursor:pointer; }
    .filter-row:hover { background:#f7f9fb; }
    .filter-row.selected { background:#edf4ff; box-shadow:inset 3px 0 0 var(--blue); }
    .filter-name { min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-weight:700; font-size:13px; }
    .filter-meta { margin-top:4px; color:var(--muted); font-size:12px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
    .pill { display:inline-flex; align-items:center; height:22px; padding:0 8px; border-radius:999px; border:1px solid #c8d0d9; color:#3a414b; background:#eef1f4; font-size:12px; font-weight:700; white-space:nowrap; }
    .pill.on { color:var(--green); background:#eaf7ee; border-color:#a8dfba; }
    .pill.off { color:var(--red); background:#fff0ee; border-color:#f5b6ad; }
    .editor { min-height:0; overflow:auto; padding:18px; background:var(--surface); }
    .editor-head { display:flex; align-items:center; justify-content:space-between; gap:12px; margin-bottom:16px; }
    .editor-head h2 { margin:0; font-size:18px; line-height:1.2; }
    .form-grid { display:grid; grid-template-columns:repeat(4,minmax(120px,1fr)); gap:14px; }
    .field { min-width:0; display:flex; flex-direction:column; gap:6px; }
    .field.wide { grid-column:span 2; }
    .field.full { grid-column:1 / -1; }
    label { color:var(--muted); font-size:12px; font-weight:700; text-transform:uppercase; }
    input,textarea { width:100%; min-width:0; border:1px solid var(--border); border-radius:6px; background:#fff; color:var(--text); padding:9px 10px; }
    textarea { min-height:80px; resize:vertical; line-height:1.4; }
    .checkline { height:40px; display:inline-flex; align-items:center; gap:8px; color:var(--text); font-size:13px; text-transform:none; }
    .combo { position:relative; min-width:0; }
    .combo-button { width:100%; min-height:40px; display:flex; align-items:center; justify-content:space-between; gap:8px; border:1px solid var(--border); border-radius:6px; background:#fff; color:var(--text); padding:8px 10px; cursor:pointer; text-align:left; }
    .combo-button:disabled { color:#98a2ae; background:#f3f5f7; cursor:default; }
    .combo-summary { min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
    .combo-caret { color:var(--muted); font-size:12px; }
    .combo-menu { display:none; position:absolute; left:0; right:0; top:calc(100% + 4px); z-index:10; border:1px solid var(--border); border-radius:6px; background:#fff; box-shadow:0 8px 24px rgba(20,28,38,.16); overflow:hidden; }
    .combo.open .combo-menu { display:block; }
    .combo-search { border:0; border-bottom:1px solid var(--border); border-radius:0; }
    .country-list { max-height:280px; overflow:auto; padding:4px 0; }
    .country-row { min-height:34px; display:flex; align-items:center; gap:8px; padding:7px 10px; cursor:pointer; font-size:13px; }
    .country-row:hover { background:#f7f9fb; }
    .country-row input { width:auto; min-width:16px; margin:0; }
    .country-code { min-width:58px; font-weight:700; color:#303844; }
    .country-name { min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; color:#3a414b; }
    .country-empty { padding:12px 10px; color:var(--muted); font-size:13px; }
    .status { min-height:34px; display:flex; align-items:center; padding:0 10px; border:1px solid var(--border); border-radius:6px; color:var(--muted); background:#fbfcfd; font-size:13px; }
    .hint { color:var(--muted); font-size:12px; line-height:1.45; margin-top:6px; }
    .sample { grid-column:1 / -1; border:1px solid var(--border); border-radius:6px; background:#111827; color:#d1d5db; padding:12px; white-space:pre-wrap; font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace; font-size:12px; line-height:1.45; }
    @media (max-width:920px) { .topbar{align-items:flex-start; flex-direction:column; padding:12px;} .main{grid-template-columns:1fr;} .list-pane{max-height:40vh; border-right:0; border-bottom:1px solid var(--border);} .form-grid{grid-template-columns:repeat(2,minmax(0,1fr));} .field.wide{grid-column:1 / -1;} }
  </style>
</head>
<body>
  <div class="shell">
    <header class="topbar">
      <div class="brand"><h1>Filters</h1><span id="filterPath"></span></div>
      <div class="toolbar">
        <button id="queueBtn" class="button">Queue</button>
        <button id="reloadBtn" class="button">Reload</button>
        <button id="saveBtn" class="button primary">Save</button>
      </div>
    </header>
    <main class="main">
      <section class="list-pane">
        <div class="list-head">
          <button id="addBtn" class="button primary">Add</button>
          <button id="copyBtn" class="button">Duplicate</button>
          <button id="deleteBtn" class="button danger">Delete</button>
        </div>
        <ul id="filterList" class="filter-list"></ul>
      </section>
      <section class="editor">
        <div class="editor-head"><h2 id="editorTitle">Filter</h2><div id="status" class="status">Ready</div></div>
        <div class="form-grid">
          <div class="field wide"><label for="nameInput">Name</label><input id="nameInput" autocomplete="off"></div>
          <div class="field"><label for="priorityInput">Priority</label><input id="priorityInput" type="number" min="0" step="1"></div>
          <div class="field"><label class="checkline"><input id="enabledInput" type="checkbox"> Enabled</label></div>
          <div class="field wide"><label for="boxesInput">BOX Min</label><input id="boxesInput" autocomplete="off" placeholder="100/25"><div class="hint">Nhập 100/25 nghĩa là lấy BOX có giá trị 1 &gt;= 100 và giá trị 2 &gt;= 25.</div></div>
          <div class="field wide">
            <label for="countryComboButton">Countries</label>
            <div id="countryCombo" class="combo">
              <button id="countryComboButton" class="combo-button" type="button" aria-haspopup="listbox" aria-expanded="false">
                <span id="countriesSummary" class="combo-summary">Any country</span>
                <span class="combo-caret">v</span>
              </button>
              <div id="countryMenu" class="combo-menu">
                <input id="countrySearchInput" class="combo-search" autocomplete="off" placeholder="Search country or code">
                <label class="country-row"><input id="allCountriesInput" type="checkbox"><span class="country-code">ALL</span><span class="country-name">Tất cả quốc gia</span></label>
                <div id="countryList" class="country-list" role="listbox" aria-multiselectable="true"></div>
              </div>
            </div>
          </div>
          <div class="field wide"><label for="badgesInput">Badges</label><input id="badgesInput" autocomplete="off" placeholder="💎,🏅"></div>
          <div class="field"><label for="minRateInput">Min Rate</label><input id="minRateInput" type="number" min="0" step="0.01"><div class="hint">Lấy Rate &gt;= giá trị nhập.</div></div>
          <div class="field"><label for="minViewsInput">Min Views</label><input id="minViewsInput" type="number" min="0" step="1"><div class="hint">Lấy Views &gt;= giá trị nhập.</div></div>
          <div class="field wide"><label for="noteInput">Note Contains</label><textarea id="noteInput" placeholder='"Rương treo", "ABC", "CDE"'></textarea><div class="hint">Có thể nhập nhiều từ khoá: "ABC", "CDE". So sánh không phân biệt hoa/thường.</div></div>
          <div class="sample">Mẫu tin nhắn:
🎁 BOX: 100/25 💎 🏅 🇰🇷
📈 Rate : 5.5
👀 12
📝 Rương treo ít view

Form trên sẽ hiểu: BOX value 1 = 100, BOX value 2 = 25, country = KR, badges = 💎 🏅, rate = 5.5, views = 12, note = Rương treo ít view.</div>
        </div>
      </section>
    </main>
  </div>
  <script>
    const state = { filters: [], selected: 0, path: '' };
    const $ = (id) => document.getElementById(id);
    const els = { path:$('filterPath'), list:$('filterList'), status:$('status'), title:$('editorTitle'), name:$('nameInput'), priority:$('priorityInput'), enabled:$('enabledInput'), boxes:$('boxesInput'), countryCombo:$('countryCombo'), countryButton:$('countryComboButton'), countrySummary:$('countriesSummary'), countrySearch:$('countrySearchInput'), countryList:$('countryList'), badges:$('badgesInput'), minRate:$('minRateInput'), minViews:$('minViewsInput'), note:$('noteInput'), allCountries:$('allCountriesInput') };
    const COUNTRY_CODES = 'AD AE AF AG AI AL AM AO AQ AR AS AT AU AW AX AZ BA BB BD BE BF BG BH BI BJ BL BM BN BO BQ BR BS BT BV BW BY BZ CA CC CD CF CG CH CI CK CL CM CN CO CR CU CV CW CX CY CZ DE DJ DK DM DO DZ EC EE EG EH ER ES ET FI FJ FK FM FO FR GA GB GD GE GF GG GH GI GL GM GN GP GQ GR GS GT GU GW GY HK HM HN HR HT HU ID IE IL IM IN IO IQ IR IS IT JE JM JO JP KE KG KH KI KM KN KP KR KW KY KZ LA LB LC LI LK LR LS LT LU LV LY MA MC MD ME MF MG MH MK ML MM MN MO MP MQ MR MS MT MU MV MW MX MY MZ NA NC NE NF NG NI NL NO NP NR NU NZ OM PA PE PF PG PH PK PL PM PN PR PS PT PW PY QA RE RO RS RU RW SA SB SC SD SE SG SH SI SJ SK SL SM SN SO SR SS ST SV SX SY SZ TC TD TF TG TH TJ TK TL TM TN TO TR TT TV TW TZ UA UG UM US UY UZ VA VC VE VG VI VN VU WF WS XK YE YT ZA ZM ZW'.split(' ');
    const regionNames = typeof Intl !== 'undefined' && Intl.DisplayNames ? new Intl.DisplayNames([navigator.language || 'en'], { type:'region' }) : null;
    const COUNTRY_OPTIONS = COUNTRY_CODES.map((code) => ({ code, name: countryName(code), flag: flagFromCode(code) })).sort((a,b) => a.name.localeCompare(b.name) || a.code.localeCompare(b.code));
    const COUNTRY_ORDER = new Map(COUNTRY_OPTIONS.map((item,index) => [item.code, index]));
    function esc(value) { return String(value ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#039;'); }
    function toCsv(value) { return Array.isArray(value) ? value.join(',') : String(value ?? ''); }
    function cleanKeyword(value) { return String(value || '').trim().replace(/^[\'\"]+|[\'\"]+$/g, '').trim(); }
    function fromCsv(value) { return String(value || '').split(',').map(cleanKeyword).filter(Boolean); }
    function parseBoxMin(value) {
      const text = String(value || '').trim();
      if (!text) return null;
      const match = text.match(/^(\d+)\s*\/\s*(\d+)$/);
      return match ? { left:Number(match[1]), right:Number(match[2]), label:`${match[1]}/${match[2]}` } : null;
    }
    function optionalNumber(value) { return value === '' ? undefined : Number(value); }
    function optionalText(value) { const text = String(value || '').trim(); return text ? text : undefined; }
    function countryName(code) { try { return regionNames?.of(code) || code; } catch { return code; } }
    function flagFromCode(code) { return /^[A-Z]{2}$/.test(code) ? String.fromCodePoint(...code.split('').map((char) => 127397 + char.charCodeAt(0))) : ''; }
    function normalizeCountries(value) {
      const seen = new Set();
      const values = Array.isArray(value) ? value : fromCsv(value);
      return values.map((item) => String(item).trim().toUpperCase()).filter((code) => /^[A-Z]{2}$/.test(code) && !seen.has(code) && seen.add(code));
    }
    function sortCountries(value) {
      return normalizeCountries(value).sort((a,b) => (COUNTRY_ORDER.get(a) ?? 9999) - (COUNTRY_ORDER.get(b) ?? 9999) || a.localeCompare(b));
    }
    function currentFilter() { return state.filters[state.selected] || null; }
    function compactFilter(filter) {
      ['priority','min_box1','max_box1','min_box2','max_box2','min_rate','max_rate','min_views','max_views','text_regex'].forEach((key) => { if (filter[key] === undefined || filter[key] === null || filter[key] === '') delete filter[key]; });
      ['boxes','countries','badges','note_contains','text_contains'].forEach((key) => { if (!Array.isArray(filter[key]) || filter[key].length === 0) delete filter[key]; });
    }
    function syncFormToFilter() {
      const filter = currentFilter(); if (!filter) return;
      filter.name = els.name.value.trim() || `filter_${state.selected + 1}`;
      filter.enabled = els.enabled.checked;
      filter.priority = optionalNumber(els.priority.value);
      const boxMin = parseBoxMin(els.boxes.value);
      filter.boxes = [];
      filter.min_box1 = boxMin ? boxMin.left : undefined;
      filter.min_box2 = boxMin ? boxMin.right : undefined;
      delete filter.max_box1;
      delete filter.max_box2;
      filter.countries = sortCountries(filter.countries);
      filter.badges = fromCsv(els.badges.value);
      filter.min_rate = optionalNumber(els.minRate.value);
      delete filter.max_rate;
      filter.min_views = optionalNumber(els.minViews.value);
      delete filter.max_views;
      filter.note_contains = fromCsv(els.note.value);
      filter.text_contains = [];
      filter.text_regex = undefined;
      compactFilter(filter);
    }
    function renderList() {
      els.list.innerHTML = state.filters.map((filter,index) => {
        const selected = index === state.selected ? 'selected' : '';
        const enabled = filter.enabled !== false;
        const boxMin = filter.min_box1 !== undefined || filter.min_box2 !== undefined ? `box>=${filter.min_box1 ?? 0}/${filter.min_box2 ?? 0}` : toCsv(filter.boxes);
        const meta = [boxMin, toCsv(filter.countries) || 'all countries', filter.min_rate !== undefined ? `rate>=${filter.min_rate}` : '', filter.min_views !== undefined ? `views>=${filter.min_views}` : '', filter.priority !== undefined ? `p${filter.priority}` : ''].filter(Boolean).join(' | ');
        return `<li class="filter-row ${selected}" data-index="${index}"><div><div class="filter-name">${esc(filter.name || `filter_${index + 1}`)}</div><div class="filter-meta">${esc(meta || 'empty')}</div></div><span class="pill ${enabled ? 'on' : 'off'}">${enabled ? 'on' : 'off'}</span></li>`;
      }).join('');
      els.list.querySelectorAll('.filter-row').forEach((row) => row.addEventListener('click', () => { syncFormToFilter(); state.selected = Number(row.dataset.index); render(); }));
    }
    function updateCountrySummary(filter) {
      if (!filter) {
        els.countrySummary.textContent = 'No filter selected';
        return;
      }
      const selected = sortCountries(filter.countries);
      if (!selected.length) {
        els.countrySummary.textContent = 'All countries';
        return;
      }
      const preview = selected.slice(0, 6).join(', ');
      els.countrySummary.textContent = selected.length > 6 ? `${preview} +${selected.length - 6}` : preview;
    }
    function renderCountryList(filter) {
      const selected = new Set(sortCountries(filter?.countries));
      const query = els.countrySearch.value.trim().toLowerCase();
      const options = COUNTRY_OPTIONS.filter((item) => !query || item.code.toLowerCase().includes(query) || item.name.toLowerCase().includes(query));
      if (!options.length) {
        els.countryList.innerHTML = '<div class="country-empty">No countries found</div>';
        return;
      }
      els.countryList.innerHTML = options.map((item) => {
        const checked = selected.has(item.code) ? 'checked' : '';
        return `<label class="country-row"><input type="checkbox" data-code="${esc(item.code)}" ${checked}><span class="country-code">${esc(item.flag)} ${esc(item.code)}</span><span class="country-name">${esc(item.name)}</span></label>`;
      }).join('');
    }
    function renderCountryCombo(filter) {
      const disabled = !filter;
      els.countryButton.disabled = disabled;
      els.countrySearch.disabled = disabled;
      els.countryCombo.classList.toggle('disabled', disabled);
      if (disabled) {
        els.countryCombo.classList.remove('open');
        els.countryButton.setAttribute('aria-expanded', 'false');
      }
      updateCountrySummary(filter);
      renderCountryList(filter);
      if (els.allCountries) els.allCountries.checked = !sortCountries(filter?.countries).length;
    }
    function renderForm() {
      const filter = currentFilter();
      document.querySelectorAll('input, textarea').forEach((node) => node.disabled = !filter);
      els.title.textContent = filter ? (filter.name || `Filter #${state.selected + 1}`) : 'Filter';
      els.name.value = filter?.name || ''; els.priority.value = filter?.priority ?? ''; els.enabled.checked = filter ? filter.enabled !== false : false;
      els.boxes.value = filter?.min_box1 !== undefined || filter?.min_box2 !== undefined ? `${filter.min_box1 ?? 0}/${filter.min_box2 ?? 0}` : (Array.isArray(filter?.boxes) ? (filter.boxes[0] || '') : String(filter?.boxes || '')); els.badges.value = toCsv(filter?.badges);
      els.minRate.value = filter?.min_rate ?? ''; els.minViews.value = filter?.min_views ?? '';
      els.note.value = toCsv(filter?.note_contains);
      renderCountryCombo(filter);
    }
    function render() { renderList(); renderForm(); }
    function newFilter() { return { name:`filter_${state.filters.length + 1}`, enabled:true, priority:100, min_box1:100, min_box2:25, countries:[], badges:[] }; }
    async function loadFilters() {
      const res = await fetch('/api/filters?_=' + Date.now(), { cache:'no-store' });
      const data = await res.json(); if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
      state.path = data.path || ''; state.filters = Array.isArray(data.filters) ? data.filters : [];
      state.selected = Math.min(state.selected, Math.max(0, state.filters.length - 1));
      els.path.textContent = state.path; els.status.textContent = `Loaded ${state.filters.length}`; render();
    }
    async function saveFilters() {
      syncFormToFilter();
      const res = await fetch('/api/filters', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({ filters:state.filters }) });
      const data = await res.json(); if (!res.ok) throw new Error(data.error || 'Save failed');
      state.filters = data.filters || []; state.selected = Math.min(state.selected, Math.max(0, state.filters.length - 1)); els.status.textContent = `Saved ${state.filters.length}`; render();
    }
    $('queueBtn').addEventListener('click', () => window.location.href = '/');
    $('reloadBtn').addEventListener('click', () => loadFilters().catch((err) => els.status.textContent = err.message));
    $('saveBtn').addEventListener('click', () => saveFilters().catch((err) => els.status.textContent = err.message));
    $('addBtn').addEventListener('click', () => { syncFormToFilter(); state.filters.push(newFilter()); state.selected = state.filters.length - 1; render(); els.status.textContent = 'Added'; });
    $('copyBtn').addEventListener('click', () => { syncFormToFilter(); const filter = currentFilter(); if (!filter) return; const copy = JSON.parse(JSON.stringify(filter)); copy.name = `${copy.name || 'filter'}_copy`; state.filters.splice(state.selected + 1, 0, copy); state.selected += 1; render(); els.status.textContent = 'Duplicated'; });
    $('deleteBtn').addEventListener('click', () => { if (!currentFilter()) return; state.filters.splice(state.selected, 1); state.selected = Math.min(state.selected, Math.max(0, state.filters.length - 1)); render(); els.status.textContent = 'Deleted'; });
    els.countryButton.addEventListener('click', () => {
      if (!currentFilter()) return;
      const open = !els.countryCombo.classList.contains('open');
      els.countryCombo.classList.toggle('open', open);
      els.countryButton.setAttribute('aria-expanded', open ? 'true' : 'false');
      if (open) { els.countrySearch.focus(); renderCountryList(currentFilter()); }
    });
    els.countrySearch.addEventListener('input', () => renderCountryList(currentFilter()));
    els.allCountries.addEventListener('change', () => { const filter = currentFilter(); if (!filter) return; if (els.allCountries.checked) filter.countries = []; updateCountrySummary(filter); renderCountryList(filter); renderList(); });
    els.countryList.addEventListener('change', (event) => {
      const checkbox = event.target.closest('input[type="checkbox"][data-code]');
      const filter = currentFilter();
      if (!checkbox || !filter) return;
      const selected = new Set(sortCountries(filter.countries));
      if (checkbox.checked) selected.add(checkbox.dataset.code);
      else selected.delete(checkbox.dataset.code);
      filter.countries = sortCountries([...selected]);
      compactFilter(filter);
      updateCountrySummary(filter);
      renderCountryList(filter);
      renderList();
    });
    document.addEventListener('click', (event) => {
      if (els.countryCombo.contains(event.target)) return;
      els.countryCombo.classList.remove('open');
      els.countryButton.setAttribute('aria-expanded', 'false');
    });
    document.querySelectorAll('input, textarea').forEach((node) => { node.addEventListener('input', () => { syncFormToFilter(); renderList(); els.title.textContent = currentFilter()?.name || 'Filter'; }); node.addEventListener('change', () => { syncFormToFilter(); renderList(); }); });
    loadFilters().catch((err) => els.status.textContent = err.message);
  </script>
</body>
</html>
"""

PHONE_MONITOR_HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Phone Monitor</title>
  <style>
    body { margin:0; background:#f5f6f8; color:#20242a; font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }
    .topbar { min-height:58px; display:flex; align-items:center; justify-content:space-between; gap:12px; padding:0 20px; background:#151922; color:#f9fafb; }
    h1 { margin:0; font-size:18px; }
    .button { min-height:34px; border:1px solid #394252; background:#263040; color:#f9fafb; border-radius:6px; padding:0 12px; cursor:pointer; }
    .main { max-width:980px; margin:0 auto; padding:18px; }
    .card { background:#fff; border:1px solid #d7dce2; border-radius:8px; padding:16px; margin-bottom:14px; }
    label { display:block; margin:10px 0 6px; color:#66707b; font-size:12px; font-weight:700; text-transform:uppercase; }
    input,textarea { width:100%; box-sizing:border-box; border:1px solid #d7dce2; border-radius:6px; padding:10px; font:inherit; }
    .row { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:10px; }
    .actions { display:flex; gap:8px; flex-wrap:wrap; margin-top:12px; }
    .light { background:#fff; color:#20242a; border-color:#d7dce2; }
    .primary { background:#1d5fd0; border-color:#3170df; }
    pre { min-height:220px; max-height:55vh; overflow:auto; background:#111827; color:#d1d5db; border-radius:8px; padding:12px; white-space:pre-wrap; }
    @media (max-width:720px){ .topbar{align-items:flex-start; flex-direction:column; padding:12px;} .row{grid-template-columns:1fr 1fr;} }
  </style>
</head>
<body>
  <header class="topbar"><h1>Phone Monitor</h1><button id="queueBtn" class="button">Queue</button></header>
  <main class="main">
    <section class="card">
      <h2>Connect Android app</h2>
      <p>Install APK from <code>phone_monitor_app</code>, enable Accessibility + Overlay, then enter the phone IP shown in the app. Default port is 8791.</p>
      <label>Phone base URL</label><input id="baseUrl" placeholder="http://192.168.1.23:8791">
      <div class="actions"><button id="saveBtn" class="button primary">Save URL</button><button id="logsBtn" class="button light">Load Logs</button><button id="openPendingBtn" class="button primary">Open pending queue link</button></div>
    </section>
    <section class="card">
      <h2>USB Type-C / ADB</h2>
      <p>Dùng khi điện thoại đang cắm dây Type-C và đã bật USB debugging. Có thể cài APK monitor hoặc mở deeplink trực tiếp qua ADB.</p>
      <label>ADB device</label><select id="adbDevice"><option value="">Auto select</option></select>
      <label>APK path</label><input id="apkPath" value="phone_monitor_app/app/build/outputs/apk/debug/app-debug.apk" placeholder="phone_monitor_app/app/build/outputs/apk/debug/app-debug.apk">
      <label>Default click point after TIME</label><div class="row"><input id="clickX" type="number" placeholder="click x" value="540"><input id="clickY" type="number" placeholder="click y" value="1800"><input id="clickDelay" type="number" placeholder="manual delay ms"><button id="saveClickPointBtn" class="button light">Save click point</button></div>
      <div class="actions"><button id="adbRefreshBtn" class="button light">Refresh devices</button><button id="adbInstallBtn" class="button primary">Install APK via Type-C</button><button id="adbOpenBtn" class="button primary">Open deeplink via ADB</button></div>
    </section>
    <section class="card">
      <h2>Direct actions</h2>
      <label>Deeplink</label><input id="deeplink" placeholder="tiktok://... or https://...">
      <div class="row"><input id="x" type="number" placeholder="x"><input id="y" type="number" placeholder="y"><input id="x2" type="number" placeholder="x2"><input id="y2" type="number" placeholder="y2"></div>
      <div class="actions"><button id="tapBtn" class="button primary">Tap x,y</button><button id="swipeBtn" class="button primary">Swipe x,y → x2,y2</button><button id="deepBtn" class="button primary">Open Deeplink</button></div>
    </section>
    <section class="card"><h2>Logs</h2><pre id="logs">Ready.</pre></section>
  </main>
<script>
  const $ = id => document.getElementById(id);
  const base = $('baseUrl');
  base.value = localStorage.getItem('phoneMonitorBaseUrl') || '';
  function url(path){ const root = base.value.trim().replace(/\/$/, ''); if(!root) throw new Error('Enter phone base URL first'); return root + path; }
  async function post(path, data){ const body = new URLSearchParams(data); const res = await fetch(url(path), {method:'POST', headers:{'Content-Type':'application/x-www-form-urlencoded'}, body}); const text = await res.text(); if(!res.ok) throw new Error(text); $('logs').textContent = text; }
  function pendingLink(){ return localStorage.getItem('pendingQueueLink') || ''; }
  function clickPoint(){ return {x:Number($('clickX').value || localStorage.getItem('phoneClickX') || 540), y:Number($('clickY').value || localStorage.getItem('phoneClickY') || 1800)}; }
  function initClickPoint(){ $('clickX').value = localStorage.getItem('phoneClickX') || '540'; $('clickY').value = localStorage.getItem('phoneClickY') || '1800'; }
  function renderPending(){ const link = pendingLink(); $('openPendingBtn').disabled = !link; if(link) { $('deeplink').value = link; $('logs').textContent = `Pending queue #${localStorage.getItem('pendingQueueJobId') || ''}: ${link}`; } }
  async function openPending(){ const link = pendingLink(); if(!link) return; const point = clickPoint(); await post('/actions/deeplink', {url:link, source:'queue', queue_id:localStorage.getItem('pendingQueueJobId') || '', time:localStorage.getItem('pendingQueueTime') || '', click_after_ms:localStorage.getItem('pendingQueueClickAfterMs') || '0', click_x:point.x, click_y:point.y}); localStorage.removeItem('pendingQueueLink'); localStorage.removeItem('pendingQueueJobId'); localStorage.removeItem('pendingQueueTime'); localStorage.removeItem('pendingQueueClickAfterMs'); renderPending(); }
  initClickPoint();
  renderPending();
  function selectedAdbDevice(){ return $('adbDevice').value || ''; }
  async function jsonPost(path, data){ const res = await fetch(path, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(data || {})}); const payload = await res.json(); if(!res.ok) throw new Error(payload.error || `HTTP ${res.status}`); $('logs').textContent = JSON.stringify(payload, null, 2); return payload; }
  async function refreshAdbDevices(){ const res = await fetch('/api/phone/adb-devices?_=' + Date.now(), {cache:'no-store'}); const data = await res.json(); if(!res.ok || data.error) throw new Error(data.error || `HTTP ${res.status}`); const devices = data.devices || []; $('adbDevice').innerHTML = '<option value="">Auto select</option>' + devices.map((d) => `<option value="${String(d.serial).replace(/&/g,'&amp;').replace(/"/g,'&quot;')}">${d.serial} (${d.state})</option>`).join(''); $('logs').textContent = devices.length ? JSON.stringify(data, null, 2) : 'No ADB devices. Plug phone by Type-C, enable USB debugging, accept RSA prompt.'; }
  async function installViaAdb(){ await jsonPost('/api/phone/adb-install', {device_id:selectedAdbDevice(), apk_path:$('apkPath').value.trim()}); }
  async function openViaAdb(){ const link = $('deeplink').value.trim() || pendingLink(); if(!link) throw new Error('Enter deeplink or choose queue pending link first'); const point = clickPoint(); await jsonPost('/api/phone/adb-open', {device_id:selectedAdbDevice(), url:link, click_after_ms:Number($('clickDelay').value || 0), click_x:point.x, click_y:point.y}); }
  $('adbRefreshBtn').onclick = () => refreshAdbDevices().catch(e => $('logs').textContent = e.message);
  $('adbInstallBtn').onclick = () => installViaAdb().catch(e => $('logs').textContent = e.message);
  $('adbOpenBtn').onclick = () => openViaAdb().catch(e => $('logs').textContent = e.message);
  $('saveClickPointBtn').onclick = () => { const point = clickPoint(); localStorage.setItem('phoneClickX', String(point.x)); localStorage.setItem('phoneClickY', String(point.y)); $('logs').textContent = `Saved click point ${point.x},${point.y}`; };
  refreshAdbDevices().catch(() => {});
  $('queueBtn').onclick = () => location.href = '/';
  $('saveBtn').onclick = () => { localStorage.setItem('phoneMonitorBaseUrl', base.value.trim()); $('logs').textContent = 'Saved ' + base.value.trim(); if(pendingLink()) openPending().catch(e => $('logs').textContent = e.message); };
  $('logsBtn').onclick = async () => { try { const res = await fetch(url('/logs')); $('logs').textContent = await res.text(); } catch(e) { $('logs').textContent = e.message; } };
  $('openPendingBtn').onclick = () => openPending().catch(e => $('logs').textContent = e.message);
  $('tapBtn').onclick = () => post('/actions/tap', {x:$('x').value, y:$('y').value}).catch(e => $('logs').textContent = e.message);
  $('swipeBtn').onclick = () => post('/actions/swipe', {x1:$('x').value, y1:$('y').value, x2:$('x2').value, y2:$('y2').value, duration_ms:450}).catch(e => $('logs').textContent = e.message);
  $('deepBtn').onclick = () => post('/actions/deeplink', {url:$('deeplink').value}).catch(e => $('logs').textContent = e.message);
</script>
</body>
</html>
"""

class QueueUiHandler(BaseHTTPRequestHandler):
    db: ChatDatabase
    config: QueueUiConfig

    def do_HEAD(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._send_headers("text/html; charset=utf-8", len(HTML.encode("utf-8")))
            return

        if parsed.path == "/filters":
            self._send_headers("text/html; charset=utf-8", len(FILTERS_HTML.encode("utf-8")))
            return

        if parsed.path == "/phone-monitor":
            self._send_headers("text/html; charset=utf-8", len(PHONE_MONITOR_HTML.encode("utf-8")))
            return

        if parsed.path == "/api/queue":
            self._send_headers("application/json; charset=utf-8", 0)
            return

        if parsed.path == "/api/filters":
            self._send_headers("application/json; charset=utf-8", 0)
            return

        if parsed.path == "/api/phone/config":
            self._send_headers("application/json; charset=utf-8", 0)
            return

        if parsed.path == "/api/phone/next-job":
            self._send_headers("application/json; charset=utf-8", 0)
            return

        if parsed.path.startswith("/api/phone/screenshots/"):
            self._send_phone_screenshot(parsed.path, head_only=True)
            return

        if parsed.path == "/api/phone/adb-devices":
            self._send_headers("application/json; charset=utf-8", 0)
            return

        self.send_error(404)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._send_html(HTML)
            return

        if parsed.path == "/filters":
            self._send_html(FILTERS_HTML)
            return

        if parsed.path == "/phone-monitor":
            self._send_html(PHONE_MONITOR_HTML)
            return

        if parsed.path == "/api/queue":
            self._send_json(self._queue_snapshot(parse_qs(parsed.query)))
            return

        if parsed.path == "/api/filters":
            self._send_json(self._filters_snapshot())
            return

        if parsed.path == "/api/phone/config":
            self._send_json(_phone_config())
            return

        if parsed.path == "/api/phone/next-job":
            self._send_json(self._phone_next_job(parse_qs(parsed.query)))
            return

        if parsed.path.startswith("/api/phone/screenshots/"):
            self._send_phone_screenshot(parsed.path)
            return

        if parsed.path == "/api/phone/adb-devices":
            self._send_json(_adb_devices())
            return

        self.send_error(404)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/filters":
            self._save_filters()
            return

        if parsed.path == "/api/phone/job-result":
            self._phone_job_result()
            return

        if parsed.path == "/api/queue/mark-done":
            self._queue_mark_done()
            return

        if parsed.path == "/api/phone/screenshot":
            self._phone_screenshot_upload()
            return

        if parsed.path == "/api/phone/adb-open":
            self._adb_open_link()
            return

        if parsed.path == "/api/phone/adb-install":
            self._adb_install_app()
            return

        self.send_error(404)

    def log_message(self, fmt: str, *args) -> None:
        logger.debug("%s - %s", self.client_address[0], fmt % args)

    def _phone_next_job(self, query: Dict[str, List[str]]) -> Dict[str, object]:
        after_id = non_negative_int((query.get("after_id") or ["0"])[0], 0)
        device_id = str((query.get("device_id") or ["phone"])[0] or "phone")
        claimed = self.db.claim_next_after(device_id, self.config.queue_lease_seconds, after_id)
        if claimed:
            job = _phone_job_from_claimed_job(claimed)
            if job:
                return {"generated_at": datetime.now(timezone.utc).isoformat(), "config": _phone_config(), "job": job}
            self.db.mark_job_done(claimed.id, f"{device_id}: unsupported phone job")
        wait_seconds = min(_int_query(query, "wait", 0), 25)
        deadline = time.time() + wait_seconds
        while wait_seconds > 0 and time.time() < deadline:
            time.sleep(1)
            claimed = self.db.claim_next_after(device_id, self.config.queue_lease_seconds, after_id)
            if claimed:
                job = _phone_job_from_claimed_job(claimed)
                if job:
                    return {"generated_at": datetime.now(timezone.utc).isoformat(), "config": _phone_config(), "job": job}
                self.db.mark_job_done(claimed.id, f"{device_id}: unsupported phone job")
        return {"generated_at": datetime.now(timezone.utc).isoformat(), "config": _phone_config(), "job": None}

    def _phone_job_result(self) -> None:
        try:
            payload = self._read_json_body()
            job_id = non_negative_int(payload.get("job_id"), 0)
            status = str(payload.get("status") or "")
            device_id = str(payload.get("device_id") or "phone")
            error = str(payload.get("error") or "")
            done_statuses = {"done", "after_tap_screenshot_uploaded", "after_open_tap_screenshot_uploaded"}
            terminal_skip_statuses = {
                "client_filter_skipped",
                "deeplink_open_failed_next_task",
                "deeplink_not_in_tiktok_next_task",
                "open_deadline_missed",
                "open_time_missing",
                "time_window_skipped",
                "treasure_not_found",
                "treasure_not_found_next_task",
                "treasure_scan_skipped_next_task",
            }
            progress_statuses = {
                "opened",
                "waiting_time_window",
                "treasure_detected_tapped",
                "treasure_tapped",
                "treasure_scan_screenshot_uploaded",
                "open_button_tapped",
                "after_open_tap_screenshot_uploaded",
                "screenshot_uploaded",
            }
            if job_id > 0 and status in done_statuses:
                self.db.mark_job_done(job_id, f"{device_id}: {status} {error}".strip())
            elif job_id > 0 and status in terminal_skip_statuses:
                self.db.mark_job_done(job_id, f"{device_id}: {status} {error}".strip())
            elif job_id > 0 and status == "failed":
                self.db.fail_job(job_id, device_id, error or status, self.config.queue_retry_delay_seconds)
            elif job_id > 0 and status in progress_statuses:
                self.db.renew_job_lease(job_id, device_id, self.config.queue_lease_seconds)
            logger.info("Phone job result: %s", payload)
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=400)
            return
        self._send_json({"ok": True, "generated_at": datetime.now(timezone.utc).isoformat()})

    def _queue_mark_done(self) -> None:
        try:
            payload = self._read_json_body()
            job_id = non_negative_int(payload.get("job_id"), 0)
            if job_id <= 0:
                raise ValueError("job_id is required")
            ok = self.db.mark_job_done(job_id, str(payload.get("note") or "manual"))
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=400)
            return
        self._send_json({"ok": ok, "job_id": job_id, "generated_at": datetime.now(timezone.utc).isoformat()})

    def _phone_screenshot_upload(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > PHONE_SCREENSHOT_MAX_BYTES:
                raise ValueError("Invalid screenshot size")

            content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            extensions = {"image/jpeg": "jpg", "image/png": "png"}
            extension = extensions.get(content_type)
            if extension is None:
                raise ValueError("Content-Type must be image/jpeg or image/png")

            job_id = non_negative_int(self.headers.get("X-Job-ID"), 0)
            device_id = re.sub(r"[^a-zA-Z0-9_-]+", "-", self.headers.get("X-Device-ID", "iphone")).strip("-")
            device_id = device_id[:40] or "iphone"
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            filename = f"job-{job_id}_{device_id}_{timestamp}.{extension}"

            PHONE_SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
            image_data = self.rfile.read(length)
            if len(image_data) != length:
                raise ValueError("Incomplete screenshot body")
            path = PHONE_SCREENSHOT_DIR / filename
            path.write_bytes(image_data)
            logger.info("Saved phone screenshot: %s", path)
        except Exception as exc:
            logger.exception("Failed to save phone screenshot")
            self._send_json({"error": str(exc)}, status=400)
            return

        self._send_json(
            {
                "ok": True,
                "job_id": job_id,
                "filename": filename,
                "url": f"/api/phone/screenshots/{filename}",
                "size": length,
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }
        )

    def _send_phone_screenshot(self, request_path: str, head_only: bool = False) -> None:
        filename = request_path.rsplit("/", 1)[-1]
        if not re.fullmatch(r"[a-zA-Z0-9_.-]+", filename):
            self.send_error(404)
            return

        path = PHONE_SCREENSHOT_DIR / filename
        if not path.is_file():
            self.send_error(404)
            return

        content_type = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
        body = path.read_bytes()
        self._send_headers(content_type, len(body))
        if not head_only:
            self.wfile.write(body)

    def _queue_snapshot(self, query: Dict[str, List[str]]) -> Dict[str, object]:
        requested_limit = _int_query(query, "limit", self.config.limit)
        limit = min(requested_limit, self.config.limit)
        statuses = _statuses_query(query)
        items = self.db.get_queue_items(
            limit=limit,
            statuses=statuses or None,
        )
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "db_path": self.config.db_path,
            "refresh_seconds": self.config.refresh_seconds,
            "limit": limit,
            "requested_limit": requested_limit,
            "latest_id": items[0]["id"] if items else 0,
            "latest_pending_id": _latest_pending_id(items),
            "stats": self.db.get_queue_stats(),
            "items": items,
        }

    def _filters_snapshot(self) -> Dict[str, object]:
        path = Path(self.config.filter_config_path)
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "path": str(path),
            "filters": _load_filter_rules(path),
        }

    def _read_json_body(self, max_size: int = 1024 * 1024) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > max_size:
            raise ValueError("Invalid request body size")
        raw_body = self.rfile.read(length).decode("utf-8")
        payload = json.loads(raw_body)
        if not isinstance(payload, dict):
            raise ValueError("request body must be an object")
        return payload

    def _adb_open_link(self) -> None:
        try:
            payload = self._read_json_body()
            url = str(payload.get("url") or "").strip()
            if not url:
                raise ValueError("url is required")
            device_id = str(payload.get("device_id") or "").strip() or None
            click_after_ms = non_negative_int(payload.get("click_after_ms"), 0)
            click_x = non_negative_int(payload.get("click_x"), 0)
            click_y = non_negative_int(payload.get("click_y"), 0)
            result = _adb_open_link(url, device_id=device_id, click_after_ms=click_after_ms, click_x=click_x, click_y=click_y)
        except Exception as exc:
            logger.exception("Failed to open link through ADB")
            self._send_json({"error": str(exc)}, status=400)
            return
        self._send_json(result)

    def _adb_install_app(self) -> None:
        try:
            payload = self._read_json_body()
            device_id = str(payload.get("device_id") or "").strip() or None
            apk_path = str(payload.get("apk_path") or _default_apk_path()).strip()
            result = _adb_install_apk(apk_path, device_id=device_id)
        except Exception as exc:
            logger.exception("Failed to install APK through ADB")
            self._send_json({"error": str(exc)}, status=400)
            return
        self._send_json(result)

    def _save_filters(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send_json({"error": "Invalid Content-Length"}, status=400)
            return

        if length <= 0 or length > 1024 * 1024:
            self._send_json({"error": "Invalid request body size"}, status=400)
            return

        try:
            raw_body = self.rfile.read(length).decode("utf-8")
            payload = json.loads(raw_body)
            filters = _normalize_filter_rules(payload.get("filters", payload))
            path = Path(self.config.filter_config_path)
            _write_filter_rules(path, filters)
        except Exception as exc:
            logger.exception("Failed to save message filters")
            self._send_json({"error": str(exc)}, status=400)
            return

        self._send_json(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "path": str(path),
                "filters": filters,
            }
        )

    def _send_html(self, content: str) -> None:
        body = content.encode("utf-8")
        self._send_headers("text/html; charset=utf-8", len(body))
        self.wfile.write(body)

    def _send_json(self, payload: Dict[str, object], status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send_headers("application/json; charset=utf-8", len(body), status=status)
        self.wfile.write(body)

    def _send_headers(self, content_type: str, content_length: int, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(content_length))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.end_headers()


def _latest_pending_id(items: List[Dict[str, Any]]) -> int:
    pending_ids = [int(item.get("id") or 0) for item in items if item.get("status") == "pending"]
    return max(pending_ids) if pending_ids else 0


def non_negative_int(value: Any, default: int = 0) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


def _phone_config() -> Dict[str, object]:
    return {
        "poll_seconds": 0,
        "long_poll_seconds": 25,
        "click_x": 540,
        "click_y": 1800,
        "auto_open": True,
        "auto_tap_requires_accessibility": True,
    }


def _extract_link_from_item(item: Dict[str, Any]) -> str:
    payload = item.get("payload") or {}
    message = item.get("message") or {}
    candidates = [
        payload.get("url"), payload.get("link"), payload.get("deeplink"), payload.get("deep_link"),
        payload.get("live_url"), payload.get("room_url"), message.get("text"),
    ]
    for value in candidates:
        match = re.search(r"(?:https?://|tiktok://)[^\s<>'\"]+", str(value or ""), re.I)
        if match:
            return match.group(0)
    return ""


def _parse_time_delay_ms(value: Any) -> int:
    text = str(value or "").strip()
    match = re.search(r"(\d{1,2}):(\d{2})\s*s?", text, re.I)
    if match:
        return (int(match.group(1)) * 60 + int(match.group(2))) * 1000
    match = re.search(r"(\d+(?:\.\d+)?)\s*s", text, re.I)
    if match:
        return int(float(match.group(1)) * 1000)
    return 0


def _extract_time_from_item(item: Dict[str, Any]) -> Dict[str, object]:
    payload = item.get("payload") or {}
    message = item.get("message") or {}
    candidates = [payload.get("TIME"), payload.get("time"), payload.get("Time"), payload.get("click_time"), payload.get("open_time"), message.get("text")]
    for value in candidates:
        text = str(value or "")
        match = re.search(r"TIME\s*[:：]\s*([^\n\r]+)", text, re.I) or re.search(r"(\d{1,2}:\d{2}\s*s?\s*-\s*\d{1,2}:\d{2}:\d{2})", text, re.I) or re.search(r"(\d{1,2}:\d{2}\s*s?)", text, re.I)
        if match:
            label = match.group(1).strip()
            target_match = re.search(r"-\s*(\d{1,2}:\d{2}:\d{2})", label)
            return {
                "label": label,
                "click_after_ms": _parse_time_delay_ms(label),
                "target_time_hhmmss": target_match.group(1).strip() if target_match else "",
            }
    return {"label": "", "click_after_ms": 0, "target_time_hhmmss": ""}


def _phone_job_from_queue_item(item: Dict[str, Any]) -> Optional[Dict[str, object]]:
    url = _extract_link_from_item(item)
    if not url:
        return None
    time_meta = _extract_time_from_item(item)
    config = _phone_config()
    return {
        "id": item.get("id"),
        "url": url,
        "time": time_meta["label"],
        "click_after_ms": time_meta["click_after_ms"],
        "target_time_hhmmss": time_meta.get("target_time_hhmmss", ""),
        "click_x": config["click_x"],
        "click_y": config["click_y"],
        "message": (item.get("message") or {}).get("text", ""),
        "payload": item.get("payload") or {},
    }


def _phone_job_from_claimed_job(claimed: QueueJob) -> Optional[Dict[str, object]]:
    item = {
        "id": claimed.id,
        "payload": claimed.payload,
        "message": {"text": claimed.message_text},
        "room": {"chat_id": claimed.room_chat_id},
    }
    return _phone_job_from_queue_item(item)


def _adb_path() -> str:
    adb = shutil.which("adb")
    if not adb:
        raise RuntimeError("ADB not found. Install android-platform-tools or add adb to PATH.")
    return adb


def _adb_base_command(device_id: Optional[str] = None) -> List[str]:
    command = [_adb_path()]
    if device_id:
        command += ["-s", device_id]
    return command


def _run_adb(args: List[str], device_id: Optional[str] = None, timeout: int = 30) -> subprocess.CompletedProcess:
    command = _adb_base_command(device_id) + args
    return subprocess.run(command, text=True, capture_output=True, timeout=timeout, check=False)


def _adb_devices() -> Dict[str, object]:
    try:
        result = _run_adb(["devices", "-l"], timeout=10)
    except Exception as exc:
        return {"adb_available": False, "error": str(exc), "devices": []}
    devices = []
    for line in result.stdout.splitlines()[1:]:
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        devices.append({
            "serial": parts[0],
            "state": parts[1] if len(parts) > 1 else "unknown",
            "details": " ".join(parts[2:]),
        })
    return {"adb_available": True, "adb_path": _adb_path(), "devices": devices}


def _default_apk_path() -> str:
    return str(Path(__file__).resolve().parents[2] / "phone_monitor_app" / "app" / "build" / "outputs" / "apk" / "debug" / "app-debug.apk")


def _adb_install_apk(apk_path: str, device_id: Optional[str] = None) -> Dict[str, object]:
    path = Path(apk_path).expanduser().resolve()
    if not path.exists():
        raise RuntimeError(f"APK not found: {path}. Build it first with: cd phone_monitor_app && gradle assembleDebug")
    result = _run_adb(["install", "-r", str(path)], device_id=device_id, timeout=120)
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "adb install failed").strip())
    return {"ok": True, "apk_path": str(path), "device": device_id or "auto", "output": result.stdout.strip()}


def _adb_open_link(url: str, device_id: Optional[str] = None, click_after_ms: int = 0, click_x: int = 0, click_y: int = 0) -> Dict[str, object]:
    result = _run_adb(["shell", "am", "start", "-a", "android.intent.action.VIEW", "-d", url], device_id=device_id, timeout=20)
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "adb open link failed").strip())
    tap_output = ""
    if click_after_ms > 0 and click_x > 0 and click_y > 0:
        time.sleep(click_after_ms / 1000)
        tap_result = _run_adb(["shell", "input", "tap", str(click_x), str(click_y)], device_id=device_id, timeout=20)
        if tap_result.returncode != 0:
            raise RuntimeError((tap_result.stderr or tap_result.stdout or "adb timed tap failed").strip())
        tap_output = tap_result.stdout.strip()
    return {"ok": True, "url": url, "device": device_id or "auto", "click_after_ms": click_after_ms, "click_x": click_x, "click_y": click_y, "output": result.stdout.strip(), "tap_output": tap_output}


def _int_query(query: Dict[str, List[str]], key: str, default: int) -> int:
    raw_value = (query.get(key) or [""])[0]
    try:
        value = int(raw_value)
    except ValueError:
        return default
    return max(1, min(value, 5000))


def _statuses_query(query: Dict[str, List[str]]) -> List[str]:
    raw_value = (query.get("statuses") or [""])[0]
    return [value.strip() for value in raw_value.split(",") if value.strip()]


def _load_filter_rules(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []

    with path.open(encoding="utf-8") as file:
        payload = json.load(file)

    raw_filters = payload.get("filters", payload) if isinstance(payload, dict) else payload
    return _normalize_filter_rules(raw_filters)


def _write_filter_rules(path: Path, filters: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"filters": filters}
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    tmp_path.replace(path)


def _normalize_filter_rules(raw_filters: Any) -> List[Dict[str, Any]]:
    if not isinstance(raw_filters, list):
        raise ValueError("filters must be a list")

    return [_normalize_filter_rule(raw_filter, index) for index, raw_filter in enumerate(raw_filters)]


def _normalize_filter_rule(raw_filter: Any, index: int) -> Dict[str, Any]:
    if not isinstance(raw_filter, dict):
        raise ValueError(f"filter #{index + 1} must be an object")

    rule: Dict[str, Any] = {
        "name": str(raw_filter.get("name") or f"filter_{index + 1}").strip(),
        "enabled": bool(raw_filter.get("enabled", True)),
    }

    for key in (
        "priority",
        "min_box1",
        "max_box1",
        "min_box2",
        "max_box2",
        "min_views",
        "max_views",
    ):
        value = _optional_number(raw_filter.get(key), integer=True)
        if value is not None:
            rule[key] = value

    for key in ("min_rate", "max_rate"):
        value = _optional_number(raw_filter.get(key), integer=False)
        if value is not None:
            rule[key] = value

    for key in ("boxes", "countries", "badges", "note_contains", "text_contains"):
        values = _string_list(raw_filter.get(key))
        if values:
            rule[key] = values

    text_regex = str(raw_filter.get("text_regex") or "").strip()
    if text_regex:
        rule["text_regex"] = text_regex

    return rule


def _optional_number(value: Any, integer: bool) -> Any:
    if value in (None, ""):
        return None

    number = int(value) if integer else float(value)
    if number < 0:
        raise ValueError("numeric filter values must be >= 0")
    return number


def _string_list(value: Any) -> List[str]:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [item.strip() for item in str(value).split(",") if item.strip()]


def setup_logging(log_level: str) -> None:
    level = getattr(logging, log_level, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )


def create_server(config: QueueUiConfig) -> ThreadingHTTPServer:
    db = ChatDatabase(config.db_path)
    db.init_schema()

    class Handler(QueueUiHandler):
        pass

    Handler.db = db
    Handler.config = config
    return _bind_server(config.host, config.port, Handler)


def _bind_server(host: str, port: int, handler) -> ThreadingHTTPServer:
    for candidate_port in range(port, port + 20):
        try:
            return ThreadingHTTPServer((host, candidate_port), handler)
        except OSError as exc:
            if exc.errno not in {48, 98}:
                raise

    raise RuntimeError(f"No available port found from {port} to {port + 19}")


def main() -> None:
    config = load_queue_ui_config()
    setup_logging(config.log_level)
    server = create_server(config)
    host, port = server.server_address
    logger.info("Queue UI running at http://%s:%s", host, port)
    server.serve_forever()


if __name__ == "__main__":
    main()
