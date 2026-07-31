const $ = (id) => document.getElementById(id);

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const text = await response.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = { raw: text };
  }
  if (!response.ok) {
    const detail = data?.detail || data?.error || text || response.statusText;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return data;
}

function setHealth(ok, label) {
  const pill = $("health-pill");
  pill.className = `pill ${ok ? "ok" : "bad"}`;
  pill.textContent = label;
}

function fmtTime(value) {
  if (!value) return "";
  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
}

function shortUdid(udid) {
  if (!udid) return "";
  if (udid.length <= 16) return udid;
  return `${udid.slice(0, 8)}…${udid.slice(-6)}`;
}

function setActiveTab(name) {
  for (const tab of document.querySelectorAll(".tab")) {
    tab.classList.toggle("active", tab.dataset.tab === name);
  }
  for (const panel of document.querySelectorAll(".tab-panel")) {
    panel.classList.toggle("active", panel.id === `tab-${name}`);
  }
}

async function refreshHealth() {
  try {
    const health = await api("/api/health");
    setHealth(health.wda_ok, health.wda_ok ? "WDA online" : "WDA offline");
    const device = health.device || {};
    const lines = [
      `Stack: go-ios`,
      `UDID: ${device.udid || "(chưa chọn)"}`,
      `Binary: ${device.binary_exists === false ? "MISSING" : (device.binary || "")}`,
      `IPA: ${device.ipa_exists === false ? "MISSING" : (device.ipa || "")}`,
      `WDA: ${health.wda_url || ""}`,
      `tunnel=${device.tunnel_running} wda=${device.wda_running} forward=${device.forward_running}`,
      `accounts: ${health.config?.accounts ?? 0} · method: ${health.config?.signup_method || ""}`,
    ];
    if (health.wda_error) lines.push(`WDA error: ${health.wda_error}`);
    if (device.last_error) lines.push(`Last error: ${device.last_error}`);
    $("device-meta").textContent = lines.join("\n");

    const hint = $("profile-hint");
    const err = String(health.wda_error || device.last_error || "");
    if (/not trusted|Developer App Certificate/i.test(err)) {
      hint.textContent =
        "Trên iPhone: Cài đặt → Cài đặt chung → VPN & Quản lý thiết bị → Developer App → Trust";
    } else if (/0xe8008011|expired|provisioning/i.test(err)) {
      hint.textContent =
        "IPA/profile hết hạn — thay file resources/ipa/WebDriverAgentRunner.ipa đã ký mới, rồi Install IPA";
    } else if (!health.wda_ok) {
      hint.textContent =
        "WDA offline — mở khóa iPhone → Install IPA (nếu chưa) → Bootstrap";
    } else {
      hint.textContent = "";
    }
  } catch (error) {
    setHealth(false, "server error");
    $("device-meta").textContent = String(error.message || error);
  }
}

async function refreshPhones() {
  const body = $("phones-body");
  try {
    const data = await api("/api/devices?enrich=true");
    const phones = data.phones || [];
    $("phones-count").textContent = `${phones.length} máy USB`;
    body.innerHTML = "";
    if (!phones.length) {
      body.innerHTML =
        '<tr><td colspan="7" class="muted">Không thấy iPhone. Cắm USB, mở khóa, Trust This Computer.</td></tr>';
      return;
    }
    for (const phone of phones) {
      const tr = document.createElement("tr");
      if (phone.selected) tr.classList.add("phone-selected");
      const statusBits = [];
      statusBits.push(phone.connected ? "USB" : "offline");
      if (phone.selected) statusBits.push("selected");
      if (phone.wda_active) statusBits.push("WDA");
      if (phone.password_protected) statusBits.push("locked?");
      tr.innerHTML = `
        <td>${phone.slot}</td>
        <td><strong>${phone.name || "iPhone"}</strong></td>
        <td>${phone.model || phone.product_type || ""}</td>
        <td>${phone.ios_version || ""}</td>
        <td class="udid-cell" title="${phone.udid}"><code>${shortUdid(phone.udid)}</code></td>
        <td><span class="status ${phone.selected ? "succeeded" : "queued"}">${statusBits.join(" · ")}</span></td>
        <td class="row" style="margin:0"></td>
      `;
      const actions = tr.querySelector("td:last-child");

      const selectBtn = document.createElement("button");
      selectBtn.className = phone.selected ? "ghost" : "";
      selectBtn.textContent = phone.selected ? "Đang chọn" : "Chọn";
      selectBtn.disabled = !!phone.selected;
      selectBtn.onclick = async () => {
        await api("/api/devices/select", {
          method: "POST",
          body: JSON.stringify({ udid: phone.udid, persist: true }),
        });
        await refreshAll();
      };
      actions.appendChild(selectBtn);

      const bootBtn = document.createElement("button");
      bootBtn.className = "ghost";
      bootBtn.textContent = "Bootstrap";
      bootBtn.onclick = async () => {
        bootBtn.disabled = true;
        bootBtn.textContent = "…";
        try {
          const result = await api(`/api/devices/${encodeURIComponent(phone.udid)}/bootstrap`, {
            method: "POST",
            body: "{}",
          });
          alert(`Bootstrap ok\nWDA: ${result.wda_url || ""}\nlauncher: ${result.launcher || ""}`);
        } catch (error) {
          const message = String(error.message || error);
          if (/not trusted|Developer App Certificate/i.test(message)) {
            alert(
              "Developer certificate chưa Trust trên iPhone.\n\nCài đặt → Cài đặt chung → VPN & Quản lý thiết bị → Developer App → Trust"
            );
          } else if (/0xe8008011|expired|provisioning/i.test(message)) {
            alert("IPA/profile hết hạn. Thay resources/ipa/WebDriverAgentRunner.ipa rồi Install IPA.");
          } else {
            alert(message);
          }
        } finally {
          bootBtn.disabled = false;
          bootBtn.textContent = "Bootstrap";
          await refreshAll();
        }
      };
      actions.appendChild(bootBtn);

      const infoBtn = document.createElement("button");
      infoBtn.className = "ghost";
      infoBtn.textContent = "Info";
      infoBtn.onclick = async () => {
        const result = await api(`/api/devices/${encodeURIComponent(phone.udid)}/info`);
        $("phone-dialog-title").textContent = phone.name || phone.udid;
        $("phone-dialog-json").textContent = JSON.stringify(result.info || result, null, 2);
        $("phone-dialog").showModal();
      };
      actions.appendChild(infoBtn);

      body.appendChild(tr);
    }
  } catch (error) {
    body.innerHTML = `<tr><td colspan="7" class="muted">${String(error.message || error)}</td></tr>`;
  }
}

async function refreshConfig() {
  const cfg = await api("/api/config");
  const accounts = cfg.tiktok_signup?.accounts || [];
  $("accounts-meta").textContent = accounts.length
    ? accounts
        .map((account, index) => {
          const id = account.email || account.phone || "(empty)";
          return `#${index} ${id}${account.username ? ` · @${account.username}` : ""}`;
        })
        .join("\n")
    : "No accounts in config. Edit config.yaml → tiktok_signup.accounts";
}

async function refreshJobs() {
  const data = await api("/api/jobs");
  const jobs = data.jobs || [];
  $("jobs-count").textContent = `${jobs.length} jobs`;
  const body = $("jobs-body");
  body.innerHTML = "";
  for (const job of jobs) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><code>${job.id}</code></td>
      <td>${job.kind}</td>
      <td><span class="status ${job.status}">${job.status}</span></td>
      <td>#${job.account_index}</td>
      <td>${fmtTime(job.updated_at)}</td>
      <td class="row" style="margin:0"></td>
    `;
    const actions = tr.querySelector("td:last-child");
    const viewBtn = document.createElement("button");
    viewBtn.className = "ghost";
    viewBtn.textContent = "View";
    viewBtn.onclick = () => showJob(job);
    actions.appendChild(viewBtn);

    if (job.status === "waiting_otp") {
      const useBtn = document.createElement("button");
      useBtn.textContent = "OTP";
      useBtn.onclick = () => {
        setActiveTab("jobs");
        $("otp-job-id").value = job.id;
        $("otp-code").focus();
      };
      actions.appendChild(useBtn);
    }
    if (["queued", "running", "waiting_otp"].includes(job.status)) {
      const cancelBtn = document.createElement("button");
      cancelBtn.className = "danger ghost";
      cancelBtn.textContent = "Cancel";
      cancelBtn.onclick = async () => {
        await api(`/api/jobs/${job.id}/cancel`, { method: "POST", body: "{}" });
        await refreshAll();
      };
      actions.appendChild(cancelBtn);
    }
    body.appendChild(tr);
  }
}

function showJob(job) {
  $("dialog-title").textContent = `Job ${job.id}`;
  $("dialog-json").textContent = JSON.stringify(job, null, 2);
  $("job-dialog").showModal();
}

async function refreshLogs() {
  const data = await api("/api/logs?limit=250");
  const logs = data.logs || [];
  $("logs").textContent = logs.join("\n");
  $("logs").scrollTop = $("logs").scrollHeight;
}

async function refreshAll() {
  await Promise.all([
    refreshHealth(),
    refreshPhones(),
    refreshConfig(),
    refreshJobs(),
    refreshLogs(),
  ]);
}

for (const tab of document.querySelectorAll(".tab")) {
  tab.addEventListener("click", () => setActiveTab(tab.dataset.tab));
}

$("btn-refresh").onclick = () => refreshAll().catch(alert);
$("btn-scan-phones").onclick = () => refreshPhones().catch(alert);
$("btn-install-wda").onclick = async () => {
  try {
    const result = await api("/api/device/install-wda", { method: "POST", body: "{}" });
    alert(`Installed WDA IPA\n${JSON.stringify(result, null, 2)}`);
    await refreshAll();
  } catch (error) {
    alert(error.message || error);
  }
};
$("btn-bootstrap").onclick = async () => {
  try {
    const result = await api("/api/device/bootstrap", { method: "POST", body: "{}" });
    alert(`Bootstrap ok\n${JSON.stringify(result, null, 2)}`);
    await refreshAll();
  } catch (error) {
    const message = String(error.message || error);
    if (/not trusted|Developer App Certificate/i.test(message)) {
      alert(
        "Developer certificate chưa Trust trên iPhone.\n\nCài đặt → Cài đặt chung → VPN & Quản lý thiết bị → Developer App → Trust\n\nRồi Bootstrap lại."
      );
    } else if (/0xe8008011|expired|provisioning/i.test(message)) {
      alert("IPA/profile hết hạn. Thay resources/ipa/WebDriverAgentRunner.ipa rồi Install IPA.");
    } else {
      alert(message);
    }
  }
};
$("btn-stop").onclick = async () => {
  await api("/api/device/stop", { method: "POST", body: "{}" });
  await refreshAll();
};
$("btn-home").onclick = async () => {
  await api("/api/device/home", { method: "POST", body: "{}" });
};
$("btn-screenshot").onclick = async () => {
  const result = await api("/api/device/screenshot", { method: "POST", body: "{}" });
  $("preview").src = `${result.url}?t=${Date.now()}`;
};
$("btn-reload-config").onclick = async () => {
  await api("/api/config/reload", { method: "POST", body: "{}" });
  await refreshAll();
};
$("btn-create-job").onclick = async () => {
  try {
    const health = await api("/api/health");
    if (!health.wda_ok) {
      const go = confirm(
        "WDA đang offline. Job sẽ tự Bootstrap (cần iPhone mở khóa).\n\nOK = tiếp tục\nCancel = hủy, bạn Bootstrap tay trước"
      );
      if (!go) return;
    }
    const kind = $("job-kind").value;
    const account_index = Number($("account-index").value || 0);
    const result = await api("/api/jobs", {
      method: "POST",
      body: JSON.stringify({ kind, account_index }),
    });
    if (result.job?.id) {
      $("otp-job-id").value = result.job.id;
    }
    setActiveTab("jobs");
    await refreshAll();
  } catch (error) {
    alert(error.message || error);
  }
};
$("btn-otp").onclick = async () => {
  const jobId = $("otp-job-id").value.trim();
  const code = $("otp-code").value.trim();
  if (!jobId || !code) {
    alert("Need job id and OTP code");
    return;
  }
  await api(`/api/jobs/${jobId}/otp`, {
    method: "POST",
    body: JSON.stringify({ code }),
  });
  $("otp-code").value = "";
  await refreshAll();
};

refreshAll().catch(console.error);
setInterval(() => {
  refreshJobs().catch(() => {});
  refreshLogs().catch(() => {});
  refreshHealth().catch(() => {});
}, 2500);
setInterval(() => {
  refreshPhones().catch(() => {});
}, 5000);
