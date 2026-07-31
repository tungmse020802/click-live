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
]).catch((err) => {
  statusEl.textContent = `Lỗi tải settings: ${err.message}`;
});
