const delayLabel = document.getElementById('delayLabel');
const statusEl = document.getElementById('status');
const lastClickResult = document.getElementById('lastClickResult');
const lastClickPos = document.getElementById('lastClickPos');
const lastClickAt = document.getElementById('lastClickAt');
const lastClickRawTime = document.getElementById('lastClickRawTime');
const lastClickTarget = document.getElementById('lastClickTarget');
const lastClickOffsetHint = document.getElementById('lastClickOffsetHint');
const lastClickOffsetLead = document.getElementById('lastClickOffsetLead');
const lastClickDrift = document.getElementById('lastClickDrift');
const jobTimeline = document.getElementById('jobTimeline');
const offsetExplain = document.getElementById('offsetExplain');
const defaultWaitSec = document.getElementById('defaultWaitSec');
const clickX = document.getElementById('clickX');
const clickY = document.getElementById('clickY');
const autoClickEnabled = document.getElementById('autoClickEnabled');
const loginPanel = document.getElementById('loginPanel');
const loggedInPanel = document.getElementById('loggedInPanel');
const loggedInUser = document.getElementById('loggedInUser');
const loggedInUrl = document.getElementById('loggedInUrl');
const queueUrlInput = document.getElementById('queueUrl');
const loginUsername = document.getElementById('loginUsername');
const loginPassword = document.getElementById('loginPassword');
const logPanel = document.getElementById('logPanel');
const logEmpty = document.getElementById('logEmpty');
const logPath = document.getElementById('logPath');

let logAutoScroll = true;
const MAX_LOG_LINES_UI = 200;
const MAX_TIMELINE_LINES = 8;
let currentTimelineJobId = null;

function formatLogDetail(entry) {
  const d = entry.data;
  if (!d || typeof d !== 'object') return '';
  const parts = [];
  if (d.jobId != null) parts.push(`#${d.jobId}`);
  if (d.source) parts.push(`src=${d.source}`);
  if (d.method) parts.push(d.method);
  if (d.driftFromDisplayMs != null) parts.push(`drift=${d.driftFromDisplayMs}ms`);
  if (d.driftMs != null) parts.push(`drift=${d.driftMs}ms`);
  if (d.clickDurationMs != null) parts.push(`click=${d.clickDurationMs}ms`);
  if (d.fireDelayMs != null) parts.push(`fire=${d.fireDelayMs}ms`);
  if (d.offsetMs != null) parts.push(`off=${d.offsetMs}ms`);
  if (d.leadMs != null) parts.push(`lead=${d.leadMs}ms`);
  if (d.baseLeadMs != null) parts.push(`base=${d.baseLeadMs}ms`);
  if (d.correctionMs != null && d.correctionMs !== 0) parts.push(`corr=${d.correctionMs}ms`);
  if (d.driftEma != null) parts.push(`driftEma=${d.driftEma}ms`);
  if (d.startupMs != null) parts.push(`startup=${d.startupMs}ms`);
  if (d.error) parts.push(String(d.error));
  return parts.length ? ` · ${parts.join(' · ')}` : '';
}

function formatLogTime(iso) {
  try {
    return new Date(iso).toLocaleTimeString('vi-VN', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      fractionalSecondDigits: 3,
      hour12: false,
    });
  } catch {
    return iso;
  }
}

function renderLogEntry(entry) {
  const line = document.createElement('div');
  const level = entry.level || 'info';
  const event = entry.event || level;
  line.className = `log-line level-${level} evt-${event}`;
  const detail = formatLogDetail(entry);
  line.innerHTML = `<span class="time">${formatLogTime(entry.ts)}</span> `
    + `<span class="evt">[${event}]</span> `
    + `<span class="msg">${entry.msg || ''}</span>`
    + (detail ? `<span class="detail">${detail}</span>` : '');
  return line;
}

function trimLogPanel() {
  const lines = logPanel.querySelectorAll('.log-line');
  if (lines.length <= MAX_LOG_LINES_UI) return;
  for (let i = 0; i < lines.length - MAX_LOG_LINES_UI; i += 1) {
    lines[i].remove();
  }
}

function appendLogEntry(entry) {
  if (logEmpty.parentNode) logEmpty.remove();
  logPanel.appendChild(renderLogEntry(entry));
  trimLogPanel();
  if (logAutoScroll) {
    logPanel.scrollTop = logPanel.scrollHeight;
  }
}

function renderLogList(entries) {
  logPanel.querySelectorAll('.log-line').forEach((el) => el.remove());
  if (!entries.length) {
    if (!logEmpty.parentNode) logPanel.appendChild(logEmpty);
    return;
  }
  if (logEmpty.parentNode) logEmpty.remove();
  entries.forEach((entry) => logPanel.appendChild(renderLogEntry(entry)));
  if (logAutoScroll) {
    logPanel.scrollTop = logPanel.scrollHeight;
  }
}

async function loadLogHistory() {
  const info = await window.desktopTool.getLogs(MAX_LOG_LINES_UI);
  if (info.logFile) {
    logPath.textContent = info.logFile;
    logPath.title = info.logFile;
  }
  renderLogList(info.logs || []);
}

logPanel.addEventListener('scroll', () => {
  const nearBottom = logPanel.scrollHeight - logPanel.scrollTop - logPanel.clientHeight < 24;
  logAutoScroll = nearBottom;
});

document.getElementById('clearLogsBtn').addEventListener('click', async () => {
  await window.desktopTool.clearLogs();
  renderLogList([]);
});

document.getElementById('openLogFolderBtn').addEventListener('click', async () => {
  try {
    await window.desktopTool.openLogFolder();
  } catch (err) {
    statusEl.textContent = err.message || 'Không mở được folder log';
  }
});

window.desktopTool.onLog((entry) => {
  appendLogEntry(entry);
});

function formatClockTime(ms) {
  if (ms == null || !Number.isFinite(ms)) return '—';
  try {
    return new Date(ms).toLocaleTimeString('vi-VN', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      fractionalSecondDigits: 3,
      hour12: false,
    });
  } catch {
    return '—';
  }
}

function updateOffsetExplain(offsetMs) {
  const ms = Number(offsetMs) || 0;
  const sec = Math.abs(ms / 1000).toFixed(2);
  if (ms < 0) {
    offsetExplain.innerHTML = `Offset <strong>${(ms / 1000).toFixed(2)}s</strong>: mốc overlay <strong>0.0s</strong> sớm hơn TIME trong tin <strong>${sec}s</strong> → click sớm hơn TIME gốc. Số còn lại trên overlay lúc click (~0.08–0.10s) là do <strong>lead</strong> (bù độ trễ OS), không phải offset.`;
  } else if (ms > 0) {
    offsetExplain.innerHTML = `Offset <strong>+${sec}s</strong>: mốc overlay 0.0s muộn hơn TIME trong tin ${sec}s → click muộn hơn TIME gốc. Lead vẫn khiến click chạy sớm ~0.1s trên overlay so với 0.0s.`;
  } else {
    offsetExplain.innerHTML = 'Offset <strong>0.00s</strong>: mốc overlay 0.0s trùng TIME trong tin. Click vẫn chạy sớm ~lead (≈0.1s trên overlay) để bù độ trễ OS.';
  }
}

function appendTimelineLine(event, msg, detailParts) {
  jobTimeline.classList.add('visible');
  const line = document.createElement('div');
  line.className = 'tl-line';
  const now = formatLogTime(new Date().toISOString());
  const parts = (detailParts || []).filter(Boolean);
  const detail = parts.length ? ` · ${parts.join(' · ')}` : '';
  line.innerHTML = `<span class="time">${now}</span> `
    + `<span class="evt">[${event}]</span> `
    + `<span class="msg">${msg}</span>`
    + (detail ? `<span class="detail">${detail}</span>` : '');
  jobTimeline.appendChild(line);
  while (jobTimeline.children.length > MAX_TIMELINE_LINES) {
    jobTimeline.removeChild(jobTimeline.firstChild);
  }
  jobTimeline.scrollTop = jobTimeline.scrollHeight;
}

function resetJobTimeline(jobId) {
  currentTimelineJobId = jobId;
  jobTimeline.innerHTML = '';
  jobTimeline.classList.remove('visible');
}

function formatDriftSec(ms) {
  if (ms == null || !Number.isFinite(ms)) {
    return { text: '—', className: '' };
  }
  const sec = ms / 1000;
  const sign = sec >= 0 ? '+' : '';
  let hint = 'đúng giờ';
  if (sec > 0.05) hint = 'muộn';
  else if (sec < -0.05) hint = 'sớm';
  return {
    text: `${sign}${sec.toFixed(3)}s (${hint})`,
    className: sec > 0.05 ? 'drift-late' : sec < -0.05 ? 'drift-early' : 'drift-ok',
  };
}

/** Diễn giải lệch giờ cho người dùng + gợi ý chỉnh offset. */
function formatUserTimingFeedback(driftMs) {
  if (driftMs == null || !Number.isFinite(driftMs)) {
    return {
      driftText: '—',
      offsetHint: '—',
      className: '',
      adjustMs: null,
    };
  }

  const absMs = Math.abs(driftMs);
  const absSec = (absMs / 1000).toFixed(3).replace('.', ',');

  if (absMs <= 30) {
    return {
      driftText: `Gần đúng (lệch ${absSec}s)`,
      offsetHint: 'Offset hiện tại ổn, chưa cần chỉnh.',
      className: 'drift-ok',
      adjustMs: 0,
    };
  }

  const adjustMs = -Math.round(driftMs / 10) * 10;
  const adjustSec = (adjustMs / 1000).toFixed(2).replace('.', ',');
  const sign = adjustMs >= 0 ? '+' : '';

  if (driftMs > 0) {
    return {
      driftText: `Muộn ${absSec}s so với giờ chuẩn`,
      offsetHint: `Giảm offset ${sign}${adjustSec}s để click sớm hơn.`,
      className: 'drift-late',
      adjustMs,
    };
  }

  return {
    driftText: `Sớm ${absSec}s so với giờ chuẩn`,
    offsetHint: `Tăng offset ${sign}${adjustSec}s để click muộn hơn.`,
    className: 'drift-early',
    adjustMs,
  };
}

function renderClickStatusSummary(payload) {
  const jobLabel = payload.isTest ? 'Test click' : `Job #${payload.jobId || '?'}`;
  const clickAt = formatClockTime(payload.clickedAt);
  const targetAt = payload.displayTargetMs != null
    ? formatClockTime(payload.displayTargetMs)
    : null;
  const feedback = formatUserTimingFeedback(payload.driftFromDisplayMs);

  if (payload.isTest || targetAt == null) {
    statusEl.innerHTML = `<div class="status-line"><strong>${jobLabel}</strong> · click thử tại <strong>${payload.x}, ${payload.y}</strong> lúc <strong>${clickAt}</strong></div>`;
    return;
  }

  statusEl.innerHTML = [
    `<div class="status-line"><strong>${jobLabel}</strong> · click tại <strong>${payload.x}, ${payload.y}</strong></div>`,
    `<div class="status-line">Click thực tế: <strong>${clickAt}</strong> · Giờ chuẩn: <strong>${targetAt}</strong></div>`,
    `<div class="status-line">Lệch: <strong class="${feedback.className}">${feedback.driftText}</strong></div>`,
    `<div class="status-line offset-tip">${feedback.offsetHint}</div>`,
  ].join('');
}

function renderLastClickResult(payload) {
  if (!payload || payload.type !== 'clicked') return;

  lastClickResult.classList.add('visible');
  const who = payload.isTest ? ' (test)' : '';
  lastClickPos.textContent = `${payload.x}, ${payload.y}${payload.method ? ` · ${payload.method}` : ''}${who}`;

  lastClickAt.textContent = formatClockTime(payload.clickedAt);

  if (payload.displayTargetMs != null) {
    lastClickTarget.textContent = formatClockTime(payload.displayTargetMs);
  } else {
    lastClickTarget.textContent = payload.isTest ? '— (test)' : '—';
  }

  lastClickRawTime.textContent = payload.endTimeMs != null
    ? formatClockTime(payload.endTimeMs)
    : (payload.isTest ? '— (test)' : '—');

  const feedback = formatUserTimingFeedback(payload.driftFromDisplayMs);
  lastClickDrift.textContent = feedback.driftText;
  lastClickDrift.className = `value ${feedback.className}`.trim();
  lastClickOffsetHint.textContent = feedback.offsetHint;
  lastClickOffsetHint.className = 'value';

  const offSec = payload.offsetMs != null
    ? `${payload.offsetMs >= 0 ? '+' : ''}${(payload.offsetMs / 1000).toFixed(2)}s`
    : '—';
  lastClickOffsetLead.textContent = offSec;

  renderClickStatusSummary(payload);

  if (!payload.isTest) {
    appendTimelineLine('click', `job #${payload.jobId} clicked`, [
      `#${payload.jobId}`,
      payload.source ? `src=${payload.source}` : null,
      payload.method || null,
      payload.driftFromDisplayMs != null ? `drift=${payload.driftFromDisplayMs}ms` : null,
      payload.clickDurationMs != null ? `click=${payload.clickDurationMs}ms` : null,
      payload.offsetMs != null ? `off=${payload.offsetMs}ms` : null,
      payload.leadMs != null ? `lead=${payload.leadMs}ms` : null,
    ]);
  }
}

function formatOffset(ms) {
  const sec = ms / 1000;
  const text = `${sec >= 0 ? '+' : ''}${sec.toFixed(2)}s`;
  delayLabel.textContent = text;
  delayLabel.classList.toggle('positive', ms > 0);
  delayLabel.classList.toggle('negative', ms < 0);
  updateOffsetExplain(ms);
}

function applySettings(s) {
  defaultWaitSec.value = ((s.defaultWaitMs || 0) / 1000).toFixed(2);
  clickX.value = s.clickX;
  clickY.value = s.clickY;
  autoClickEnabled.checked = Boolean(s.autoClickEnabled);
  formatOffset(s.delayOffsetMs || 0);
  if (s.queueUrl) {
    queueUrlInput.value = s.queueUrl;
  }
  if (s.queueUsername && !loginUsername.value) {
    loginUsername.value = s.queueUsername;
  }
}

function renderAuthSession(session) {
  const loggedIn = Boolean(session?.loggedIn);
  loginPanel.classList.toggle('hidden', loggedIn);
  loggedInPanel.classList.toggle('hidden', !loggedIn);
  if (loggedIn) {
    loggedInUser.textContent = session.queueUsername || '?';
    loggedInUrl.textContent = session.queueUrl ? `Poll: ${session.queueUrl}` : '';
  } else if (session?.queueUrl) {
    queueUrlInput.value = session.queueUrl;
  }
}

async function refreshAuthSession() {
  const session = await window.desktopTool.getSession();
  renderAuthSession(session);
  if (!session.loggedIn) {
    statusEl.textContent = 'Nhập user/mật khẩu queue UI rồi bấm Đăng nhập desktop.';
  }
  return session;
}

async function persistPartial(partial) {
  const s = await window.desktopTool.saveSettings(partial);
  applySettings(s);
}

defaultWaitSec.addEventListener('change', () => {
  const sec = Number(defaultWaitSec.value);
  persistPartial({ defaultWaitMs: Math.max(0, Math.round(sec * 1000)) });
});

clickX.addEventListener('change', () => persistPartial({ clickX: Number(clickX.value) || 0 }));
clickY.addEventListener('change', () => persistPartial({ clickY: Number(clickY.value) || 0 }));
autoClickEnabled.addEventListener('change', () => {
  persistPartial({ autoClickEnabled: autoClickEnabled.checked });
});

document.querySelectorAll('[data-delta]').forEach((btn) => {
  btn.addEventListener('click', async () => {
    const delta = Number(btn.dataset.delta);
    const s = await window.desktopTool.adjustDelay(delta);
    applySettings(s);
  });
});

document.getElementById('pickBtn').addEventListener('click', async () => {
  statusEl.textContent = 'Chọn điểm trên màn hình...';
  try {
    const point = await window.desktopTool.pickPoint();
    await persistPartial({ clickX: point.x, clickY: point.y });
    statusEl.innerHTML = `Đã lưu điểm click: <strong>${point.x}, ${point.y}</strong>`;
  } catch (err) {
    statusEl.textContent = err.message || 'Đã huỷ';
  }
});

document.getElementById('testClickBtn').addEventListener('click', async () => {
  statusEl.textContent = 'Đang test click...';
  try {
    await window.desktopTool.ensureAccessibility();
    await window.desktopTool.testClick();
    /* notifySchedule từ main → onSchedule → renderLastClickResult */
  } catch (err) {
    statusEl.textContent = `Lỗi click: ${err.message}`;
  }
});

document.getElementById('accessBtn').addEventListener('click', async () => {
  const result = await window.desktopTool.ensureAccessibility();
  statusEl.textContent = result?.trusted
    ? 'Accessibility đã được cấp quyền.'
    : 'macOS đã mở hộp thoại — bật quyền Accessibility cho Electron / Click Live Desktop Tool, rồi Test click lại.';
});

document.getElementById('loginBtn').addEventListener('click', async () => {
  statusEl.textContent = 'Đang đăng nhập...';
  try {
    const queueUrl = queueUrlInput.value.trim();
    const username = loginUsername.value.trim();
    if (!username) throw new Error('Nhập tên đăng nhập');
    if (!loginPassword.value) throw new Error('Nhập mật khẩu');
    const result = await window.desktopTool.login({
      queueUrl,
      username,
      password: loginPassword.value,
    });
    loginPassword.value = '';
    await refreshAuthSession();
    statusEl.innerHTML = `Đã đăng nhập <strong>${result.username}</strong> — chỉ link từ user này trên web mới mở Chrome.`;
  } catch (err) {
    statusEl.textContent = err.message || 'Đăng nhập thất bại';
  }
});

document.getElementById('logoutBtn').addEventListener('click', async () => {
  await window.desktopTool.logout();
  await refreshAuthSession();
  statusEl.textContent = 'Đã đăng xuất — nhập user/mật khẩu và đăng nhập lại.';
});

loginPassword.addEventListener('keydown', (event) => {
  if (event.key === 'Enter') {
    document.getElementById('loginBtn').click();
  }
});

queueUrlInput.addEventListener('change', () => {
  const url = queueUrlInput.value.trim();
  if (url) persistPartial({ queueUrl: url });
});

window.desktopTool.onSchedule((payload) => {
  if (payload.type === 'scheduled') {
    if (payload.jobId !== currentTimelineJobId) {
      resetJobTimeline(payload.jobId);
    }
    const sec = (payload.waitMs / 1000).toFixed(2).replace('.', ',');
    statusEl.innerHTML = `<div class="status-line">Job #${payload.jobId || '?'} · còn <strong>${sec}s</strong> tới giờ click</div>`
      + (payload.timeLabel ? `<div class="status-line offset-tip">${payload.timeLabel}</div>` : '');
    appendTimelineLine('schedule', `job #${payload.jobId} scheduled`, [
      `#${payload.jobId}`,
      payload.source ? `src=${payload.source}` : null,
      payload.fireDelayMs != null ? `fire=${payload.fireDelayMs}ms` : null,
      payload.offsetMs != null ? `off=${payload.offsetMs}ms` : null,
      payload.leadMs != null ? `lead=${payload.leadMs}ms` : null,
    ]);
  } else if (payload.type === 'wait') {
    statusEl.innerHTML = `<div class="status-line">Job #${payload.jobId || '?'} · sắp click…</div>`;
    appendTimelineLine('wait', `job #${payload.jobId} wait done`, [
      `#${payload.jobId}`,
      payload.driftMs != null ? `drift=${payload.driftMs}ms` : null,
      payload.offsetMs != null ? `off=${payload.offsetMs}ms` : null,
    ]);
  } else if (payload.type === 'clicked') {
    renderLastClickResult(payload);
  } else if (payload.type === 'error') {
    statusEl.innerHTML = `Lỗi job #${payload.jobId || '?'}: ${payload.error || '?'}`;
    appendTimelineLine('error', `job #${payload.jobId} failed`, [
      `#${payload.jobId}`,
      payload.error || null,
    ]);
  }
});

Promise.all([
  window.desktopTool.getSettings().then(applySettings),
  refreshAuthSession(),
  loadLogHistory(),
]).catch((err) => {
  statusEl.textContent = `Lỗi tải settings: ${err.message}`;
});
