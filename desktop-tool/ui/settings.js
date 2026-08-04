const delayLabel = document.getElementById('delayLabel');
const statusEl = document.getElementById('status');
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

function formatOffset(ms) {
  const sec = ms / 1000;
  const text = `${sec >= 0 ? '+' : ''}${sec.toFixed(2)}s`;
  delayLabel.textContent = text;
  delayLabel.classList.toggle('positive', ms > 0);
  delayLabel.classList.toggle('negative', ms < 0);
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
    const result = await window.desktopTool.testClick();
    statusEl.innerHTML = `Test click OK tại <strong>${result.x}, ${result.y}</strong> (${result.method})`;
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
    const sec = (payload.waitMs / 1000).toFixed(2);
    const closeSec = payload.closeWaitMs ? (payload.closeWaitMs / 1000).toFixed(0) : '30';
    statusEl.innerHTML = `Job #${payload.jobId || '?'} · click <strong>${sec}s</strong> (0.0s) · đóng tab +${closeSec}s${payload.timeLabel ? ` · ${payload.timeLabel}` : ''}`;
  } else if (payload.type === 'clicked') {
    statusEl.innerHTML = `Đã click desktop tại <strong>${payload.x}, ${payload.y}</strong> · job #${payload.jobId || '?'}`;
  }
});

Promise.all([
  window.desktopTool.getSettings().then(applySettings),
  refreshAuthSession(),
  loadLogHistory(),
]).catch((err) => {
  statusEl.textContent = `Lỗi tải settings: ${err.message}`;
});
