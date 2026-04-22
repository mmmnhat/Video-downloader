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
import { DownloadCloud, Cookie, AudioLines } from "lucide-react";
import CookiesManager from "./components/CookiesManager";
import UpdaterDialog from "./components/UpdaterDialog";
import { useLocalStorage } from "./hooks/use-local-storage";

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
import {
  InputGroup,
  InputGroupAddon,
  InputGroupButton,
  InputGroupInput,
} from "@/components/ui/input-group";
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

const EMPTY_SETTINGS: Settings = {
  output_dir: "",
  quality: "auto",
  concurrent_downloads: 20,
  retry_count: 1,
  use_browser_cookies: true,
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

type TableMode = "preview" | "queue" | "empty";
type BadgeVariant = "default" | "secondary" | "destructive" | "outline";

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

function App() {
  const [currentView, setCurrentView] = useLocalStorage<
    "downloader" | "cookies" | "tts"
  >("app.current-view", "downloader");
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

    setPreviewLoading(true);
    setPreviewError("");

    try {
      const nextPreview = await previewSheet(trimmedSheetUrl);
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

    setStartLoading(true);
    try {
      const batchSettings = normalizeSettings(settingsDraft);
      const detail = await createBatch(trimmedSheetUrl, batchSettings);
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
      toast.success("Batch đang dừng.");
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

      <div className="flex h-dvh overflow-hidden bg-background text-foreground">
        {/* Sidebar */}
        <aside className="w-[72px] lg:w-64 flex flex-col border-r border-border bg-card py-4 transition-all duration-300 z-10">
          <div className="flex items-center justify-center lg:justify-start lg:px-6 mb-8 gap-3">
             <div className="bg-primary/10 p-2 rounded-md"><DownloadCloud className="w-5 h-5 text-primary" /></div>
             <span className="font-bold text-lg hidden lg:block">Trình tải video</span>
          </div>
          
          <nav className="flex-1 px-3 space-y-2">
             <Button 
                variant={currentView === "downloader" ? "secondary" : "ghost"} 
                className="w-full justify-center lg:justify-start" 
                onClick={() => setCurrentView("downloader")}
             >
                <DownloadCloud className="w-4 h-4 lg:mr-2" />
                <span className="hidden lg:block">Bảng điều khiển</span>
             </Button>
             <Button 
                variant={currentView === "tts" ? "secondary" : "ghost"} 
                className="w-full justify-center lg:justify-start" 
                onClick={() => setCurrentView("tts")}
             >
                <AudioLines className="w-4 h-4 lg:mr-2" />
                <span className="hidden lg:block">Studio TTS</span>
             </Button>
             <Button 
                variant={currentView === "cookies" ? "secondary" : "ghost"} 
                className="w-full justify-center lg:justify-start" 
                onClick={() => setCurrentView("cookies")}
             >
                <Cookie className="w-4 h-4 lg:mr-2" />
                <span className="hidden lg:block">Quản lý Cookie</span>
             </Button>
          </nav>

          <div className="mt-auto pt-2 px-3">
             <UpdaterDialog />
          </div>
        </aside>

        {/* Main Content Area */}
        <div className="flex-1 overflow-auto">
          <main
            className={
              currentView === "downloader"
                ? "mx-auto grid w-full max-w-[1520px] gap-6 px-4 py-6 sm:px-6 lg:grid-cols-[minmax(22rem,28rem)_minmax(0,1fr)] lg:px-8"
                : "hidden"
            }
          >
              {bootError ? (
                <Alert className="lg:col-span-2" variant="destructive">
                  <AlertTitle>Lỗi kết nối backend</AlertTitle>
                  <AlertDescription>{bootError}</AlertDescription>
                </Alert>
              ) : null}

          <Card className="border-border/70 shadow-[0_24px_90px_rgba(15,23,42,0.08)] lg:sticky lg:top-6 lg:h-[calc(100dvh-3rem)] lg:overflow-hidden">
            <CardContent className="flex flex-col gap-6 pt-6 lg:h-full lg:overflow-auto">
              <Alert>
                <AlertTitle>
                  {authStatus?.authenticated
                    ? "Phiên trình duyệt đã sẵn sàng"
                    : "Phiên trình duyệt chưa sẵn sàng"}
                </AlertTitle>
                <AlertDescription>{authSummary(authStatus)}</AlertDescription>
              </Alert>

              <div className="flex flex-wrap gap-2">
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => void handleOpenGoogleLogin()}
                >
                  Mở đăng nhập Google
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => void handleRefreshAuth()}
                  disabled={authRefreshing}
                >
                  {authRefreshing ? "Đang làm mới..." : "Làm mới phiên"}
                </Button>
              </div>

              <form className="flex flex-col gap-6" onSubmit={handleSubmitSheetUrl}>
                  <Field data-invalid={Boolean(previewError)}>
                  <TooltipFieldLabel
                    htmlFor="sheet-url"
                    tooltip="Dán liên kết Google Sheets chứa các video cần xử lý."
                  >
                    URL Google Sheets
                  </TooltipFieldLabel>
                  <InputGroup>
                    <InputGroupInput
                      id="sheet-url"
                      value={sheetUrl}
                      onChange={(event) => {
                        setSheetUrl(event.target.value);
                        setPreview(null);
                        setPreviewError("");
                      }}
                      type="url"
                      name="sheet_url"
                      inputMode="url"
                      spellCheck={false}
                      autoComplete="off"
                      aria-invalid={Boolean(previewError)}
                      placeholder="https://docs.google.com/spreadsheets/d/..."
                    />
                    <InputGroupAddon align="inline-end">
                      <InputGroupButton
                        type="button"
                        variant="outline"
                        size="sm"
                        disabled={previewLoading || startLoading}
                        onClick={() => void handlePasteSheetUrl()}
                      >
                        Dán
                      </InputGroupButton>
                    </InputGroupAddon>
                  </InputGroup>
                  <FieldError>{previewError}</FieldError>
                </Field>

                <div className="flex flex-wrap gap-2">
                  <Button
                    type="submit"
                    variant="outline"
                    disabled={previewLoading || startLoading}
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
                </div>
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
                  <InputGroup>
                    <InputGroupInput
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
                      autoComplete="off"
                      placeholder="/Volumes/External/Video downloader/downloads"
                    />
                    <InputGroupAddon align="inline-end">
                      <InputGroupButton
                        type="button"
                        variant="ghost"
                        size="sm"
                        disabled={folderLoading}
                        onClick={() => void handleChooseFolder()}
                      >
                        {folderLoading ? "Đang chọn..." : "Chọn"}
                      </InputGroupButton>
                      <InputGroupButton
                        type="button"
                        variant="ghost"
                        size="sm"
                        disabled={!settingsDraft.output_dir.trim()}
                        onClick={() => void handleOpenFolder(settingsDraft.output_dir)}
                      >
                        Mở
                      </InputGroupButton>
                    </InputGroupAddon>
                  </InputGroup>
                </Field>

                <FieldSet>
                  <FieldLegend variant="label">Thiết lập tải mặc định</FieldLegend>
                  <FieldGroup className="md:grid md:grid-cols-2">
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
                        Luồng tải
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
                        Số lần thử lại
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
          </Card>

          {SHOW_UNIFIED_TABLE ? (
            <Card className="border-border/70 shadow-[0_24px_90px_rgba(15,23,42,0.08)] lg:h-[calc(100dvh-3rem)] lg:overflow-hidden">
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
                        <SelectTrigger className="w-full">
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
                                  {formatCount(summary.discoveredUrlCount)} URLs ·{" "}
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
              <CardContent className="flex flex-col gap-5 lg:h-full lg:min-h-0">
                <div className="flex justify-end">
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    disabled={tableMode === "empty"}
                    onClick={handleRefreshTable}
                  >
                    Xóa bảng
                  </Button>
                </div>
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
                        onClick={() => void handleOpenFolder(currentBatch.outputDir)}
                      >
                        Mở thư mục
                      </Button>
                      <Button
                        type="button"
                        variant="outline"
                        onClick={() => void handleRetryFailed(currentBatch.id)}
                        disabled={currentBatch.status === "running"}
                      >
                        Chạy lại lỗi
                      </Button>

                      <AlertDialog>
                        <AlertDialogTrigger asChild>
                          <Button
                            type="button"
                            variant="destructive"
                            disabled={
                              !["running", "queued", "cancelling"].includes(
                                currentBatch.status,
                              )
                            }
                          >
                            Dừng batch
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
                  <div className="max-h-[60dvh] overflow-auto rounded-xl border border-border/70 lg:flex-1 lg:min-h-0 lg:max-h-none">
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
              currentView === "tts"
                ? "mx-auto w-full max-w-[1520px] px-4 py-6 sm:px-6 lg:px-8"
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
              currentView === "cookies"
                ? "mx-auto w-full px-4 py-8 sm:px-6 lg:px-12"
                : "hidden"
            }
          >
            <CookiesManager
              settings={settingsDraft}
              onSettingsChange={setSettingsDraft}
            />
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

function normalizeSettings(settings: Settings): Settings {
  return {
    ...settings,
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
