"use strict";

const SETTING_FIELDS = [
  "launcherTool",
  "goIosPath",
  "pymobiledevice3Path",
  "wdaBundleId",
  "queueUrl",
  "wdaProjectPath",
  "automationControllerPath",
  "pythonPath",
  "queuePollWaitSeconds",
  "liveTimeMinSeconds",
  "liveTimeMaxSeconds",
  "openTapRequestLeadMs",
  "openTapTransportCompensationMs",
  "openMaxLatenessMs",
  "filterMaxViews",
  "filterRewardMode",
  "filterMinBox1",
  "filterMinBox2",
  "filterMinRate",
  "filterNoteContains",
  "automationEnabled",
];

const SETTING_FIELD_ALIASES = {
  appleTeamIdSettings: "appleTeamId",
};

const COUNTRY_FILTER_OPTIONS = [
  ["BR", "Brazil"],
  ["VN", "Vietnam"],
  ["TH", "Thailand"],
  ["PH", "Philippines"],
  ["ID", "Indonesia"],
  ["MY", "Malaysia"],
  ["SG", "Singapore"],
  ["KH", "Cambodia"],
  ["LA", "Laos"],
  ["MM", "Myanmar"],
  ["JP", "Japan"],
  ["KR", "Korea"],
  ["TW", "Taiwan"],
  ["HK", "Hong Kong"],
  ["CN", "China"],
  ["IN", "India"],
  ["BD", "Bangladesh"],
  ["PK", "Pakistan"],
  ["US", "United States"],
  ["MX", "Mexico"],
  ["CO", "Colombia"],
  ["AR", "Argentina"],
  ["CL", "Chile"],
  ["PE", "Peru"],
  ["GB", "United Kingdom"],
  ["FR", "France"],
  ["DE", "Germany"],
  ["IT", "Italy"],
  ["ES", "Spain"],
  ["TR", "Turkey"],
  ["RU", "Russia"],
  ["UA", "Ukraine"],
  ["AE", "UAE"],
  ["SA", "Saudi Arabia"],
  ["EG", "Egypt"],
  ["NG", "Nigeria"],
  ["ZA", "South Africa"],
];

const $ = (id) => document.getElementById(id);
let lastState = null;
let queueSnapshot = null;
let queueLoading = false;
let queueTimer = null;
const logBuffers = new Map([["all", []]]);

function escapeHtml(value) {
  return String(value || "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[char]));
}

function appendLog(line) {
  const text = String(line || "");
  const deviceMatch = text.match(/\[(iphone-\d+)\]/i);
  const deviceId = deviceMatch ? deviceMatch[1] : "";
  pushLogLine("all", text);
  if (deviceId) pushLogLine(deviceId, text);
  renderActiveLog();
}

function pushLogLine(key, line) {
  const lines = logBuffers.get(key) || [];
  lines.push(line);
  logBuffers.set(key, lines.slice(-1000));
}

function renderActiveLog() {
  const view = $("logView");
  const key = $("logDeviceFilter")?.value || "all";
  view.textContent = (logBuffers.get(key) || []).join("\n");
  view.scrollTop = view.scrollHeight;
}

function updateLogDeviceOptions(state) {
  const select = $("logDeviceFilter");
  if (!select || !state?.devices) return;
  const previous = select.value || "all";
  const options = ['<option value="all">All devices</option>'].concat(
    state.devices.map((device) => (
      `<option value="${escapeHtml(device.deviceId)}">${escapeHtml(device.deviceId)} · ${escapeHtml(device.name || device.udid?.slice(-8) || "unassigned")}</option>`
    )),
  );
  select.innerHTML = options.join("");
  select.value = [...select.options].some((option) => option.value === previous) ? previous : "all";
  renderActiveLog();
}

function setActiveTab(name) {
  for (const tab of document.querySelectorAll(".tab")) {
    tab.classList.toggle("active", tab.dataset.tab === name);
  }
  for (const panel of document.querySelectorAll(".tab-panel")) {
    panel.classList.toggle("active", panel.id === `tab-${name}`);
  }
  if (name === "queue") {
    loadQueue().catch((error) => showQueueError(error.message));
    scheduleQueueRefresh();
  } else if (queueTimer) {
    clearTimeout(queueTimer);
    queueTimer = null;
  }
}

function queueUrlFromItem(item) {
  const payload = item?.payload || {};
  const candidates = [
    payload.url,
    payload.link,
    payload.deeplink,
    payload.deep_link,
    payload.live_url,
    payload.room_url,
    item?.message?.text,
  ];
  for (const value of candidates) {
    const match = String(value || "").match(/(?:https?:\/\/|tiktok:\/\/)[^\s<>'"]+/i);
    if (match) return match[0];
  }
  return "";
}

function queueTimeFromItem(item) {
  const payload = item?.payload || {};
  const text = String(payload.TIME || payload.time || item?.message?.text || "");
  const match = text.match(/TIME\s*[:：]\s*(\d{1,2}:\d{2}\s*s?(?:\s*-\s*\d{1,2}:\d{2}:\d{2})?)/i)
    || text.match(/(\d{1,2}:\d{2}\s*s?\s*-\s*\d{1,2}:\d{2}:\d{2})/i);
  return match ? match[1].trim() : "";
}

function queueCountryCodesFromItem(item) {
  const signal = item?.payload?.box_signal || {};
  const codes = new Set();
  for (const code of signal.country_codes || []) {
    const normalized = String(code || "").trim().toUpperCase();
    if (/^[A-Z]{2}$/.test(normalized)) codes.add(normalized);
  }
  const text = String(item?.message?.text || "");
  for (const match of text.matchAll(/(?:^|\s|#)([A-Z]{2})\d{2,}/g)) {
    codes.add(match[1].toUpperCase());
  }
  return [...codes];
}

function selectedQueueCountries() {
  return [...document.querySelectorAll('#queueCountryMenu input[type="checkbox"]:checked')]
    .map((input) => input.value)
    .filter(Boolean);
}

function updateQueueCountryButton() {
  const selected = selectedQueueCountries();
  const button = $("queueCountryButton");
  if (!button) return;
  if (!selected.length) {
    button.textContent = "All countries";
  } else if (selected.length <= 3) {
    button.textContent = selected.join(", ");
  } else {
    button.textContent = `${selected.length} countries`;
  }
}

function queueCountryMatches(item) {
  const selected = selectedQueueCountries();
  if (!selected.length) return true;
  const codes = queueCountryCodesFromItem(item);
  return codes.some((code) => selected.includes(code));
}

function showQueueError(message) {
  const node = $("queueError");
  node.textContent = message || "";
  node.classList.toggle("visible", Boolean(message));
}

function updateQueueDeviceOptions(state) {
  const select = $("queueDevice");
  if (!select || !state?.devices) return;
  const previous = select.value;
  const devices = state.devices.filter((device) => device.enabled && device.udid);
  select.innerHTML = devices.length
    ? devices.map((device) => {
      const runtime = device.runtime?.state || "idle";
      return `<option value="${escapeHtml(device.deviceId)}">${escapeHtml(device.deviceId)} · ${escapeHtml(device.name || device.udid.slice(-8))} · ${escapeHtml(runtime)}</option>`;
    }).join("")
    : '<option value="">No assigned iPhone</option>';
  if (devices.some((device) => device.deviceId === previous)) select.value = previous;
  else {
    const running = devices.find((device) => device.runtime?.state === "running");
    if (running) select.value = running.deviceId;
  }
}

function initQueueCountryFilter() {
  const menu = $("queueCountryMenu");
  const button = $("queueCountryButton");
  if (!menu || !button) return;
  menu.innerHTML = COUNTRY_FILTER_OPTIONS.map(([code, label]) => `
    <label>
      <input type="checkbox" value="${escapeHtml(code)}" />
      <span>${escapeHtml(code)} · ${escapeHtml(label)}</span>
    </label>
  `).join("");
  button.addEventListener("click", (event) => {
    event.stopPropagation();
    button.closest(".queue-country-filter")?.classList.toggle("open");
  });
  menu.addEventListener("click", (event) => event.stopPropagation());
  menu.addEventListener("change", () => {
    updateQueueCountryButton();
    if (queueSnapshot) renderQueue(queueSnapshot);
  });
  document.addEventListener("click", () => {
    button.closest(".queue-country-filter")?.classList.remove("open");
  });
  updateQueueCountryButton();
}

function renderQueue(snapshot) {
  queueSnapshot = snapshot;
  const tbody = $("queueTableBody");
  const allItems = snapshot?.items || [];
  const items = allItems.filter(queueCountryMatches);
  tbody.innerHTML = "";
  $("queueStats").textContent = `${items.length}/${allItems.length} shown · ${snapshot?.stats?.pending || 0} pending`;
  $("queueUpdated").textContent = snapshot?.generated_at
    ? `Updated ${new Date(snapshot.generated_at).toLocaleTimeString()}`
    : "Updated now";
  $("queueServerLabel").textContent = lastState?.config?.queueUrl || "";
  if (!items.length) {
    tbody.innerHTML = '<tr><td colspan="6" class="muted">No queue messages for this filter.</td></tr>';
    return;
  }
  for (const item of items) {
    const signal = item.payload?.box_signal || {};
    const countries = queueCountryCodesFromItem(item);
    const url = queueUrlFromItem(item);
    const time = queueTimeFromItem(item);
    const source = item.payload?.target_label || item.room?.title || item.payload?.source || "—";
    const text = item.message?.text || "";
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><span class="queue-id">#${escapeHtml(item.id)}</span></td>
      <td>
        <span class="queue-badge ${escapeHtml(item.status)}">${escapeHtml(item.status)}</span>
        ${item.lease_expired ? '<span class="queue-badge dead">expired</span>' : ""}
      </td>
      <td>
        <div class="queue-meta">
          <strong>BOX ${escapeHtml(signal.box || "—")}</strong>
          <span>${escapeHtml(time || "No TIME")}</span>
          <span class="muted">Country ${escapeHtml(countries.join(", ") || "—")}</span>
          <span class="muted">Rate ${escapeHtml(signal.rate ?? "—")} · Views ${escapeHtml(signal.views ?? "—")}</span>
        </div>
      </td>
      <td>
        <div class="queue-message">${escapeHtml(text)}</div>
        ${url ? `<div class="queue-link">${escapeHtml(url)}</div>` : '<div class="error">No URL found</div>'}
      </td>
      <td>${escapeHtml(source)}</td>
      <td>
        <div class="queue-actions">
          <button class="btn small primary" data-queue-open="${escapeHtml(item.id)}" ${url ? "" : "disabled"}>Run on iPhone</button>
          <button class="btn small" data-queue-done="${escapeHtml(item.id)}" ${item.status === "done" ? "disabled" : ""}>Mark done</button>
        </div>
      </td>
    `;
    tbody.appendChild(tr);
  }
  for (const button of tbody.querySelectorAll("[data-queue-open]")) {
    button.addEventListener("click", async () => {
      const deviceId = $("queueDevice").value;
      if (!deviceId) return showQueueError("Assign and select an iPhone first.");
      button.disabled = true;
      try {
        const result = await window.wdaPanel.queueDispatch(Number(button.dataset.queueOpen), deviceId);
        appendLog(`Queue #${result.jobId} ran on ${result.deviceId}`);
        showQueueError("");
      } catch (error) {
        showQueueError(error.message);
        appendLog(`Queue dispatch failed: ${error.message}`);
      } finally {
        button.disabled = false;
      }
    });
  }
  for (const button of tbody.querySelectorAll("[data-queue-done]")) {
    button.addEventListener("click", async () => {
      button.disabled = true;
      try {
        await window.wdaPanel.queueMarkDone(Number(button.dataset.queueDone), "WDA Control Panel manual");
        await loadQueue();
      } catch (error) {
        showQueueError(error.message);
        button.disabled = false;
      }
    });
  }
}

async function loadQueue() {
  if (queueLoading) return;
  queueLoading = true;
  $("queueRefreshButton").disabled = true;
  try {
    const snapshot = await window.wdaPanel.queueList({
      limit: Number($("queueLimit").value || 50),
      statuses: $("queueStatus").value,
    });
    showQueueError("");
    renderQueue(snapshot);
  } finally {
    queueLoading = false;
    $("queueRefreshButton").disabled = false;
    scheduleQueueRefresh();
  }
}

function scheduleQueueRefresh() {
  if (queueTimer) clearTimeout(queueTimer);
  queueTimer = null;
  const active = document.querySelector('.tab[data-tab="queue"]')?.classList.contains("active");
  if (!active || !$("queueAutoRefresh")?.checked) return;
  queueTimer = setTimeout(() => {
    loadQueue().catch((error) => showQueueError(error.message));
  }, 2000);
}

function setDot(node, status) {
  if (!node) return;
  node.classList.remove("ok", "bad", "warn");
  if (status === true) node.classList.add("ok");
  else if (status === false) node.classList.add("bad");
  else if (status === "warn") node.classList.add("warn");
}

async function refreshSetupStatus() {
  try {
    const status = await window.wdaPanel.setupStatus();
    setDot($("driverDot"), status.driver.ok);
    $("driverDetail").textContent = status.driver.detail || "—";
    setDot($("goIosDot"), status.goIos.ok);
    $("goIosDetail").textContent = `${status.goIos.detail} (${status.goIos.path})`;
    setDot($("ipaDot"), status.ipa.ok);
    $("ipaDetail").textContent = `${status.ipa.detail}`;
  } catch (error) {
    appendLog(`Setup status failed: ${error.message}`);
  }
  await refreshMacStatus();
}

async function refreshMacStatus() {
  if (!window.wdaPanel?.macStatus) return;
  try {
    const status = await window.wdaPanel.macStatus();
    if (!status?.supported) return;
    setDot($("xcodeDot"), status.xcode.ok);
    $("xcodeDetail").textContent = status.xcode.detail || "—";
    setDot($("wdaProjectDot"), status.wdaProject.ok);
    $("wdaProjectDetail").textContent = status.wdaProject.detail || status.wdaProject.path;
    setDot($("signingDot"), Boolean(status.signing?.identities?.length));
    populateSigningSelect(status.signing?.identities || []);
  } catch (error) {
    appendLog(`macOS setup status failed: ${error.message}`);
  }
}

function populateSigningSelect(identities) {
  const select = $("signingSelect");
  if (!select) return;
  const previous = select.value;
  select.innerHTML = '<option value="">— chưa chọn —</option>';
  for (const identity of identities) {
    const option = document.createElement("option");
    option.value = identity.teamId || identity.hash;
    option.textContent = `${identity.name}${identity.teamId ? ` · TEAM ${identity.teamId}` : ""}`;
    option.dataset.teamId = identity.teamId || "";
    select.appendChild(option);
  }
  if (previous) select.value = previous;
}

function renderSetupDetected(state) {
  const tbody = $("setupDetectedTable");
  tbody.innerHTML = "";
  $("setupDetectedCount").textContent = `${state.detected?.length || 0} device đã cắm`;
  if (!state.detected || !state.detected.length) {
    tbody.innerHTML = '<tr><td colspan="5" class="muted">Chưa có. Bấm Scan USB.</td></tr>';
    return;
  }
  for (const device of state.detected) {
    const slot = state.devices.find((row) => row.udid === device.udid);
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${escapeHtml(device.name || "iPhone")}</td>
      <td>${escapeHtml(device.version || "—")}</td>
      <td><code>${escapeHtml(device.udid || "—")}</code></td>
      <td>${slot ? escapeHtml(slot.deviceId) : '<span class="muted">chưa gán</span>'}</td>
      <td><button class="btn small" data-copy-udid="${escapeHtml(device.udid || "")}">Copy</button></td>
    `;
    tbody.appendChild(tr);
  }
  for (const button of tbody.querySelectorAll("button[data-copy-udid]")) {
    button.addEventListener("click", async () => {
      const udid = button.dataset.copyUdid;
      if (!udid) return;
      try {
        await navigator.clipboard.writeText(udid);
        button.textContent = "Đã copy";
        setTimeout(() => { button.textContent = "Copy"; }, 1200);
      } catch (error) {
        appendLog(`Clipboard write failed: ${error.message}`);
      }
    });
  }
}

function renderSetupInstall(state, installResults) {
  const tbody = $("setupInstallTable");
  tbody.innerHTML = "";
  const enabled = state.devices.filter((device) => device.enabled && device.udid);
  if (!enabled.length) {
    tbody.innerHTML = '<tr><td colspan="4" class="muted">Sau khi gán UDID, danh sách hiện ra ở đây.</td></tr>';
    return;
  }
  const map = new Map((installResults || []).map((row) => [row.deviceId, row]));
  for (const device of enabled) {
    const status = map.get(device.deviceId);
    const tr = document.createElement("tr");
    let statusText = '<span class="muted">chưa kiểm tra</span>';
    if (status) {
      statusText = status.installed
        ? '<span style="color: #2ecc71;">đã cài</span>'
        : `<span style="color: #f97171;">${escapeHtml(status.detail || "chưa cài")}</span>`;
    }
    tr.innerHTML = `
      <td><strong>${escapeHtml(device.deviceId)}</strong></td>
      <td><code>${escapeHtml(device.udid.slice(-12))}</code></td>
      <td>${statusText}</td>
      <td><button class="btn small" data-install-id="${escapeHtml(device.deviceId)}">Install IPA</button></td>
    `;
    tbody.appendChild(tr);
  }
  for (const button of tbody.querySelectorAll("button[data-install-id]")) {
    button.addEventListener("click", async () => {
      const deviceId = button.dataset.installId;
      button.disabled = true;
      button.textContent = "installing...";
      try {
        await window.wdaPanel.installWda(deviceId);
        button.textContent = "ok";
      } catch (error) {
        button.textContent = "lỗi";
        appendLog(`Install ${deviceId} failed: ${error.message}`);
      } finally {
        await checkInstalledList();
        button.disabled = false;
      }
    });
  }
}

async function checkInstalledList() {
  if (!lastState) return;
  try {
    const results = await window.wdaPanel.checkWdaInstalledAll();
    renderSetupInstall(lastState, results);
    const ok = results.filter((row) => row.installed).length;
    $("setupInstallSummary").textContent = `${ok}/${results.length} đã cài WDA`;
  } catch (error) {
    appendLog(`Check WDA installed failed: ${error.message}`);
  }
}

function applySettings(config) {
  for (const field of SETTING_FIELDS) {
    const el = $(field);
    if (!el) continue;
    if (el.type === "checkbox") el.checked = Boolean(config[field]);
    else el.value = config[field] != null ? String(config[field]) : "";
  }
  for (const [elementId, configKey] of Object.entries(SETTING_FIELD_ALIASES)) {
    const el = $(elementId);
    if (!el) continue;
    el.value = config[configKey] != null ? String(config[configKey]) : "";
  }
  // Mac wizard mirrors the same Team ID input
  if ($("appleTeamId") && config.appleTeamId) $("appleTeamId").value = config.appleTeamId;
}

function readSettings() {
  const result = {};
  for (const field of SETTING_FIELDS) {
    const el = $(field);
    if (!el) continue;
    if (el.type === "checkbox") {
      result[field] = el.checked;
    } else if (el.type === "number") {
      const value = Number(el.value);
      result[field] = Number.isFinite(value) ? value : undefined;
    } else {
      result[field] = el.value.trim();
    }
  }
  for (const [elementId, configKey] of Object.entries(SETTING_FIELD_ALIASES)) {
    const el = $(elementId);
    if (!el) continue;
    result[configKey] = el.value.trim();
  }
  if ($("appleTeamId")) {
    const wizardValue = $("appleTeamId").value.trim();
    if (wizardValue) result.appleTeamId = wizardValue;
  }
  return result;
}

function ensureCard(deviceId) {
  const grid = $("deviceGrid");
  let card = grid.querySelector(`.device-card[data-device-id="${deviceId}"]`);
  if (card) return card;
  const template = $("deviceCardTemplate");
  card = template.content.firstElementChild.cloneNode(true);
  card.dataset.deviceId = deviceId;
  grid.appendChild(card);
  card.querySelector('[data-role="save"]').addEventListener("click", async () => {
    const patch = readDeviceCard(card);
    try {
      await window.wdaPanel.saveDevice(deviceId, patch);
      appendLog(`Saved ${deviceId}`);
    } catch (error) {
      appendLog(`Save ${deviceId} failed: ${error.message}`);
    }
  });
  card.querySelector('[data-role="start"]').addEventListener("click", async () => {
    const patch = readDeviceCard(card);
    try {
      await window.wdaPanel.saveDevice(deviceId, patch);
      await window.wdaPanel.startDevice(deviceId);
    } catch (error) {
      appendLog(`Start ${deviceId} failed: ${error.message}`);
    }
  });
  card.querySelector('[data-role="stop"]').addEventListener("click", async () => {
    try {
      await window.wdaPanel.stopDevice(deviceId);
    } catch (error) {
      appendLog(`Stop ${deviceId} failed: ${error.message}`);
    }
  });
  card.querySelector('[data-role="open"]').addEventListener("click", async () => {
    const url = $("bulkUrl").value.trim() || prompt(`URL to open on ${deviceId}`);
    if (!url) return;
    try {
      await window.wdaPanel.openUrl(deviceId, url);
    } catch (error) {
      appendLog(`Open URL on ${deviceId} failed: ${error.message}`);
    }
  });
  card.querySelector('[data-role="enabled"]').addEventListener("change", async (event) => {
    try {
      await window.wdaPanel.saveDevice(deviceId, { enabled: event.target.checked });
    } catch (error) {
      appendLog(`Toggle ${deviceId} failed: ${error.message}`);
    }
  });
  return card;
}

function readDeviceCard(card) {
  return {
    udid: card.querySelector('[data-role="udid"]').value.trim(),
    name: card.querySelector('[data-role="name"]').value.trim(),
    port: Number(card.querySelector('[data-role="port"]').value),
    enabled: card.querySelector('[data-role="enabled"]').checked,
  };
}

function updateCardFromState(card, device) {
  const stateName = device.runtime?.state || "idle";
  card.classList.remove("state-running", "state-starting", "state-error", "state-idle", "state-stopping");
  card.classList.add(`state-${stateName}`);
  card.classList.toggle("disabled", !device.enabled);

  if (document.activeElement?.dataset?.role !== "udid"
      || card.contains(document.activeElement) === false) {
    card.querySelector('[data-role="udid"]').value = device.udid || "";
  }
  card.querySelector('[data-role="name"]').value = device.name || "";
  card.querySelector('[data-role="port"]').value = device.port || "";
  card.querySelector('[data-role="enabled"]').checked = Boolean(device.enabled);
  card.querySelector('[data-role="label"]').textContent = device.deviceId;

  const statePill = card.querySelector('[data-role="state"]');
  statePill.textContent = stateName;
  statePill.className = `state-pill ${stateName}`;

  card.querySelector('[data-role="wdaUrl"]').textContent = device.wdaUrl
    ? `WDA: ${device.wdaUrl}`
    : "";
  card.querySelector('[data-role="error"]').textContent = device.runtime?.lastError || device.automation?.lastError || "";
  const automation = device.automation?.state || "idle";
  card.querySelector('[data-role="automation"]').textContent = `Automation: ${automation}`;
  card.querySelector('[data-role="automation"]').className = automation === "running" ? "muted automation-running" : "muted";

  card.querySelector('[data-role="start"]').disabled = !device.enabled || !device.udid || stateName === "running" || stateName === "starting";
  card.querySelector('[data-role="stop"]').disabled = stateName === "idle";
}

function renderFleet(state) {
  if (!state || !Array.isArray(state.devices)) return;
  const grid = $("deviceGrid");

  const validIds = new Set(state.devices.map((device) => device.deviceId));
  for (const card of [...grid.querySelectorAll(".device-card")]) {
    if (!validIds.has(card.dataset.deviceId)) card.remove();
  }

  const ordered = [...state.devices].sort((a, b) => a.deviceId.localeCompare(b.deviceId));
  for (const device of ordered) {
    const card = ensureCard(device.deviceId);
    if (card.parentElement !== grid || grid.lastElementChild !== card) {
      grid.appendChild(card);
    }
    updateCardFromState(card, device);
  }

  const enabled = state.devices.filter((device) => device.enabled);
  const running = enabled.filter((device) => device.runtime?.state === "running");
  const starting = enabled.filter((device) => device.runtime?.state === "starting");
  const error = enabled.filter((device) => device.runtime?.state === "error");
  $("pillTotal").textContent = `${enabled.length} enabled`;
  $("pillRunning").textContent = `${running.length} running`;
  $("pillStarting").textContent = `${starting.length} starting`;
  $("pillError").textContent = `${error.length} error`;

  const lastScan = state.lastScanAt
    ? new Date(state.lastScanAt).toLocaleTimeString()
    : "never";
  $("lastScanLabel").textContent = `Last scan: ${lastScan}`;
}

function renderDetected(state) {
  const tbody = $("detectedTable");
  tbody.innerHTML = "";
  if (!state.detected || !state.detected.length) {
    tbody.innerHTML = '<tr><td colspan="5" class="muted">No devices yet. Click <strong>Scan USB</strong>.</td></tr>';
    return;
  }
  for (const device of state.detected) {
    const tr = document.createElement("tr");
    const slotOptions = state.devices
      .map((slot) => `<option value="${escapeHtml(slot.deviceId)}">${escapeHtml(slot.deviceId)}</option>`)
      .join("");
    tr.innerHTML = `
      <td>${escapeHtml(device.name || "iPhone")}</td>
      <td>${escapeHtml(device.version || "—")}</td>
      <td><code>${escapeHtml(device.udid || "—")}</code></td>
      <td>${escapeHtml(device.status || "")}</td>
      <td>
        <select data-udid="${escapeHtml(device.udid || "")}">
          <option value="">— assign —</option>
          ${slotOptions}
        </select>
      </td>
    `;
    tbody.appendChild(tr);
  }
  for (const select of tbody.querySelectorAll("select[data-udid]")) {
    select.addEventListener("change", async (event) => {
      const udid = select.dataset.udid;
      const deviceId = event.target.value;
      if (!deviceId) return;
      try {
        await window.wdaPanel.saveDevice(deviceId, { udid, enabled: true });
        appendLog(`Assigned ${udid.slice(-8)} → ${deviceId}`);
      } catch (error) {
        appendLog(`Assign failed: ${error.message}`);
      } finally {
        event.target.value = "";
      }
    });
  }
}

function applyState(state) {
  lastState = state;
  applySettings(state.config);
  updateQueueDeviceOptions(state);
  updateLogDeviceOptions(state);
  renderFleet(state);
  renderDetected(state);
  renderSetupDetected(state);
  renderSetupInstall(state);
}

async function init() {
  if (!window.wdaPanel) return;
  window.wdaPanel.onState((state) => applyState(state));
  window.wdaPanel.onLog((line) => appendLog(line));
  initQueueCountryFilter();

  for (const tab of document.querySelectorAll(".tab")) {
    tab.addEventListener("click", () => setActiveTab(tab.dataset.tab));
  }

  $("settingsForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      const settings = readSettings();
      if (settings.liveTimeMinSeconds > settings.liveTimeMaxSeconds) {
        throw new Error("Min Time must be less than or equal to Max Time");
      }
      await window.wdaPanel.saveConfig(settings);
      appendLog("Settings saved");
    } catch (error) {
      appendLog(`Save settings failed: ${error.message}`);
    }
  });

  $("scanButton").addEventListener("click", async () => {
    try {
      await window.wdaPanel.scan();
    } catch (error) {
      appendLog(`Scan failed: ${error.message}`);
    }
  });

  $("healthButton").addEventListener("click", async () => {
    try {
      const results = await window.wdaPanel.health();
      for (const row of results) {
        appendLog(`[${row.deviceId}] ${row.ok ? "ok" : "down"}: ${row.detail}`);
      }
    } catch (error) {
      appendLog(`Health check failed: ${error.message}`);
    }
  });

  $("startAllButton").addEventListener("click", async () => {
    try {
      const results = await window.wdaPanel.startAll();
      const failed = results.filter((row) => !row.ok);
      if (!failed.length) appendLog(`Started ${results.length} device(s)`);
      else for (const row of failed) appendLog(`Start ${row.deviceId} failed: ${row.error}`);
    } catch (error) {
      appendLog(`Start all failed: ${error.message}`);
    }
  });

  $("stopAllButton").addEventListener("click", async () => {
    try { await window.wdaPanel.stopAll(); } catch (error) { appendLog(`Stop all failed: ${error.message}`); }
  });

  $("bulkOpenButton").addEventListener("click", async () => {
    const url = $("bulkUrl").value.trim();
    if (!url) {
      appendLog("Enter a URL first");
      return;
    }
    if (!lastState) return;
    const targets = [...document.querySelectorAll('.device-card [data-role="selected"]:checked')]
      .map((checkbox) => checkbox.closest(".device-card").dataset.deviceId)
      .filter(Boolean);
    if (!targets.length) {
      appendLog("Tick at least one device under Select for bulk");
      return;
    }
    for (const deviceId of targets) {
      try {
        await window.wdaPanel.openUrl(deviceId, url);
      } catch (error) {
        appendLog(`Open ${deviceId} failed: ${error.message}`);
      }
    }
  });

  $("queueRefreshButton").addEventListener("click", () => {
    loadQueue().catch((error) => showQueueError(error.message));
  });
  $("queueStatus").addEventListener("change", () => {
    loadQueue().catch((error) => showQueueError(error.message));
  });
  $("queueLimit").addEventListener("change", () => {
    loadQueue().catch((error) => showQueueError(error.message));
  });
  $("queueAutoRefresh").addEventListener("change", scheduleQueueRefresh);

  $("clearLogsButton").addEventListener("click", () => {
    const key = $("logDeviceFilter")?.value || "all";
    logBuffers.set(key, []);
    if (key === "all") {
      for (const device of lastState?.devices || []) logBuffers.set(device.deviceId, []);
    }
    renderActiveLog();
  });
  $("logDeviceFilter").addEventListener("change", renderActiveLog);

  // Setup wizard buttons
  $("driverInstallButton").addEventListener("click", async () => {
    try { await window.wdaPanel.openDriverDownload(); } catch (error) { appendLog(`Open driver page failed: ${error.message}`); }
  });
  $("setupScanButton").addEventListener("click", async () => {
    try { await window.wdaPanel.scan(); } catch (error) { appendLog(`Scan failed: ${error.message}`); }
  });
  $("setupAssignButton").addEventListener("click", async () => {
    try {
      const result = await window.wdaPanel.assignDetected();
      appendLog(`Auto-assigned ${result.assignedCount} device(s)`);
    } catch (error) {
      appendLog(`Auto-assign failed: ${error.message}`);
    }
  });
  $("setupCheckInstalledButton").addEventListener("click", () => checkInstalledList());
  $("setupInstallAllButton").addEventListener("click", async () => {
    try {
      const results = await window.wdaPanel.installWdaAll();
      const failed = results.filter((row) => !row.ok);
      if (!failed.length) appendLog(`Installed WDA on ${results.length} device(s)`);
      else for (const row of failed) appendLog(`Install ${row.deviceId} failed: ${row.error}`);
      await checkInstalledList();
    } catch (error) {
      appendLog(`Install all failed: ${error.message}`);
    }
  });
  for (const [buttonId, format] of [
    ["setupExportDeveloperButton", "developer"],
    ["setupExportInternalButton", "internal"],
    ["setupExportTxtButton", "txt"],
  ]) {
    $(buttonId).addEventListener("click", async () => {
      try {
        const result = await window.wdaPanel.exportUdid(format);
        if (result.canceled) return;
        appendLog(`Exported ${result.count} UDID(s) → ${result.filePath}`);
      } catch (error) {
        appendLog(`Export ${format} UDID failed: ${error.message}`);
      }
    });
  }
  $("setupGoFleetButton").addEventListener("click", () => setActiveTab("fleet"));

  if ($("signingSelect")) {
    $("signingSelect").addEventListener("change", async () => {
      const value = $("signingSelect").value;
      const teamId = value && /^[A-Z0-9]{10}$/.test(value) ? value : "";
      if (teamId) {
        $("appleTeamId").value = teamId;
        $("appleTeamIdSettings").value = teamId;
        try {
          await window.wdaPanel.saveConfig({ appleTeamId: teamId });
          appendLog(`Selected Team ID ${teamId}`);
        } catch (error) {
          appendLog(`Save Team ID failed: ${error.message}`);
        }
      }
    });
  }
  if ($("appleTeamId")) {
    $("appleTeamId").addEventListener("change", async () => {
      const value = $("appleTeamId").value.trim();
      if (!value) return;
      $("appleTeamIdSettings").value = value;
      try {
        await window.wdaPanel.saveConfig({ appleTeamId: value });
      } catch (error) {
        appendLog(`Save Team ID failed: ${error.message}`);
      }
    });
  }
  if ($("refreshSigningButton")) {
    $("refreshSigningButton").addEventListener("click", () => refreshMacStatus());
  }
  if ($("buildIpaButton")) {
    $("buildIpaButton").addEventListener("click", async () => {
      const teamId = ($("appleTeamId").value || $("appleTeamIdSettings").value || "").trim();
      if (!teamId) {
        appendLog("Cần chọn signing identity hoặc nhập Apple Team ID trước.");
        return;
      }
      $("buildIpaSummary").textContent = "đang build...";
      $("buildIpaButton").disabled = true;
      try {
        const result = await window.wdaPanel.buildIpa({ appleTeamId: teamId });
        $("buildIpaSummary").textContent = `IPA: ${result.ipaPath}`;
        appendLog(`Build IPA ok → ${result.ipaPath}`);
        await refreshSetupStatus();
      } catch (error) {
        $("buildIpaSummary").textContent = `lỗi: ${error.message}`;
        appendLog(`Build IPA failed: ${error.message}`);
      } finally {
        $("buildIpaButton").disabled = false;
      }
    });
  }

  document.body.dataset.platform = navigator.platform.toLowerCase().includes("mac") ? "darwin" : "other";

  await refreshSetupStatus();
  const initialState = await window.wdaPanel.refresh();
  applyState(initialState);
}

document.addEventListener("DOMContentLoaded", init);
