const batchList = document.querySelector("#batch-list");
const batchForm = document.querySelector("#batch-form");
const settingsForm = document.querySelector("#settings-form");
const flash = document.querySelector("#flash");
const refreshButton = document.querySelector("#refresh-button");
const saveSettingsButton = document.querySelector("#save-settings-button");
const chooseFolderButton = document.querySelector("#choose-folder-button");
const openFolderButton = document.querySelector("#open-folder-button");
const batchTemplate = document.querySelector("#batch-template");
const itemTemplate = document.querySelector("#item-template");
const authStatusLabel = document.querySelector("#auth-status-label");
const authStatusDetail = document.querySelector("#auth-status-detail");
const browserLoginButton = document.querySelector("#browser-login-button");
const refreshSessionButton = document.querySelector("#refresh-session-button");

function showFlash(message, isError = false) {
  flash.textContent = message;
  flash.classList.remove("hidden");
  flash.classList.toggle("error", isError);
}

function clearFlash() {
  flash.textContent = "";
  flash.classList.add("hidden");
  flash.classList.remove("error");
}

function statusLabel(status) {
  const map = {
    queued: "Queued",
    downloading: "Downloading",
    completed: "Completed",
    completed_with_errors: "Completed with errors",
    failed: "Failed",
    unsupported: "Unsupported",
    running: "Running",
    cancelling: "Stopping",
    cancelled: "Cancelled",
  };
  return map[status] || status;
}

function renderStats(stats) {
  return `
    <div class="stat-chip">Supported ${stats.supported_total}</div>
    <div class="stat-chip">Queued ${stats.queued}</div>
    <div class="stat-chip">Downloading ${stats.downloading}</div>
    <div class="stat-chip">Completed ${stats.completed}</div>
    <div class="stat-chip">Failed ${stats.failed}</div>
    <div class="stat-chip">Cancelled ${stats.cancelled}</div>
    <div class="stat-chip">Unsupported ${stats.unsupported}</div>
  `;
}

function accessModeLabel(mode) {
  if (mode === "private_google_oauth") {
    return "Google auth";
  }
  if (mode === "browser_session") {
    return "Browser session";
  }
  return "Public link";
}

function renderItem(item) {
  const node = itemTemplate.content.firstElementChild.cloneNode(true);
  node.querySelector(".platform-badge").textContent = item.platform;
  node.querySelector(".sequence-badge").textContent = `STT ${item.sequence_label}`;

  const sourceLink = node.querySelector(".source-link");
  sourceLink.href = item.source_url;
  sourceLink.textContent = item.source_url;

  const clipLabel = item.clip_range_label ? ` · Cut ${item.clip_range_label}` : "";
  node.querySelector(".item-status").textContent =
    `${statusLabel(item.status)}${item.attempt_count ? ` · Attempt ${item.attempt_count}` : ""}${clipLabel}`;

  const output = node.querySelector(".item-output");
  if (item.output_path) {
    output.textContent = item.output_path;
  } else if (item.error) {
    output.textContent = item.error;
  } else if (item.supported) {
    output.textContent =
      `Row ${item.sheet_row_number} · ${item.clip_range_label ? `Auto-cut ${item.clip_range_label}` : "Waiting for downloader"}`;
  } else {
    output.textContent = "Link not mapped to a supported platform";
  }

  return node;
}

function renderBatch(batch) {
  const node = batchTemplate.content.firstElementChild.cloneNode(true);
  node.querySelector(".batch-status").textContent = statusLabel(batch.status);
  node.querySelector(".batch-title").textContent = `${batch.discovered_url_count} URLs found`;
  node.querySelector(".batch-time").textContent = batch.created_at;
  node.querySelector(".stats").innerHTML =
    `<div class="stat-chip">Sheet ${accessModeLabel(batch.sheet_access_mode)}</div>` +
    `<div class="stat-chip">Output ${batch.output_dir}</div>` +
    `<div class="stat-chip">Quality ${batch.quality}</div>` +
    `<div class="stat-chip">Threads ${batch.concurrent_downloads}</div>` +
    `<div class="stat-chip">Retry ${batch.retry_count}</div>` +
    renderStats(batch.stats);

  const openFolderButton = node.querySelector(".batch-open-folder");
  const retryButton = node.querySelector(".batch-retry");
  const cancelButton = node.querySelector(".batch-cancel");

  openFolderButton.dataset.path = batch.output_dir;
  retryButton.dataset.batchId = batch.id;
  cancelButton.dataset.batchId = batch.id;

  const isRunning = batch.status === "running" || batch.status === "cancelling";
  retryButton.disabled = isRunning;
  cancelButton.disabled = !isRunning;

  const itemsRoot = node.querySelector(".items");
  batch.items.forEach((item) => itemsRoot.appendChild(renderItem(item)));
  return node;
}

function collectSettings() {
  const formData = new FormData(settingsForm);
  return {
    output_dir: String(formData.get("output_dir") || "").trim(),
    quality: String(formData.get("quality") || "auto").trim(),
    concurrent_downloads: Number(formData.get("concurrent_downloads") || 20),
    retry_count: Number(formData.get("retry_count") || 1),
    use_browser_cookies: document.querySelector("#use-browser-cookies").checked,
    cookies_text: String(formData.get("cookies_text") || ""),
  };
}

function applySettings(settings) {
  settingsForm.querySelector("#output-dir").value = settings.output_dir || "";
  settingsForm.querySelector("#quality").value = settings.quality || "auto";
  settingsForm.querySelector("#concurrent-downloads").value = settings.concurrent_downloads ?? 20;
  settingsForm.querySelector("#retry-count").value = settings.retry_count ?? 1;
  settingsForm.querySelector("#use-browser-cookies").checked = Boolean(settings.use_browser_cookies);
  settingsForm.querySelector("#cookies-text").value = settings.cookies_text || "";
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, options);
  const payload = await response.json();

  if (!response.ok) {
    throw new Error(payload.error || "Request failed.");
  }
  return payload;
}

async function loadSettings() {
  const settings = await requestJson("/api/settings");
  applySettings(settings);
}

async function saveSettings() {
  const settings = collectSettings();
  const payload = await requestJson("/api/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(settings),
  });
  applySettings(payload);
  return payload;
}

async function loadBatches() {
  const batches = await requestJson("/api/batches");

  batchList.innerHTML = "";
  if (!Array.isArray(batches) || batches.length === 0) {
    batchList.classList.add("empty");
    batchList.textContent = "Chưa có batch nào. Dán link sheet để bắt đầu.";
    return;
  }

  batchList.classList.remove("empty");
  batches
    .slice()
    .reverse()
    .forEach((batch) => batchList.appendChild(renderBatch(batch)));
}

function updateAuthUi(status) {
  authStatusLabel.textContent = status.authenticated
    ? "Da tim thay Google session trong browser"
    : "Browser session chua san sang";

  authStatusDetail.textContent =
    status.message ||
    "Hay dang nhap Google tren browser local roi bam Refresh Session.";

  browserLoginButton.disabled = !status.dependencies_ready;
  refreshSessionButton.disabled = !status.dependencies_ready;
}

async function loadAuthStatus() {
  const status = await requestJson("/api/browser-session/status");
  updateAuthUi(status);
}

batchForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  clearFlash();

  const formData = new FormData(batchForm);
  const sheetUrl = String(formData.get("sheet_url") || "").trim();
  if (!sheetUrl) {
    showFlash("Bạn cần nhập link Google Sheets.", true);
    return;
  }

  const submitButton = batchForm.querySelector("button[type='submit']");
  submitButton.disabled = true;
  submitButton.textContent = "Scanning...";

  try {
    const payload = await requestJson("/api/batches", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        sheet_url: sheetUrl,
        settings: collectSettings(),
      }),
    });
    showFlash(`Đã tạo batch ${payload.id.slice(0, 8)} và bắt đầu download.`);
    await loadBatches();
  } catch (error) {
    showFlash(error.message, true);
  } finally {
    submitButton.disabled = false;
    submitButton.textContent = "Scan & Download";
  }
});

saveSettingsButton.addEventListener("click", async () => {
  clearFlash();
  saveSettingsButton.disabled = true;
  try {
    await saveSettings();
    showFlash("Da luu settings downloader.");
  } catch (error) {
    showFlash(error.message, true);
  } finally {
    saveSettingsButton.disabled = false;
  }
});

chooseFolderButton.addEventListener("click", async () => {
  clearFlash();
  try {
    const payload = await requestJson("/api/system/choose-folder", { method: "POST" });
    settingsForm.querySelector("#output-dir").value = payload.path;
    showFlash("Da chon output folder.");
  } catch (error) {
    showFlash(error.message, true);
  }
});

openFolderButton.addEventListener("click", async () => {
  clearFlash();
  const path = settingsForm.querySelector("#output-dir").value.trim();
  if (!path) {
    showFlash("Chua co output folder de mo.", true);
    return;
  }

  try {
    await requestJson("/api/system/open-folder", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path }),
    });
    showFlash("Da mo output folder.");
  } catch (error) {
    showFlash(error.message, true);
  }
});

browserLoginButton.addEventListener("click", async () => {
  clearFlash();
  browserLoginButton.disabled = true;

  try {
    await requestJson("/api/browser-session/open-login", { method: "POST" });
    showFlash("Da mo Google trong browser. Hay dang nhap roi bam Refresh Session.");
  } catch (error) {
    showFlash(error.message, true);
  } finally {
    browserLoginButton.disabled = false;
  }
});

refreshSessionButton.addEventListener("click", async () => {
  clearFlash();
  try {
    await loadAuthStatus();
    showFlash("Da refresh browser session.");
  } catch (error) {
    showFlash(error.message, true);
  }
});

refreshButton.addEventListener("click", () => {
  loadBatches().catch((error) => showFlash(error.message, true));
});

batchList.addEventListener("click", async (event) => {
  const target = event.target;
  if (!(target instanceof HTMLElement)) {
    return;
  }

  const retryButton = target.closest(".batch-retry");
  const cancelButton = target.closest(".batch-cancel");
  const openButton = target.closest(".batch-open-folder");

  try {
    if (retryButton instanceof HTMLButtonElement) {
      await requestJson(`/api/batches/${retryButton.dataset.batchId}/retry-failed`, {
        method: "POST",
      });
      showFlash("Da queue lai cac item failed/cancelled.");
      await loadBatches();
      return;
    }

    if (cancelButton instanceof HTMLButtonElement) {
      await requestJson(`/api/batches/${cancelButton.dataset.batchId}/cancel`, {
        method: "POST",
      });
      showFlash("Da gui lenh stop batch.");
      await loadBatches();
      return;
    }

    if (openButton instanceof HTMLButtonElement) {
      await requestJson("/api/system/open-folder", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: openButton.dataset.path }),
      });
      showFlash("Da mo folder cua batch.");
    }
  } catch (error) {
    showFlash(error.message, true);
  }
});

Promise.all([
  loadAuthStatus(),
  loadSettings(),
  loadBatches(),
]).catch((error) => showFlash(error.message, true));

setInterval(() => {
  loadBatches().catch(() => {});
}, 5000);
