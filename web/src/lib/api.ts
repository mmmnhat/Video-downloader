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
  channel_prefix: string;
  cookies_map: Record<string, string>;
};

export type FeatureBrowserConfig = {
  browser_path: string;
  profile_name: string;
};

export type BrowserConfigPayload = {
  downloader: FeatureBrowserConfig;
  tts: FeatureBrowserConfig;
  story: FeatureBrowserConfig;
};

export type BrowserProfileOption = {
  name: string;
  display_name: string;
  path: string;
  cookie_count: number;
};

export type BrowserProfileProbeResult = {
  browserName: string;
  executablePath: string;
  userDataDir: string;
  profiles: BrowserProfileOption[];
  selectedProfileName: string;
  selectedProfileDir: string;
  message: string;
};

export type BrowserProfileMutationResult = {
  profiles: BrowserProfileOption[];
  profileName?: string;
  profileDir?: string;
  config?: BrowserConfigPayload;
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
    channelPrefix?: string;
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

export type TtsSessionStatus = {
  dependencies_ready: boolean;
  authenticated: boolean;
  profileLocked: boolean;
  browser: string;
  profileDir: string;
  message: string;
  checkedAt: string;
};

export type TtsPreviewRow = {
  sequenceLabel: string;
  rowNumber: number;
  text: string;
};

export type TtsPreview = {
  sheetId: string;
  gid: string | null;
  accessMode: string;
  sheetTitle: string;
  textColumn: string;
  availableColumns: string[];
  rowCount: number;
  skippedRowCount: number;
  warnings: string[];
  rows: TtsPreviewRow[];
};

export type TtsTake = {
  id: string;
  takeIndex: number;
  takeLabel: string;
  status: string;
  outputName: string;
  outputPath: string | null;
  error: string | null;
  previewUrl: string | null;
};

export type TtsItem = {
  id: string;
  sequenceLabel: string;
  rowNumber: number;
  text: string;
  status: string;
  pickedTakeId: string | null;
  message: string;
  takes: TtsTake[];
};

export type TtsBatchStats = {
  queued: number;
  running: number;
  completed: number;
  failed: number;
  cancelled: number;
  total: number;
};

export type TtsBatchSummary = {
  id: string;
  createdAt: string;
  lastUpdatedAt: string;
  status: string;
  sheetUrl: string;
  textColumn: string;
  filenamePrefix?: string | null;
  channelPrefix?: string | null;
  voiceQuery: string;
  voiceId?: string | null;
  voiceName?: string | null;
  voiceLabel?: string;
  modelFamily: string;
  takeCount: number;
  retryCount: number;
  workerCount: number;
  headless: boolean;
  stats: TtsBatchStats;
};

export type TtsBatchDetail = TtsBatchSummary & {
  sheetId: string;
  gid: string | null;
  sheetAccessMode: string;
  tagText: string;
  workDir: string;
  items: TtsItem[];
};

export type TtsBootstrapPayload = {
  sessionStatus: TtsSessionStatus;
  batchSummaries: TtsBatchSummary[];
  activeBatchId: string | null;
};

export type CacheGroup = {
  id: string;
  feature: "story" | "tts" | string;
  title: string;
  description: string;
  path: string;
  openPath: string;
  exists: boolean;
  sizeBytes: number;
  fileCount: number;
  dirCount: number;
  active: boolean;
  canDelete: boolean;
};

export type CacheBootstrapPayload = {
  rootPath: string;
  groups: CacheGroup[];
  summary: {
    groupCount: number;
    existingGroupCount: number;
    totalSizeBytes: number;
    totalFileCount: number;
  };
};

export type TtsVoice = {
  voiceId: string;
  name: string;
  previewUrl?: string;
  category?: string;
  isOwner?: boolean;
  isMyVoice?: boolean;
  sharingStatus?: string;
  labels: Record<string, string>;
};

export type StorySettings = {
  output_root: string;
  max_parallel_videos: number;
  generation_backend: "local_preview" | "gemini_web" | string;
  gemini_headless: boolean;
  gemini_base_url: string;
  gemini_response_timeout_ms: number;
  gemini_model: string;
};

export type StorySessionStatus = {
  backend: string;
  dependencies_ready: boolean;
  authenticated: boolean;
  browser: string | null;
  profile_dir: string;
  message: string;
};

export type StoryAttempt = {
  id: string;
  index: number;
  mode: "auto" | "regenerate" | "refine" | string;
  status: string;
  prompt: string;
  inputImagePath: string;
  previewPath: string | null;
  normalizedPath: string | null;
  error: string | null;
  startedAt: string | null;
  completedAt: string | null;
};

export type StoryStep = {
  id: string;
  index: number;
  title: string;
  modifierPrompt: string;
  status: string;
  selectedAttemptId: string | null;
  attempts: StoryAttempt[];
};

export type StoryMarker = {
  id: string;
  index: number;
  label: string;
  timestampMs: number;
  inputFramePath: string;
  seedPrompt: string;
  status: string;
  steps: StoryStep[];
  parentMarkerId: string | null;
  variantIndex: number;
};

export type StoryVideoSummary = {
  id: string;
  name: string;
  sourceVideoPath: string;
  status: string;
  mode: "chain" | "from_source" | string;
  createdAt: string;
  lastUpdatedAt: string;
  markerCount: number;
  stepTotal: number;
  completedSteps: number;
  reviewSteps: number;
  error: string | null;
};

export type StoryVideoDetail = StoryVideoSummary & {
  videoPrompt: string;
  markers: StoryMarker[];
};

export type StoryBootstrapPayload = {
  settings: StorySettings;
  globalPrompt: string;
  videoSummaries: StoryVideoSummary[];
  activeVideoId: string | null;
  sessionStatus: StorySessionStatus;
};

export type StoryControlResult = {
  ok: boolean;
  action: "run" | "pause" | "resume" | "cancel";
  affectedVideoIds: string[];
  count: number;
};

export type ThumbnailButtonField = {
  key: string;
  label: string;
  type: "text" | "textarea" | "select" | "multi-select" | "color" | "number" | "slider" | "toggle";
  value: string | number | boolean | string[] | null;
  tooltip: string;
  options?: string[];
  min?: number | null;
  max?: number | null;
  required?: boolean;
  visibleIf?: string | Record<string, any> | null;
};

export type ThumbnailButton = {
  id: string;
  name: string;
  icon: string;
  category: string;
  promptTemplate: string;
  requiresMask: boolean;
  createNewChat: boolean;
  allowRegenerate: boolean;
  summary: string;
  fields: ThumbnailButtonField[];
  isPinned?: boolean;
};

export type ThumbnailProfileEffect = {
  buttonId: string;
  fields: ThumbnailButtonField[];
};

export type ThumbnailProfile = {
  id: string;
  name: string;
  icon: string;
  effects: ThumbnailProfileEffect[];
  description: string;
  isPinned?: boolean;
};

export async function createThumbnailProfile(payload: {
  id?: string;
  name: string;
  icon: string;
  effects: ThumbnailProfileEffect[];
  description: string;
}) {
  return requestJson<ThumbnailProfile>("/api/thumbnail/profiles", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function deleteThumbnailProfile(id: string) {
  return requestJson<{ success: boolean }>("/api/thumbnail/profiles/delete", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id }),
  });
}

export async function togglePinThumbnailProfile(id: string) {
  return requestJson<ThumbnailProfile>("/api/thumbnail/profiles/toggle-pin", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id }),
  });
}


export async function selectThumbnailProject(projectId: string) {
  return requestJson<ThumbnailProjectDetail>("/api/thumbnail/select-project", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ project_id: projectId }),
  });
}

export async function selectThumbnailVersion(projectId: string, versionId: string) {
  return requestJson<ThumbnailProjectDetail>("/api/thumbnail/select-version", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ project_id: projectId, version_id: versionId }),
  });
}

export async function deleteThumbnailVersion(projectId: string, versionId: string) {
  return requestJson<ThumbnailProjectDetail>("/api/thumbnail/delete-version", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ project_id: projectId, version_id: versionId }),
  });
}

export async function renameThumbnailProject(projectId: string, name: string) {
  return requestJson<ThumbnailProjectDetail>("/api/thumbnail/projects/rename", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ project_id: projectId, name }),
  });
}

export type ThumbnailVersion = {
  id: string;
  label: string;
  note: string;
  prompt: string;
  buttonName: string;
  fields: Record<string, string | number>;
  maskMode: "none" | "selected" | "red" | string;
  createdAt: string;
  status: "current" | "branch" | "history" | string;
  sourceImagePath: string;
  outputImagePath: string;
  threadUrl?: string | null;
  parentVersionId?: string | null;
};

export type ThumbnailProjectSummary = {
  id: string;
  name: string;
  folder: string;
  sourceImagePath: string;
  base64Image?: string;
  createdAt: string;
  updatedAt: string;
  selectedVersionId: string;
  versionCount: number;
};

export type ThumbnailProjectDetail = ThumbnailProjectSummary & {
  versions: ThumbnailVersion[];
  currentVersion: ThumbnailVersion;
};

export type ThumbnailBootstrapPayload = {
  buttons: ThumbnailButton[];
  projects: ThumbnailProjectSummary[];
  activeProjectId: string | null;
  activeProject: ThumbnailProjectDetail | null;
  profiles: ThumbnailProfile[];
  sessionStatus: {
    backend: string;
    dependencies_ready: boolean;
    authenticated: boolean;
    baseUrl: string;
  };
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
    throw new ApiError(String(payload.error ?? "Yêu cầu thất bại."));
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

export async function previewSheet(
  sheetUrl: string,
  sequenceRange?: { sequenceStart?: number; sequenceEnd?: number },
) {
  return requestJson<SheetPreview>("/api/sheets/preview", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      sheet_url: sheetUrl,
      ...(typeof sequenceRange?.sequenceStart === "number"
        ? { sequence_start: sequenceRange.sequenceStart }
        : {}),
      ...(typeof sequenceRange?.sequenceEnd === "number"
        ? { sequence_end: sequenceRange.sequenceEnd }
        : {}),
    }),
  });
}

export async function createBatch(
  sheetUrl: string,
  settings: Settings,
  sequenceRange?: { sequenceStart?: number; sequenceEnd?: number },
) {
  return requestJson<BatchDetail>("/api/batches", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      sheet_url: sheetUrl,
      settings,
      ...(typeof sequenceRange?.sequenceStart === "number"
        ? { sequence_start: sequenceRange.sequenceStart }
        : {}),
      ...(typeof sequenceRange?.sequenceEnd === "number"
        ? { sequence_end: sequenceRange.sequenceEnd }
        : {}),
    }),
  });
}

export async function cancelBatch(batchId: string) {
  return requestJson<Record<string, unknown>>(`/api/batches/${batchId}/cancel`, {
    method: "POST",
  });
}

export async function pauseBatch(batchId: string) {
  return requestJson<Record<string, unknown>>(`/api/batches/${batchId}/pause`, {
    method: "POST",
  });
}

export async function resumeBatch(batchId: string) {
  return requestJson<Record<string, unknown>>(`/api/batches/${batchId}/resume`, {
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

export async function getBrowserConfig() {
  return requestJson<BrowserConfigPayload>("/api/browser-config");
}

export async function updateBrowserConfig(payload: BrowserConfigPayload) {
  return requestJson<BrowserConfigPayload>("/api/browser-config", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function probeBrowserProfiles(
  feature: "downloader" | "tts" | "story",
  browserPath: string,
  profileName = "",
) {
  return requestJson<BrowserProfileProbeResult>("/api/browser-config/profiles", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      feature,
      browser_path: browserPath,
      profile_name: profileName,
    }),
  });
}

export async function createBrowserProfile(
  feature: "downloader" | "tts" | "story",
  profileName = "",
) {
  return requestJson<BrowserProfileMutationResult>("/api/browser-config/profiles/create", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      feature,
      profile_name: profileName,
    }),
  });
}

export async function deleteBrowserProfile(
  feature: "downloader" | "tts" | "story",
  profileName: string,
) {
  return requestJson<BrowserProfileMutationResult>("/api/browser-config/profiles/delete", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      feature,
      profile_name: profileName,
    }),
  });
}

export async function chooseFolder() {
  return requestJson<{ path: string }>("/api/system/choose-folder", {
    method: "POST",
  });
}

export async function chooseBrowser() {
  return requestJson<{ path: string }>("/api/system/choose-browser", {
    method: "POST",
  });
}

export async function chooseImage() {
  return requestJson<{ path: string }>("/api/system/choose-image", {
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

export async function getTtsBootstrap() {
  return requestJson<TtsBootstrapPayload>("/api/tts/bootstrap");
}

export async function getTtsSessionStatus(refresh = false) {
  const suffix = refresh ? "?refresh=1" : "";
  return requestJson<TtsSessionStatus>(`/api/tts/session/status${suffix}`);
}

export async function openTtsLogin() {
  return requestJson<{ opened: boolean; url: string; message: string }>("/api/tts/session/open-login", {
    method: "POST",
  });
}

export async function previewTtsSheet(
  sheetUrl: string,
  textColumn?: string,
  sequenceRange?: { sequenceStart?: number; sequenceEnd?: number },
) {
  return requestJson<TtsPreview>("/api/tts/sheets/preview", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      sheet_url: sheetUrl,
      ...(textColumn ? { text_column: textColumn } : {}),
      ...(typeof sequenceRange?.sequenceStart === "number"
        ? { sequence_start: sequenceRange.sequenceStart }
        : {}),
      ...(typeof sequenceRange?.sequenceEnd === "number"
        ? { sequence_end: sequenceRange.sequenceEnd }
        : {}),
    }),
  });
}

export async function listTtsBatches() {
  return requestJson<TtsBatchSummary[]>("/api/tts/batches");
}

export async function listTtsVoices(refresh = false) {
  const suffix = refresh ? "?refresh=1" : "";
  return requestJson<TtsVoice[]>(`/api/tts/voices${suffix}`);
}

export async function getTtsBatch(batchId: string) {
  return requestJson<TtsBatchDetail>(`/api/tts/batches/${batchId}`);
}

export async function createTtsBatch(payload: {
  sheetUrl: string;
  textColumn?: string;
  voiceQuery: string;
  voiceId?: string;
  voiceName?: string;
  modelFamily: "v2" | "v3";
  tagText?: string;
  takeCount: number;
  retryCount: number;
  workerCount: number;
  headless: boolean;
  filenamePrefix?: string;
  channelPrefix?: string;
  sequenceStart?: number;
  sequenceEnd?: number;
}) {
  return requestJson<TtsBatchDetail>("/api/tts/batches", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      sheet_url: payload.sheetUrl,
      text_column: payload.textColumn,
      voice_query: payload.voiceQuery,
      voice_id: payload.voiceId,
      voice_name: payload.voiceName,
      model_family: payload.modelFamily,
      tag_text: payload.tagText ?? "",
      take_count: payload.takeCount,
      retry_count: payload.retryCount,
      worker_count: payload.workerCount,
      headless: payload.headless,
      filenamePrefix: payload.filenamePrefix,
      channelPrefix: payload.channelPrefix,
      sequence_start: payload.sequenceStart,
      sequence_end: payload.sequenceEnd,
    }),
  });
}

export async function cancelTtsBatch(batchId: string) {
  return requestJson<TtsBatchDetail>(`/api/tts/batches/${batchId}/cancel`, {
    method: "POST",
  });
}

export async function pauseTtsBatch(batchId: string) {
  return requestJson<TtsBatchDetail>(`/api/tts/batches/${batchId}/pause`, {
    method: "POST",
  });
}

export async function resumeTtsBatch(batchId: string) {
  return requestJson<TtsBatchDetail>(`/api/tts/batches/${batchId}/resume`, {
    method: "POST",
  });
}

export async function pickTtsTake(batchId: string, itemId: string, takeId: string) {
  return requestJson<TtsBatchDetail>(`/api/tts/batches/${batchId}/pick`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ item_id: itemId, take_id: takeId }),
  });
}

export async function retryTtsBatch(batchId: string) {
  return requestJson<TtsBatchDetail>(`/api/tts/batches/${batchId}/retry-failed`, {
    method: "POST",
  });
}

export async function retryTtsItem(batchId: string, itemId: string) {
  return requestJson<TtsBatchDetail>(`/api/tts/batches/${batchId}/items/${itemId}/retry`, {
    method: "POST",
  });
}

export async function exportTtsBatch(batchId: string, itemIds: string[], destinationDir: string) {
  return requestJson<{ exportedCount: number; destinationDir: string; files: string[] }>(
    `/api/tts/batches/${batchId}/export`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        item_ids: itemIds,
        destination_dir: destinationDir,
      }),
    },
  );
}

export async function getCacheBootstrap() {
  return requestJson<CacheBootstrapPayload>("/api/cache/bootstrap");
}

export async function clearCache(cacheId: string) {
  return requestJson<{
    cleared: string[];
    skipped: Array<{ id: string; reason: string }>;
    removedBytes: number;
    bootstrap: CacheBootstrapPayload;
  }>("/api/cache/clear", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ cache_id: cacheId }),
  });
}

export async function getStoryBootstrap() {
  return requestJson<StoryBootstrapPayload>("/api/story/bootstrap");
}

export async function listStoryVideos(params?: { status?: string; limit?: number }) {
  const query = new URLSearchParams();
  if (params?.status) {
    query.set("status", params.status);
  }
  if (typeof params?.limit === "number") {
    query.set("limit", String(params.limit));
  }
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return requestJson<StoryVideoSummary[]>(`/api/story/videos${suffix}`);
}

export async function getStoryVideo(videoId: string) {
  return requestJson<StoryVideoDetail>(`/api/story/videos/${videoId}`);
}

export async function updateStorySettings(settings: Partial<StorySettings>) {
  return requestJson<StorySettings>("/api/story/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(settings),
  });
}

export function getStoryAssetUrl(path: string) {
  if (!path) return "";
  const encoded = encodeURIComponent(path);
  return `/api/story/file?path=${encoded}`;
}

export async function getStorySessionStatus(refresh = false) {
  const suffix = refresh ? "?refresh=1" : "";
  return requestJson<StorySessionStatus>(`/api/story/session/status${suffix}`);
}

export async function openStoryLogin() {
  return requestJson<{ opened: boolean; url: string; message: string }>("/api/story/session/open-login", {
    method: "POST",
  });
}

export async function scanStoryFolder(folderPath: string) {
  return requestJson<StoryVideoDetail[]>("/api/story/videos/scan-folder", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ folder_path: folderPath }),
  });
}

export async function listStoryGems() {
  return requestJson<{ name: string; url: string }[]>("/api/story/gems");
}

export async function applyStoryAction(payload: {
  action: string;
  video_id: string;
  marker_id?: string;
  step_id?: string;
  attempt_id?: string;
  prompt?: string;
}) {
  return requestJson<StoryVideoDetail>("/api/story/actions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function updateStoryGlobalPrompt(prompt: string) {
  return requestJson<{ globalPrompt: string }>("/api/story/global-prompt", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ prompt }),
  });
}

export async function controlStoryQueue(action: "run" | "pause" | "resume" | "cancel") {
  return requestJson<StoryControlResult>(`/api/story/control/${action}`, {
    method: "POST",
  });
}

export async function exportStorySelected(videoId: string, destinationDir: string, stepIds?: string[]) {
  return requestJson<{ exportedCount: number; destinationDir: string; files: string[] }>(
    `/api/story/videos/${videoId}/export`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        destination_dir: destinationDir,
        step_ids: stepIds,
      }),
    },
  );
}

export async function clearStoryVideos() {
  return requestJson<{ ok: boolean }>("/api/story/videos/clear", {
    method: "POST",
  });
}

export async function getThumbnailBootstrap() {
  return requestJson<ThumbnailBootstrapPayload>("/api/thumbnail/bootstrap");
}

export async function getThumbnailProject(projectId: string) {
  return requestJson<ThumbnailProjectDetail>(`/api/thumbnail/projects/${projectId}`);
}

export async function createThumbnailProject(payload: {
  name: string;
  folder: string;
  sourceImagePath?: string;
  base64Image?: string;
}) {
  return requestJson<ThumbnailProjectDetail>("/api/thumbnail/projects", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      name: payload.name,
      folder: payload.folder,
      source_image_path: payload.sourceImagePath,
      base64_image: payload.base64Image,
    }),
  });
}

export async function deleteThumbnailProject(projectId: string) {
  return requestJson<{ ok: boolean }>("/api/thumbnail/projects/delete", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ project_id: projectId }),
  });
}

export async function createThumbnailButton(payload: {
  id?: string;
  name: string;
  icon: string;
  category: string;
  promptTemplate: string;
  requiresMask: boolean;
  createNewChat: boolean;
  allowRegenerate: boolean;
  summary?: string;
  fields: ThumbnailButtonField[];
}) {
  return requestJson<ThumbnailButton>("/api/thumbnail/buttons", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function deleteThumbnailButton(id: string) {
  return requestJson<{ success: boolean }>("/api/thumbnail/buttons/delete", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id }),
  });
}

export async function togglePinThumbnailButton(id: string) {
  return requestJson<ThumbnailButton>("/api/thumbnail/buttons/toggle-pin", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id }),
  });
}



export async function runThumbnailGeneration(payload: {
  projectId: string;
  buttonId: string;
  fieldValues?: Record<string, string | number | string[] | boolean>;
  selectedMode?: string;
  regenerateMode?: string;
  maskMode?: string;
  isRegenerate?: boolean;
  maskBase64?: string;
  canvasGuide?: {
    mode: "crop" | "artboard";
    ratioLabel?: string | null;
    rect: { x: number; y: number; width: number; height: number };
  } | null;
}): Promise<ThumbnailProjectDetail> {
  return requestJson<ThumbnailProjectDetail>("/api/thumbnail/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      project_id: payload.projectId,
      button_id: payload.buttonId,
      field_values: payload.fieldValues,
      selected_mode: payload.selectedMode,
      regenerate_mode: payload.regenerateMode,
      mask_mode: payload.maskMode,
      is_regenerate: payload.isRegenerate ?? false,
      mask_base64: payload.maskBase64,
      canvas_guide: payload.canvasGuide,
    }),
  });
}

export async function runThumbnailGenerationBatch(payload: {
  projectId: string;
  effects: Array<{
    buttonId: string;
    fieldValues?: Record<string, string | number | string[] | boolean>;
  }>;
  selectedMode?: string;
  regenerateMode?: string;
  maskMode?: string;
  isRegenerate?: boolean;
  maskBase64?: string;
  canvasGuide?: {
    mode: "crop" | "artboard";
    ratioLabel?: string | null;
    rect: { x: number; y: number; width: number; height: number };
  } | null;
}): Promise<ThumbnailProjectDetail> {
  return requestJson<ThumbnailProjectDetail>("/api/thumbnail/run-batch", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      project_id: payload.projectId,
      effects: payload.effects.map(e => ({
        button_id: e.buttonId,
        field_values: e.fieldValues,
      })),
      selected_mode: payload.selectedMode,
      regenerate_mode: payload.regenerateMode,
      mask_mode: payload.maskMode,
      is_regenerate: payload.isRegenerate ?? false,
      mask_base64: payload.maskBase64,
      canvas_guide: payload.canvasGuide,
    }),
  });
}

export async function runThumbnailProfile(payload: {
  projectId: string;
  profileId: string;
  maskBase64?: string;
  canvasGuide?: {
    mode: "crop" | "artboard";
    ratioLabel?: string | null;
    rect: { x: number; y: number; width: number; height: number };
  } | null;
}): Promise<ThumbnailProjectDetail> {
  return requestJson<ThumbnailProjectDetail>("/api/thumbnail/profile/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      project_id: payload.projectId,
      profile_id: payload.profileId,
      mask_base64: payload.maskBase64,
      canvas_guide: payload.canvasGuide,
    }),
  });
}

export async function exportThumbnailImage(payload: {
  projectId: string;
  versionId: string;
  destinationDir: string;
  fileName: string;
  format: string;
  size: string;
}) {
  return requestJson<{ ok: boolean; path: string }>("/api/thumbnail/export", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      project_id: payload.projectId,
      version_id: payload.versionId,
      destination_dir: payload.destinationDir,
      file_name: payload.fileName,
      format: payload.format,
      size: payload.size,
    }),
  });
}

export async function clearThumbnailCache() {
  return requestJson<{ ok: boolean }>("/api/thumbnail/clear", {
    method: "POST",
  });
}

export function getThumbnailAssetUrl(path: string) {
  if (!path) return "";
  return `/api/thumbnail/file?path=${encodeURIComponent(path)}`;
}
