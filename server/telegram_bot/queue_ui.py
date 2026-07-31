import json
import logging
import os
import re
import shutil
import socket
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, quote, urlparse

from bot_broadcast import discover_all_bot_groups, list_configured_bots, register_discovered_groups
from desktop_auth import desktop_pull_token_for_user, list_queue_usernames
from config import QueueUiConfig, _parse_client_targets, load_config, load_queue_ui_config, queue_users_map
from open_link import open_link_for_queue
from desktop_relay import desktop_status, enqueue_open, pull_pending
from logging_setup import setup_logging
from db import ChatDatabase, QueueJob
from phone_push import pop_phone_open, push_phone_open
from phone_jobs import phone_config, phone_job_from_claimed_job, phone_job_from_queue_item
from phone_registry import (
    next_pending_job_for_device,
    register_device,
    sync_broadcast_enabled,
)
from deeplink_resolve import (
    DEEPLINK_PREFIX,
    build_thanhtai_countdown_url,
    extract_countdown_url,
    find_countdown_url_for_open,
    find_first_convertible_url,
    find_first_countdown_url,
    normalize_url_href,
    resolve_countdown_open_url,
    extract_room_id,
    enrich_payload_with_deeplink,
    item_context_from_parts,
    resolve_deeplink_for_broadcast,
    resolve_link_for_open,
    resolve_live_url,
)
from message_format import broadcast_text_from_payload, queue_display_from_payload
from dotenv import load_dotenv
from telegram import Bot
from ui_auth import (
    LOGIN_HTML,
    LOGOUT_SCRIPT,
    PUBLIC_PATHS,
    SESSION_COOKIE,
    SESSION_TTL_SECONDS,
    create_session_token,
    is_authenticated,
    parse_cookie_header,
    session_username_from_token,
    verify_credentials,
)


logger = logging.getLogger(__name__)

PHONE_SCREENSHOT_DIR = Path(__file__).resolve().parent / "data" / "phone_screenshots"
PHONE_SCREENSHOT_MAX_BYTES = 15 * 1024 * 1024
QUEUE_CHAT_HTML_PATH = Path(__file__).resolve().parent / "templates" / "queue_chat.html"


def _load_queue_html() -> str:
    template = QUEUE_CHAT_HTML_PATH.read_text(encoding="utf-8")
    return template.replace("__LOGOUT_SCRIPT__", LOGOUT_SCRIPT)


def _enrich_queue_item(item: Dict[str, Any]) -> Dict[str, Any]:
    payload = item.get("payload") or {}
    message = item.get("message") or {}
    message_text = str(message.get("text") or "")
    display_html, _ = queue_display_from_payload(message_text, payload)

    deeplink = str(payload.get("deeplink") or payload.get("deep_link") or "").strip()
    room_id = str(payload.get("room_id") or "").strip() or (extract_room_id(deeplink) or "")
    if not deeplink:
        enriched = enrich_payload_with_deeplink(message_text, payload)
        deeplink = str(enriched.get("deeplink") or "").strip()
        room_id = room_id or str(enriched.get("room_id") or "").strip() or (extract_room_id(deeplink) or "")
    combined = item_context_from_parts(message_text, payload)
    countdown_url = extract_countdown_url(message_text, payload) or find_countdown_url_for_open(
        str(payload.get("telegram_html") or "")
    )
    if not countdown_url and room_id.isdigit():
        countdown_url = build_thanhtai_countdown_url(room_id)
    if countdown_url:
        countdown_url = normalize_url_href(countdown_url)

    source_url = str(payload.get("source_url") or "").strip()
    has_link = bool(
        countdown_url
        or source_url
        or deeplink
        or re.search(r"https?://|snssdk1180://", combined, re.I)
    )

    enriched = dict(item)
    enriched["display_html"] = display_html
    enriched["countdown_url"] = countdown_url
    enriched["deeplink"] = deeplink
    enriched["room_id"] = room_id
    enriched["has_link"] = has_link
    return enriched


HTML = _load_queue_html()



FILTERS_HTML = r"""<!doctype html>
<html lang="vi">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Setup Filter</title>
  <style>
    :root { --bg:#0f141b; --card:#17202b; --line:#2a3544; --text:#e8edf4; --muted:#8b98a8; --blue:#3b82f6; --green:#22c55e; --red:#ef4444; --input:#0d1218; --accent:#fbbf24; }
    * { box-sizing: border-box; }
    body { margin:0; min-height:100vh; background:linear-gradient(180deg,#101722,#0b1016); color:var(--text); font-family:ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }
    button,input { font:inherit; }
    .shell { min-height:100vh; display:grid; grid-template-rows:auto 1fr; }
    .topbar { min-height:58px; display:flex; align-items:center; justify-content:space-between; gap:16px; padding:0 20px; background:#0c1118; border-bottom:1px solid #1f2937; flex-wrap:wrap; }
    .topbar-main { display:flex; align-items:center; gap:10px; min-width:0; flex:1 1 auto; }
    .header-collapse-btn { width:34px; padding:0; flex:0 0 auto; }
    .header-collapsible { display:block; }
    .shell.header-collapsed .header-collapsible { display:none !important; }
    .shell.header-collapsed .topbar { min-height:46px; border-bottom-color:transparent; }
    .shell.header-collapsed .brand span { display:none; }
    .brand { display:flex; align-items:baseline; gap:12px; min-width:0; }
    h1 { margin:0; font-size:18px; }
    .brand span { color:var(--muted); font-size:12px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
    .toolbar { display:flex; align-items:center; gap:8px; flex-wrap:wrap; }
    .button { height:34px; display:inline-flex; align-items:center; justify-content:center; border:1px solid #334155; background:#1e293b; color:#f8fafc; border-radius:8px; padding:0 12px; cursor:pointer; }
    .button:hover { background:#273449; }
    .button.primary { background:var(--blue); border-color:#2563eb; }
    .button.danger { background:#3f1d24; border-color:#7f1d1d; }
    .main { min-height:0; display:grid; grid-template-columns:300px minmax(0,1fr); }
    .list-pane { min-height:0; overflow:auto; border-right:1px solid var(--line); background:#111822; }
    .list-head { position:sticky; top:0; z-index:1; display:flex; gap:8px; padding:12px; border-bottom:1px solid var(--line); background:#151d28; }
    .filter-list { margin:0; padding:0; list-style:none; }
    .filter-row { display:grid; grid-template-columns:minmax(0,1fr) auto; gap:8px; padding:12px; border-bottom:1px solid #1a2330; cursor:pointer; }
    .filter-row:hover { background:#162030; }
    .filter-row.selected { background:#1a2740; box-shadow:inset 3px 0 0 var(--blue); }
    .filter-name { font-weight:700; font-size:13px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
    .filter-meta { margin-top:4px; color:var(--muted); font-size:12px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
    .pill { display:inline-flex; align-items:center; height:22px; padding:0 8px; border-radius:999px; border:1px solid #334155; font-size:12px; font-weight:700; }
    .pill.on { color:#86efac; background:#052e16; border-color:#166534; }
    .pill.off { color:#fca5a5; background:#450a0a; border-color:#7f1d1d; }
    .editor { min-height:0; overflow:auto; padding:24px; display:flex; justify-content:center; }
    .editor-wrap { width:min(720px,100%); display:flex; flex-direction:column; gap:14px; }
    .status { min-height:34px; display:flex; align-items:center; padding:0 12px; border:1px solid var(--line); border-radius:8px; color:var(--muted); background:#121925; font-size:13px; }
    .meta-bar { display:grid; grid-template-columns:minmax(0,1fr) 110px 90px; gap:10px; align-items:end; }
    .meta-bar label { display:block; margin-bottom:6px; color:var(--muted); font-size:11px; font-weight:700; text-transform:uppercase; letter-spacing:.04em; }
    .meta-bar input[type=text], .meta-bar input[type=number] { width:100%; height:38px; border:1px solid var(--line); border-radius:8px; background:var(--input); color:var(--text); padding:0 10px; }
    .checkline { height:38px; display:inline-flex; align-items:center; gap:8px; color:var(--text); font-size:13px; }
    .msg-card { border:1px solid #2b384a; border-radius:16px; background:linear-gradient(180deg,#1a2432,#141c27); box-shadow:0 18px 40px rgba(0,0,0,.28); padding:18px 18px 16px; font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace; }
    .msg-title { color:#cbd5e1; font-size:13px; margin-bottom:14px; }
    .msg-line { display:flex; align-items:center; flex-wrap:wrap; gap:8px; min-height:40px; margin:0 0 10px; font-size:15px; line-height:1.45; }
    .msg-line.dim { color:#64748b; }
    .msg-line .label { color:#e2e8f0; white-space:nowrap; }
    .msg-line .sep { color:#94a3b8; }
    .range { display:inline-flex; align-items:center; gap:6px; }
    .range input { width:78px; height:34px; border:1px solid #3b4a5f; border-radius:8px; background:#0b1118; color:var(--accent); text-align:center; padding:0 6px; font-weight:700; }
    .range input:focus { outline:2px solid rgba(59,130,246,.35); border-color:#3b82f6; }
    .range .dash { color:#94a3b8; }
    .hint { color:var(--muted); font-size:12px; line-height:1.45; }
    .reject-box { border:1px dashed #3b4a5f; border-radius:12px; padding:12px; background:#121925; }
    .reject-box label { display:block; margin-bottom:6px; color:var(--muted); font-size:11px; font-weight:700; text-transform:uppercase; }
    .reject-box input { width:100%; height:38px; border:1px solid var(--line); border-radius:8px; background:var(--input); color:var(--text); padding:0 10px; }
    .content-filter-box { border:1px solid #2a3544; border-radius:12px; padding:14px; background:#121925; }
    .content-filter-box label { display:block; margin-bottom:8px; color:#e2e8f0; font-size:13px; font-weight:700; }
    .content-filter-box input { width:100%; min-height:42px; border:1px solid var(--line); border-radius:10px; background:var(--input); color:var(--text); padding:10px 12px; }
    .content-filter-box input:focus { outline:2px solid rgba(59,130,246,.35); border-color:#3b82f6; }
    .content-chips { display:flex; flex-wrap:wrap; gap:6px; margin-top:10px; }
    .content-chip { display:inline-flex; align-items:center; height:26px; padding:0 10px; border-radius:999px; background:#1a2740; border:1px solid #334155; color:#bfdbfe; font-size:12px; }
    .groups-panel { border:1px solid #2a3544; border-radius:16px; background:linear-gradient(180deg,#151d28 0%,#101722 100%); padding:16px; box-shadow:0 12px 32px rgba(0,0,0,.22); }
    .groups-panel-head { display:flex; align-items:flex-start; justify-content:space-between; gap:12px; flex-wrap:wrap; margin-bottom:14px; }
    .groups-panel-title { margin:0; font-size:15px; font-weight:700; }
    .groups-panel-sub { margin:4px 0 0; color:var(--muted); font-size:12px; line-height:1.4; }
    .groups-count { display:inline-flex; align-items:center; height:28px; padding:0 10px; border-radius:999px; background:#0a1a12; border:1px solid #166534; color:#86efac; font-size:12px; font-weight:700; white-space:nowrap; }
    .group-toolbar { display:flex; gap:8px; flex-wrap:wrap; }
    .group-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(240px,1fr)); gap:10px; max-height:320px; overflow:auto; padding-right:2px; }
    .group-card { display:flex; align-items:flex-start; gap:12px; padding:12px 14px; border-radius:12px; border:1px solid #2a3544; background:#0d1218; cursor:pointer; transition:border-color .15s,background .15s,opacity .15s; user-select:none; }
    .group-card:hover { border-color:#3b82f6; }
    .group-card.on { border-color:#166534; background:linear-gradient(180deg,#0c1a13,#0a1410); }
    .group-card.off { opacity:.62; border-color:#3f1d24; background:#121018; }
    .group-card input { width:18px; height:18px; margin-top:2px; flex:0 0 auto; accent-color:var(--green); cursor:pointer; }
    .group-card-body { min-width:0; flex:1; }
    .group-card-top { display:flex; align-items:center; justify-content:space-between; gap:8px; }
    .group-card-name { font-weight:700; font-size:13px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
    .group-badge { font-size:10px; font-weight:700; letter-spacing:.03em; text-transform:uppercase; white-space:nowrap; }
    .group-badge.on { color:#86efac; }
    .group-badge.off { color:#fca5a5; }
    .group-card-id { color:var(--muted); font-size:11px; margin-top:6px; font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace; word-break:break-all; }
    .groups-empty { color:var(--muted); font-size:13px; line-height:1.5; padding:8px 0; }
    .groups-empty a { color:var(--blue); text-decoration:none; }
    .empty { color:var(--muted); padding:40px 12px; text-align:center; }
    @media (max-width:920px) {
      .main { grid-template-columns:1fr; }
      .list-pane { max-height:34vh; border-right:0; border-bottom:1px solid var(--line); }
      .meta-bar { grid-template-columns:1fr; }
      .range input { width:68px; }
    }
  </style>
</head>
<body>
  <div class="shell" id="filterShell">
    <header class="topbar">
      <div class="topbar-main">
        <button type="button" id="headerCollapseBtn" class="button header-collapse-btn" title="Thu gọn header" aria-expanded="true">▲</button>
        <div class="brand"><h1>Setup Filter</h1><span id="filterPath"></span></div>
      </div>
      <div class="toolbar header-collapsible">
        <button id="queueBtn" class="button">Hàng đợi</button>
        <button id="reloadBtn" class="button">Tải lại</button>
        <button id="saveBtn" class="button primary">Lưu</button>
        <button id="logoutBtn" class="button">Đăng xuất</button>
      </div>
    </header>
    <main class="main">
      <section class="list-pane">
        <div class="list-head">
          <button id="addBtn" class="button primary">Thêm</button>
          <button id="copyBtn" class="button">Nhân bản</button>
          <button id="deleteBtn" class="button danger">Xóa</button>
        </div>
        <ul id="filterList" class="filter-list"></ul>
      </section>
      <section class="editor">
        <div class="editor-wrap">
          <div id="status" class="status header-collapsible">Sẵn sàng</div>

          <section class="groups-panel header-collapsible" aria-label="Nhóm lắng nghe">
            <div class="groups-panel-head">
              <div>
                <h2 class="groups-panel-title">Nhóm đang lắng nghe</h2>
                <p class="groups-panel-sub">Tick nhóm cần nhận tin vào queue. Bỏ tick = tắt nhóm đó (không giải mã, không enqueue).</p>
              </div>
              <span id="listenCount" class="groups-count">0/0 đang bật</span>
            </div>
            <div class="group-toolbar">
              <button type="button" id="listenAllBtn" class="button primary">Chọn tất cả</button>
              <button type="button" id="listenNoneBtn" class="button">Bỏ chọn tất cả</button>
              <button type="button" id="watchGroupsBtn" class="button">Quản lý nhóm</button>
            </div>
            <div id="listenGroupGrid" class="group-grid"></div>
          </section>

          <div id="editorEmpty" class="empty" hidden>Chưa có bộ lọc. Bấm Thêm để tạo.</div>
          <div id="editorBody">
            <div class="meta-bar">
              <div>
                <label for="nameInput">Tên bộ lọc</label>
                <input id="nameInput" type="text" autocomplete="off" placeholder="filter_1">
              </div>
              <div>
                <label for="priorityInput">Ưu tiên</label>
                <input id="priorityInput" type="number" min="0" step="1">
              </div>
              <div>
                <label>&nbsp;</label>
                <label class="checkline"><input id="enabledInput" type="checkbox"> Bật</label>
              </div>
            </div>

            <div class="msg-card" aria-label="Message-style filter">
              <div class="msg-title">##  BT25754 › sample.room</div>

              <div class="msg-line dim">
                <span class="label">⏳ TIME :</span>
                <span>00:57s - 22:17:26</span>
              </div>

              <div class="msg-line">
                <span class="label">🟪  BAG :</span>
                <span class="range">
                  <input id="box1" type="number" min="0" step="1" placeholder="50">
                </span>
                <span class="sep">/</span>
                <span class="range">
                  <input id="box2" type="number" min="0" step="1" placeholder="1">
                </span>
                <span class="sep">🏅🇦🇪</span>
              </div>

              <div class="msg-line">
                <span class="label">📈  Rate :</span>
                <span class="range">
                  <input id="minRate" type="number" min="0" step="0.1" placeholder="min">
                  <span class="dash">-</span>
                  <input id="maxRate" type="number" min="0" step="0.1" placeholder="max">
                </span>
                <span class="sep">👀 …</span>
              </div>

              <div class="msg-line">
                <span class="label">🎯  Level:</span>
                <span class="range">
                  <input id="minLevel" type="number" min="0" step="1" placeholder="min">
                  <span class="dash">-</span>
                  <input id="maxLevel" type="number" min="0" step="1" placeholder="max">
                </span>
                <span class="sep">👤 …</span>
              </div>
            </div>

            <p class="hint">BAG/Box nhập đúng một số mỗi phía (vd. <code>50 / 1</code> = chỉ lấy 50/1). Rate/Level vẫn dùng min–max; để trống = không giới hạn.</p>

            <div class="content-filter-box">
              <label for="textContainsInput">Tin phải chứa nội dung</label>
              <input id="textContainsInput" type="text" autocomplete="off" placeholder='"có thể treo", "Rương treo"'>
              <div id="textContainsPreview" class="content-chips"></div>
              <p class="hint" style="margin:10px 0 0">Dùng <code>"..."</code> cho cụm từ (vd. <code>"có thể treo"</code>). Nhiều cụm cách nhau bởi dấu phẩy — khớp <strong>một</strong> cụm là qua. Để trống = không lọc theo chữ.</p>
            </div>

            <div class="reject-box">
              <label for="rejectCommentInput">Chặn nếu dòng 💬 chứa</label>
              <input id="rejectCommentInput" autocomplete="off" placeholder="҉">
              <p class="hint" style="margin:8px 0 0">Không chuyển tiếp tin có ký tự này trên dòng bình luận 💬 (vd. watermark mặt trời ҉).</p>
            </div>
          </div>
        </div>
      </section>
    </main>
  </div>
  <script>
    const state = { filters: [], reject: [], excludeGroups: [], selected: 0, path: '', watchGroups: [] };
    const $ = (id) => document.getElementById(id);
    const els = {
      path:$('filterPath'), list:$('filterList'), status:$('status'),
      editorEmpty:$('editorEmpty'), editorBody:$('editorBody'),
      name:$('nameInput'), priority:$('priorityInput'), enabled:$('enabledInput'),
      box1:$('box1'), box2:$('box2'),
      minRate:$('minRate'), maxRate:$('maxRate'), minLevel:$('minLevel'), maxLevel:$('maxLevel'),
      rejectComment:$('rejectCommentInput'), textContains:$('textContainsInput'), textContainsPreview:$('textContainsPreview'),
      listenGroupGrid:$('listenGroupGrid'), listenCount:$('listenCount'),
    };
    function allWatchGroupIds() {
      return state.watchGroups.map((g) => String(g.chat_id || '')).filter(Boolean);
    }
    function listeningGroupIds() {
      const excluded = new Set((state.excludeGroups || []).map(String));
      return allWatchGroupIds().filter((id) => !excluded.has(id));
    }
    function updateListenCount() {
      const total = allWatchGroupIds().length;
      const on = listeningGroupIds().length;
      els.listenCount.textContent = total ? `${on}/${total} đang bật` : '0/0 đang bật';
    }
    function esc(value) { return String(value ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#039;'); }
    function cleanKeyword(value) { return String(value || '').trim().replace(/^[\'\"]+|[\'\"]+$/g, '').trim(); }
    function fromCsv(value) { return String(value || '').split(',').map(cleanKeyword).filter(Boolean); }
    function parseTextContains(value) {
      const text = String(value || '');
      const tokens = [];
      const re = /"([^"]+)"|'([^']+)'/g;
      let match;
      while ((match = re.exec(text))) {
        const token = (match[1] || match[2] || '').trim();
        if (token) tokens.push(token);
      }
      if (tokens.length) return tokens;
      return fromCsv(text);
    }
    function renderTextContainsPreview(phrases) {
      const list = phrases || [];
      els.textContainsPreview.innerHTML = list.length
        ? list.map((p) => `<span class="content-chip">${esc(p)}</span>`).join('')
        : '';
    }
    function textContainsToInput(values) {
      return (values || []).map((v) => {
        const s = String(v || '');
        return (s.includes(',') || s.includes('"')) ? `"${s.replace(/"/g, '')}"` : s;
      }).join(', ');
    }
    function optionalNumber(value) { return value === '' || value === null || value === undefined ? undefined : Number(value); }
    function boxExactFromFilter(filter, minKey, maxKey) {
      const minV = filter[minKey];
      const maxV = filter[maxKey];
      if (minV === undefined && maxV === undefined) return undefined;
      if (minV !== undefined) return minV;
      return maxV;
    }
    function applyBoxExact(filter, minKey, maxKey, value) {
      if (value === undefined) {
        delete filter[minKey];
        delete filter[maxKey];
      } else {
        filter[minKey] = value;
        filter[maxKey] = value;
      }
    }
    function currentFilter() { return state.filters[state.selected] || null; }
    function compactFilter(filter) {
      ['priority','min_box1','max_box1','min_box2','max_box2','min_rate','max_rate','min_level','max_level','min_views','max_views','text_regex'].forEach((key) => {
        if (filter[key] === undefined || filter[key] === null || filter[key] === '' || Number.isNaN(filter[key])) delete filter[key];
      });
      ['boxes','countries','badges','note_contains','text_contains'].forEach((key) => {
        if (!Array.isArray(filter[key]) || filter[key].length === 0) delete filter[key];
      });
    }
    function fmtRange(minV, maxV, label) {
      if (minV === undefined && maxV === undefined) return '';
      if (minV !== undefined && maxV !== undefined) return `${label}${minV}-${maxV}`;
      if (minV !== undefined) return `${label}>=${minV}`;
      return `${label}<=${maxV}`;
    }
    function syncRejectFromForm() {
      const tokens = fromCsv(els.rejectComment.value);
      if (!tokens.length) { state.reject = []; return; }
      const existing = (state.reject || []).find((r) => r.name === 'block_sun_comment') || {};
      state.reject = [{ name:'block_sun_comment', enabled: existing.enabled !== false, comment_contains: tokens }];
    }
    function syncFormToFilter() {
      const filter = currentFilter();
      syncRejectFromForm();
      if (!filter) return;
      filter.name = els.name.value.trim() || `filter_${state.selected + 1}`;
      filter.enabled = els.enabled.checked;
      filter.priority = optionalNumber(els.priority.value);
      applyBoxExact(filter, 'min_box1', 'max_box1', optionalNumber(els.box1.value));
      applyBoxExact(filter, 'min_box2', 'max_box2', optionalNumber(els.box2.value));
      filter.min_rate = optionalNumber(els.minRate.value);
      filter.max_rate = optionalNumber(els.maxRate.value);
      filter.min_level = optionalNumber(els.minLevel.value);
      filter.max_level = optionalNumber(els.maxLevel.value);
      const phrases = parseTextContains(els.textContains.value);
      if (phrases.length) filter.text_contains = phrases;
      else delete filter.text_contains;
      renderTextContainsPreview(phrases);
      delete filter.telegram_groups;
      delete filter.boxes;
      delete filter.countries;
      delete filter.badges;
      delete filter.note_contains;
      delete filter.text_regex;
      delete filter.min_views;
      delete filter.max_views;
      compactFilter(filter);
    }
    function syncExcludeFromForm() {
      const excluded = new Set();
      els.listenGroupGrid.querySelectorAll('.group-card').forEach((card) => {
        const input = card.querySelector('input[type=checkbox]');
        if (input && !input.checked) excluded.add(String(input.value));
      });
      state.excludeGroups = Array.from(excluded);
      updateListenCount();
    }
    function renderListenGroupGrid() {
      const excluded = new Set((state.excludeGroups || []).map(String));
      if (!state.watchGroups.length) {
        els.listenGroupGrid.innerHTML = '<p class="groups-empty">Chưa có nhóm theo dõi. Thêm tại <a href="/watch-groups">Nhóm theo dõi</a> trước.</p>';
        updateListenCount();
        return;
      }
      els.listenGroupGrid.innerHTML = state.watchGroups.map((group) => {
        const chatId = String(group.chat_id || '');
        const name = esc(group.name || chatId);
        const listening = !excluded.has(chatId);
        const checked = listening ? 'checked' : '';
        const cls = listening ? 'group-card on' : 'group-card off';
        const badge = listening ? '<span class="group-badge on">Đang bật</span>' : '<span class="group-badge off">Tắt</span>';
        return `<label class="${cls}"><input type="checkbox" value="${esc(chatId)}" ${checked}><div class="group-card-body"><div class="group-card-top"><div class="group-card-name">${name}</div>${badge}</div><div class="group-card-id">${esc(chatId)}</div></div></label>`;
      }).join('');
      els.listenGroupGrid.querySelectorAll('input[type=checkbox]').forEach((input) => {
        input.addEventListener('change', () => {
          const card = input.closest('.group-card');
          if (card) {
            card.classList.toggle('on', input.checked);
            card.classList.toggle('off', !input.checked);
            const badge = card.querySelector('.group-badge');
            if (badge) {
              badge.textContent = input.checked ? 'Đang bật' : 'Tắt';
              badge.className = input.checked ? 'group-badge on' : 'group-badge off';
            }
          }
          syncExcludeFromForm();
        });
      });
      updateListenCount();
    }
    function renderList() {
      els.list.innerHTML = state.filters.map((filter,index) => {
        const selected = index === state.selected ? 'selected' : '';
        const enabled = filter.enabled !== false;
        const bagLeft = boxExactFromFilter(filter, 'min_box1', 'max_box1');
        const bagRight = boxExactFromFilter(filter, 'min_box2', 'max_box2');
        const bag = (bagLeft !== undefined || bagRight !== undefined)
          ? `BAG ${bagLeft ?? '*'}/${bagRight ?? '*'}`
          : '';
        const meta = [
          bag,
          fmtRange(filter.min_rate, filter.max_rate, 'rate '),
          fmtRange(filter.min_level, filter.max_level, 'lv '),
          filter.priority !== undefined ? `p${filter.priority}` : '',
          Array.isArray(filter.text_contains) && filter.text_contains.length
            ? `"${filter.text_contains[0]}"${filter.text_contains.length > 1 ? ` +${filter.text_contains.length - 1}` : ''}`
            : '',
        ].filter(Boolean).join(' | ');
        return `<li class="filter-row ${selected}" data-index="${index}"><div><div class="filter-name">${esc(filter.name || `filter_${index + 1}`)}</div><div class="filter-meta">${esc(meta || 'không giới hạn')}</div></div><span class="pill ${enabled ? 'on' : 'off'}">${enabled ? 'bật' : 'tắt'}</span></li>`;
      }).join('');
      els.list.querySelectorAll('.filter-row').forEach((row) => row.addEventListener('click', () => {
        syncFormToFilter();
        state.selected = Number(row.dataset.index);
        render();
      }));
    }
    function setVal(el, value) { el.value = value === undefined || value === null ? '' : value; }
    function renderForm() {
      const filter = currentFilter();
      const has = !!filter;
      els.editorEmpty.hidden = has || state.filters.length > 0 ? has : false;
      els.editorEmpty.hidden = has;
      els.editorBody.hidden = !has;
      if (!filter) {
        const rejectTokens = [];
        (state.reject || []).forEach((rule) => {
          if (rule.enabled === false) return;
          (rule.comment_contains || []).forEach((v) => rejectTokens.push(v));
          (rule.text_contains || []).forEach((v) => rejectTokens.push(v));
        });
        els.rejectComment.value = rejectTokens.join(',');
        renderListenGroupGrid();
        return;
      }
      els.name.value = filter.name || '';
      els.priority.value = filter.priority ?? '';
      els.enabled.checked = filter.enabled !== false;
      setVal(els.box1, boxExactFromFilter(filter, 'min_box1', 'max_box1'));
      setVal(els.box2, boxExactFromFilter(filter, 'min_box2', 'max_box2'));
      setVal(els.minRate, filter.min_rate);
      setVal(els.maxRate, filter.max_rate);
      setVal(els.minLevel, filter.min_level);
      setVal(els.maxLevel, filter.max_level);
      els.textContains.value = textContainsToInput(filter.text_contains || []);
      renderTextContainsPreview(filter.text_contains || []);
      renderListenGroupGrid();
      const rejectTokens = [];
      (state.reject || []).forEach((rule) => {
        if (rule.enabled === false) return;
        (rule.comment_contains || []).forEach((v) => rejectTokens.push(v));
        (rule.text_contains || []).forEach((v) => rejectTokens.push(v));
      });
      els.rejectComment.value = rejectTokens.join(',');
    }
    function render() { renderList(); renderForm(); }
    function newFilter() {
      return {
        name: `filter_${state.filters.length + 1}`,
        enabled: true,
        priority: 100,
      };
    }
    async function loadWatchGroups() {
      try {
        const res = await fetch('/api/watch-groups?_=' + Date.now(), { cache:'no-store' });
        const data = await res.json();
        state.watchGroups = (data.groups || []).filter((g) => g.enabled !== false);
      } catch (_) {
        state.watchGroups = [];
      }
    }
    async function loadFilters() {
      await loadWatchGroups();
      const res = await fetch('/api/filters?_=' + Date.now(), { cache:'no-store' });
      const data = await res.json(); if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
      state.path = data.path || '';
      state.filters = Array.isArray(data.filters) ? data.filters : [];
      state.reject = Array.isArray(data.reject) ? data.reject : [];
      state.excludeGroups = Array.isArray(data.exclude_telegram_groups) ? data.exclude_telegram_groups : [];
      state.selected = Math.min(state.selected, Math.max(0, state.filters.length - 1));
      els.path.textContent = state.path;
      const listening = listeningGroupIds().length;
      const excludeNote = state.excludeGroups.length ? ` | tắt ${state.excludeGroups.length} nhóm` : '';
      els.status.textContent = `Đã tải ${state.filters.length} bộ lọc` + (state.reject.length ? ` | chặn ${state.reject.length}` : '') + (listening ? ` | lắng nghe ${listening} nhóm` : '') + excludeNote;
      render();
    }
    async function saveFilters() {
      syncFormToFilter();
      syncExcludeFromForm();
      const res = await fetch('/api/filters', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({ filters:state.filters, reject:state.reject, exclude_telegram_groups:state.excludeGroups }) });
      const data = await res.json(); if (!res.ok) throw new Error(data.error || 'Lưu thất bại');
      state.filters = data.filters || [];
      state.reject = data.reject || [];
      state.excludeGroups = Array.isArray(data.exclude_telegram_groups) ? data.exclude_telegram_groups : [];
      state.selected = Math.min(state.selected, Math.max(0, state.filters.length - 1));
      const listening = listeningGroupIds().length;
      const excludeNote = state.excludeGroups.length ? ` | tắt ${state.excludeGroups.length} nhóm` : '';
      els.status.textContent = `Đã lưu ${state.filters.length} bộ lọc` + (state.reject.length ? ` | chặn ${state.reject.length}` : '') + (listening ? ` | lắng nghe ${listening} nhóm` : '') + excludeNote;
      render();
    }
    $('listenAllBtn').addEventListener('click', () => {
      state.excludeGroups = [];
      renderListenGroupGrid();
      els.status.textContent = 'Đã bật lắng nghe tất cả nhóm';
    });
    $('listenNoneBtn').addEventListener('click', () => {
      state.excludeGroups = allWatchGroupIds();
      renderListenGroupGrid();
      els.status.textContent = 'Đã tắt lắng nghe tất cả nhóm';
    });
    $('watchGroupsBtn').addEventListener('click', () => { location.href = '/watch-groups'; });
    els.textContains.addEventListener('input', () => {
      renderTextContainsPreview(parseTextContains(els.textContains.value));
    });
    (function initHeaderCollapse() {
      const shell = document.getElementById('filterShell');
      const btn = document.getElementById('headerCollapseBtn');
      if (!shell || !btn) return;
      const storageKey = 'click-live-filter-header-collapsed';
      function apply(collapsed) {
        shell.classList.toggle('header-collapsed', collapsed);
        btn.textContent = collapsed ? '▼' : '▲';
        btn.title = collapsed ? 'Mở rộng header' : 'Thu gọn header';
        btn.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
      }
      apply(localStorage.getItem(storageKey) === '1');
      btn.addEventListener('click', () => {
        const next = !shell.classList.contains('header-collapsed');
        apply(next);
        localStorage.setItem(storageKey, next ? '1' : '0');
      });
    })();
    $('queueBtn').addEventListener('click', () => window.location.href = '/');
    $('reloadBtn').addEventListener('click', () => loadFilters().catch((err) => els.status.textContent = err.message));
    $('saveBtn').addEventListener('click', () => saveFilters().catch((err) => els.status.textContent = err.message));
    $('addBtn').addEventListener('click', () => { syncFormToFilter(); state.filters.push(newFilter()); state.selected = state.filters.length - 1; render(); els.status.textContent = 'Đã thêm'; });
    $('copyBtn').addEventListener('click', () => {
      syncFormToFilter();
      const filter = currentFilter(); if (!filter) return;
      const copy = JSON.parse(JSON.stringify(filter));
      copy.name = `${copy.name || 'filter'}_copy`;
      state.filters.splice(state.selected + 1, 0, copy);
      state.selected += 1;
      render();
      els.status.textContent = 'Đã nhân bản';
    });
    $('deleteBtn').addEventListener('click', () => {
      if (!currentFilter()) return;
      state.filters.splice(state.selected, 1);
      state.selected = Math.min(state.selected, Math.max(0, state.filters.length - 1));
      render();
      els.status.textContent = 'Đã xóa';
    });
    document.querySelectorAll('input').forEach((node) => {
      node.addEventListener('input', () => { syncFormToFilter(); renderList(); });
      node.addEventListener('change', () => { syncFormToFilter(); renderList(); });
    });
    loadFilters().catch((err) => els.status.textContent = err.message);
  </script>
  <script>
""" + LOGOUT_SCRIPT + r"""
</body>
</html>
"""

BROADCAST_HTML = r"""<!doctype html>
<html lang="vi">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Nhóm nhận Bot broadcast</title>
  <style>
    :root { --bg:#f5f6f8; --surface:#fff; --border:#d7dce2; --text:#20242a; --muted:#66707b; --blue:#1d5fd0; --green:#17803d; --amber:#9a6500; --red:#b42318; }
    * { box-sizing:border-box; }
    body { margin:0; min-height:100vh; background:var(--bg); color:var(--text); font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }
    button,input,textarea { font:inherit; }
    .shell { min-height:100vh; display:grid; grid-template-rows:auto auto 1fr; }
    .topbar,.subbar { display:flex; align-items:center; justify-content:space-between; gap:12px; padding:0 20px; background:#151922; color:#f9fafb; }
    .topbar { min-height:58px; }
    .subbar { min-height:46px; background:#1d2430; border-top:1px solid #252b36; }
    h1 { margin:0; font-size:18px; }
    .toolbar { display:flex; gap:8px; flex-wrap:wrap; }
    .button { height:34px; display:inline-flex; align-items:center; justify-content:center; border:1px solid #394252; background:#263040; color:#f9fafb; border-radius:6px; padding:0 12px; cursor:pointer; }
    .button.primary { background:var(--blue); border-color:#3170df; }
    .button.danger { background:#4a2530; border-color:#6d3342; }
    .tabs { display:flex; gap:8px; }
    .tab { height:30px; border:1px solid #394252; background:#263040; color:#f9fafb; border-radius:999px; padding:0 12px; cursor:pointer; }
    .tab.active { background:var(--blue); border-color:#3170df; }
    .main { display:grid; grid-template-columns:360px minmax(0,1fr); min-height:0; background:var(--surface); }
    .list-pane { border-right:1px solid var(--border); overflow:auto; background:#fbfcfd; }
    .list-head { padding:12px; border-bottom:1px solid var(--border); background:#eef1f4; position:sticky; top:0; }
    .group-list { list-style:none; margin:0; padding:0; }
    .group-row { display:grid; grid-template-columns:minmax(0,1fr) auto; gap:8px; padding:12px; border-bottom:1px solid #edf0f3; cursor:pointer; }
    .group-row.selected { background:#edf4ff; box-shadow:inset 3px 0 0 var(--blue); }
    .group-name { font-weight:700; font-size:13px; }
    .group-meta { color:var(--muted); font-size:12px; margin-top:4px; word-break:break-all; }
    .pill { display:inline-flex; align-items:center; height:22px; padding:0 8px; border-radius:999px; font-size:12px; font-weight:700; white-space:nowrap; }
    .pill.pending { color:var(--amber); background:#fff7e8; border:1px solid #f0d199; }
    .pill.approved { color:var(--green); background:#eaf7ee; border:1px solid #a8dfba; }
    .pill.off { color:var(--red); background:#fff0ee; border:1px solid #f5b6ad; }
    .editor { padding:18px; overflow:auto; }
    .form-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:14px; }
    .field { display:flex; flex-direction:column; gap:6px; }
    .field.full { grid-column:1 / -1; }
    label { color:var(--muted); font-size:12px; font-weight:700; text-transform:uppercase; }
    input,textarea { width:100%; border:1px solid var(--border); border-radius:6px; padding:9px 10px; }
    textarea { min-height:100px; resize:vertical; }
    .status,.hint { margin-top:12px; padding:10px; border:1px solid var(--border); border-radius:6px; background:#fbfcfd; color:var(--muted); font-size:13px; line-height:1.45; white-space:pre-wrap; }
    .hint { margin-top:0; margin-bottom:12px; background:#fffdf5; border-color:#f0d199; }
    .bot-panel { margin-bottom:12px; padding:12px; border:1px solid var(--border); border-radius:8px; background:#f8fbff; }
    .bot-panel h2 { margin:0 0 10px; font-size:14px; }
    .bot-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(220px,1fr)); gap:10px; }
    .bot-card { border:1px solid var(--border); border-radius:8px; padding:10px; background:#fff; }
    .bot-title { font-weight:700; font-size:13px; }
    .bot-meta { color:var(--muted); font-size:12px; margin-top:4px; line-height:1.45; word-break:break-all; }
    .pill.ok { color:var(--green); background:#eaf7ee; border:1px solid #a8dfba; }
    .pill.err { color:var(--red); background:#fff0ee; border:1px solid #f5b6ad; }
  </style>
</head>
<body>
  <div class="shell">
    <header class="topbar">
      <h1>Nhóm nhận Bot broadcast</h1>
      <div class="toolbar">
        <button id="queueBtn" class="button">Hàng đợi</button>
        <button id="watchBtn" class="button">Nhóm theo dõi</button>
        <button id="botsBtn" class="button">Bot (24)</button>
        <button id="discoverBtn" class="button primary">Quét nhóm bot vừa được add</button>
        <button id="reloadBtn" class="button">Tải lại</button>
        <button id="logoutBtn" class="button">Đăng xuất</button>
      </div>
    </header>
    <div class="subbar">
      <div class="tabs">
        <button id="tabPending" class="tab active">Chờ duyệt</button>
        <button id="tabApproved" class="tab">Đã duyệt</button>
      </div>
      <div id="summary" class="hint" style="margin:0;border:0;background:transparent;color:#aeb6c3;padding:0;">Sẵn sàng</div>
    </div>
    <main class="main">
      <section class="list-pane">
        <div class="list-head" id="listTitle">Nhóm chờ duyệt</div>
        <ul id="groupList" class="group-list"></ul>
      </section>
      <section class="editor">
        <div id="botPanel" class="bot-panel">
          <h2>Bot broadcast đang cấu hình</h2>
          <div id="botGrid" class="bot-grid"><div class="bot-card"><div class="bot-title">Đang tải bot...</div></div></div>
        </div>
        <div id="botHint" class="hint">
          <b>Telethon session</b> chỉ dùng để đọc tin từ nhóm nguồn.<br>
          Các bot bên trên gửi tin tới nhóm đã add bot và được <b>duyệt trên web</b>.<br>
          <b>Quét nhóm</b> chỉ thấy group có update gần đây (add bot / nhắn tin). Bot API <b>không list</b> hết group cũ.
          Nếu không ra: kick bot → add lại, hoặc gửi 1 tin trong group, hoặc nhập Chat ID bên dưới.
        </div>
        <div class="form-grid" style="margin-bottom:14px;">
          <div class="field"><label for="manualNameInput">Thêm thủ công — Tên</label><input id="manualNameInput" placeholder="Tên nhóm"></div>
          <div class="field"><label for="manualChatIdInput">Chat ID</label><input id="manualChatIdInput" placeholder="-100xxxxxxxxxx"></div>
          <div class="field full"><button id="manualAddBtn" class="button">Thêm vào chờ duyệt</button></div>
        </div>
        <div class="form-grid">
          <div class="field"><label for="nameInput">Tên nhóm</label><input id="nameInput"></div>
          <div class="field"><label for="chatIdInput">Chat ID</label><input id="chatIdInput" readonly></div>
          <div class="field"><label class="checkline"><input id="enabledInput" type="checkbox"> Bật</label></div>
          <div class="field full">
            <button id="approveBtn" class="button primary">Duyệt nhóm này</button>
            <button id="saveBtn" class="button">Lưu nhóm đã duyệt</button>
            <button id="deleteBtn" class="button danger">Xóa</button>
          </div>
          <div class="field full"><label for="testTextInput">Tin test</label><textarea id="testTextInput" placeholder="Nội dung tin test broadcast..."></textarea></div>
          <div class="field"><button id="testOneBtn" class="button">Test nhóm đang chọn</button></div>
          <div class="field"><button id="testAllBtn" class="button primary">Test tất cả nhóm đã duyệt</button></div>
        </div>
        <div id="status" class="status">Sẵn sàng</div>
      </section>
    </main>
  </div>
  <script>
    const state = { tab:'pending', pending:[], approved:[], selected:0, bots:[] };
    const $ = (id) => document.getElementById(id);
    const els = { list:$('groupList'), status:$('status'), summary:$('summary'), listTitle:$('listTitle'), name:$('nameInput'), chatId:$('chatIdInput'), enabled:$('enabledInput'), testText:$('testTextInput'), approveBtn:$('approveBtn'), saveBtn:$('saveBtn'), botGrid:$('botGrid') };
    function esc(v){ return String(v ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
    function groups(){ return state.tab === 'pending' ? state.pending : state.approved; }
    function current(){ return groups()[state.selected] || null; }
    function syncForm(){
      const g = current(); if (!g) return;
      g.name = els.name.value.trim() || g.name;
      g.enabled = els.enabled.checked;
    }
    function renderList(){
      const items = groups();
      els.listTitle.textContent = state.tab === 'pending' ? 'Nhóm chờ duyệt' : 'Nhóm đã duyệt';
      els.list.innerHTML = items.length ? items.map((g,i) => {
        const pill = state.tab === 'pending' ? 'pending' : (g.enabled !== false ? 'approved' : 'off');
        const pillText = state.tab === 'pending' ? 'chờ' : (g.enabled !== false ? 'bật' : 'tắt');
        return `<li class="group-row ${i===state.selected?'selected':''}" data-index="${i}"><div><div class="group-name">${esc(g.name)}</div><div class="group-meta">${esc(g.chat_id)}</div></div><span class="pill ${pill}">${pillText}</span></li>`;
      }).join('') : `<li class="group-row"><div><div class="group-name">Không có nhóm</div><div class="group-meta">Add bot vào nhóm rồi bấm Quét</div></div></li>`;
      els.list.querySelectorAll('.group-row[data-index]').forEach((row) => row.addEventListener('click', () => { syncForm(); state.selected = Number(row.dataset.index); renderForm(); renderList(); }));
      els.summary.textContent = `Bot ${state.bots.length} | Chờ duyệt ${state.pending.length} | Đã duyệt ${state.approved.length}`;
    }
    function renderBots(){
      const bots = state.bots || [];
      els.botGrid.innerHTML = bots.length ? bots.map((bot) => {
        const pill = bot.ok ? 'ok' : 'err';
        const pillText = bot.ok ? 'OK' : 'Lỗi';
        const title = esc(bot.display_name || bot.first_name || `Bot ${bot.index}`);
        const mention = bot.mention ? `<div class="bot-meta">${esc(bot.mention)}</div>` : '';
        const meta = bot.ok
          ? `<div class="bot-meta">ID: ${esc(bot.id)}</div><div class="bot-meta">Token: ${esc(bot.token_hint)}</div>`
          : `<div class="bot-meta">${esc(bot.error || 'Không kết nối được Bot API')}</div>`;
        return `<div class="bot-card"><div style="display:flex;justify-content:space-between;gap:8px;align-items:start;"><div><div class="bot-title">#${bot.index} ${title}</div>${mention}${meta}</div><span class="pill ${pill}">${pillText}</span></div></div>`;
      }).join('') : `<div class="bot-card"><div class="bot-title">Chưa cấu hình bot</div><div class="bot-meta">Thêm TELEGRAM_BOT_TOKEN hoặc TELEGRAM_BOT_TOKENS trong .env</div></div>`;
    }
    function renderForm(){
      const g = current();
      const approvedTab = state.tab === 'approved';
      els.name.disabled = !g;
      els.enabled.disabled = !g || !approvedTab;
      els.approveBtn.style.display = state.tab === 'pending' && g ? 'inline-flex' : 'none';
      els.saveBtn.style.display = approvedTab ? 'inline-flex' : 'none';
      els.name.value = g?.name || '';
      els.chatId.value = g?.chat_id || '';
      els.enabled.checked = g ? g.enabled !== false : false;
      ['testOneBtn','testAllBtn','deleteBtn'].forEach((id) => { $(id).disabled = !g; });
    }
    function setTab(tab){
      state.tab = tab;
      state.selected = 0;
      $('tabPending').classList.toggle('active', tab === 'pending');
      $('tabApproved').classList.toggle('active', tab === 'approved');
      renderList(); renderForm();
    }
    async function loadBots(){
      const res = await fetch('/api/broadcast-bots?_=' + Date.now(), { cache:'no-store' });
      const data = await res.json(); if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
      state.bots = data.bots || [];
      renderBots();
      renderList();
    }
    async function loadGroups(){
      const res = await fetch('/api/broadcast-groups?_=' + Date.now(), { cache:'no-store' });
      const data = await res.json(); if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
      state.pending = data.pending || [];
      state.approved = data.approved || [];
      state.selected = Math.min(state.selected, Math.max(0, groups().length - 1));
      renderList(); renderForm();
    }
    async function discoverGroups(){
      els.status.textContent = 'Đang quét getUpdates trên tất cả bot...';
      const res = await fetch('/api/broadcast-groups/discover', { method:'POST' });
      const data = await res.json(); if (!res.ok) throw new Error(data.error || 'Discover failed');
      state.pending = data.pending || [];
      state.approved = data.approved || [];
      state.tab = 'pending';
      setTab('pending');
      const scans = data.scans || [];
      const withUpdates = scans.filter((s) => (s.update_count || s.count || 0) > 0).length;
      const empty = scans.length - withUpdates;
      const names = (data.new_pending || []).map((g) => g.name).filter(Boolean);
      const parts = [
        `Thêm mới ${data.added || 0}`,
        `cập nhật ${data.updated || 0}`,
        `đã duyệt sẵn ${data.already_approved || 0}`,
        `bot có update ${withUpdates}/${scans.length}`,
      ];
      if (names.length) parts.push('mới: ' + names.join(', '));
      if (empty > 0) parts.push(`${empty} bot chưa có update (add lại bot hoặc nhắn 1 tin trong group)`);
      els.status.textContent = 'Quét xong: ' + parts.join(' | ');
    }
    async function manualAddGroup(){
      const name = $('manualNameInput').value.trim();
      const chatId = $('manualChatIdInput').value.trim();
      if (!chatId) throw new Error('Nhập Chat ID');
      const res = await fetch('/api/broadcast-groups/manual-add', {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({ name, chat_id: chatId }),
      });
      const data = await res.json(); if (!res.ok) throw new Error(data.error || 'Add failed');
      state.pending = data.pending || [];
      state.approved = data.approved || [];
      state.tab = 'pending';
      setTab('pending');
      $('manualChatIdInput').value = '';
      els.status.textContent = data.created ? `Đã thêm ${chatId} vào chờ duyệt` : `Đã cập nhật ${chatId}`;
    }
    async function approveCurrent(){
      const g = current(); if (!g?.id) throw new Error('Chọn nhóm pending');
      syncForm();
      const res = await fetch('/api/broadcast-groups/approve', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({ id:g.id, name:els.name.value.trim() || g.name }) });
      const data = await res.json(); if (!res.ok) throw new Error(data.error || 'Approve failed');
      state.pending = data.pending || [];
      state.approved = data.approved || [];
      state.tab = 'approved';
      state.selected = Math.max(0, state.approved.length - 1);
      setTab('approved');
      els.status.textContent = `Đã duyệt ${g.name}`;
    }
    async function saveApproved(){
      syncForm();
      const res = await fetch('/api/broadcast-groups', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({ groups: state.approved }) });
      const data = await res.json(); if (!res.ok) throw new Error(data.error || 'Save failed');
      state.pending = data.pending || [];
      state.approved = data.approved || [];
      els.status.textContent = `Đã lưu ${state.approved.length} nhóm đã duyệt`;
      renderList(); renderForm();
    }
    async function deleteCurrent(){
      const g = current(); if (!g?.id) return;
      const res = await fetch('/api/broadcast-groups/delete', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({ id:g.id }) });
      const data = await res.json(); if (!res.ok) throw new Error(data.error || 'Delete failed');
      state.pending = data.pending || [];
      state.approved = data.approved || [];
      state.selected = Math.min(state.selected, Math.max(0, groups().length - 1));
      renderList(); renderForm();
    }
    async function testSend(all){
      const text = els.testText.value.trim();
      if (!text) throw new Error('Nhập nội dung tin test');
      const body = { text, all };
      if (!all) {
        const g = current(); if (!g?.chat_id) throw new Error('Chọn nhóm');
        body.chat_id = g.chat_id;
      }
      const res = await fetch('/api/broadcast-groups/test', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body) });
      const data = await res.json(); if (!res.ok) throw new Error(data.error || 'Test failed');
      els.status.textContent = JSON.stringify(data, null, 2);
    }
    $('queueBtn').onclick = () => location.href = '/';
    $('watchBtn').onclick = () => location.href = '/watch';
    $('botsBtn').onclick = () => location.href = '/bots';
    $('reloadBtn').onclick = () => Promise.all([loadBots(), loadGroups()]).catch((e) => els.status.textContent = e.message);
    $('discoverBtn').onclick = () => discoverGroups().catch((e) => els.status.textContent = e.message);
    $('manualAddBtn').onclick = () => manualAddGroup().catch((e) => els.status.textContent = e.message);
    $('tabPending').onclick = () => setTab('pending');
    $('tabApproved').onclick = () => setTab('approved');
    $('approveBtn').onclick = () => approveCurrent().catch((e) => els.status.textContent = e.message);
    $('saveBtn').onclick = () => saveApproved().catch((e) => els.status.textContent = e.message);
    $('deleteBtn').onclick = () => deleteCurrent().catch((e) => els.status.textContent = e.message);
    $('testOneBtn').onclick = () => testSend(false).catch((e) => els.status.textContent = e.message);
    $('testAllBtn').onclick = () => testSend(true).catch((e) => els.status.textContent = e.message);
    ['nameInput','enabledInput'].forEach((id) => { $(id).addEventListener('input', () => { syncForm(); renderList(); }); $(id).addEventListener('change', () => { syncForm(); renderList(); }); });
    Promise.all([loadBots(), loadGroups()]).catch((e) => els.status.textContent = e.message);
  </script>
  <script>
""" + LOGOUT_SCRIPT + r"""
</body>
</html>
"""

BOTS_HTML = r"""<!doctype html>
<html lang="vi">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Quản lý Bot</title>
  <style>
    :root { --bg:#f5f6f8; --surface:#fff; --border:#d7dce2; --text:#20242a; --muted:#66707b; --blue:#1d5fd0; --green:#17803d; --red:#b42318; }
    * { box-sizing:border-box; }
    body { margin:0; min-height:100vh; background:var(--bg); color:var(--text); font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }
    button,input { font:inherit; }
    .shell { min-height:100vh; display:grid; grid-template-rows:auto auto 1fr; }
    .topbar,.subbar { display:flex; align-items:center; justify-content:space-between; gap:12px; padding:0 20px; background:#151922; color:#f9fafb; }
    .topbar { min-height:58px; }
    .subbar { min-height:46px; background:#1d2430; border-top:1px solid #252b36; }
    h1 { margin:0; font-size:18px; }
    .toolbar { display:flex; gap:8px; flex-wrap:wrap; }
    .button { height:34px; display:inline-flex; align-items:center; justify-content:center; border:1px solid #394252; background:#263040; color:#f9fafb; border-radius:6px; padding:0 12px; cursor:pointer; }
    .button.primary { background:var(--blue); border-color:#3170df; }
    .main { padding:18px; overflow:auto; }
    .card { background:var(--surface); border:1px solid var(--border); border-radius:8px; padding:16px; }
    table { width:100%; border-collapse:collapse; font-size:13px; }
    th,td { border-bottom:1px solid #edf0f3; padding:10px 8px; text-align:left; vertical-align:middle; }
    th { color:var(--muted); font-size:11px; text-transform:uppercase; background:#fbfcfd; position:sticky; top:0; }
    input[type=text] { width:100%; border:1px solid var(--border); border-radius:6px; padding:8px 10px; }
    .pill { display:inline-flex; align-items:center; height:22px; padding:0 8px; border-radius:999px; font-size:12px; font-weight:700; }
    .pill.on { color:var(--green); background:#eaf7ee; border:1px solid #a8dfba; }
    .pill.off { color:var(--red); background:#fff0ee; border:1px solid #f5b6ad; }
    .hint,.status { margin-top:12px; padding:10px; border:1px solid var(--border); border-radius:6px; background:#fbfcfd; color:var(--muted); font-size:13px; line-height:1.45; }
    .hint { margin-top:0; margin-bottom:12px; background:#fffdf5; border-color:#f0d199; }
    .mono { font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:12px; }
  </style>
</head>
<body>
  <div class="shell">
    <header class="topbar">
      <h1>Bot Telegram</h1>
      <div class="toolbar">
        <button id="queueBtn" class="button">Hàng đợi</button>
        <button id="watchBtn" class="button">Nhóm theo dõi</button>
        <button id="broadcastBtn" class="button">Phát tin</button>
        <button id="importEnvBtn" class="button">Import .env</button>
        <button id="reloadBtn" class="button">Tải lại</button>
        <button id="syncBtn" class="button">Đồng bộ Telegram</button>
        <button id="saveBtn" class="button primary">Lưu</button>
        <button id="logoutBtn" class="button">Đăng xuất</button>
      </div>
    </header>
    <div class="subbar"><div id="summary" style="color:#aeb6c3;">Sẵn sàng</div></div>
    <main class="main">
      <div class="card">
        <div class="hint">Load nhanh từ cache DB. Bấm <b>Đồng bộ Telegram</b> khi cần gọi getMe lại (song song). Mỗi nhóm theo dõi chọn list bot riêng.</div>
        <table>
          <thead><tr><th>Slot</th><th>Tên</th><th>@username</th><th>Token</th><th>Bật</th></tr></thead>
          <tbody id="botRows"></tbody>
        </table>
        <div id="status" class="status">Sẵn sàng</div>
      </div>
    </main>
  </div>
  <script>
    const state = { bots: [] };
    const $ = (id) => document.getElementById(id);
    function esc(v){ return String(v ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
    function render(){
      $('botRows').innerHTML = state.bots.map((b) => {
        const user = b.username ? '@' + b.username : (b.telegram_username ? '@' + b.telegram_username : '-');
        const pill = b.enabled !== false ? 'on' : 'off';
        return `<tr data-id="${b.id}">
          <td class="mono">${esc(b.short_name)}</td>
          <td>${esc(b.display_name || b.telegram_display_name || b.short_name)}</td>
          <td class="mono">${esc(user)}</td>
          <td><input data-field="token" type="text" value="${esc(b.token || '')}" placeholder="${esc(b.token_hint || 'token...')}"></td>
          <td><label><input data-field="enabled" type="checkbox" ${b.enabled !== false ? 'checked' : ''}> <span class="pill ${pill}">${b.enabled !== false ? 'on' : 'off'}</span></label></td>
        </tr>`;
      }).join('');
      const active = state.bots.filter((b) => b.enabled !== false && (b.token || '').trim()).length;
      $('summary').textContent = `${active}/${state.bots.length} bot có token`;
    }
    function collect(){
      return state.bots.map((b) => {
        const row = document.querySelector(`tr[data-id="${b.id}"]`);
        const token = row?.querySelector('[data-field="token"]')?.value?.trim() || b.token || '';
        const enabled = !!row?.querySelector('[data-field="enabled"]')?.checked;
        return { short_name:b.short_name, token, enabled, sort_order:b.sort_order, telegram_username:b.telegram_username, telegram_display_name:b.telegram_display_name };
      });
    }
    async function load(refresh=false){
      $('status').textContent = refresh ? 'Đang đồng bộ Telegram...' : 'Đang tải cache...';
      const url = '/api/bot-slots?_=' + Date.now() + (refresh ? '&refresh=1' : '');
      const res = await fetch(url, { cache:'no-store' });
      const data = await res.json(); if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
      state.bots = data.bots || [];
      render();
      const mode = data.from_cache ? 'cache' : 'telegram';
      $('status').textContent = `Đã tải ${state.bots.length} bot (${mode}${data.refreshed ? `, sync ${data.refreshed}` : ''}).`;
    }
    async function save(){
      const res = await fetch('/api/bot-slots', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({ bots: collect() }) });
      const data = await res.json(); if (!res.ok) throw new Error(data.error || 'Save failed');
      state.bots = data.bots || [];
      render();
      $('status').textContent = 'Đã lưu bot slots. Restart broadcast worker để áp dụng token mới.';
    }
    async function importEnv(){
      const res = await fetch('/api/bot-slots/import-env', { method:'POST' });
      const data = await res.json(); if (!res.ok) throw new Error(data.error || 'Import failed');
      state.bots = data.bots || [];
      render();
      $('status').textContent = data.imported ? `Import ${data.imported} token từ .env` : 'Không có token mới';
    }
    $('queueBtn').onclick = () => location.href = '/';
    $('watchBtn').onclick = () => location.href = '/watch';
    $('broadcastBtn').onclick = () => location.href = '/broadcast';
    $('reloadBtn').onclick = () => load(false).catch((e) => $('status').textContent = e.message);
    $('syncBtn').onclick = () => load(true).catch((e) => $('status').textContent = e.message);
    $('saveBtn').onclick = () => save().catch((e) => $('status').textContent = e.message);
    $('importEnvBtn').onclick = () => importEnv().catch((e) => $('status').textContent = e.message);
    load(false).catch((e) => $('status').textContent = e.message);
  </script>
  <script>
""" + LOGOUT_SCRIPT + r"""
</body>
</html>
"""

WATCH_HTML = r"""<!doctype html>
<html lang="vi">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Nhóm theo dõi Telethon</title>
  <style>
    :root { --bg:#f5f6f8; --surface:#fff; --border:#d7dce2; --text:#20242a; --muted:#66707b; --blue:#1d5fd0; --green:#17803d; --red:#b42318; }
    * { box-sizing:border-box; }
    body { margin:0; min-height:100vh; background:var(--bg); color:var(--text); font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }
    button,input,textarea { font:inherit; }
    .shell { min-height:100vh; display:grid; grid-template-rows:auto auto 1fr; }
    .topbar,.subbar { display:flex; align-items:center; justify-content:space-between; gap:12px; padding:0 20px; background:#151922; color:#f9fafb; }
    .topbar { min-height:58px; }
    .subbar { min-height:46px; background:#1d2430; border-top:1px solid #252b36; }
    h1 { margin:0; font-size:18px; }
    .toolbar { display:flex; gap:8px; flex-wrap:wrap; }
    .button { height:34px; display:inline-flex; align-items:center; justify-content:center; border:1px solid #394252; background:#263040; color:#f9fafb; border-radius:6px; padding:0 12px; cursor:pointer; }
    .button.primary { background:var(--blue); border-color:#3170df; }
    .button.danger { background:#4a2530; border-color:#6d3342; }
    .main { display:grid; grid-template-columns:360px minmax(0,1fr); min-height:0; background:var(--surface); }
    .list-pane { border-right:1px solid var(--border); overflow:auto; background:#fbfcfd; }
    .list-head { padding:12px; border-bottom:1px solid var(--border); background:#eef1f4; position:sticky; top:0; }
    .group-list { list-style:none; margin:0; padding:0; }
    .group-row { display:grid; grid-template-columns:minmax(0,1fr) auto; gap:8px; padding:12px; border-bottom:1px solid #edf0f3; cursor:pointer; }
    .group-row.selected { background:#edf4ff; box-shadow:inset 3px 0 0 var(--blue); }
    .group-name { font-weight:700; font-size:13px; }
    .group-meta { color:var(--muted); font-size:12px; margin-top:4px; word-break:break-all; }
    .pill { display:inline-flex; align-items:center; height:22px; padding:0 8px; border-radius:999px; font-size:12px; font-weight:700; white-space:nowrap; }
    .pill.on { color:var(--green); background:#eaf7ee; border:1px solid #a8dfba; }
    .pill.off { color:var(--red); background:#fff0ee; border:1px solid #f5b6ad; }
    .editor { padding:18px; overflow:auto; }
    .form-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:14px; }
    .field { display:flex; flex-direction:column; gap:6px; }
    .field.full { grid-column:1 / -1; }
    label { color:var(--muted); font-size:12px; font-weight:700; text-transform:uppercase; }
    input,textarea { width:100%; border:1px solid var(--border); border-radius:6px; padding:9px 10px; }
    .status,.hint { margin-top:12px; padding:10px; border:1px solid var(--border); border-radius:6px; background:#fbfcfd; color:var(--muted); font-size:13px; line-height:1.45; white-space:pre-wrap; }
    .hint { margin-top:0; margin-bottom:12px; background:#fffdf5; border-color:#f0d199; }
    .checkline { display:flex; align-items:center; gap:8px; min-height:38px; }
    .bot-add-row { display:flex; gap:8px; align-items:center; }
    .bot-add-row input { flex:1; }
    .bot-tags { display:flex; flex-wrap:wrap; gap:8px; margin-top:10px; min-height:36px; }
    .bot-tag { display:inline-flex; align-items:center; gap:8px; border:1px solid #b8d4f5; border-radius:6px; padding:6px 10px; background:#edf4ff; font-size:13px; }
    .bot-tag .mono { font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-weight:700; }
    .bot-tag button { border:0; background:transparent; cursor:pointer; color:var(--red); font-size:16px; line-height:1; padding:0; }
    .bot-empty { color:var(--muted); font-size:13px; padding:8px 0; }
    .env-bot-list { display:flex; flex-wrap:wrap; gap:8px; margin-top:8px; }
    .env-bot-pick { display:inline-flex; align-items:center; border:1px dashed #b8c4d6; border-radius:6px; padding:6px 10px; background:#fff; font-size:12px; cursor:pointer; color:var(--blue); }
    .env-bot-pick:hover { background:#edf4ff; border-color:#8eb8ea; }
  </style>
</head>
<body>
  <div class="shell">
    <header class="topbar">
      <h1>Nhóm theo dõi (Telethon)</h1>
      <div class="toolbar">
        <button id="queueBtn" class="button">Hàng đợi</button>
        <button id="botsBtn" class="button">Bot (24)</button>
        <button id="broadcastBtn" class="button">Phát tin</button>
        <button id="importEnvBtn" class="button">Import từ .env</button>
        <button id="reloadBtn" class="button">Tải lại</button>
        <button id="logoutBtn" class="button">Đăng xuất</button>
      </div>
    </header>
    <div class="subbar">
      <div id="summary" class="hint" style="margin:0;border:0;background:transparent;color:#aeb6c3;padding:0;">Sẵn sàng</div>
    </div>
    <main class="main">
      <section class="list-pane">
        <div class="list-head">Nhóm nguồn đang theo dõi</div>
        <ul id="groupList" class="group-list"></ul>
      </section>
      <section class="editor">
        <div class="hint">
          <b>Telethon session</b> (tài khoản của bạn) đọc tin từ các nhóm này.<br>
          Tin khớp filter sẽ vào queue. Chỉ các bot được chọn bên dưới mới gửi broadcast cho nhóm này.
        </div>
        <div class="form-grid">
          <div class="field"><label for="nameInput">Tên nhóm</label><input id="nameInput" placeholder="Moon v7.81"></div>
          <div class="field"><label for="chatIdInput">Chat ID / @username</label><input id="chatIdInput" placeholder="-1003431776950"></div>
          <div class="field"><label class="checkline"><input id="enabledInput" type="checkbox" checked> Bật</label></div>
          <div class="field full">
            <label for="botIdInput">Bot gửi tin cho nhóm này</label>
            <div class="bot-add-row">
              <input id="botIdInput" placeholder="@clone_tetris02_bot, @cl_bot1_bot">
              <button id="addBotBtn" class="button primary" type="button">Thêm bot</button>
            </div>
            <div id="envBotList" class="env-bot-list"></div>
            <div id="botTags" class="bot-tags"></div>
            <div class="group-meta" style="margin-top:8px;">Chỉ dùng bot có token trong <b>.env</b> (<code>TELEGRAM_BOT_TOKEN</code> / <code>TELEGRAM_BOT_TOKENS</code>). Nhập <b>@username</b> hoặc bấm tên bên trên.</div>
          </div>
          <div class="field full">
            <button id="addBtn" class="button primary">Thêm nhóm</button>
            <button id="saveBtn" class="button">Lưu thay đổi</button>
            <button id="deleteBtn" class="button danger">Xóa nhóm đang chọn</button>
          </div>
        </div>
        <div id="status" class="status">Sẵn sàng</div>
      </section>
    </main>
  </div>
  <script>
    const state = { groups:[], selected:0, bots:[] };
    const $ = (id) => document.getElementById(id);
    const els = { list:$('groupList'), status:$('status'), summary:$('summary'), name:$('nameInput'), chatId:$('chatIdInput'), enabled:$('enabledInput'), botIdInput:$('botIdInput'), botTags:$('botTags'), envBotList:$('envBotList') };
    function esc(v){ return String(v ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
    function current(){ return state.groups[state.selected] || null; }
    function botById(){ return Object.fromEntries(state.bots.map((b) => [Number(b.id), b])); }
    function botUsername(bot){ return String(bot?.username || '').trim().toLowerCase().replace(/^@+/, ''); }
    function botDisplayName(bot){ return bot?.name || (bot?.username ? '@' + bot.username : '?'); }
    function buildBotLookups(){
      const byUsername = {};
      for (const b of state.bots) {
        const username = botUsername(b);
        if (username) byUsername[username] = b;
      }
      return { byUsername };
    }
    function parseBotRefs(text){
      return String(text || '').split(/[\s,;]+/).map((v) => v.trim()).filter(Boolean);
    }
    function findBot(ref){
      const key = String(ref || '').trim().toLowerCase().replace(/^@+/, '');
      if (!key) return null;
      return buildBotLookups().byUsername[key] || null;
    }
    function availableBotNames(){
      return state.bots.map((b) => botDisplayName(b)).filter((v) => v && v !== '?');
    }
    function ensureBotIds(g){
      if (!Array.isArray(g.bot_ids)) g.bot_ids = [];
      return g.bot_ids;
    }
    function syncForm(){
      const g = current(); if (!g) return;
      g.name = els.name.value.trim() || g.name;
      g.enabled = els.enabled.checked;
    }
    function addBotByUsername(username){
      const g = current(); if (!g) throw new Error('Chọn nhóm trước');
      const bot = findBot(username);
      if (!bot) throw new Error('Bot không có trong .env: ' + username);
      const ids = ensureBotIds(g);
      const id = Number(bot.id);
      if (!ids.includes(id)) ids.push(id);
      renderBotTags(); renderList();
      return botDisplayName(bot);
    }
    function addBotsFromInput(){
      const g = current(); if (!g) throw new Error('Chọn nhóm trước');
      const refs = parseBotRefs(els.botIdInput.value);
      if (!refs.length) throw new Error('Nhập @username bot từ danh sách .env');
      const added = [];
      const unknown = [];
      for (const ref of refs) {
        try {
          const name = addBotByUsername(ref);
          if (!added.includes(name)) added.push(name);
        } catch (e) {
          unknown.push(ref);
        }
      }
      if (unknown.length) {
        const hint = availableBotNames().join(', ');
        throw new Error('Bot không có trong .env: ' + unknown.join(', ') + (hint ? ' — có: ' + hint : ''));
      }
      els.botIdInput.value = '';
      if (added.length) els.status.textContent = `Đã thêm ${added.join(', ')} — bấm Lưu để áp dụng`;
    }
    function removeBot(botId){
      const g = current(); if (!g) return;
      g.bot_ids = ensureBotIds(g).filter((id) => Number(id) !== Number(botId));
      renderBotTags(); renderList(); renderEnvBotList();
    }
    function renderBotTags(){
      const g = current();
      const byId = botById();
      if (!g) {
        els.botTags.innerHTML = '<div class="bot-empty">Chọn nhóm để gán bot</div>';
        els.botIdInput.disabled = true;
        $('addBotBtn').disabled = true;
        return;
      }
      els.botIdInput.disabled = false;
      $('addBotBtn').disabled = false;
      const tags = ensureBotIds(g).map((id) => {
        const bot = byId[Number(id)];
        const name = botDisplayName(bot);
        return `<span class="bot-tag"><span class="mono">${esc(name)}</span><button type="button" data-remove-bot="${id}" title="Xóa">×</button></span>`;
      });
      els.botTags.innerHTML = tags.length ? tags.join('') : '<div class="bot-empty">Chưa gán bot — nhập @username từ danh sách .env</div>';
      els.botTags.querySelectorAll('[data-remove-bot]').forEach((btn) => btn.addEventListener('click', () => removeBot(btn.dataset.removeBot)));
    }
    function groupBotSummary(g){
      const byId = botById();
      const names = (g.bot_ids || []).map((id) => botDisplayName(byId[Number(id)])).filter((v) => v && v !== '?');
      if (!names.length) return '0 bot';
      const preview = names.slice(0, 3).join(', ');
      const more = names.length > 3 ? ` +${names.length - 3}` : '';
      return `${preview}${more} · ${names.length} bot`;
    }
    function renderEnvBotList(){
      const g = current();
      if (!state.bots.length) {
        els.envBotList.innerHTML = '<div class="bot-empty">Chưa có bot trong .env — thêm TELEGRAM_BOT_TOKEN / TELEGRAM_BOT_TOKENS</div>';
        return;
      }
      const selected = new Set((g?.bot_ids || []).map(Number));
      els.envBotList.innerHTML = state.bots.map((b) => {
        const name = botDisplayName(b);
        const picked = selected.has(Number(b.id));
        return `<button type="button" class="env-bot-pick" data-pick-bot="${esc(b.username || name)}" ${g && !picked ? '' : 'disabled'}>${esc(name)}</button>`;
      }).join('');
      els.envBotList.querySelectorAll('[data-pick-bot]').forEach((btn) => {
        btn.addEventListener('click', () => {
          try {
            const added = addBotByUsername(btn.dataset.pickBot);
            els.status.textContent = `Đã thêm ${added} — bấm Lưu để áp dụng`;
          } catch (e) { els.status.textContent = e.message; }
        });
      });
    }
    function renderList(){
      els.list.innerHTML = state.groups.length ? state.groups.map((g,i) => {
        const pill = g.enabled !== false ? 'on' : 'off';
        const pillText = g.enabled !== false ? 'bật' : 'tắt';
        const botCount = (g.bot_ids || []).length;
        const botMeta = groupBotSummary(g);
        return `<li class="group-row ${i===state.selected?'selected':''}" data-index="${i}"><div><div class="group-name">${esc(g.name)}</div><div class="group-meta">${esc(g.chat_id)} · ${esc(botMeta)}</div></div><span class="pill ${pill}">${pillText}</span></li>`;
      }).join('') : `<li class="group-row"><div><div class="group-name">Chưa có nhóm</div><div class="group-meta">Thêm Chat ID bên phải</div></div></li>`;
      els.list.querySelectorAll('.group-row[data-index]').forEach((row) => row.addEventListener('click', () => { syncForm(); state.selected = Number(row.dataset.index); renderForm(); renderList(); }));
      els.summary.textContent = `${state.groups.length} nhóm | ${state.groups.filter((g) => g.enabled !== false).length} đang bật`;
    }
    function renderForm(){
      const g = current();
      els.name.disabled = !g;
      els.enabled.disabled = !g;
      els.name.value = g?.name || '';
      els.chatId.value = g?.chat_id || '';
      els.enabled.checked = g ? g.enabled !== false : true;
      $('deleteBtn').disabled = !g;
      $('saveBtn').disabled = !g;
      renderBotTags();
      renderEnvBotList();
    }
    async function loadGroups(){
      const res = await fetch('/api/watch-groups?_=' + Date.now(), { cache:'no-store' });
      const data = await res.json(); if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
      state.groups = (data.groups || []).map((g) => ({ ...g, bot_ids: g.bot_ids || [] }));
      state.bots = data.bots || [];
      state.selected = Math.min(state.selected, Math.max(0, state.groups.length - 1));
      renderList(); renderForm();
    }
    async function saveGroups(){
      syncForm();
      const res = await fetch('/api/watch-groups', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({ groups: state.groups }) });
      const data = await res.json(); if (!res.ok) throw new Error(data.error || 'Save failed');
      state.groups = data.groups || [];
      state.bots = data.bots || state.bots;
      els.status.textContent = `Đã lưu ${state.groups.length} nhóm. Telethon reader sẽ tự reload trong ~30s.`;
      renderList(); renderForm();
    }
    function addGroup(){
      const name = els.name.value.trim();
      const chatId = els.chatId.value.trim();
      if (!chatId) throw new Error('Nhập Chat ID hoặc @username');
      if (state.groups.some((g) => g.chat_id === chatId)) throw new Error('Chat ID đã tồn tại');
      state.groups.push({ name: name || chatId, chat_id: chatId, enabled: els.enabled.checked, bot_ids: [] });
      state.selected = state.groups.length - 1;
      renderList(); renderForm();
      els.status.textContent = 'Đã thêm vào danh sách — bấm Lưu để áp dụng';
    }
    async function deleteCurrent(){
      const g = current(); if (!g) return;
      if (g.id) {
        const res = await fetch('/api/watch-groups/delete', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({ id:g.id }) });
        const data = await res.json(); if (!res.ok) throw new Error(data.error || 'Delete failed');
        state.groups = data.groups || [];
      } else {
        state.groups.splice(state.selected, 1);
      }
      state.selected = Math.min(state.selected, Math.max(0, state.groups.length - 1));
      renderList(); renderForm();
      els.status.textContent = 'Đã xóa nhóm';
    }
    async function importEnv(){
      const res = await fetch('/api/watch-groups/import-env', { method:'POST' });
      const data = await res.json(); if (!res.ok) throw new Error(data.error || 'Import failed');
      state.groups = data.groups || [];
      state.selected = 0;
      renderList(); renderForm();
      els.status.textContent = data.imported ? `Import ${data.imported} nhóm từ .env` : 'Không có nhóm mới từ .env';
    }
    $('queueBtn').onclick = () => location.href = '/';
    $('botsBtn').onclick = () => location.href = '/bots';
    $('broadcastBtn').onclick = () => location.href = '/broadcast';
    $('reloadBtn').onclick = () => loadGroups().catch((e) => els.status.textContent = e.message);
    $('importEnvBtn').onclick = () => importEnv().catch((e) => els.status.textContent = e.message);
    $('addBtn').onclick = () => { try { addGroup(); } catch (e) { els.status.textContent = e.message; } };
    $('addBotBtn').onclick = () => { try { addBotsFromInput(); } catch (e) { els.status.textContent = e.message; } };
    $('saveBtn').onclick = () => saveGroups().catch((e) => els.status.textContent = e.message);
    $('deleteBtn').onclick = () => deleteCurrent().catch((e) => els.status.textContent = e.message);
    els.botIdInput.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); try { addBotsFromInput(); } catch (err) { els.status.textContent = err.message; } } });
    ['nameInput','enabledInput'].forEach((id) => { $(id).addEventListener('input', () => { syncForm(); renderList(); }); $(id).addEventListener('change', () => { syncForm(); renderList(); }); });
    loadGroups().catch((e) => els.status.textContent = e.message);
  </script>
  <script>
""" + LOGOUT_SCRIPT + r"""
</body>
</html>
"""

PHONE_MONITOR_HTML = r"""<!doctype html>
<html lang="vi">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Giám sát điện thoại</title>
  <style>
    body { margin:0; background:#f5f6f8; color:#20242a; font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }
    .topbar { min-height:58px; display:flex; align-items:center; justify-content:space-between; gap:12px; padding:0 20px; background:#151922; color:#f9fafb; }
    .toolbar { display:flex; gap:8px; flex-wrap:wrap; }
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
  <header class="topbar"><h1>Giám sát điện thoại</h1><div class="toolbar"><button id="queueBtn" class="button">Hàng đợi</button><button id="logoutBtn" class="button">Đăng xuất</button></div></header>
  <main class="main">
    <section class="card">
      <h2>Kết nối app Android</h2>
      <p>Cài APK từ <code>phone_monitor_app</code>, bật Accessibility + Overlay, rồi nhập IP điện thoại hiển thị trong app. Cổng mặc định là 8791.</p>
      <label>URL điện thoại</label><input id="baseUrl" placeholder="http://192.168.1.23:8791">
      <div class="actions"><button id="saveBtn" class="button primary">Lưu URL</button><button id="logsBtn" class="button light">Tải log</button><button id="openPendingBtn" class="button primary">Mở link tin chờ</button></div>
    </section>
    <section class="card">
      <h2>USB Type-C / ADB</h2>
      <p>Dùng khi điện thoại cắm dây Type-C và đã bật USB debugging. Có thể cài APK monitor hoặc mở deeplink trực tiếp qua ADB.</p>
      <label>Thiết bị ADB</label><select id="adbDevice"><option value="">Tự chọn</option></select>
      <label>Đường dẫn APK</label><input id="apkPath" value="phone_monitor_app/app/build/outputs/apk/debug/app-debug.apk" placeholder="phone_monitor_app/app/build/outputs/apk/debug/app-debug.apk">
      <label>Điểm click mặc định sau TIME</label><div class="row"><input id="clickX" type="number" placeholder="x" value="540"><input id="clickY" type="number" placeholder="y" value="1800"><input id="clickDelay" type="number" placeholder="delay ms"><button id="saveClickPointBtn" class="button light">Lưu điểm click</button></div>
      <div class="actions"><button id="adbRefreshBtn" class="button light">Làm mới thiết bị</button><button id="adbInstallBtn" class="button primary">Cài APK qua Type-C</button><button id="adbOpenBtn" class="button primary">Mở deeplink qua ADB</button></div>
    </section>
    <section class="card">
      <h2>Thao tác trực tiếp</h2>
      <label>Deeplink</label><input id="deeplink" placeholder="tiktok://... hoặc https://...">
      <div class="row"><input id="x" type="number" placeholder="x"><input id="y" type="number" placeholder="y"><input id="x2" type="number" placeholder="x2"><input id="y2" type="number" placeholder="y2"></div>
      <div class="actions"><button id="tapBtn" class="button primary">Tap x,y</button><button id="swipeBtn" class="button primary">Vuốt x,y → x2,y2</button><button id="deepBtn" class="button primary">Mở Deeplink</button></div>
    </section>
    <section class="card"><h2>Log</h2><pre id="logs">Sẵn sàng.</pre></section>
  </main>
<script>
  const $ = id => document.getElementById(id);
  const base = $('baseUrl');
  base.value = localStorage.getItem('phoneMonitorBaseUrl') || '';
  function url(path){ const root = base.value.trim().replace(/\/$/, ''); if(!root) throw new Error('Nhập URL điện thoại trước'); return root + path; }
  async function post(path, data){ const body = new URLSearchParams(data); const res = await fetch(url(path), {method:'POST', headers:{'Content-Type':'application/x-www-form-urlencoded'}, body}); const text = await res.text(); if(!res.ok) throw new Error(text); $('logs').textContent = text; }
  function pendingLink(){ return localStorage.getItem('pendingQueueLink') || ''; }
  function clickPoint(){ return {x:Number($('clickX').value || localStorage.getItem('phoneClickX') || 540), y:Number($('clickY').value || localStorage.getItem('phoneClickY') || 1800)}; }
  function initClickPoint(){ $('clickX').value = localStorage.getItem('phoneClickX') || '540'; $('clickY').value = localStorage.getItem('phoneClickY') || '1800'; }
  function renderPending(){ const link = pendingLink(); $('openPendingBtn').disabled = !link; if(link) { $('deeplink').value = link; $('logs').textContent = `Tin chờ #${localStorage.getItem('pendingQueueJobId') || ''}: ${link}`; } }
  async function openPending(){ const link = pendingLink(); if(!link) return; const point = clickPoint(); await post('/actions/deeplink', {url:link, source:'queue', queue_id:localStorage.getItem('pendingQueueJobId') || '', time:localStorage.getItem('pendingQueueTime') || '', click_after_ms:localStorage.getItem('pendingQueueClickAfterMs') || '0', click_x:point.x, click_y:point.y}); localStorage.removeItem('pendingQueueLink'); localStorage.removeItem('pendingQueueJobId'); localStorage.removeItem('pendingQueueTime'); localStorage.removeItem('pendingQueueClickAfterMs'); renderPending(); }
  initClickPoint();
  renderPending();
  function selectedAdbDevice(){ return $('adbDevice').value || ''; }
  async function jsonPost(path, data){ const res = await fetch(path, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(data || {})}); const payload = await res.json(); if(!res.ok) throw new Error(payload.error || `HTTP ${res.status}`); $('logs').textContent = JSON.stringify(payload, null, 2); return payload; }
  async function refreshAdbDevices(){ const res = await fetch('/api/phone/adb-devices?_=' + Date.now(), {cache:'no-store'}); const data = await res.json(); if(!res.ok || data.error) throw new Error(data.error || `HTTP ${res.status}`); const devices = data.devices || []; $('adbDevice').innerHTML = '<option value="">Tự chọn</option>' + devices.map((d) => `<option value="${String(d.serial).replace(/&/g,'&amp;').replace(/"/g,'&quot;')}">${d.serial} (${d.state})</option>`).join(''); $('logs').textContent = devices.length ? JSON.stringify(data, null, 2) : 'Không thấy thiết bị ADB. Cắm Type-C, bật USB debugging, chấp nhận RSA.'; }
  async function installViaAdb(){ await jsonPost('/api/phone/adb-install', {device_id:selectedAdbDevice(), apk_path:$('apkPath').value.trim()}); }
  async function openViaAdb(){ const link = $('deeplink').value.trim() || pendingLink(); if(!link) throw new Error('Nhập deeplink hoặc chọn tin chờ trước'); const point = clickPoint(); await jsonPost('/api/phone/adb-open', {device_id:selectedAdbDevice(), url:link, click_after_ms:Number($('clickDelay').value || 0), click_x:point.x, click_y:point.y}); }
  $('adbRefreshBtn').onclick = () => refreshAdbDevices().catch(e => $('logs').textContent = e.message);
  $('adbInstallBtn').onclick = () => installViaAdb().catch(e => $('logs').textContent = e.message);
  $('adbOpenBtn').onclick = () => openViaAdb().catch(e => $('logs').textContent = e.message);
  $('saveClickPointBtn').onclick = () => { const point = clickPoint(); localStorage.setItem('phoneClickX', String(point.x)); localStorage.setItem('phoneClickY', String(point.y)); $('logs').textContent = `Đã lưu điểm click ${point.x},${point.y}`; };
  refreshAdbDevices().catch(() => {});
  $('queueBtn').onclick = () => location.href = '/';
  $('saveBtn').onclick = () => { localStorage.setItem('phoneMonitorBaseUrl', base.value.trim()); $('logs').textContent = 'Đã lưu ' + base.value.trim(); if(pendingLink()) openPending().catch(e => $('logs').textContent = e.message); };
  $('logsBtn').onclick = async () => { try { const res = await fetch(url('/logs')); $('logs').textContent = await res.text(); } catch(e) { $('logs').textContent = e.message; } };
  $('openPendingBtn').onclick = () => openPending().catch(e => $('logs').textContent = e.message);
  $('tapBtn').onclick = () => post('/actions/tap', {x:$('x').value, y:$('y').value}).catch(e => $('logs').textContent = e.message);
  $('swipeBtn').onclick = () => post('/actions/swipe', {x1:$('x').value, y1:$('y').value, x2:$('x2').value, y2:$('y2').value, duration_ms:450}).catch(e => $('logs').textContent = e.message);
  $('deepBtn').onclick = () => post('/actions/deeplink', {url:$('deeplink').value}).catch(e => $('logs').textContent = e.message);
</script>
<script>
""" + LOGOUT_SCRIPT + r"""
</body>
</html>
"""

class QueueUiHandler(BaseHTTPRequestHandler):
    db: ChatDatabase
    config: QueueUiConfig
    _last_queue_prune_at: float = 0.0

    def _session_cookie_value(self) -> Optional[str]:
        return parse_cookie_header(self.headers.get("Cookie", ""), SESSION_COOKIE)

    def _session_username(self) -> Optional[str]:
        return session_username_from_token(self._session_cookie_value(), self.config)

    def _effective_queue_user(self) -> str:
        user = self._session_username() or ""
        if user:
            return user
        if not self.config.auth_enabled:
            return self.config.auth_username or ""
        return ""

    def _is_user_authenticated(self) -> bool:
        return is_authenticated(self._session_cookie_value(), self.config)

    def _auth_is_public(self, path: str) -> bool:
        return (
            path in PUBLIC_PATHS
            or path.startswith("/api/auth/")
            or path == "/api/desktop/auth/login"
            or path == "/api/desktop/auth/users"
            or path == "/api/desktop/pull"
            or path.startswith("/api/phone/")
        )

    def _ensure_auth(self) -> bool:
        parsed = urlparse(self.path)
        path = parsed.path or "/"
        if self._auth_is_public(path):
            if path == "/login" and self._is_user_authenticated():
                self._redirect("/")
                return False
            return True
        if self._is_user_authenticated():
            return True
        if path.startswith("/api/"):
            self._send_json({"error": "Chưa đăng nhập", "login_url": "/login"}, status=401)
        else:
            self._redirect(f"/login?next={quote(self.path)}")
        return False

    def _redirect(self, location: str) -> None:
        self.send_response(302)
        self.send_header("Location", location)
        self.end_headers()

    def _set_session_cookie_header(self, username: str = "") -> None:
        token = create_session_token(self.config.auth_secret, username)
        self.send_header(
            "Set-Cookie",
            f"{SESSION_COOKIE}={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={SESSION_TTL_SECONDS}",
        )

    def _clear_session_cookie_header(self) -> None:
        self.send_header(
            "Set-Cookie",
            f"{SESSION_COOKIE}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0",
        )

    def _auth_status(self) -> None:
        username = self._session_username() if self._is_user_authenticated() else None
        self._send_json(
            {
                "auth_enabled": self.config.auth_enabled,
                "authenticated": self._is_user_authenticated(),
                "username": username,
            }
        )

    def _auth_login(self) -> None:
        try:
            payload = self._read_json_body()
            username = str(payload.get("username") or "").strip()
            password = str(payload.get("password") or "")
            if not verify_credentials(username, password, self.config):
                raise ValueError("Sai tên đăng nhập hoặc mật khẩu")
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=401)
            return

        body = json.dumps(
            {"ok": True, "username": username},
            ensure_ascii=False,
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        if self.config.auth_enabled:
            self._set_session_cookie_header(username)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _desktop_auth_users(self) -> None:
        users = list_queue_usernames(queue_users_map(self.config))
        self._send_json({"ok": True, "users": users})

    def _desktop_auth_login(self) -> None:
        try:
            payload = self._read_json_body()
            username = str(payload.get("username") or "").strip()
            password = str(payload.get("password") or "")
            if not verify_credentials(username, password, self.config):
                raise ValueError("Sai tên đăng nhập hoặc mật khẩu")
            pull_token = desktop_pull_token_for_user(username, self.config.auth_secret)
            if not pull_token:
                raise ValueError("Desktop auth chưa bật trên server")
        except Exception as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=401)
            return

        host = self.headers.get("Host", f"{self.config.host}:{self.config.port}")
        scheme = "https" if str(host).endswith(":443") else "http"
        queue_url = f"{scheme}://{host}"
        self._send_json(
            {
                "ok": True,
                "username": username,
                "pull_token": pull_token,
                "queue_url": queue_url,
            }
        )

    def _auth_logout(self) -> None:
        body = b'{"ok":true}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self._clear_session_cookie_header()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_HEAD(self) -> None:
        if not self._ensure_auth():
            return
        parsed = urlparse(self.path)
        if parsed.path == "/login":
            self._send_headers("text/html; charset=utf-8", len(LOGIN_HTML.encode("utf-8")))
            return

        if parsed.path == "/":
            self._send_headers("text/html; charset=utf-8", len(HTML.encode("utf-8")))
            return

        if parsed.path == "/filters":
            self._send_headers("text/html; charset=utf-8", len(FILTERS_HTML.encode("utf-8")))
            return

        if parsed.path == "/broadcast":
            self._send_headers("text/html; charset=utf-8", len(BROADCAST_HTML.encode("utf-8")))
            return

        if parsed.path == "/watch":
            self._send_headers("text/html; charset=utf-8", len(WATCH_HTML.encode("utf-8")))
            return

        if parsed.path == "/bots":
            self._send_headers("text/html; charset=utf-8", len(BOTS_HTML.encode("utf-8")))
            return

        if parsed.path == "/phone-monitor":
            self._send_headers("text/html; charset=utf-8", len(PHONE_MONITOR_HTML.encode("utf-8")))
            return

        if parsed.path == "/api/queue":
            self._send_headers("application/json; charset=utf-8", 0)
            return

        if parsed.path == "/api/deeplink/resolve":
            self._send_headers("application/json; charset=utf-8", 0)
            return

        if parsed.path == "/events":
            self._send_headers("text/event-stream; charset=utf-8", 0)
            return

        if parsed.path == "/api/filters":
            self._send_headers("application/json; charset=utf-8", 0)
            return

        if parsed.path == "/api/broadcast-groups":
            self._send_headers("application/json; charset=utf-8", 0)
            return

        if parsed.path == "/api/broadcast-bots":
            self._send_headers("application/json; charset=utf-8", 0)
            return

        if parsed.path == "/api/watch-groups":
            self._send_headers("application/json; charset=utf-8", 0)
            return

        if parsed.path == "/api/bot-slots":
            self._send_headers("application/json; charset=utf-8", 0)
            return

        if parsed.path == "/api/phone/config":
            self._send_headers("application/json; charset=utf-8", 0)
            return

        if parsed.path == "/api/phone/register":
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
        if parsed.path == "/api/desktop/pull":
            query = parse_qs(parsed.query)
            token = str((query.get("token") or [""])[0])
            self._send_json(pull_pending(token, self.config))
            return

        if parsed.path == "/api/desktop/auth/users":
            self._desktop_auth_users()
            return

        if not self._ensure_auth():
            return
        if parsed.path == "/login":
            self._send_html(LOGIN_HTML)
            return

        if parsed.path == "/api/auth/status":
            self._auth_status()
            return

        if parsed.path == "/":
            self._send_html(HTML)
            return

        if parsed.path == "/desktop-tool":
            self._send_html(HTML)
            return

        if parsed.path == "/filters":
            self._send_html(FILTERS_HTML)
            return

        if parsed.path == "/broadcast":
            self._send_html(BROADCAST_HTML)
            return

        if parsed.path == "/watch":
            self._send_html(WATCH_HTML)
            return

        if parsed.path == "/bots":
            self._send_html(BOTS_HTML)
            return

        if parsed.path == "/phone-monitor":
            self._send_html(PHONE_MONITOR_HTML)
            return

        if parsed.path == "/api/queue":
            self._send_json(self._queue_snapshot(parse_qs(parsed.query)))
            return

        if parsed.path == "/api/deeplink/resolve":
            self._resolve_deeplink_link(parse_qs(parsed.query))
            return

        if parsed.path == "/events":
            self._send_events(parse_qs(parsed.query))
            return

        if parsed.path == "/api/filters":
            self._send_json(self._filters_snapshot())
            return

        if parsed.path == "/api/broadcast-groups":
            self._send_json(self._broadcast_groups_snapshot())
            return

        if parsed.path == "/api/broadcast-bots":
            self._send_json(self._broadcast_bots_snapshot())
            return

        if parsed.path == "/api/watch-groups":
            self._send_json(self._watch_groups_snapshot())
            return

        if parsed.path == "/api/bot-slots":
            query = parse_qs(parsed.query)
            refresh = str((query.get("refresh") or ["0"])[0]).strip().lower() in {
                "1",
                "true",
                "yes",
            }
            self._send_json(self._bot_slots_snapshot(refresh=refresh))
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

        if parsed.path == "/api/desktop/status":
            query = parse_qs(parsed.query)
            user = str((query.get("user") or [""])[0]).strip()
            if not user:
                user = self._effective_queue_user()
            self._send_json(desktop_status(queue_user=user))
            return

        self.send_error(404)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/auth/login":
            self._auth_login()
            return

        if parsed.path == "/api/auth/logout":
            self._auth_logout()
            return

        if parsed.path == "/api/desktop/auth/login":
            self._desktop_auth_login()
            return

        if not self._ensure_auth():
            return

        if parsed.path == "/api/deeplink/resolve":
            self._resolve_deeplink_link_post()
            return

        if parsed.path == "/api/filters":
            self._save_filters()
            return

        if parsed.path == "/api/broadcast-groups":
            self._save_broadcast_groups()
            return

        if parsed.path == "/api/broadcast-groups/discover":
            self._discover_broadcast_groups()
            return

        if parsed.path == "/api/broadcast-groups/manual-add":
            self._manual_add_broadcast_group()
            return

        if parsed.path == "/api/broadcast-groups/approve":
            self._approve_broadcast_group()
            return

        if parsed.path == "/api/broadcast-groups/delete":
            self._delete_broadcast_group()
            return

        if parsed.path == "/api/broadcast-groups/test":
            self._broadcast_groups_test()
            return

        if parsed.path == "/api/watch-groups":
            self._save_watch_groups()
            return

        if parsed.path == "/api/watch-groups/delete":
            self._delete_watch_group()
            return

        if parsed.path == "/api/watch-groups/import-env":
            self._import_watch_groups_from_env()
            return

        if parsed.path == "/api/bot-slots":
            self._save_bot_slots()
            return

        if parsed.path == "/api/bot-slots/import-env":
            self._import_bot_slots_from_env()
            return

        if parsed.path == "/api/phone/job-result":
            self._phone_job_result()
            return

        if parsed.path == "/api/phone/register":
            self._phone_register()
            return

        if parsed.path == "/api/queue/mark-done":
            self._queue_mark_done()
            return

        if parsed.path == "/api/desktop/open":
            self._desktop_open_post()
            return

        if parsed.path == "/api/open/link":
            self._open_link_post()
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

    def _desktop_open_post(self) -> None:
        import html as html_module

        try:
            payload = self._read_json_body()
            url = html_module.unescape(str(payload.get("url") or "").strip())
            job_id = payload.get("job_id")
            ttl_seconds = int(payload.get("ttl_seconds") or 30)
            click_after_ms = int(payload.get("click_after_ms") or 0)
            time_label = str(payload.get("time_label") or "").strip()
            parsed_job_id = int(job_id) if job_id is not None else None
        except Exception as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=400)
            return

        result = enqueue_open(
            url,
            job_id=parsed_job_id,
            ttl_seconds=ttl_seconds,
            dedup_seconds=self.config.desktop_dedup_seconds,
            click_after_ms=click_after_ms,
            time_label=time_label,
            queue_user=self._effective_queue_user(),
        )
        status = 200 if result.get("ok") else 400
        self._send_json(result, status=status)

    def _open_link_post(self) -> None:
        try:
            payload = self._read_json_body()
            url = str(payload.get("url") or "").strip()
            context = str(payload.get("context") or "").strip()
            job_id = payload.get("job_id")
            parsed_job_id = int(job_id) if job_id is not None else None
            message_text = str(payload.get("message") or payload.get("message_text") or "").strip()
            raw_payload = payload.get("payload")
            queue_payload = raw_payload if isinstance(raw_payload, dict) else {}
            if not context:
                context = item_context_from_parts(message_text, queue_payload)
            ttl_seconds = int(payload.get("ttl_seconds") or 30)
            click_after_ms = int(payload.get("click_after_ms") or 0)
            time_label = str(payload.get("time_label") or "").strip()
            click_x = non_negative_int(payload.get("click_x"), 0)
            click_y = non_negative_int(payload.get("click_y"), 0)
            device_id = str(payload.get("device_id") or "").strip() or None
            open_phone = payload.get("open_phone", True) is not False
            open_desktop = payload.get("open_desktop", True) is not False
        except Exception as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=400)
            return

        result = open_link_for_queue(
            url,
            context=context,
            message_text=message_text,
            queue_payload=queue_payload,
            job_id=parsed_job_id,
            ttl_seconds=ttl_seconds,
            dedup_seconds=self.config.desktop_dedup_seconds,
            click_after_ms=click_after_ms,
            time_label=time_label,
            click_x=click_x,
            click_y=click_y,
            device_id=device_id,
            open_phone=open_phone,
            open_desktop=open_desktop,
            queue_user=self._effective_queue_user(),
        )
        status = 200 if result.get("ok") else 400
        self._send_json(result, status=status)

    def _phone_next_job(self, query: Dict[str, List[str]]) -> Dict[str, object]:
        self._prune_queue_ttl()
        after_id = non_negative_int((query.get("after_id") or ["0"])[0], 0)
        device_id = str((query.get("device_id") or ["phone"])[0] or "phone")
        wait_seconds = min(_int_query(query, "wait", 0), 25)

        register_device(device_id)

        pushed = pop_phone_open(device_id)
        if pushed:
            return {"generated_at": datetime.now(timezone.utc).isoformat(), "config": _phone_config(), "job": pushed}

        if sync_broadcast_enabled():
            job = next_pending_job_for_device(device_id, after_id, self.db)
            if job:
                return {"generated_at": datetime.now(timezone.utc).isoformat(), "config": _phone_config(), "job": job}
        else:
            claimed = self.db.claim_next_after(device_id, self.config.queue_lease_seconds, after_id)
            if claimed:
                job = _phone_job_from_claimed_job(claimed)
                if job:
                    return {"generated_at": datetime.now(timezone.utc).isoformat(), "config": _phone_config(), "job": job}
                self.db.mark_job_done(claimed.id, f"{device_id}: unsupported phone job")

        deadline = time.time() + wait_seconds
        while wait_seconds > 0 and time.time() < deadline:
            time.sleep(1)
            pushed = pop_phone_open(device_id)
            if pushed:
                return {"generated_at": datetime.now(timezone.utc).isoformat(), "config": _phone_config(), "job": pushed}
            if sync_broadcast_enabled():
                job = next_pending_job_for_device(device_id, after_id, self.db)
                if job:
                    return {"generated_at": datetime.now(timezone.utc).isoformat(), "config": _phone_config(), "job": job}
            else:
                claimed = self.db.claim_next_after(device_id, self.config.queue_lease_seconds, after_id)
                if claimed:
                    job = _phone_job_from_claimed_job(claimed)
                    if job:
                        return {"generated_at": datetime.now(timezone.utc).isoformat(), "config": _phone_config(), "job": job}
                    self.db.mark_job_done(claimed.id, f"{device_id}: unsupported phone job")
        return {"generated_at": datetime.now(timezone.utc).isoformat(), "config": _phone_config(), "job": None}

    def _phone_register(self) -> None:
        try:
            payload = self._read_json_body()
        except Exception as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=400)
            return
        device_id = str(payload.get("device_id") or "").strip()
        result = register_device(
            device_id,
            label=str(payload.get("label") or device_id),
            click_x=int(payload.get("click_x") or 0),
            click_y=int(payload.get("click_y") or 0),
            screen_w=int(payload.get("screen_w") or 0),
            screen_h=int(payload.get("screen_h") or 0),
        )
        status = 200 if result.get("ok") else 400
        self._send_json(result, status=status)

    def _send_events(self, query: Dict[str, List[str]]) -> None:
        self._prune_queue_ttl()
        after_id = (
            _non_negative_int_query(query, "after_id", 0, max_value=None)
            if "after_id" in query
            else _latest_phone_job_id(self.db, _int_query(query, "limit", 50))
        )
        poll_seconds = _float_query(query, "poll", 0.5, 0.1, 10.0)
        limit = _int_query(query, "limit", 50)

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        self._write_sse_comment("connected")
        logger.debug("SSE client connected address=%s after_id=%s", self.client_address[0], after_id)

        last_keepalive = time.time()
        while True:
            try:
                job = _next_phone_job(self.db, after_id=after_id, limit=limit)
                if job:
                    after_id = int(job.get("id") or after_id)
                    self._write_sse_event("link", {
                        "generated_at": datetime.now(timezone.utc).isoformat(),
                        "job": job,
                        "id": job.get("id"),
                        "url": job.get("url"),
                        "link": job.get("url"),
                    }, event_id=str(after_id))
                    last_keepalive = time.time()
                    continue

                now = time.time()
                if now - last_keepalive >= 15:
                    self._write_sse_comment("keepalive")
                    last_keepalive = now
                time.sleep(poll_seconds)
            except (BrokenPipeError, ConnectionResetError):
                logger.debug("SSE client disconnected address=%s", self.client_address[0])
                return
            except Exception as exc:
                logger.exception("SSE stream failed")
                try:
                    self._write_sse_event("error", {"error": str(exc)})
                except Exception:
                    return
                time.sleep(poll_seconds)

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

    def _resolve_deeplink_link(self, query: Dict[str, List[str]]) -> None:
        url = (query.get("url") or [""])[0]
        context = (query.get("context") or [""])[0]
        self._send_json(resolve_link_for_open(url, context))

    def _resolve_deeplink_link_post(self) -> None:
        try:
            payload = self._read_json_body()
        except Exception as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=400)
            return

        url = str(payload.get("url") or "").strip()
        context = str(payload.get("context") or "").strip()
        if not context:
            message = str(payload.get("message") or "").strip()
            raw_payload = payload.get("payload")
            context = item_context_from_parts(
                message,
                raw_payload if isinstance(raw_payload, dict) else {},
            )
        self._send_json(resolve_link_for_open(url, context))

    def _queue_snapshot(self, query: Dict[str, List[str]]) -> Dict[str, object]:
        self._prune_queue_ttl()
        requested_limit = _int_query(query, "limit", self.config.limit)
        limit = min(requested_limit, self.config.limit)
        statuses = _statuses_query(query)
        items = self.db.get_queue_items(
            limit=limit,
            statuses=statuses or None,
        )
        items = [_enrich_queue_item(item) for item in items]
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "db_path": self.config.db_path,
            "refresh_seconds": self.config.refresh_seconds,
            "queue_ttl_seconds": self.config.queue_ttl_seconds,
            "limit": limit,
            "requested_limit": requested_limit,
            "latest_id": items[0]["id"] if items else 0,
            "latest_pending_id": _latest_pending_id(items),
            "stats": self.db.get_queue_stats(),
            "items": items,
        }

    def _prune_queue_ttl(self) -> None:
        now = time.time()
        if now - QueueUiHandler._last_queue_prune_at < 60:
            return
        QueueUiHandler._last_queue_prune_at = now
        deleted = self.db.prune_queue_older_than(self.config.queue_ttl_seconds)
        if deleted["queue"] or deleted["messages"]:
            logger.info(
                "Pruned queue TTL queue=%s messages=%s ttl=%ss",
                deleted["queue"],
                deleted["messages"],
                self.config.queue_ttl_seconds,
            )

    def _filters_snapshot(self) -> Dict[str, object]:
        path = Path(self.config.filter_config_path)
        filters, reject, exclude_groups = _load_filter_config(path)
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "path": str(path),
            "filters": filters,
            "reject": reject,
            "exclude_telegram_groups": exclude_groups,
        }

    def _broadcast_groups_snapshot(self) -> Dict[str, object]:
        pending = self.db.list_pending_broadcast_groups()
        approved = self.db.list_approved_broadcast_groups()
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "pending": pending,
            "approved": approved,
            "groups": pending + approved,
        }

    def _broadcast_bots_snapshot(self) -> Dict[str, object]:
        return self._bot_slots_snapshot(refresh=False)

    def _bot_slots_snapshot(self, *, refresh: bool = False) -> Dict[str, object]:
        from bot_broadcast import fetch_bot_info, mask_bot_token

        slots = self.db.list_broadcast_bots(include_disabled=True)
        bots: List[Dict[str, Any]] = []
        pending: List[tuple[int, Dict[str, Any], str]] = []

        for slot in slots:
            token = (slot.get("token") or "").strip()
            if not token:
                continue
            cached_username = str(slot.get("telegram_username") or "").strip()
            cached_display = str(slot.get("telegram_display_name") or "").strip()
            item: Dict[str, Any] = {
                "id": slot["id"],
                "short_name": slot["short_name"],
                "token": token,
                "token_hint": mask_bot_token(token),
                "enabled": slot.get("enabled", True),
                "sort_order": slot.get("sort_order", 0),
                "telegram_username": cached_username or None,
                "telegram_display_name": cached_display or None,
                "username": cached_username,
                "display_name": cached_display or cached_username or slot["short_name"],
                "mention": f"@{cached_username}" if cached_username else "",
                "ok": bool(cached_username),
                "cached": bool(cached_username),
            }
            bots.append(item)
            if refresh or not cached_username:
                pending.append((len(bots) - 1, slot, token))

        refreshed = 0
        if pending:
            workers = min(12, len(pending))
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {
                    pool.submit(fetch_bot_info, token): (index, slot)
                    for index, slot, token in pending
                }
                for future in as_completed(futures):
                    index, slot = futures[future]
                    item = bots[index]
                    try:
                        me = future.result()
                        item.update(me)
                        item["ok"] = True
                        item["cached"] = False
                        item["telegram_username"] = me.get("username") or item.get("telegram_username")
                        item["telegram_display_name"] = me.get("display_name") or item.get(
                            "telegram_display_name"
                        )
                        self.db.update_broadcast_bot_profile(
                            int(slot["id"]),
                            telegram_username=me.get("username"),
                            telegram_display_name=me.get("display_name"),
                        )
                        refreshed += 1
                    except Exception as exc:
                        item["error"] = str(exc)
                        if item.get("telegram_username"):
                            item["ok"] = True
                            item["cached"] = True

        active = [bot for bot in bots if bot.get("enabled") and bot.get("token")]
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "count": len(bots),
            "active_count": len(active),
            "from_cache": not refresh,
            "refreshed": refreshed,
            "bots": bots,
        }

    def _save_bot_slots(self) -> None:
        try:
            payload = self._read_json_body()
            raw_bots = payload.get("bots")
            if not isinstance(raw_bots, list):
                raise ValueError("bots must be a list")
            normalized = []
            for raw in raw_bots:
                if not isinstance(raw, dict):
                    raise ValueError("each bot must be an object")
                normalized.append(
                    {
                        "short_name": str(raw.get("short_name") or "").strip(),
                        "token": str(raw.get("token") or "").strip(),
                        "enabled": bool(raw.get("enabled", True)),
                        "sort_order": raw.get("sort_order"),
                        "telegram_username": raw.get("telegram_username"),
                        "telegram_display_name": raw.get("telegram_display_name"),
                    }
                )
            self.db.replace_broadcast_bots(normalized)
        except Exception as exc:
            logger.exception("Failed to save bot slots")
            self._send_json({"error": str(exc)}, status=400)
            return
        self._send_json(self._bot_slots_snapshot(refresh=False))

    def _import_bot_slots_from_env(self) -> None:
        try:
            imported = self.db.seed_broadcast_bots_from_tokens(_bot_tokens())
            removed = self.db.delete_broadcast_bots_without_tokens()
        except Exception as exc:
            logger.exception("Failed to import bot tokens from .env")
            self._send_json({"error": str(exc)}, status=400)
            return
        snapshot = self._bot_slots_snapshot(refresh=False)
        snapshot["imported"] = imported
        snapshot["removed_empty"] = removed
        self._send_json(snapshot)

    def _save_broadcast_groups(self) -> None:
        try:
            payload = self._read_json_body()
            raw_groups = payload.get("groups", payload)
            if not isinstance(raw_groups, list):
                raise ValueError("groups must be a list")
            normalized = []
            for raw in raw_groups:
                if not isinstance(raw, dict):
                    continue
                normalized.append(
                    {
                        **raw,
                        "approved": True,
                        "enabled": bool(raw.get("enabled", True)),
                    }
                )
            groups = self.db.replace_approved_broadcast_groups(normalized)
        except Exception as exc:
            logger.exception("Failed to save broadcast groups")
            self._send_json({"error": str(exc)}, status=400)
            return

        self._send_json(self._broadcast_groups_snapshot())

    def _normalize_watch_group_bot_ids(self, raw: Dict[str, object]) -> List[int]:
        bot_ids: List[int] = []
        for bot_id in raw.get("bot_ids") or []:
            try:
                value = int(bot_id)
            except (TypeError, ValueError):
                continue
            if value not in bot_ids:
                bot_ids.append(value)

        raw_names = raw.get("bot_names") or raw.get("bot_short_names") or []
        if isinstance(raw_names, str):
            raw_names = re.split(r"[\s,;]+", raw_names.strip())
        if isinstance(raw_names, list) and raw_names:
            env_bots = _env_broadcast_bots(self.db)
            username_to_id = {
                str(bot.get("username") or "").strip().lower(): int(bot["id"])
                for bot in env_bots
                if str(bot.get("username") or "").strip()
            }
            for name in raw_names:
                key = str(name or "").strip().lower().lstrip("@")
                if not key:
                    continue
                bot_id = username_to_id.get(key)
                if bot_id is not None and bot_id not in bot_ids:
                    bot_ids.append(bot_id)
        return bot_ids

    def _watch_groups_snapshot(self) -> Dict[str, object]:
        groups = self.db.list_watch_groups()
        picker_bots = _env_broadcast_bots(self.db)
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "groups": groups,
            "bots": picker_bots,
        }

    def _save_watch_groups(self) -> None:
        try:
            payload = self._read_json_body()
            raw_groups = payload.get("groups")
            if not isinstance(raw_groups, list):
                raise ValueError("groups must be a list")

            normalized = []
            for raw in raw_groups:
                if not isinstance(raw, dict):
                    raise ValueError("each watch group must be an object")
                normalized.append(
                    {
                        "id": raw.get("id"),
                        "name": str(raw.get("name") or "").strip(),
                        "chat_id": str(raw.get("chat_id") or "").strip(),
                        "enabled": bool(raw.get("enabled", True)),
                        "created_at": raw.get("created_at"),
                        "bot_ids": self._normalize_watch_group_bot_ids(raw),
                    }
                )

            groups = self.db.replace_watch_groups(normalized)
        except Exception as exc:
            logger.exception("Failed to save watch groups")
            self._send_json({"error": str(exc)}, status=400)
            return

        self._send_json(self._watch_groups_snapshot())

    def _delete_watch_group(self) -> None:
        try:
            payload = self._read_json_body()
            group_id = int(payload.get("id"))
            if not self.db.delete_watch_group(group_id):
                raise ValueError(f"watch group not found: {group_id}")
        except Exception as exc:
            logger.exception("Failed to delete watch group")
            self._send_json({"error": str(exc)}, status=400)
            return

        self._send_json(self._watch_groups_snapshot())

    def _import_watch_groups_from_env(self) -> None:
        try:
            load_dotenv(Path(__file__).resolve().parent / ".env")
            raw_value = os.environ.get("TELEGRAM_CLIENT_TARGETS", "").strip()
            if not raw_value:
                raise ValueError("TELEGRAM_CLIENT_TARGETS is empty in .env")

            targets = _parse_client_targets(raw_value, "")
            if not targets:
                raise ValueError("No targets parsed from TELEGRAM_CLIENT_TARGETS")

            existing = {group["chat_id"] for group in self.db.list_watch_groups()}
            merged = list(self.db.list_watch_groups())
            imported = 0
            for target in targets:
                chat_id = target.chat_ref or target.entity_ref
                if chat_id in existing:
                    continue
                merged.append(
                    {
                        "name": target.label,
                        "chat_id": chat_id,
                        "enabled": True,
                    }
                )
                existing.add(chat_id)
                imported += 1

            if imported:
                self.db.replace_watch_groups(merged)
        except Exception as exc:
            logger.exception("Failed to import watch groups from env")
            self._send_json({"error": str(exc)}, status=400)
            return

        snapshot = self._watch_groups_snapshot()
        snapshot["imported"] = imported
        self._send_json(snapshot)

    def _discover_broadcast_groups(self) -> None:
        try:
            tokens = _bot_tokens()
            discovered = discover_all_bot_groups(tokens)
            result = register_discovered_groups(self.db, discovered["discovered"])
            result["discovered"] = discovered["discovered"]
            result["scans"] = discovered["scans"]
        except Exception as exc:
            logger.exception("Failed to discover broadcast groups")
            self._send_json({"error": str(exc)}, status=400)
            return

        self._send_json(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                **result,
            }
        )

    def _manual_add_broadcast_group(self) -> None:
        try:
            payload = self._read_json_body()
            chat_id = str(payload.get("chat_id") or "").strip()
            name = str(payload.get("name") or "").strip() or chat_id
            if not chat_id:
                raise ValueError("chat_id is required")
            # Normalize common paste formats
            chat_id = chat_id.replace(" ", "")
            if chat_id.startswith("https://t.me/") or chat_id.startswith("@"):
                raise ValueError("Cần numeric chat_id (vd -100...), không dùng link/@username")
            int(chat_id)  # validate numeric
            created = self.db.upsert_pending_broadcast_group(chat_id=chat_id, name=name)
            snapshot = self._broadcast_groups_snapshot()
            snapshot["created"] = created
            snapshot["chat_id"] = chat_id
        except Exception as exc:
            logger.exception("Failed to manual-add broadcast group")
            self._send_json({"error": str(exc)}, status=400)
            return
        self._send_json(snapshot)

    def _approve_broadcast_group(self) -> None:
        try:
            payload = self._read_json_body()
            group_id = int(payload.get("id"))
            name = str(payload.get("name") or "").strip() or None
            group = self.db.approve_broadcast_group(group_id, name=name)
            if group is None:
                raise ValueError(f"broadcast group not found: {group_id}")
        except Exception as exc:
            logger.exception("Failed to approve broadcast group")
            self._send_json({"error": str(exc)}, status=400)
            return

        self._send_json(self._broadcast_groups_snapshot())

    def _delete_broadcast_group(self) -> None:
        try:
            payload = self._read_json_body()
            group_id = int(payload.get("id"))
            if not self.db.delete_broadcast_group(group_id):
                raise ValueError(f"broadcast group not found: {group_id}")
        except Exception as exc:
            logger.exception("Failed to delete broadcast group")
            self._send_json({"error": str(exc)}, status=400)
            return

        self._send_json(self._broadcast_groups_snapshot())

    def _broadcast_groups_test(self) -> None:
        try:
            payload = self._read_json_body()
            text = str(payload.get("text") or "").strip()
            if not text:
                raise ValueError("text is required")

            token = _bot_token()
            bot = Bot(token)
            send_all = bool(payload.get("all"))
            if send_all:
                targets = self.db.list_enabled_broadcast_groups()
            else:
                chat_id = str(payload.get("chat_id") or "").strip()
                if not chat_id:
                    raise ValueError("chat_id is required when all=false")
                targets = [{"name": chat_id, "chat_id": chat_id}]

            if not targets:
                raise ValueError("No broadcast targets configured")

            sent = []
            errors = []
            for group in targets:
                chat_id = int(group["chat_id"])
                name = str(group.get("name") or chat_id)
                try:
                    message = bot.send_message(chat_id=chat_id, text=text)
                    sent.append({"name": name, "chat_id": chat_id, "message_id": message.message_id})
                except Exception as exc:
                    errors.append({"name": name, "chat_id": chat_id, "error": str(exc)})

            if not sent:
                raise ValueError("; ".join(item["error"] for item in errors) or "Send failed")

            self._send_json(
                {
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "sent": sent,
                    "errors": errors,
                }
            )
        except Exception as exc:
            logger.exception("Failed to test broadcast groups")
            self._send_json({"error": str(exc)}, status=400)

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
            filters = _normalize_filter_rules(payload.get("filters", []))
            path = Path(self.config.filter_config_path)
            existing_filters, existing_reject, existing_exclude = _load_filter_config(path)
            if "reject" in payload:
                reject = _normalize_reject_rules(payload.get("reject"))
            else:
                reject = existing_reject
            if "exclude_telegram_groups" in payload:
                exclude_groups = _normalize_exclude_groups(payload.get("exclude_telegram_groups"))
            else:
                exclude_groups = existing_exclude
            _write_filter_config(path, filters, reject, exclude_groups)
        except Exception as exc:
            logger.exception("Failed to save message filters")
            self._send_json({"error": str(exc)}, status=400)
            return

        self._send_json(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "path": str(path),
                "filters": filters,
                "reject": reject,
                "exclude_telegram_groups": exclude_groups,
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

    def _write_sse_event(self, event: str, payload: Dict[str, object], event_id: Optional[str] = None) -> None:
        if event_id:
            self.wfile.write(f"id: {event_id}\n".encode("utf-8"))
        self.wfile.write(f"event: {event}\n".encode("utf-8"))
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        for line in data.splitlines() or [""]:
            self.wfile.write(f"data: {line}\n".encode("utf-8"))
        self.wfile.write(b"\n")
        self.wfile.flush()

    def _write_sse_comment(self, message: str) -> None:
        self.wfile.write(f": {message}\n\n".encode("utf-8"))
        self.wfile.flush()

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
    return phone_config()


def _next_phone_job(db: ChatDatabase, after_id: int, limit: int) -> Optional[Dict[str, object]]:
    items = db.get_queue_items(limit=limit, statuses=["pending"])
    for item in reversed(items):
        if int(item.get("id") or 0) <= after_id:
            continue
        job = phone_job_from_queue_item(item)
        if job:
            return job
    return None


def _latest_phone_job_id(db: ChatDatabase, limit: int) -> int:
    items = db.get_queue_items(limit=limit, statuses=["pending"])
    ids = [
        int(item.get("id") or 0)
        for item in items
        if phone_job_from_queue_item(item)
    ]
    return max(ids) if ids else 0


def _phone_job_from_queue_item(item: Dict[str, Any]) -> Optional[Dict[str, object]]:
    return phone_job_from_queue_item(item)


def _phone_job_from_claimed_job(claimed: QueueJob) -> Optional[Dict[str, object]]:
    return phone_job_from_claimed_job(claimed)


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


def _non_negative_int_query(
    query: Dict[str, List[str]],
    key: str,
    default: int,
    max_value: Optional[int] = 5000,
) -> int:
    raw_value = (query.get(key) or [""])[0]
    try:
        value = int(raw_value)
    except ValueError:
        return default
    value = max(0, value)
    if max_value is None:
        return value
    return min(value, max_value)


def _float_query(
    query: Dict[str, List[str]],
    key: str,
    default: float,
    min_value: float,
    max_value: float,
) -> float:
    raw_value = (query.get(key) or [""])[0]
    try:
        value = float(raw_value)
    except ValueError:
        return default
    return max(min_value, min(value, max_value))


def _statuses_query(query: Dict[str, List[str]]) -> List[str]:
    raw_value = (query.get("statuses") or [""])[0]
    return [value.strip() for value in raw_value.split(",") if value.strip()]


def _load_filter_rules(path: Path) -> List[Dict[str, Any]]:
    filters, _reject, _exclude = _load_filter_config(path)
    return filters


def _load_filter_config(
    path: Path,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[str]]:
    if not path.exists():
        return [], [], []

    with path.open(encoding="utf-8") as file:
        payload = json.load(file)

    if isinstance(payload, dict):
        raw_filters = payload.get("filters", [])
        raw_reject = payload.get("reject", [])
        raw_exclude = payload.get("exclude_telegram_groups") or payload.get("exclude_groups") or []
    else:
        raw_filters = payload
        raw_reject = []
        raw_exclude = []

    return (
        _normalize_filter_rules(raw_filters),
        _normalize_reject_rules(raw_reject),
        _normalize_exclude_groups(raw_exclude),
    )


def _bot_tokens() -> List[str]:
    return list(load_config().bot_tokens)


def _env_broadcast_bots(db: ChatDatabase) -> List[Dict[str, Any]]:
    from bot_broadcast import fetch_bot_info

    tokens = _bot_tokens()
    if not tokens:
        return []

    db.seed_broadcast_bots_from_tokens(tokens)
    slots_by_token = {
        str(bot.get("token") or "").strip(): bot
        for bot in db.list_broadcast_bots(include_disabled=True)
        if str(bot.get("token") or "").strip()
    }
    bots: List[Dict[str, Any]] = []
    pending: List[tuple[int, Dict[str, Any], str]] = []

    for index, token in enumerate(tokens):
        token = token.strip()
        slot = slots_by_token.get(token)
        if not slot:
            continue

        username = str(slot.get("telegram_username") or "").strip()
        display_name = str(
            slot.get("telegram_display_name") or username or f"bot{index + 1}"
        ).strip()
        bots.append(
            {
                "id": int(slot["id"]),
                "username": username,
                "name": f"@{username}" if username else display_name,
                "display_name": display_name,
                "has_token": True,
                "ok": bool(username),
                "env_index": index + 1,
                "_slot": slot,
                "_token": token,
            }
        )
        if not username:
            pending.append((len(bots) - 1, slot, token))

    if pending:
        with ThreadPoolExecutor(max_workers=min(12, len(pending))) as pool:
            futures = {
                pool.submit(fetch_bot_info, token): (index, slot)
                for index, slot, token in pending
            }
            for future in as_completed(futures):
                index, slot = futures[future]
                item = bots[index]
                try:
                    me = future.result()
                    username = str(me.get("username") or "").strip()
                    display_name = str(
                        me.get("display_name") or username or item["display_name"]
                    ).strip()
                    item["username"] = username
                    item["display_name"] = display_name
                    item["name"] = f"@{username}" if username else display_name
                    item["ok"] = bool(username)
                    if username:
                        db.update_broadcast_bot_profile(
                            int(slot["id"]),
                            telegram_username=username,
                            telegram_display_name=display_name,
                        )
                except Exception:
                    item["ok"] = False

    for item in bots:
        item.pop("_slot", None)
        item.pop("_token", None)
    return bots


def _bot_token() -> str:
    tokens = _bot_tokens()
    if not tokens:
        raise RuntimeError("Set TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKENS in .env for Bot API broadcast")
    return tokens[0]


def _write_filter_rules(path: Path, filters: List[Dict[str, Any]]) -> None:
    _, reject, exclude_groups = _load_filter_config(path)
    _write_filter_config(path, filters, reject, exclude_groups)


def _write_filter_config(
    path: Path,
    filters: List[Dict[str, Any]],
    reject: List[Dict[str, Any]],
    exclude_groups: Optional[List[str]] = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: Dict[str, Any] = {"filters": filters, "reject": reject}
    if exclude_groups is None:
        _, _, exclude_groups = _load_filter_config(path)
    if exclude_groups:
        payload["exclude_telegram_groups"] = exclude_groups
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    tmp_path.replace(path)


def _normalize_exclude_groups(raw_exclude: Any) -> List[str]:
    if raw_exclude in (None, ""):
        return []
    if isinstance(raw_exclude, str):
        return _string_list(raw_exclude)
    if isinstance(raw_exclude, list):
        return _string_list(raw_exclude)
    raise ValueError("exclude_telegram_groups must be a list")


def _normalize_filter_rules(raw_filters: Any) -> List[Dict[str, Any]]:
    if not isinstance(raw_filters, list):
        raise ValueError("filters must be a list")

    return [_normalize_filter_rule(raw_filter, index) for index, raw_filter in enumerate(raw_filters)]


def _normalize_reject_rules(raw_reject: Any) -> List[Dict[str, Any]]:
    if raw_reject in (None, ""):
        return []
    if not isinstance(raw_reject, list):
        raise ValueError("reject must be a list")

    rules: List[Dict[str, Any]] = []
    for index, raw_rule in enumerate(raw_reject):
        if not isinstance(raw_rule, dict):
            raise ValueError(f"reject #{index + 1} must be an object")
        rule: Dict[str, Any] = {
            "name": str(raw_rule.get("name") or f"reject_{index + 1}").strip(),
            "enabled": bool(raw_rule.get("enabled", True)),
        }
        for key in ("text_contains", "comment_contains"):
            values = _string_list(raw_rule.get(key))
            if values:
                rule[key] = values
        text_regex = str(raw_rule.get("text_regex") or "").strip()
        if text_regex:
            rule["text_regex"] = text_regex
        rules.append(rule)
    return rules


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
        "min_level",
        "max_level",
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

    for key in ("boxes", "countries", "badges", "note_contains", "text_contains", "telegram_groups"):
        values = _string_list(raw_filter.get(key))
        if values:
            rule[key] = values

    text_regex = str(raw_filter.get("text_regex") or "").strip()
    if text_regex:
        rule["text_regex"] = text_regex

    _apply_box_exact_pair(rule, "min_box1", "max_box1")
    _apply_box_exact_pair(rule, "min_box2", "max_box2")

    return rule


def _apply_box_exact_pair(rule: Dict[str, Any], min_key: str, max_key: str) -> None:
    min_v = rule.get(min_key)
    max_v = rule.get(max_key)
    if min_v is None and max_v is None:
        return
    exact = min_v if min_v is not None else max_v
    rule[min_key] = exact
    rule[max_key] = exact


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


def _seed_watch_groups_from_env(db: ChatDatabase) -> None:
    if db.list_watch_groups():
        return

    load_dotenv(Path(__file__).resolve().parent / ".env")
    raw_value = os.environ.get("TELEGRAM_CLIENT_TARGETS", "").strip()
    if not raw_value:
        return

    targets = _parse_client_targets(raw_value, "")
    if not targets:
        return

    groups = [
        {
            "name": target.label,
            "chat_id": target.chat_ref or target.entity_ref,
            "enabled": True,
        }
        for target in targets
    ]
    imported = db.seed_watch_groups_if_empty(groups)
    if imported:
        logger.debug("Seeded %s watch groups from TELEGRAM_CLIENT_TARGETS", imported)


def create_server(config: QueueUiConfig) -> ThreadingHTTPServer:
    db = ChatDatabase(config.db_path)
    db.init_schema()
    try:
        seeded = db.seed_broadcast_bots_from_tokens(_bot_tokens())
        removed = db.delete_broadcast_bots_without_tokens()
        if seeded:
            logger.debug("Seeded %s broadcast bot tokens from .env into DB slots", seeded)
        if removed:
            logger.debug("Removed %s broadcast bot slots without tokens", removed)
    except Exception:
        logger.exception("Failed to seed broadcast bots from .env")
    _seed_watch_groups_from_env(db)

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
    logger.warning("Queue UI running at http://%s:%s", host, port)
    if config.auth_enabled:
        logger.warning("Queue UI login enabled for user=%s", config.auth_username)
    else:
        logger.warning(
            "Queue UI login disabled. Set QUEUE_UI_PASSWORD in .env to require authentication."
        )
    server.serve_forever()


if __name__ == "__main__":
    main()
