import {
  Suspense,
  lazy,
  startTransition,
  useCallback,
  useEffect,
  useEffectEvent,
  useMemo,
  useRef,
  useState,
} from "react";
import type { FormEvent } from "react";
import { toast } from "sonner";
import {
  DownloadCloud,
  Cookie,
  AudioLines,
  Archive,
  Clapperboard,
  Settings2,
  Loader2,
  RefreshCw,
} from "lucide-react";
import CookiesManager from "./components/CookiesManager";
import UpdaterDialog from "./components/UpdaterDialog";
import { useLocalStorage } from "./hooks/use-local-storage";
import BrowserProfilesSettings from "./components/BrowserProfilesSettings";

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyTitle,
} from "@/components/ui/empty";
import {
  Field,
  FieldError,
  FieldGroup,
  FieldLegend,
  FieldSet,
} from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { SessionStatusAlert } from "@/components/ui/session-status-alert";
import { TooltipFieldLabel } from "@/components/ui/tooltip-field-label";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Toaster } from "@/components/ui/sonner";
import {
  cancelBatch,
  pauseBatch,
  resumeBatch,
  chooseFolder,
  createBatch,
  getBatch,
  getBootstrap,
  listBatches,
  openBrowserLogin,
  refreshBrowserSession,
  openFolder,
  previewSheet,
  retryFailed,
  updateSettings,
  checkUpdate,
  type AuthStatus,
  type BatchDetail,
  type BatchEvent,
  type BatchItem,
  type BatchSummary,
  type Settings,
  type SheetPreview,
} from "@/lib/api";
import {
  accessModeLabel,
  authSummary,
  batchPrimaryMessage,
  formatCount,
  formatDateTime,
  progressRatio,
  qualityLabel,
  statusLabel,
} from "@/lib/format";
import {
  resolveSequenceRangeInput,
  type SequenceRangeMode,
} from "@/lib/sequence-range";
import {
  TAB_CARD_GAP_CLASS,
  TAB_PAGE_PADDING_CLASS,
  TAB_STICKY_TOP_CLASS,
  TAB_VIEWPORT_CARD_HEIGHT_CLASS,
} from "@/lib/layout";

const EMPTY_SETTINGS: Settings = {
  output_dir: "",
  quality: "auto",
  concurrent_downloads: 20,
  retry_count: 1,
  use_browser_cookies: true,
  channel_prefix: "",
  cookies_map: {},
};

const MAX_CONCURRENT_DOWNLOADS = 20;
const TABLE_SOURCE_PREVIEW = "__preview__";
const AUTOSAVE_DELAY_MS = 700;
const LIVE_REFRESH_INTERVAL_MS = 2000;
const SHOW_UNIFIED_TABLE = true;
const SHOW_TABLE_CONTEXT = false;
const ACTIVE_BATCH_STATUSES = new Set(["queued", "running", "cancelling"]);
const QUALITY_OPTIONS = [
  { value: "auto", label: "Tự động / tốt nhất hiện có" },
  { value: "1080", label: "Tối đa 1080p" },
  { value: "720", label: "Tối đa 720p" },
  { value: "480", label: "Tối đa 480p" },
  { value: "360", label: "Tối đa 360p" },
];
const TtsStudio = lazy(() => import("./components/TtsStudio"));
const StoryStudio = lazy(() => import("./components/StoryStudio"));
const CacheManager = lazy(() => import("./components/CacheManager"));

type TableMode = "preview" | "queue" | "empty";
type BadgeVariant = "default" | "secondary" | "destructive" | "outline";
type AppView = "downloader" | "tts" | "story" | "settings";
type SettingsView = "cookies" | "browser-settings" | "cache";
type StoredView = AppView | SettingsView;

type UnifiedTableRow = {
  id: string;
  sequenceLabel: string;
  rowNumber: number;
  platform: string;
  sourceUrl: string;
  clipRange: string | null;
  stateLabel: string;
  stateVariant: BadgeVariant;
  attempts: string;
  result: string;
};

const DEFAULT_SETTINGS_VIEW: SettingsView = "cookies";
const SETTINGS_NAV_ITEMS: Array<{
  id: SettingsView;
  label: string;
  description: string;
  icon: typeof Cookie;
}> = [
  {
    id: "cookies",
    label: "Cookie thủ công",
    description: "Dán, chỉnh sửa hoặc xoá cookie thủ công theo nền tảng.",
    icon: Cookie,
  },
  {
    id: "browser-settings",
    label: "Trình duyệt",
    description: "Chọn profile và cấu hình cookie lấy từ trình duyệt.",
    icon: Settings2,
  },
  {
    id: "cache",
    label: "Quản lý cache",
    description: "Xem và dọn cache runtime cho Tạo ảnh AI và TTS.",
    icon: Archive,
  },
];

function App() {
  const [storedView, setStoredView] = useLocalStorage<StoredView>(
    "app.current-view",
    "settings",
  );
  const [settingsView, setSettingsView] = useLocalStorage<SettingsView>(
    "app.settings-view",
    DEFAULT_SETTINGS_VIEW,
  );
  const [batchSummaries, setBatchSummaries] = useState<BatchSummary[]>([]);
  const [selectedBatchId, setSelectedBatchId] = useState<string | null>(null);
  const [selectedBatch, setSelectedBatch] = useState<BatchDetail | null>(null);
  const [tableSource, setTableSource] = useState("");
  const [activeBatchId, setActiveBatchId] = useState<string | null>(null);
  const [authStatus, setAuthStatus] = useState<AuthStatus | null>(null);
  const [persistedSettings, setPersistedSettings] =
    useState<Settings>(EMPTY_SETTINGS);
  const [settingsDraft, setSettingsDraft] =
    useState<Settings>(EMPTY_SETTINGS);
  const [sheetUrl, setSheetUrl] = useState("");
  const [sequenceRangeMode, setSequenceRangeMode] =
    useState<SequenceRangeMode>("all");
  const [sequenceStart, setSequenceStart] = useState("");
  const [sequenceEnd, setSequenceEnd] = useState("");
  const [preview, setPreview] = useState<SheetPreview | null>(null);
  const [previewError, setPreviewError] = useState("");
  const [bootError, setBootError] = useState("");
  const [bootLoading, setBootLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [startLoading, setStartLoading] = useState(false);
  const [, setSaveLoading] = useState(false);
  const [folderLoading, setFolderLoading] = useState(false);
  const [authRefreshing, setAuthRefreshing] = useState(false);
  const [tableCleared, setTableCleared] = useState(false);
  const refreshTimerRef = useRef<number | null>(null);
  const saveInFlightRef = useRef(false);
  const queuedSettingsRef = useRef<Settings | null>(null);
  const selectedBatchIdRef = useRef<string | null>(null);
  const tableSourceRef = useRef("");
  const summaryRequestRef = useRef(0);
  const detailRequestRef = useRef(0);
  const currentView: AppView = isSettingsView(storedView)
    ? "settings"
    : storedView;

  const currentBatch =
    tableSource !== TABLE_SOURCE_PREVIEW && selectedBatch?.id === selectedBatchId
      ? selectedBatch
      : null;
  const currentBatchSummary =
    selectedBatchId === null
      ? null
      : batchSummaries.find((summary) => summary.id === selectedBatchId) ?? null;
  const hasActiveBatch = batchSummaries.some((summary) =>
    ACTIVE_BATCH_STATUSES.has(summary.status),
  );
  const isDirty =
    settingsSignature(settingsDraft) !== settingsSignature(persistedSettings);

  useEffect(() => {
    if (!isSettingsView(storedView)) {
      return;
    }

    if (settingsView !== storedView) {
      setSettingsView(storedView);
    }

    setStoredView("settings");
  }, [settingsView, setSettingsView, setStoredView, storedView]);

  useEffect(() => {
    selectedBatchIdRef.current = selectedBatchId;
  }, [selectedBatchId]);

  useEffect(() => {
    tableSourceRef.current = tableSource;
  }, [tableSource]);

  const bootstrap = useCallback(async () => {
    setBootLoading(true);
    setBootError("");

    try {
      const payload = await getBootstrap();
      const fallbackBatchId =
        payload.activeBatchId ?? payload.batchSummaries[0]?.id ?? null;
      const initialSettings = normalizeSettings(payload.settings);

      startTransition(() => {
        setBatchSummaries(payload.batchSummaries);
        setAuthStatus(payload.authStatus);
        setPersistedSettings(initialSettings);
        setSettingsDraft(initialSettings);
        setActiveBatchId(payload.activeBatchId);
        setSelectedBatchId(fallbackBatchId);
        setTableSource(fallbackBatchId ?? "");
        setTableCleared(false);
      });

      // Auto check for updates
      if (payload.authStatus) {
         try {
           const update = await checkUpdate();
           if (update.updateAvailable && !update.isPlaceholder) {
              toast("CÓ BẢN CẬP NHẬT MỚI!", {
                description: `Phiên bản ${update.latestVersion} đã sẵn sàng. Hãy bấm vào biểu tượng "i" để cập nhật ngay.`,
                duration: 10000,
                action: {
                  label: "Xem ngay",
                  onClick: () => {
                    // We can't easily open the dialog from here without more complex state sharing, 
                    // but the toast tells the user where to look.
                  }
                }
              });
           }
         } catch {
           // Ignore silent check errors
         }
      }
    } catch (error) {
      setBootError(getErrorMessage(error));
    } finally {
      setBootLoading(false);
    }
  }, []);

  const refreshSummaries = useCallback(async (suppressError = false) => {
    const requestId = ++summaryRequestRef.current;
    try {
      const summaries = await listBatches();
      if (requestId !== summaryRequestRef.current) {
        return;
      }

      const nextActive =
        summaries.find((summary) =>
          ACTIVE_BATCH_STATUSES.has(summary.status),
        )?.id ??
        summaries[0]?.id ??
        null;

      startTransition(() => {
        setBatchSummaries(summaries);
        setActiveBatchId(nextActive);
      });
    } catch (error) {
      if (!suppressError) {
        toast.error(getErrorMessage(error));
      }
    }
  }, []);

  const loadBatchDetail = useCallback(async (
    batchId: string,
    options?: { silent?: boolean; suppressError?: boolean },
  ) => {
    const { silent = false, suppressError = false } = options ?? {};
    const requestId = ++detailRequestRef.current;

    if (!silent) {
      setDetailLoading(true);
    }

    try {
      const detail = await getBatch(batchId);
      if (
        requestId !== detailRequestRef.current ||
        selectedBatchIdRef.current !== batchId
      ) {
        return;
      }
      startTransition(() => setSelectedBatch(detail));
    } catch (error) {
      if (
        requestId === detailRequestRef.current &&
        !silent &&
        selectedBatchIdRef.current === batchId
      ) {
        startTransition(() => setSelectedBatch(null));
      }
      if (!suppressError) {
        toast.error(getErrorMessage(error));
      }
    } finally {
      if (!silent && requestId === detailRequestRef.current) {
        setDetailLoading(false);
      }
    }
  }, []);

  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    void bootstrap();
  }, [bootstrap]);

  useEffect(() => {
    if (tableCleared || !selectedBatchId || tableSource === TABLE_SOURCE_PREVIEW) {
      return;
    }

    void loadBatchDetail(selectedBatchId);
  }, [loadBatchDetail, selectedBatchId, tableCleared, tableSource]);

  useEffect(() => {
    if (
      tableCleared ||
      !selectedBatchId ||
      tableSource === TABLE_SOURCE_PREVIEW ||
      !currentBatchSummary
    ) {
      return;
    }

    const detailNeedsRefresh =
      !selectedBatch ||
      selectedBatch.id !== selectedBatchId ||
      selectedBatch.lastUpdatedAt !== currentBatchSummary.lastUpdatedAt ||
      selectedBatch.status !== currentBatchSummary.status;

    if (!detailNeedsRefresh) {
      return;
    }

    void loadBatchDetail(selectedBatchId, {
      silent: true,
      suppressError: true,
    });
  }, [
    currentBatchSummary,
    loadBatchDetail,
    selectedBatch,
    selectedBatchId,
    tableCleared,
    tableSource,
  ]);

  useEffect(() => {
    if (tableCleared) {
      return;
    }

    if (tableSource === TABLE_SOURCE_PREVIEW && preview) {
      return;
    }

    const selectedStillExists =
      selectedBatchId !== null &&
      batchSummaries.some((summary) => summary.id === selectedBatchId);

    if (selectedStillExists) {
      if (!tableSource) {
        setTableSource(selectedBatchId ?? "");
      }
      return;
    }

    const fallbackBatchId = activeBatchId ?? batchSummaries[0]?.id ?? null;

    if (fallbackBatchId) {
      setSelectedBatchId(fallbackBatchId);
      setTableSource(fallbackBatchId);
      return;
    }

    setSelectedBatchId(null);
    if (tableSource !== TABLE_SOURCE_PREVIEW) {
      setTableSource("");
    }
  }, [activeBatchId, batchSummaries, preview, selectedBatchId, tableCleared, tableSource]);

  useEffect(() => {
    if (tableCleared) {
      return;
    }

    if (tableSource !== TABLE_SOURCE_PREVIEW || preview) {
      return;
    }

    const fallbackBatchId = selectedBatchId ?? activeBatchId ?? batchSummaries[0]?.id ?? "";
    setTableSource(fallbackBatchId);
  }, [activeBatchId, batchSummaries, preview, selectedBatchId, tableCleared, tableSource]);
  /* eslint-enable react-hooks/set-state-in-effect */

  useEffect(() => {
    const source = new EventSource("/api/events");

    const scheduleRefresh = () => {
      if (refreshTimerRef.current !== null) {
        return;
      }

      refreshTimerRef.current = window.setTimeout(() => {
        refreshTimerRef.current = null;
        void refreshSummaries(true);

        if (selectedBatchId && tableSource !== TABLE_SOURCE_PREVIEW) {
          void loadBatchDetail(selectedBatchId, {
            silent: true,
            suppressError: true,
          });
        }
      }, 300);
    };

    const handleEvent = (event: Event) => {
      const messageEvent = event as MessageEvent<string>;
      if (messageEvent.data) {
        const payload = JSON.parse(messageEvent.data) as BatchEvent;
        if (payload.type === "batch.created") {
          toast("Một batch mới đã được khởi chạy nền.");
        }
      }
      scheduleRefresh();
    };

    const eventTypes = [
      "batch.created",
      "batch.updated",
      "settings.updated",
      "connected",
    ];

    eventTypes.forEach((eventName) =>
      source.addEventListener(eventName, handleEvent as EventListener),
    );

    source.onerror = () => {
      scheduleRefresh();
    };

    return () => {
      if (refreshTimerRef.current !== null) {
        window.clearTimeout(refreshTimerRef.current);
      }
      eventTypes.forEach((eventName) =>
        source.removeEventListener(eventName, handleEvent as EventListener),
      );
      source.close();
    };
  }, [loadBatchDetail, refreshSummaries, selectedBatchId, tableSource]);

  useEffect(() => {
    if (!hasActiveBatch) {
      return;
    }

    const refreshLiveData = () => {
      void refreshSummaries(true);

      if (selectedBatchId && tableSource !== TABLE_SOURCE_PREVIEW) {
        void loadBatchDetail(selectedBatchId, {
          silent: true,
          suppressError: true,
        });
      }
    };

    refreshLiveData();

    const intervalId = window.setInterval(() => {
      if (document.visibilityState !== "visible") {
        return;
      }

      refreshLiveData();
    }, LIVE_REFRESH_INTERVAL_MS);

    const handleWindowFocus = () => {
      refreshLiveData();
    };

    const handleVisibilityChange = () => {
      if (document.visibilityState === "visible") {
        refreshLiveData();
      }
    };

    window.addEventListener("focus", handleWindowFocus);
    document.addEventListener("visibilitychange", handleVisibilityChange);

    return () => {
      window.clearInterval(intervalId);
      window.removeEventListener("focus", handleWindowFocus);
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, [
    hasActiveBatch,
    loadBatchDetail,
    refreshSummaries,
    selectedBatchId,
    tableSource,
  ]);

  async function loadPreviewForSheet(rawSheetUrl: string) {
    const trimmedSheetUrl = rawSheetUrl.trim();

    if (!trimmedSheetUrl) {
      setPreviewError("Hãy dán URL Google Sheets trước khi tải.");
      return null;
    }

    let sequenceRange;
    try {
      sequenceRange = resolveSequenceRangeInput(
        sequenceRangeMode,
        sequenceStart,
        sequenceEnd,
      );
    } catch (error) {
      setPreviewError(getErrorMessage(error));
      return null;
    }

    setPreviewLoading(true);
    setPreviewError("");

    try {
      const nextPreview = await previewSheet(trimmedSheetUrl, sequenceRange);
      startTransition(() => {
        setPreview(nextPreview);
        setTableSource(TABLE_SOURCE_PREVIEW);
        setTableCleared(false);
      });
      return nextPreview;
    } catch (error) {
      setPreviewError(getErrorMessage(error));
      return null;
    } finally {
      setPreviewLoading(false);
    }
  }

  async function startBatchForSheet(rawSheetUrl: string) {
    const trimmedSheetUrl = rawSheetUrl.trim();

    if (!trimmedSheetUrl) {
      setPreviewError("Hãy dán URL Google Sheets trước khi tải.");
      return;
    }

    let sequenceRange;
    try {
      sequenceRange = resolveSequenceRangeInput(
        sequenceRangeMode,
        sequenceStart,
        sequenceEnd,
      );
    } catch (error) {
      setPreviewError(getErrorMessage(error));
      return;
    }

    setStartLoading(true);
    try {
      const batchSettings = normalizeSettings(settingsDraft);
      const detail = await createBatch(
        trimmedSheetUrl,
        batchSettings,
        sequenceRange,
      );
      startTransition(() => {
        setPersistedSettings(batchSettings);
        setSettingsDraft(batchSettings);
        setSelectedBatch(detail);
        setSelectedBatchId(detail.id);
        setTableSource(detail.id);
        setPreview(null);
        setPreviewError("");
        setTableCleared(false);
      });
      toast.success("Đã tạo batch và bắt đầu tải.");
      await refreshSummaries();
    } catch (error) {
      setPreviewError(getErrorMessage(error));
    } finally {
      setStartLoading(false);
    }
  }

  async function handleSubmitSheetUrl(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await handlePreviewSheetClick();
  }

  async function handlePreviewSheetClick() {
    await loadPreviewForSheet(sheetUrl);
  }

  async function handlePasteSheetUrl() {
    if (!navigator.clipboard?.readText) {
      setPreviewError("Trình duyệt này không hỗ trợ truy cập clipboard.");
      return;
    }

    try {
      const clipboardText = (await navigator.clipboard.readText()).trim();

      if (!clipboardText) {
        setPreviewError("Clipboard đang trống. Hãy sao chép URL Google Sheets rồi thử lại.");
        return;
      }

      startTransition(() => {
        setSheetUrl(clipboardText);
        setPreview(null);
        setPreviewError("");
      });
    } catch {
      setPreviewError("Không thể đọc clipboard. Hãy cấp quyền truy cập clipboard rồi thử lại.");
    }
  }

  async function handleStartBatchClick() {
    await startBatchForSheet(sheetUrl);
  }

  const persistSettings = useEffectEvent(async (nextSettings: Settings) => {
    let pendingSettings: Settings | null = normalizeSettings(nextSettings);

    if (saveInFlightRef.current) {
      queuedSettingsRef.current = pendingSettings;
      return;
    }

    saveInFlightRef.current = true;
    setSaveLoading(true);

    try {
      while (pendingSettings) {
        const payloadSignature = settingsSignature(pendingSettings);

        try {
          const saved = normalizeSettings(await updateSettings(pendingSettings));
          startTransition(() => {
            setPersistedSettings(saved);
            setSettingsDraft((current) =>
              settingsSignature(current) === payloadSignature
                ? saved
                : normalizeSettings(current),
            );
          });
        } catch (error) {
          toast.error(getErrorMessage(error));
        }

        pendingSettings = queuedSettingsRef.current;
        queuedSettingsRef.current = null;
      }
    } finally {
      saveInFlightRef.current = false;
      setSaveLoading(false);
    }
  });

  useEffect(() => {
    if (bootLoading || !isDirty) {
      return;
    }

    const timeoutId = window.setTimeout(() => {
      void persistSettings(settingsDraft);
    }, AUTOSAVE_DELAY_MS);

    return () => window.clearTimeout(timeoutId);
  }, [bootLoading, isDirty, settingsDraft]);

  async function handleChooseFolder() {
    setFolderLoading(true);
    try {
      const payload = await chooseFolder();
      startTransition(() =>
        setSettingsDraft((current) => ({
          ...current,
          output_dir: payload.path,
        })),
      );
      toast.success("Đã chọn thư mục đầu ra.");
    } catch (error) {
      toast.error(getErrorMessage(error));
    } finally {
      setFolderLoading(false);
    }
  }

  async function handleOpenFolder(path: string) {
    try {
      await openFolder(path);
      toast.success("Đã mở thư mục.");
    } catch (error) {
      toast.error(getErrorMessage(error));
    }
  }

  async function handleRefreshTable() {
    startTransition(() => {
      setPreview(null);
      setPreviewError("");
      setSelectedBatch(null);
      setSelectedBatchId(null);
      setTableSource("");
      setTableCleared(true);
    });
    toast.success("Đã xóa bảng.");
  }

  async function handleRefreshAuth() {
    setAuthRefreshing(true);
    try {
      const status = await refreshBrowserSession();
      startTransition(() => setAuthStatus(status));
      toast.success("Đã làm mới phiên trình duyệt.");
    } catch (error) {
      toast.error(getErrorMessage(error));
    } finally {
      setAuthRefreshing(false);
    }
  }

  async function handleOpenGoogleLogin() {
    try {
      await openBrowserLogin();
      toast.success("Đã mở trang đăng nhập Google trên trình duyệt.");
    } catch (error) {
      toast.error(getErrorMessage(error));
    }
  }

  async function handleCancelBatch(batchId: string) {
    try {
      await cancelBatch(batchId);
      toast.success("Batch đã bị dừng.");
      await refreshSummaries();
      if (selectedBatchId === batchId) {
        await loadBatchDetail(batchId, { silent: true });
      }
    } catch (error) {
      toast.error(getErrorMessage(error));
    }
  }

  async function handlePauseBatch(batchId: string) {
    try {
      await pauseBatch(batchId);
      toast.success("Batch đã tạm dừng.");
      await refreshSummaries();
      if (selectedBatchId === batchId) {
        await loadBatchDetail(batchId, { silent: true });
      }
    } catch (error) {
      toast.error(getErrorMessage(error));
    }
  }

  async function handleResumeBatch(batchId: string) {
    try {
      await resumeBatch(batchId);
      toast.success("Batch tiếp tục chạy.");
      await refreshSummaries();
      if (selectedBatchId === batchId) {
        await loadBatchDetail(batchId, { silent: true });
      }
    } catch (error) {
      toast.error(getErrorMessage(error));
    }
  }

  async function handleRetryFailed(batchId: string) {
    try {
      await retryFailed(batchId);
      toast.success("Đã đưa các mục lỗi vào hàng đợi chạy lại.");
      await refreshSummaries();
      if (selectedBatchId === batchId) {
        await loadBatchDetail(batchId, { silent: true });
      }
    } catch (error) {
      toast.error(getErrorMessage(error));
    }
  }

  function handleTableSourceChange(value: string) {
    setTableSource(value);
    setTableCleared(false);
    if (value !== TABLE_SOURCE_PREVIEW) {
      setSelectedBatchId(value);
    }
  }

  function handleOpenSettings(nextView: SettingsView = settingsView) {
    setSettingsView(nextView);
    setStoredView("settings");
  }

  const tableMode: TableMode = tableCleared
    ? "empty"
    : preview && tableSource === TABLE_SOURCE_PREVIEW
      ? "preview"
      : currentBatch
        ? "queue"
        : "empty";

  const batchStats = useMemo(() => {
    if (!currentBatch) {
      return [];
    }

    return [
      { label: "Tiến độ", value: `${progressRatio(currentBatch.stats)}%` },
      {
        label: "Luồng",
        value: formatCount(currentBatch.settingsSnapshot.concurrentDownloads),
      },
      {
        label: "Thử lại",
        value: formatCount(currentBatch.settingsSnapshot.retryCount),
      },
      {
        label: "Chất lượng",
        value: qualityLabel(currentBatch.settingsSnapshot.quality),
      },
    ];
  }, [currentBatch]);

  const tableRows = useMemo<UnifiedTableRow[]>(() => {
    if (tableMode === "preview" && preview) {
      return preview.rows.map((row) => ({
        id: `${row.rowNumber}-${row.sourceUrl}`,
        sequenceLabel: row.sequenceLabel,
        rowNumber: row.rowNumber,
        platform: row.platform,
        sourceUrl: row.sourceUrl,
        clipRange: row.clipRange,
        stateLabel: row.supported ? "Được hỗ trợ" : "Không hỗ trợ",
        stateVariant: row.supported ? "secondary" : "destructive",
        attempts: "\u2014",
        result: row.supported
          ? "Sẵn sàng để xác thực trước khi đưa vào hàng đợi."
          : "Nền tảng này chưa được ánh xạ tới trình tải được hỗ trợ.",
      }));
    }

    if (tableMode === "queue" && currentBatch) {
      return currentBatch.items.map((item) => ({
        id: item.id,
        sequenceLabel: item.sequenceLabel,
        rowNumber: item.rowNumber,
        platform: item.platform,
        sourceUrl: item.sourceUrl,
        clipRange: item.clipRange,
        stateLabel: statusLabel(item.status),
        stateVariant: batchStatusVariant(item),
        attempts: formatCount(item.attemptCount),
        result: item.outputPath ?? item.message,
      }));
    }

    return [];
  }, [currentBatch, preview, tableMode]);

  return (
    <>
      <Toaster position="top-center" richColors />

      <div className="flex h-dvh min-w-0 overflow-hidden bg-background text-foreground">
        {/* Sidebar */}
        <aside className="z-10 flex w-[72px] shrink-0 flex-col border-r border-border bg-card py-4 transition-all duration-300">
          <div className="mb-8 flex items-center justify-center">
            <div className="bg-primary/10 p-2 rounded-md">
              <DownloadCloud className="w-5 h-5 text-primary" />
            </div>
          </div>
          
          <nav className="flex-1 px-3 space-y-2">
             <Button 
                variant={currentView === "downloader" ? "secondary" : "ghost"} 
                className="w-full justify-center" 
                onClick={() => setStoredView("downloader")}
                title="Tải video"
                aria-label="Tải video"
             >
                <DownloadCloud className="h-4 w-4" />
             </Button>
             <Button 
                variant={currentView === "story" ? "secondary" : "ghost"} 
                className="w-full justify-center" 
                onClick={() => setStoredView("story")}
                title="Tạo ảnh"
                aria-label="Tạo ảnh"
             >
                <Clapperboard className="h-4 w-4" />
             </Button>
             <Button 
                variant={currentView === "tts" ? "secondary" : "ghost"} 
                className="w-full justify-center" 
                onClick={() => setStoredView("tts")}
                title="Lồng tiếng"
                aria-label="Lồng tiếng"
             >
                <AudioLines className="h-4 w-4" />
             </Button>
             <Button
                variant={currentView === "settings" ? "secondary" : "ghost"}
                className="w-full justify-center"
                onClick={() => handleOpenSettings()}
                title="Cài đặt"
                aria-label="Cài đặt"
             >
                <Settings2 className="h-4 w-4" />
             </Button>
          </nav>

          <div className="mt-auto pt-2 px-3">
             <UpdaterDialog />
          </div>
        </aside>

        {/* Main Content Area */}
        <div className="min-w-0 flex-1 overflow-x-hidden overflow-y-auto">
          <main
            className={
              currentView === "downloader"
                ? `grid min-w-0 w-full ${TAB_CARD_GAP_CLASS} ${TAB_PAGE_PADDING_CLASS} lg:grid-cols-[minmax(22rem,28rem)_minmax(0,1fr)]`
                : "hidden"
            }
          >
              {bootError ? (
                <Alert className="lg:col-span-2" variant="destructive">
                  <AlertTitle>Lỗi kết nối backend</AlertTitle>
                  <AlertDescription>{bootError}</AlertDescription>
                </Alert>
              ) : null}

          <Card className={`relative min-w-0 border-border/70 shadow-[0_24px_90px_rgba(15,23,42,0.08)] lg:sticky ${TAB_STICKY_TOP_CLASS} ${TAB_VIEWPORT_CARD_HEIGHT_CLASS} lg:overflow-hidden flex flex-col`}>
            <div className="flex items-center justify-end px-4 pt-0 pb-2 shrink-0 gap-1.5">
              <div className="relative">
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="h-7 text-[10px] font-bold uppercase tracking-wider px-2.5 hover:bg-muted/80 rounded-full border border-border/40 flex items-center gap-2"
                  onClick={() => void handleOpenGoogleLogin()}
                >
                  {authStatus?.authenticated && (
                    <span className="size-1.5 rounded-full bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.6)]" />
                  )}
                  {authStatus?.authenticated ? "Đã đăng nhập" : "Đăng nhập"}
                </Button>
              </div>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="size-7 hover:bg-muted/80 rounded-full border border-border/40"
                onClick={() => void handleRefreshAuth()}
                disabled={authRefreshing}
                title="Làm mới phiên"
              >
                {authRefreshing ? (
                  <Loader2 className="size-3 animate-spin" />
                ) : (
                  <RefreshCw className="size-3" />
                )}
              </Button>
            </div>
            <CardContent className="flex min-h-0 min-w-0 flex-1 flex-col gap-6 lg:overflow-x-hidden lg:overflow-y-auto p-4 pt-5">
              <SessionStatusAlert
                authenticated={Boolean(authStatus?.authenticated)}
                notReadyTitle={"Phiên trình duyệt chưa sẵn sàng"}
                message={authSummary(authStatus)}
              />

              <form className="flex flex-col gap-6" onSubmit={handleSubmitSheetUrl}>
                <Field data-invalid={Boolean(previewError)}>
                  <TooltipFieldLabel
                    htmlFor="sheet-url"
                    tooltip="Dán liên kết Google Sheets chứa các video cần xử lý."
                  >
                    URL Google Sheets
                  </TooltipFieldLabel>
                  <div className="flex items-center gap-1 p-1 pl-3 rounded-full border border-border/70 bg-muted/20 focus-within:ring-1 focus-within:ring-primary/30 focus-within:border-primary/50 transition-all">
                    <input
                      id="sheet-url"
                      value={sheetUrl}
                      onChange={(event) => {
                        setSheetUrl(event.target.value);
                        setPreview(null);
                        setPreviewError("");
                      }}
                      type="url"
                      name="sheet_url"
                      className="flex-1 bg-transparent border-0 outline-none text-xs h-7 placeholder:text-muted-foreground/50"
                      spellCheck={false}
                      autoComplete="off"
                      placeholder="https://docs.google.com/spreadsheets/d/..."
                    />
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      className="h-7 px-3 text-xs hover:bg-background/50 rounded-full shrink-0"
                      disabled={previewLoading || startLoading}
                      onClick={() => void handlePasteSheetUrl()}
                    >
                      Dán
                    </Button>
                  </div>
                  <FieldError>{previewError}</FieldError>
                </Field>
              </form>

              <Separator />
              <FieldGroup>
                <Field>
                  <TooltipFieldLabel
                    htmlFor="output-dir"
                    tooltip="Chọn nơi lưu mặc định cho các tệp đã tải."
                  >
                    Thư mục đầu ra
                  </TooltipFieldLabel>
                  <div className="flex items-center gap-1 p-1 pl-3 rounded-full border border-border/70 bg-muted/20 focus-within:ring-1 focus-within:ring-primary/30 focus-within:border-primary/50 transition-all">
                    <input
                      id="output-dir"
                      value={settingsDraft.output_dir}
                      onChange={(event) =>
                        setSettingsDraft((current) => ({
                          ...current,
                          output_dir: event.target.value,
                        }))
                      }
                      type="text"
                      name="output_dir"
                      className="flex-1 bg-transparent border-0 outline-none text-xs h-7 placeholder:text-muted-foreground/50"
                      autoComplete="off"
                      placeholder="/Volumes/External/Video downloader/downloads"
                    />
                    <div className="flex gap-1 shrink-0">
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        className="h-7 px-3 text-xs hover:bg-background/50 rounded-full"
                        disabled={folderLoading}
                        onClick={() => void handleChooseFolder()}
                      >
                        {folderLoading ? "Đang chọn..." : "Chọn"}
                      </Button>
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        className="h-7 px-3 text-xs hover:bg-background/50 rounded-full"
                        disabled={!settingsDraft.output_dir.trim()}
                        onClick={() => void handleOpenFolder(settingsDraft.output_dir)}
                      >
                        Mở
                      </Button>
                    </div>
                  </div>
                </Field>

                <Field>
                  <TooltipFieldLabel
                    htmlFor="channel-prefix"
                    tooltip="Tiền tố tên kênh để ghép thành channel.stt cho video. Nếu để trống, file sẽ chỉ dùng stt."
                  >
                    Tên kênh
                  </TooltipFieldLabel>
                  <Input
                    id="channel-prefix"
                    value={settingsDraft.channel_prefix}
                    className="h-8 rounded-lg bg-muted/20 border-border/70 text-xs"
                    onChange={(event) =>
                      setSettingsDraft((current) => ({
                        ...current,
                        channel_prefix: event.target.value,
                      }))
                    }
                    type="text"
                    name="channel_prefix"
                    autoComplete="off"
                    placeholder="Ví dụ: theoof"
                  />
                </Field>

                <FieldSet>
                  <FieldLegend variant="label">Phạm vi STT</FieldLegend>
                  <FieldGroup>
                    <Field>
                      <TooltipFieldLabel
                        htmlFor="sheet-range-mode"
                        tooltip="Chọn tải toàn bộ sheet hoặc chỉ preview/tải theo khoảng STT."
                      >
                        Chế độ
                      </TooltipFieldLabel>
                      <Select
                        value={sequenceRangeMode}
                        onValueChange={(value) => {
                          setSequenceRangeMode(value as SequenceRangeMode);
                          setPreview(null);
                          setPreviewError("");
                        }}
                      >
                        <SelectTrigger id="sheet-range-mode" className="h-8 rounded-lg bg-muted/20 border-border/70 text-xs">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectGroup>
                            <SelectItem value="all">Tải hết</SelectItem>
                            <SelectItem value="range">Theo khoảng STT</SelectItem>
                          </SelectGroup>
                        </SelectContent>
                      </Select>
                    </Field>

                    <Field>
                      <TooltipFieldLabel
                        htmlFor="sheet-range-start"
                        tooltip="Nhập STT bắt đầu. Có thể để trống nếu chỉ muốn đến STT kết thúc."
                      >
                        Từ STT
                      </TooltipFieldLabel>
                      <Input
                        id="sheet-range-start"
                        value={sequenceStart}
                        className="h-8 rounded-lg bg-muted/20 border-border/70 text-xs"
                        onChange={(event) => {
                          setSequenceStart(event.target.value);
                          setPreview(null);
                          setPreviewError("");
                        }}
                        type="number"
                        min={1}
                        inputMode="numeric"
                        disabled={sequenceRangeMode !== "range"}
                        placeholder="Ví dụ: 10"
                      />
                    </Field>

                    <Field>
                      <TooltipFieldLabel
                        htmlFor="sheet-range-end"
                        tooltip="Nhập STT kết thúc. Có thể để trống nếu chỉ muốn từ STT bắt đầu trở đi."
                      >
                        Đến STT
                      </TooltipFieldLabel>
                      <Input
                        id="sheet-range-end"
                        value={sequenceEnd}
                        className="h-8 rounded-lg bg-muted/20 border-border/70 text-xs"
                        onChange={(event) => {
                          setSequenceEnd(event.target.value);
                          setPreview(null);
                          setPreviewError("");
                        }}
                        type="number"
                        min={1}
                        inputMode="numeric"
                        disabled={sequenceRangeMode !== "range"}
                        placeholder="Ví dụ: 30"
                      />
                    </Field>
                  </FieldGroup>
                </FieldSet>


                <FieldSet>
                  <FieldLegend variant="label">Thiết lập tải mặc định</FieldLegend>
                  <FieldGroup>
                    <Field>
                      <TooltipFieldLabel tooltip="Thiết lập chất lượng tải ưu tiên. Tự động sẽ chọn chất lượng tốt nhất hiện có.">
                        Chất lượng
                      </TooltipFieldLabel>
                      <Select
                        value={settingsDraft.quality}
                        onValueChange={(value) =>
                          setSettingsDraft((current) => ({
                            ...current,
                            quality: value,
                          }))
                        }
                      >
                        <SelectTrigger className="w-full">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectGroup>
                            <SelectLabel>Chất lượng</SelectLabel>
                            {QUALITY_OPTIONS.map((option) => (
                              <SelectItem key={option.value} value={option.value}>
                                {option.label}
                              </SelectItem>
                            ))}
                          </SelectGroup>
                        </SelectContent>
                      </Select>
                    </Field>

                    <Field>
                      <TooltipFieldLabel
                        htmlFor="concurrent-downloads"
                        tooltip="Số lượt tải có thể chạy cùng lúc."
                      >
                        Số luồng
                      </TooltipFieldLabel>
                      <Input
                        id="concurrent-downloads"
                        value={settingsDraft.concurrent_downloads}
                        onChange={(event) =>
                          setSettingsDraft((current) => ({
                            ...current,
                            concurrent_downloads: clampNumber(
                              event.target.value,
                              1,
                              MAX_CONCURRENT_DOWNLOADS,
                            ),
                          }))
                        }
                        type="number"
                        min={1}
                        max={MAX_CONCURRENT_DOWNLOADS}
                        name="concurrent_downloads"
                      />
                    </Field>

                    <Field>
                      <TooltipFieldLabel
                        htmlFor="retry-count"
                        tooltip="Số lần thử lại tự động sau khi tải thất bại."
                      >
                        Thử lại
                      </TooltipFieldLabel>
                      <Input
                        id="retry-count"
                        value={settingsDraft.retry_count}
                        onChange={(event) =>
                          setSettingsDraft((current) => ({
                            ...current,
                            retry_count: clampNumber(event.target.value, 0, 10),
                          }))
                        }
                        type="number"
                        min={0}
                        max={10}
                        name="retry_count"
                      />
                    </Field>

                  </FieldGroup>
                </FieldSet>
              </FieldGroup>
            </CardContent>
            <CardFooter className="border-t border-border/70 pt-4 flex-none gap-2">
              <Button
                type="button"
                variant="outline"
                disabled={previewLoading || startLoading}
                onClick={() => void handlePreviewSheetClick()}
              >
                {previewLoading ? "Đang kiểm tra..." : "Xem trước"}
              </Button>
              <Button
                type="button"
                disabled={
                  startLoading ||
                  previewLoading ||
                  !sheetUrl.trim()
                }
                onClick={() => void handleStartBatchClick()}
              >
                {startLoading ? "Đang bắt đầu..." : "Bắt đầu"}
              </Button>
            </CardFooter>
          </Card>

          {SHOW_UNIFIED_TABLE ? (
            <Card className={`min-w-0 border-border/70 shadow-[0_24px_90px_rgba(15,23,42,0.08)] ${TAB_VIEWPORT_CARD_HEIGHT_CLASS} lg:overflow-hidden`}>
              {SHOW_TABLE_CONTEXT ? (
                <CardHeader className="gap-4 border-b border-border/70">
                  <div>
                    <CardTitle>Bảng xem trước và hàng đợi hợp nhất</CardTitle>
                    <CardDescription>
                      {tableMode === "preview"
                        ? "Bản xem trước của sheet hiện tại dùng đúng các cột mà hàng đợi thực tế sẽ dùng khi batch bắt đầu."
                        : tableMode === "queue"
                          ? batchPrimaryMessage(currentBatch)
                          : "Hãy chọn nguồn bảng để xem bản xem trước hiện tại hoặc batch đã lưu."}
                    </CardDescription>
                  </div>
                  <div className="flex flex-col gap-3 xl:flex-row xl:items-end xl:justify-between">
                    <Field className="xl:max-w-md">
                      <TooltipFieldLabel tooltip="Chọn hiển thị bản xem trước hiện tại hoặc một batch đã lưu trước đó.">
                        Nguồn bảng
                      </TooltipFieldLabel>
                      <Select
                        value={tableSource || undefined}
                        onValueChange={handleTableSourceChange}
                        disabled={!preview && batchSummaries.length === 0}
                      >
                        <SelectTrigger className="h-8 rounded-lg bg-muted/20 border-border/70 text-xs">
                          <SelectValue placeholder="Chọn bản xem trước hoặc batch đã lưu" />
                        </SelectTrigger>
                        <SelectContent>
                          {preview ? (
                            <SelectGroup>
                              <SelectLabel>Sheet hiện tại</SelectLabel>
                              <SelectItem value={TABLE_SOURCE_PREVIEW}>
                                Xem trước · {formatCount(preview.urlCount)} dòng
                              </SelectItem>
                            </SelectGroup>
                          ) : null}
                          {batchSummaries.length > 0 ? (
                            <SelectGroup>
                              <SelectLabel>Batch đã lưu</SelectLabel>
                              {batchSummaries.map((summary) => (
                                <SelectItem key={summary.id} value={summary.id}>
                                  {statusLabel(summary.status)} ·{" "}
                                  {formatCount(summary.discoveredUrlCount)} URL ·{" "}
                                  {formatDateTime(summary.createdAt)}
                                </SelectItem>
                              ))}
                            </SelectGroup>
                          ) : null}
                        </SelectContent>
                      </Select>
                    </Field>

                    <div className="rounded-lg border border-border bg-muted/40 px-3 py-2 text-sm text-muted-foreground">
                      {currentBatchSummary
                        ? `Batch đã chọn: ${statusLabel(currentBatchSummary.status)}`
                        : preview
                          ? "Nguồn đã chọn: bản xem trước hiện tại"
                          : "Chưa chọn nguồn"}
                    </div>
                  </div>
                </CardHeader>
              ) : null}
              <div className="flex justify-end pt-0 pb-2 px-4">
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="h-7 text-xs rounded-full border-border/40 hover:bg-muted/50"
                    disabled={tableMode === "empty"}
                    onClick={handleRefreshTable}
                  >
                    Xóa bảng
                  </Button>
              </div>
              <CardContent className="flex min-h-0 flex-1 flex-col gap-5 p-4 pt-2">
                {SHOW_TABLE_CONTEXT && tableMode === "queue" && currentBatch ? (
                  <div className="flex flex-col gap-4 rounded-xl border border-border bg-muted/35 p-4">
                    <div className="flex flex-wrap gap-2">
                      <Badge variant="secondary">
                        {statusLabel(currentBatch.status)}
                      </Badge>
                      <Badge variant="outline">
                        {accessModeLabel(currentBatch.sheetAccessMode)}
                      </Badge>
                      <Badge variant="outline">
                        Cập nhật {formatDateTime(currentBatch.lastUpdatedAt)}
                      </Badge>
                    </div>

                    <p className="truncate text-sm text-muted-foreground">
                      {currentBatch.sheetUrl}
                    </p>

                    <div className="grid gap-3 sm:grid-cols-2">
                      {batchStats.map((stat) => (
                        <div
                          key={stat.label}
                          className="rounded-lg border border-border bg-background/80 px-3 py-3"
                        >
                          <p className="text-xs font-medium uppercase tracking-[0.16em] text-muted-foreground">
                            {stat.label}
                          </p>
                          <p className="mt-2 text-lg font-semibold text-foreground">
                            {stat.value}
                          </p>
                        </div>
                      ))}
                    </div>

                    <div className="flex flex-wrap gap-2">
                      <Button
                        type="button"
                        variant="outline"
                        onClick={() => void handleRetryFailed(currentBatch.id)}
                        disabled={currentBatch.status === "running"}
                      >
                        Chạy lại lỗi
                      </Button>

                      {currentBatch.status === "paused" ? (
                        <Button
                          type="button"
                          variant="outline"
                          onClick={() => void handleResumeBatch(currentBatch.id)}
                        >
                          Tiếp tục
                        </Button>
                      ) : (
                        <Button
                          type="button"
                          variant="outline"
                          onClick={() => void handlePauseBatch(currentBatch.id)}
                          disabled={!["running", "queued"].includes(currentBatch.status)}
                        >
                          Tạm dừng
                        </Button>
                      )}

                      <AlertDialog>
                        <AlertDialogTrigger asChild>
                          <Button
                            type="button"
                            variant="destructive"
                            disabled={
                              !["running", "queued", "cancelling", "paused"].includes(
                                currentBatch.status,
                              )
                            }
                          >
                            Dừng
                          </Button>
                        </AlertDialogTrigger>
                        <AlertDialogContent>
                          <AlertDialogTitle>Dừng batch này?</AlertDialogTitle>
                          <AlertDialogDescription>
                            Các tiến trình đang chạy sẽ bị dừng và các dòng còn lại
                            trong hàng đợi sẽ được đánh dấu đã hủy.
                          </AlertDialogDescription>
                          <div className="mt-6 flex justify-end gap-3">
                            <AlertDialogCancel asChild>
                              <Button type="button" variant="outline">
                                Tiếp tục chạy
                              </Button>
                            </AlertDialogCancel>
                            <AlertDialogAction asChild>
                              <Button
                                type="button"
                                variant="destructive"
                                onClick={() => void handleCancelBatch(currentBatch.id)}
                              >
                                Xác nhận dừng
                              </Button>
                            </AlertDialogAction>
                          </div>
                        </AlertDialogContent>
                      </AlertDialog>
                    </div>
                  </div>
                ) : null}

                {SHOW_TABLE_CONTEXT && tableMode === "preview" && preview ? (
                  <div className="flex flex-wrap gap-2">
                    <Badge variant="secondary">Chế độ xem trước</Badge>
                    <Badge variant="outline">
                      {accessModeLabel(preview.accessMode)}
                    </Badge>
                    <Badge variant="outline">
                      Hỗ trợ: {formatCount(preview.supportedCount)}
                    </Badge>
                    <Badge variant="outline">
                      Không hỗ trợ: {formatCount(preview.unsupportedCount)}
                    </Badge>
                  </div>
                ) : null}

                {SHOW_TABLE_CONTEXT && tableMode === "queue" && currentBatch ? (
                  <div className="flex flex-wrap gap-2">
                    <Badge variant="secondary">{statusLabel(currentBatch.status)}</Badge>
                    <Badge variant="outline">
                      Tiến độ: {progressRatio(currentBatch.stats)}%
                    </Badge>
                    <Badge variant="outline">
                      Hoàn tất: {formatCount(currentBatch.stats.completed)}
                    </Badge>
                    <Badge variant="outline">
                      Thất bại: {formatCount(currentBatch.stats.failed)}
                    </Badge>
                    <Badge variant="outline">
                      Không hỗ trợ: {formatCount(currentBatch.stats.unsupported)}
                    </Badge>
                  </div>
                ) : null}

                {SHOW_TABLE_CONTEXT ? <Separator /> : null}

                {bootLoading ||
                (tableSource !== TABLE_SOURCE_PREVIEW &&
                  selectedBatchId &&
                  detailLoading &&
                  !currentBatch) ? (
                  <Empty className="border-0 bg-transparent shadow-none">
                    <EmptyHeader>
                      <EmptyTitle>Đang tải nguồn bảng</EmptyTitle>
                      <EmptyDescription>
                        Đang lấy bản xem trước hoặc chi tiết batch mới nhất từ
                        backend Python cục bộ.
                      </EmptyDescription>
                    </EmptyHeader>
                  </Empty>
                ) : tableRows.length > 0 ? (
                  <div className="min-w-0 max-h-[60dvh] overflow-auto rounded-xl border border-border/70 lg:flex-1 lg:min-h-0 lg:max-h-none">
                  <Table className="min-w-[58rem]">
                    <TableHeader>
                      <TableRow>
                        <TableHead>Mục</TableHead>
                        <TableHead>Nền tảng</TableHead>
                        <TableHead>Đoạn cắt</TableHead>
                        <TableHead>Trạng thái</TableHead>
                        <TableHead className="w-[42%]">URL</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {tableRows.map((row) => (
                        <TableRow key={row.id}>
                          <TableCell className="align-top">
                            <span className="font-medium text-foreground">
                              {row.sequenceLabel}
                            </span>
                          </TableCell>
                          <TableCell className="align-top">{row.platform}</TableCell>
                          <TableCell className="align-top">
                            {row.clipRange ?? "Toàn bộ"}
                          </TableCell>
                          <TableCell className="align-top">
                            <Badge variant={row.stateVariant}>{row.stateLabel}</Badge>
                          </TableCell>
                          <TableCell className="max-w-[32rem] whitespace-normal align-top break-words text-muted-foreground">
                            {row.sourceUrl}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                  </div>
                ) : (
                  <Empty className="border-0 bg-transparent shadow-none">
                    <EmptyHeader>
                      <EmptyTitle>Chưa chọn xem trước hoặc hàng đợi</EmptyTitle>
                      <EmptyDescription>
                        Xem trước một sheet để điền dữ liệu ngay vào bảng này,
                        hoặc chọn một batch đã lưu ở bộ chọn nguồn bảng phía trên.
                      </EmptyDescription>
                    </EmptyHeader>
                  </Empty>
                )}
              </CardContent>
            </Card>
          ) : null}
          </main>

          <main
            className={
              currentView === "story"
                ? `min-w-0 w-full ${TAB_PAGE_PADDING_CLASS}`
                : "hidden"
            }
          >
              <Suspense
                fallback={
                  <Card className="border-border/70 shadow-[0_24px_90px_rgba(15,23,42,0.08)]">
                    <CardContent className="py-12 text-center text-sm text-muted-foreground">
                      <p className="text-sm text-muted-foreground animate-pulse">
                        Đang tải khu vực Tạo ảnh AI...
                      </p>
                    </CardContent>
                  </Card>
                }
              >
                <StoryStudio />
              </Suspense>
          </main>

          <main
            className={
              currentView === "tts"
                ? `min-w-0 w-full ${TAB_PAGE_PADDING_CLASS}`
                : "hidden"
            }
          >
              <Suspense
                fallback={
                  <Card className="border-border/70 shadow-[0_24px_90px_rgba(15,23,42,0.08)]">
                    <CardContent className="py-12 text-center text-sm text-muted-foreground">
                      Đang tải Studio TTS...
                    </CardContent>
                  </Card>
                }
              >
                <TtsStudio />
              </Suspense>
          </main>

          <main
            className={
              currentView === "settings"
                ? `min-w-0 w-full ${TAB_PAGE_PADDING_CLASS}`
                : "hidden"
            }
          >
            <div className="flex min-w-0 flex-col gap-4 lg:flex-row lg:gap-6">
              <aside className="min-w-0 lg:w-16 lg:shrink-0">
                <Card className={`border-border/70 shadow-[0_24px_90px_rgba(15,23,42,0.08)] lg:sticky ${TAB_STICKY_TOP_CLASS} ${TAB_VIEWPORT_CARD_HEIGHT_CLASS}`}>
                  <CardContent className="flex flex-col items-center gap-2 pt-4">
                    {SETTINGS_NAV_ITEMS.map((item) => {
                      const Icon = item.icon;
                      return (
                        <Button
                          key={item.id}
                          type="button"
                          variant={settingsView === item.id ? "secondary" : "ghost"}
                          size="icon"
                          className="h-10 w-10 shrink-0"
                          onClick={() => setSettingsView(item.id)}
                          title={item.label}
                          aria-label={item.label}
                        >
                          <Icon className="h-5 w-5" />
                        </Button>
                      );
                    })}
                  </CardContent>
                </Card>
              </aside>

              <section className="min-w-0 flex-1">
                {settingsView === "cache" ? (
                  <Suspense
                    fallback={
                      <Card className="border-border/70 shadow-[0_24px_90px_rgba(15,23,42,0.08)]">
                        <CardContent className="py-12 text-center text-sm text-muted-foreground">
                      Đang tải quản lý cache...
                        </CardContent>
                      </Card>
                    }
                  >
                    <CacheManager />
                  </Suspense>
                ) : null}

                {settingsView === "cookies" ? (
                  <CookiesManager
                    settings={settingsDraft}
                    onSettingsChange={setSettingsDraft}
                  />
                ) : null}

                {settingsView === "browser-settings" ? (
                  <BrowserProfilesSettings />
                ) : null}
              </section>
            </div>
          </main>
        </div>
      </div>
    </>
  );
}

function batchStatusVariant(item: BatchItem): BadgeVariant {
  if (item.status === "completed") {
    return "secondary";
  }

  if (item.status === "failed" || item.status === "unsupported") {
    return "destructive";
  }

  if (item.status === "downloading") {
    return "default";
  }

  return "outline";
}

function clampNumber(value: string, min: number, max: number) {
  const parsed = Number(value);
  if (Number.isNaN(parsed)) {
    return min;
  }
  return Math.min(max, Math.max(min, parsed));
}

function isSettingsView(value: StoredView): value is SettingsView {
  return value === "cookies" || value === "browser-settings" || value === "cache";
}

function normalizeSettings(settings: Settings): Settings {
  return {
    ...settings,
    channel_prefix: settings.channel_prefix ?? "",
    cookies_map: settings.cookies_map || {},
  };
}

function settingsSignature(settings: Settings) {
  return JSON.stringify(settings);
}

function getErrorMessage(error: unknown) {
  if (error instanceof Error) {
    return error.message;
  }
  return "Có lỗi xảy ra khi giao tiếp với backend cục bộ.";
}

export default App;
