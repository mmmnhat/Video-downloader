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
    queued: "Đang chờ",
    downloading: "Đang tải",
    completed: "Hoàn tất",
    completed_with_errors: "Hoàn tất kèm lỗi",
    failed: "Thất bại",
    unsupported: "Không hỗ trợ",
    running: "Đang chạy",
    cancelling: "Đang dừng",
    cancelled: "Đã dừng",
  };
  return map[status] || status;
}

function renderStats(stats) {
  return `
    <div class="stat-chip">Được hỗ trợ ${stats.supported_total}</div>
    <div class="stat-chip">Đang chờ ${stats.queued}</div>
    <div class="stat-chip">Đang tải ${stats.downloading}</div>
    <div class="stat-chip">Hoàn tất ${stats.completed}</div>
    <div class="stat-chip">Thất bại ${stats.failed}</div>
    <div class="stat-chip">Đã dừng ${stats.cancelled}</div>
    <div class="stat-chip">Không hỗ trợ ${stats.unsupported}</div>
  `;
}

function accessModeLabel(mode) {
  if (mode === "private_google_oauth") {
    return "Đăng nhập Google";
  }
  if (mode === "browser_session") {
    return "Phiên trình duyệt";
  }
  return "Liên kết công khai";
}

function renderItem(item) {
  const node = itemTemplate.content.firstElementChild.cloneNode(true);
  node.querySelector(".platform-badge").textContent = item.platform;
  node.querySelector(".sequence-badge").textContent = `STT ${item.sequence_label}`;

  const sourceLink = node.querySelector(".source-link");
  sourceLink.href = item.source_url;
  sourceLink.textContent = item.source_url;

  const clipLabel = item.clip_range_label ? ` · Cắt ${item.clip_range_label}` : "";
  node.querySelector(".item-status").textContent =
    `${statusLabel(item.status)}${item.attempt_count ? ` · Lần ${item.attempt_count}` : ""}${clipLabel}`;

  const output = node.querySelector(".item-output");
  if (item.output_path) {
    output.textContent = item.output_path;
  } else if (item.error) {
    output.textContent = item.error;
  } else if (item.supported) {
    output.textContent =
      `Dòng ${item.sheet_row_number} · ${item.clip_range_label ? `Tự cắt ${item.clip_range_label}` : "Đang chờ trình tải"}`;
  } else {
    output.textContent = "Liên kết chưa được ánh xạ tới nền tảng được hỗ trợ";
  }

  return node;
}

function renderBatch(batch) {
  const node = batchTemplate.content.firstElementChild.cloneNode(true);
  node.querySelector(".batch-status").textContent = statusLabel(batch.status);
  node.querySelector(".batch-title").textContent = `Tìm thấy ${batch.discovered_url_count} URL`;
  node.querySelector(".batch-time").textContent = batch.created_at;
  node.querySelector(".stats").innerHTML =
    `<div class="stat-chip">Bảng ${accessModeLabel(batch.sheet_access_mode)}</div>` +
    `<div class="stat-chip">Đầu ra ${batch.output_dir}</div>` +
    `<div class="stat-chip">Chất lượng ${batch.quality}</div>` +
    `<div class="stat-chip">Luồng ${batch.concurrent_downloads}</div>` +
    `<div class="stat-chip">Thử lại ${batch.retry_count}</div>` +
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
    throw new Error(payload.error || "Yêu cầu thất bại.");
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
    ? "Đã tìm thấy phiên Google trong trình duyệt"
    : "Phiên trình duyệt chưa sẵn sàng";

  authStatusDetail.textContent =
    status.message ||
    "Hãy đăng nhập Google trên trình duyệt cục bộ rồi bấm Làm mới phiên.";

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
  submitButton.textContent = "Đang quét...";

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
    submitButton.textContent = "Quét & Tải";
  }
});

saveSettingsButton.addEventListener("click", async () => {
  clearFlash();
  saveSettingsButton.disabled = true;
  try {
    await saveSettings();
    showFlash("Đã lưu cài đặt trình tải.");
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
    showFlash("Đã chọn thư mục đầu ra.");
  } catch (error) {
    showFlash(error.message, true);
  }
});

openFolderButton.addEventListener("click", async () => {
  clearFlash();
  const path = settingsForm.querySelector("#output-dir").value.trim();
  if (!path) {
    showFlash("Chưa có thư mục đầu ra để mở.", true);
    return;
  }

  try {
    await requestJson("/api/system/open-folder", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path }),
    });
    showFlash("Đã mở thư mục đầu ra.");
  } catch (error) {
    showFlash(error.message, true);
  }
});

browserLoginButton.addEventListener("click", async () => {
  clearFlash();
  browserLoginButton.disabled = true;

  try {
    await requestJson("/api/browser-session/open-login", { method: "POST" });
    showFlash("Đã mở Google trong trình duyệt. Hãy đăng nhập rồi bấm Làm mới phiên.");
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
    showFlash("Đã làm mới phiên trình duyệt.");
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
      showFlash("Đã đưa lại các mục lỗi/đã dừng vào hàng đợi.");
      await loadBatches();
      return;
    }

    if (cancelButton instanceof HTMLButtonElement) {
      await requestJson(`/api/batches/${cancelButton.dataset.batchId}/cancel`, {
        method: "POST",
      });
      showFlash("Đã gửi lệnh dừng batch.");
      await loadBatches();
      return;
    }

    if (openButton instanceof HTMLButtonElement) {
      await requestJson("/api/system/open-folder", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: openButton.dataset.path }),
      });
      showFlash("Đã mở thư mục của batch.");
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
