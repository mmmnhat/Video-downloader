export type AuthStatus = {
  dependencies_ready: boolean;
  authenticated: boolean;
  cookie_count: number;
  browser: string | null;
  message: string;
};

export type UpdateStatus = {
  updateAvailable: boolean;
  currentVersion: string;
  latestVersion: string;
  releaseNotes: string;
  downloadUrl: string;
  isPlaceholder: boolean;
};
export type Settings = {
  output_dir: string;
  quality: string;
  concurrent_downloads: number;
  retry_count: number;
  use_browser_cookies: boolean;
  cookies_map: Record<string, string>;
};

export type BatchStats = {
  queued: number;
  downloading: number;
  completed: number;
  failed: number;
  cancelled: number;
  unsupported: number;
  supported_total: number;
};

export type BatchSummary = {
  id: string;
  createdAt: string;
  lastUpdatedAt: string;
  status: string;
  sheetUrl: string;
  discoveredUrlCount: number;
  sheetAccessMode: string;
  outputDir: string;
  stats: BatchStats;
};

export type BatchItem = {
  id: string;
  sequenceLabel: string;
  rowNumber: number;
  platform: string;
  sourceUrl: string;
  clipRange: string | null;
  status: string;
  supported: boolean;
  attemptCount: number;
  message: string;
  outputPath: string | null;
  startedAt: string | null;
  completedAt: string | null;
};

export type BatchDetail = {
  id: string;
  createdAt: string;
  lastUpdatedAt: string;
  status: string;
  sheetUrl: string;
  sheetId: string;
  gid: string | null;
  sheetAccessMode: string;
  discoveredUrlCount: number;
  outputDir: string;
  stats: BatchStats;
  settingsSnapshot: {
    outputDir: string;
    quality: string;
    concurrentDownloads: number;
    retryCount: number;
    useBrowserCookies: boolean;
    hasManualCookies: boolean;
  };
  items: BatchItem[];
};

export type SheetPreviewRow = {
  sequenceLabel: string;
  rowNumber: number;
  platform: string;
  supported: boolean;
  sourceUrl: string;
  clipRange: string | null;
};

export type SheetPreview = {
  sheetId: string;
  gid: string | null;
  accessMode: string;
  urlCount: number;
  supportedCount: number;
  unsupportedCount: number;
  platformCounts: Record<string, number>;
  clipCount: number;
  rows: SheetPreviewRow[];
  warnings: string[];
};

export type BootstrapPayload = {
  authStatus: AuthStatus;
  settings: Settings;
  batchSummaries: BatchSummary[];
  activeBatchId: string | null;
};

export type BatchEvent = {
  id: number;
  type: string;
  timestamp: string;
  batchId?: string;
  itemId?: string;
  activeBatchId?: string | null;
};

export class ApiError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ApiError";
  }
}

async function requestJson<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(url, options);
  const text = await response.text();
  const payload = text ? (JSON.parse(text) as Record<string, unknown>) : {};

  if (!response.ok) {
    throw new ApiError(String(payload.error ?? "Request failed."));
  }
  return payload as T;
}

export async function getBootstrap() {
  return requestJson<BootstrapPayload>("/api/bootstrap");
}

export async function listBatches(params?: {
  status?: string;
  q?: string;
  limit?: number;
}) {
  const query = new URLSearchParams();
  if (params?.status && params.status !== "all") {
    query.set("status", params.status);
  }
  if (params?.q) {
    query.set("q", params.q);
  }
  if (typeof params?.limit === "number") {
    query.set("limit", String(params.limit));
  }

  const suffix = query.toString() ? `?${query.toString()}` : "";
  return requestJson<BatchSummary[]>(`/api/batches${suffix}`);
}

export async function getBatch(batchId: string) {
  return requestJson<BatchDetail>(`/api/batches/${batchId}`);
}

export async function previewSheet(sheetUrl: string) {
  return requestJson<SheetPreview>("/api/sheets/preview", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sheet_url: sheetUrl }),
  });
}

export async function createBatch(sheetUrl: string, settings: Settings) {
  return requestJson<BatchDetail>("/api/batches", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sheet_url: sheetUrl, settings }),
  });
}

export async function cancelBatch(batchId: string) {
  return requestJson<Record<string, unknown>>(`/api/batches/${batchId}/cancel`, {
    method: "POST",
  });
}

export async function retryFailed(batchId: string) {
  return requestJson<Record<string, unknown>>(`/api/batches/${batchId}/retry-failed`, {
    method: "POST",
  });
}

export async function updateSettings(settings: Settings) {
  return requestJson<Settings>("/api/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(settings),
  });
}

export async function chooseFolder() {
  return requestJson<{ path: string }>("/api/system/choose-folder", {
    method: "POST",
  });
}

export async function openFolder(path: string) {
  return requestJson<{ ok: boolean }>("/api/system/open-folder", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path }),
  });
}

export async function getBrowserSessionStatus() {
  return requestJson<AuthStatus>("/api/browser-session/status");
}

export async function openBrowserLogin() {
  return requestJson<{ opened: boolean; url: string }>("/api/browser-session/open-login", {
    method: "POST",
  });
}

export async function refreshBrowserSession() {
  return requestJson<AuthStatus>("/api/browser-session/refresh", {
    method: "POST",
  });
}

export async function scrapePlatformCookies(platform: string) {
  return requestJson<{ cookies: string }>("/api/browser-session/scrape-platform-cookies", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ platform }),
  });
}

export async function checkUpdate() {
  return requestJson<UpdateStatus>("/api/system/updater/check");
}

export async function applyUpdate(downloadUrl: string) {
  return requestJson<{ status: string }>("/api/system/updater/apply", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ downloadUrl }),
  });
}
