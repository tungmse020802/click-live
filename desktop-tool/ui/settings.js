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
const userListHint = document.getElementById('userListHint');

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
  if (!loggedIn && session?.queueUrl) {
    loadUserList(session.queueUrl).catch(() => {});
  }
}

async function refreshAuthSession() {
  const session = await window.desktopTool.getSession();
  renderAuthSession(session);
  if (!session.loggedIn) {
    statusEl.textContent = 'Chọn user và đăng nhập để nhận lệnh Mở link từ web.';
  }
  return session;
}

function fillUserSelect(users, selected = '') {
  loginUsername.innerHTML = '<option value="">— chọn user —</option>';
  for (const name of users) {
    const opt = document.createElement('option');
    opt.value = name;
    opt.textContent = name;
    if (name === selected) opt.selected = true;
    loginUsername.appendChild(opt);
  }
  userListHint.textContent = users.length
    ? `${users.length} tài khoản từ server`
    : 'Server chưa cấu hình user — kiểm tra QUEUE_UI_USERS trên VPS.';
}

async function loadUserList(queueUrl) {
  const url = String(queueUrl || queueUrlInput.value || '').trim();
  if (!url) return;
  userListHint.textContent = 'Đang tải danh sách user…';
  const users = await window.desktopTool.fetchUsers(url);
  fillUserSelect(users, loginUsername.value);
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
    if (!username) throw new Error('Chọn tài khoản');
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
  statusEl.textContent = 'Đã đăng xuất — chọn user và đăng nhập lại để nhận lệnh mở link.';
});

queueUrlInput.addEventListener('change', async () => {
  const url = queueUrlInput.value.trim();
  if (url) {
    await persistPartial({ queueUrl: url });
    loadUserList(url).catch((err) => {
      userListHint.textContent = err.message || 'Không tải được user list';
    });
  }
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
]).then(async () => {
  const url = queueUrlInput.value.trim();
  if (url) await loadUserList(url).catch(() => {});
}).catch((err) => {
  statusEl.textContent = `Lỗi tải settings: ${err.message}`;
});
