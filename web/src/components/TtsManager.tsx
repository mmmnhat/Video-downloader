import { startTransition, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { RefreshCw, Loader2 } from "lucide-react";
import { toast } from "sonner";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Field, FieldGroup } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { SessionStatusAlert } from "@/components/ui/session-status-alert";
import { TooltipFieldLabel } from "@/components/ui/tooltip-field-label";
import {
  resolveSequenceRangeInput,
  type SequenceRangeMode,
} from "@/lib/sequence-range";
import { cn } from "@/lib/utils";
import {
  chooseFolder,
  getTtsBatch,
  getTtsBootstrap,
  getTtsSessionStatus,
  listTtsVoices,
  listTtsBatches,
  openFolder,
  openTtsLogin,
  pickTtsTake,
  previewTtsSheet,
  createTtsBatch,
  exportTtsBatch,
  cancelTtsBatch,
  pauseTtsBatch,
  resumeTtsBatch,
  retryTtsItem,
  type TtsBatchDetail,
  type TtsBatchSummary,
  type TtsItem,
  type TtsPreview,
  type TtsSessionStatus,
  type TtsVoice,
} from "@/lib/api";
import { useLocalStorage } from "@/hooks/use-local-storage";
import {
  TAB_CARD_GAP_CLASS,
  TAB_STICKY_TOP_CLASS,
  TAB_VIEWPORT_CARD_HEIGHT_CLASS,
} from "@/lib/layout";


const ACTIVE_BATCH_STATUSES = new Set(["queued", "running", "cancelling"]);

function ttsStatusLabel(status: string) {
  switch (status) {
    case "queued":
      return "Đang chờ";
    case "running":
      return "Đang chạy";
    case "completed":
      return "Hoàn tất";
    case "completed_with_errors":
      return "Hoàn tất kèm lỗi";
    case "failed":
      return "Thất bại";
    case "cancelled":
      return "Đã dừng";
    case "cancelling":
      return "Đang dừng";
    default:
      return status;
  }
}

function ttsStatusVariant(status: string): "default" | "secondary" | "destructive" | "outline" {
  if (status === "completed") {
    return "secondary";
  }
  if (status === "failed" || status === "completed_with_errors") {
    return "destructive";
  }
  if (status === "running" || status === "cancelling") {
    return "default";
  }
  return "outline";
}

function getErrorMessage(error: unknown) {
  return error instanceof Error ? error.message : "Yêu cầu thất bại.";
}

function clampNumber(value: number, minimum: number, maximum: number) {
  if (!Number.isFinite(value)) {
    return minimum;
  }
  return Math.min(maximum, Math.max(minimum, value));
}

function isExportableItem(item: TtsItem) {
  return item.takes.some((take) => take.status === "completed");
}

function isMyVoice(voice: TtsVoice) {
  if (voice.isMyVoice === true) {
    return true;
  }
  if (voice.isOwner === true) {
    return true;
  }
  const sharingStatus = (voice.sharingStatus ?? "").trim().toLowerCase();
  if (sharingStatus === "copied" || sharingStatus === "saved" || sharingStatus === "library") {
    return true;
  }
  const category = (voice.category ?? "").trim().toLowerCase();
  if (!category) {
    return true;
  }
  return category !== "premade";
}

export default function TtsManager() {
  const [sessionStatus, setSessionStatus] = useState<TtsSessionStatus | null>(null);
  // Persist form fields to localStorage so they survive tab switching
  const [sheetUrl, setSheetUrl] = useLocalStorage("tts.sheetUrl", "");
  const [textColumn, setTextColumn] = useLocalStorage("tts.textColumn", "");
  const [voiceQuery, setVoiceQuery] = useLocalStorage("tts.voiceQuery", "");
  const [modelFamily, setModelFamily] = useLocalStorage<"v2" | "v3">("tts.modelFamily", "v2");
  const [tagText, setTagText] = useLocalStorage("tts.tagText", "");
  const [takeCount, setTakeCount] = useLocalStorage("tts.takeCount", 1);
  const [retryCount, setRetryCount] = useLocalStorage("tts.retryCount", 1);
  const [workerCount, setWorkerCount] = useLocalStorage("tts.workerCount", 1);
  const [headless, setHeadless] = useLocalStorage("tts.headless", false);
  const [channelPrefix, setChannelPrefix] = useLocalStorage("tts.channelPrefix", "");
  const [sequenceRangeMode, setSequenceRangeMode] =
    useLocalStorage<SequenceRangeMode>("tts.sequenceRangeMode", "all");
  const [sequenceStart, setSequenceStart] = useLocalStorage("tts.sequenceStart", "");
  const [sequenceEnd, setSequenceEnd] = useLocalStorage("tts.sequenceEnd", "");
  const [preview, setPreview] = useState<TtsPreview | null>(null);
  const [voices, setVoices] = useState<TtsVoice[]>([]);
  const [batchSummaries, setBatchSummaries] = useState<TtsBatchSummary[]>([]);
  const [selectedBatchId, setSelectedBatchId] = useState<string | null>(null);
  const [selectedBatch, setSelectedBatch] = useState<TtsBatchDetail | null>(null);
  const [selectedItemIds, setSelectedItemIds] = useState<string[]>([]);
  const [manuallyDeselectedItemIds, setManuallyDeselectedItemIds] = useState<string[]>([]);
  const [, setBootLoading] = useState(true);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [startLoading, setStartLoading] = useState(false);
  const [sessionRefreshing, setSessionRefreshing] = useState(false);
  const [voicesLoading, setVoicesLoading] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [retryingItemId, setRetryingItemId] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState("");
  const sessionRefreshInFlightRef = useRef(false);
  const voicesLoadInFlightRef = useRef(false);
  const myVoices = useMemo(
    () => voices.filter((voice) => isMyVoice(voice)),
    [voices],
  );

  const hasActiveBatch = batchSummaries.some((summary) =>
    ACTIVE_BATCH_STATUSES.has(summary.status),
  );
  const showingPreview = preview !== null;
  const completedItems = useMemo(
    () => selectedBatch?.items.filter((item) => isExportableItem(item)) ?? [],
    [selectedBatch],
  );
  const selectedVoice = useMemo(
    () => myVoices.find((voice) => voice.voiceId === voiceQuery),
    [myVoices, voiceQuery],
  );
  const selectedBatchActive = selectedBatch ? ACTIVE_BATCH_STATUSES.has(selectedBatch.status) : false;

  const loadBatch = useCallback(async (batchId: string, options?: { silent?: boolean }) => {
    const silent = options?.silent ?? false;
    if (!silent) {
      setDetailLoading(true);
    }
    try {
      const detail = await getTtsBatch(batchId);
      const autoSelectedItemIds = detail.items
        .filter((item) => isExportableItem(item) && !manuallyDeselectedItemIds.includes(item.id))
        .map((item) => item.id);
      startTransition(() => {
        setSelectedBatch(detail);
        setPreview(null);
        setSelectedItemIds((current) => {
          const validCurrent = current.filter((itemId) =>
            detail.items.some((item) => item.id === itemId),
          );
          return Array.from(new Set([...validCurrent, ...autoSelectedItemIds]));
        });
      });
    } catch (error) {
      if (!silent) {
        toast.error(getErrorMessage(error));
      }
    } finally {
      if (!silent) {
        setDetailLoading(false);
      }
    }
  }, [manuallyDeselectedItemIds]);

  const bootstrap = useCallback(async () => {
    setBootLoading(true);
    setErrorMessage("");
    try {
      const payload = await getTtsBootstrap();
      const fallbackBatchId = payload.activeBatchId ?? null;
      startTransition(() => {
        setSessionStatus(payload.sessionStatus);
        setBatchSummaries(payload.batchSummaries);
        setSelectedBatchId(fallbackBatchId);
        if (!fallbackBatchId) {
          setSelectedBatch(null);
          setSelectedItemIds([]);
          setManuallyDeselectedItemIds([]);
        }
      });
      if (fallbackBatchId) {
        await loadBatch(fallbackBatchId, { silent: true });
      }
    } catch (error) {
      setErrorMessage(getErrorMessage(error));
    } finally {
      setBootLoading(false);
    }
  }, [loadBatch]);

  const refreshSummaries = useCallback(async (silent = false) => {
    try {
      const summaries = await listTtsBatches();
      startTransition(() => setBatchSummaries(summaries));
    } catch (error) {
      if (!silent) {
        toast.error(getErrorMessage(error));
      }
    }
  }, []);

  const loadVoices = useCallback(async (options?: { silent?: boolean; refresh?: boolean }) => {
    const silent = options?.silent ?? false;
    const refresh = options?.refresh ?? false;
    if (voicesLoadInFlightRef.current) {
      return;
    }
    voicesLoadInFlightRef.current = true;
    setVoicesLoading(true);
    try {
      const nextVoices = await listTtsVoices(refresh);
      startTransition(() => {
        setVoices(nextVoices);
        const nextMyVoices = nextVoices.filter((voice) => isMyVoice(voice));
        if (voiceQuery && !nextMyVoices.some((voice) => voice.voiceId === voiceQuery)) {
          const matchedByName = nextMyVoices.find(
            (voice) => voice.name.toLowerCase() === voiceQuery.trim().toLowerCase(),
          );
          if (matchedByName) {
            setVoiceQuery(matchedByName.voiceId);
          } else {
            setVoiceQuery(nextMyVoices[0]?.voiceId ?? "");
          }
        } else if (!voiceQuery && nextMyVoices.length > 0) {
          setVoiceQuery(nextMyVoices[0].voiceId);
        }
      });
    } catch (error) {
      startTransition(() => {
        setVoices([]);
      });
      if (!silent) {
        toast.error(getErrorMessage(error));
      }
    } finally {
      voicesLoadInFlightRef.current = false;
      setVoicesLoading(false);
    }
  }, [setVoiceQuery, voiceQuery]);

  const refreshSessionStatus = useCallback(async (options?: { silent?: boolean; loadVoices?: boolean }) => {
    const silent = options?.silent ?? false;
    const shouldLoadVoices = options?.loadVoices ?? false;
    if (sessionRefreshInFlightRef.current) {
      return;
    }
    sessionRefreshInFlightRef.current = true;
    if (!silent) {
      setSessionRefreshing(true);
    }
    try {
      const status = await getTtsSessionStatus(true);
      startTransition(() => setSessionStatus(status));
      if (status.authenticated && shouldLoadVoices) {
        await loadVoices({ silent: true, refresh: false });
      }
      if (!silent && status.authenticated) {
        toast.success("Phiên ElevenLabs đã sẵn sàng.");
      }
    } catch (error) {
      if (!silent) {
        toast.error(getErrorMessage(error));
      }
    } finally {
      sessionRefreshInFlightRef.current = false;
      if (!silent) {
        setSessionRefreshing(false);
      }
    }
  }, [loadVoices]);

  useEffect(() => {
    const timerId = window.setTimeout(() => {
      void bootstrap();
    }, 0);
    return () => window.clearTimeout(timerId);
  }, [bootstrap]);

  useEffect(() => {
    if (!selectedBatchId || showingPreview) {
      return;
    }
    const timerId = window.setTimeout(() => {
      void loadBatch(selectedBatchId, { silent: false });
    }, 0);
    return () => window.clearTimeout(timerId);
  }, [loadBatch, selectedBatchId, showingPreview]);

  useEffect(() => {
    if (!hasActiveBatch && !(selectedBatch && ACTIVE_BATCH_STATUSES.has(selectedBatch.status))) {
      return;
    }

    const intervalId = window.setInterval(() => {
      void refreshSummaries(true);
      if (selectedBatchId && !showingPreview) {
        void loadBatch(selectedBatchId, { silent: true });
      }
    }, 2500);

    return () => window.clearInterval(intervalId);
  }, [hasActiveBatch, loadBatch, refreshSummaries, selectedBatch, selectedBatchId, showingPreview]);

  useEffect(() => {
    if (!sessionStatus?.authenticated || !sessionStatus.dependencies_ready) {
      const resetTimerId = window.setTimeout(() => {
        startTransition(() => {
          setVoices([]);
          setVoicesLoading(false);
        });
      }, 0);
      return () => window.clearTimeout(resetTimerId);
    }

    const loadTimerId = window.setTimeout(() => {
      void loadVoices({ silent: true, refresh: false });
    }, 0);

    return () => window.clearTimeout(loadTimerId);
  }, [loadVoices, sessionStatus?.authenticated, sessionStatus?.dependencies_ready]);

  useEffect(() => {
    if (!sessionStatus?.authenticated || !sessionStatus.dependencies_ready) {
      return;
    }

    const intervalId = window.setInterval(() => {
      void loadVoices({ silent: true, refresh: false });
    }, 45_000);

    return () => window.clearInterval(intervalId);
  }, [loadVoices, sessionStatus?.authenticated, sessionStatus?.dependencies_ready]);

  useEffect(() => {
    if (!sessionStatus?.authenticated || !sessionStatus.dependencies_ready) {
      return;
    }

    const handleFocus = () => {
      void loadVoices({ silent: true, refresh: false });
    };
    const handleVisibilityChange = () => {
      if (!document.hidden) {
        void loadVoices({ silent: true, refresh: false });
      }
    };

    window.addEventListener("focus", handleFocus);
    document.addEventListener("visibilitychange", handleVisibilityChange);
    return () => {
      window.removeEventListener("focus", handleFocus);
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, [loadVoices, sessionStatus?.authenticated, sessionStatus?.dependencies_ready]);

  useEffect(() => {
    if (!sessionStatus?.dependencies_ready) {
      return;
    }
    if (sessionStatus.authenticated) {
      return;
    }

    const intervalId = window.setInterval(() => {
      void refreshSessionStatus({ silent: true, loadVoices: false });
    }, 4000);

    return () => window.clearInterval(intervalId);
  }, [refreshSessionStatus, sessionStatus?.authenticated, sessionStatus?.dependencies_ready]);

  async function handleRefreshSession() {
    await refreshSessionStatus({ silent: false, loadVoices: true });
  }

  async function handleOpenLogin() {
    try {
      const payload = await openTtsLogin();
      toast(payload.message);
      window.setTimeout(() => {
        void refreshSessionStatus({ silent: true, loadVoices: true });
      }, 1500);
    } catch (error) {
      toast.error(getErrorMessage(error));
    }
  }

  async function handlePreview() {
    const trimmedSheetUrl = sheetUrl.trim();
    if (!trimmedSheetUrl) {
      setErrorMessage("Hãy dán URL Google Sheets trước.");
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
      setErrorMessage(getErrorMessage(error));
      return;
    }

    setPreviewLoading(true);
    setErrorMessage("");
    try {
      const nextPreview = await previewTtsSheet(
        trimmedSheetUrl,
        textColumn || undefined,
        sequenceRange,
      );
      startTransition(() => {
        setPreview(nextPreview);
        setTextColumn(nextPreview.textColumn);
        setSelectedBatch(null);
        setSelectedBatchId(null);
        setSelectedItemIds([]);
        setManuallyDeselectedItemIds([]);
      });
    } catch (error) {
      setErrorMessage(getErrorMessage(error));
    } finally {
      setPreviewLoading(false);
    }
  }

  async function handleStart() {
    const trimmedSheetUrl = sheetUrl.trim();
    if (!trimmedSheetUrl) {
      setErrorMessage("Hãy dán URL Google Sheets trước.");
      return;
    }
    if (!selectedVoice) {
      setErrorMessage("Hãy chọn một giọng trong My Voice trước khi bắt đầu.");
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
      setErrorMessage(getErrorMessage(error));
      return;
    }

    setStartLoading(true);
    setErrorMessage("");
    try {
      const detail = await createTtsBatch({
        sheetUrl: trimmedSheetUrl,
        textColumn: textColumn || undefined,
        voiceQuery: selectedVoice.voiceId,
        voiceId: selectedVoice.voiceId,
        voiceName: selectedVoice.name,
        modelFamily,
        tagText: modelFamily === "v3" ? tagText : "",
        takeCount,
        retryCount,
        workerCount,
        headless,
        channelPrefix: channelPrefix.trim() || undefined,
        sequenceStart: sequenceRange.sequenceStart,
        sequenceEnd: sequenceRange.sequenceEnd,
      });
      startTransition(() => {
        setSelectedBatch(detail);
        setSelectedBatchId(detail.id);
        setPreview(null);
        setSelectedItemIds([]);
        setManuallyDeselectedItemIds([]);
      });
      toast.success("Đã bắt đầu batch TTS.");
      await refreshSummaries(true);
    } catch (error) {
      setErrorMessage(getErrorMessage(error));
    } finally {
      setStartLoading(false);
    }
  }

  async function handlePickTake(itemId: string, takeId: string) {
    if (!selectedBatch) {
      return;
    }
    try {
      const detail = await pickTtsTake(selectedBatch.id, itemId, takeId);
      startTransition(() => {
        setSelectedBatch(detail);
        setSelectedItemIds((current) => (current.includes(itemId) ? current : [...current, itemId]));
        setManuallyDeselectedItemIds((current) => current.filter((value) => value !== itemId));
      });
    } catch (error) {
      toast.error(getErrorMessage(error));
    }
  }

  function handleToggleExportFromTakeCard(itemId: string) {
    toggleItemSelection(itemId, !selectedItemIds.includes(itemId));
  }

  async function handleCancelBatch() {
    if (!selectedBatch) {
      return;
    }
    try {
      const detail = await cancelTtsBatch(selectedBatch.id);
      startTransition(() => setSelectedBatch(detail));
      await refreshSummaries(true);
    } catch (error) {
      toast.error(getErrorMessage(error));
    }
  }

  async function handlePauseBatch() {
    if (!selectedBatch) {
      return;
    }
    try {
      const detail = await pauseTtsBatch(selectedBatch.id);
      startTransition(() => setSelectedBatch(detail));
      await refreshSummaries(true);
    } catch (error) {
      toast.error(getErrorMessage(error));
    }
  }

  async function handleResumeBatch() {
    if (!selectedBatch) {
      return;
    }
    try {
      const detail = await resumeTtsBatch(selectedBatch.id);
      startTransition(() => setSelectedBatch(detail));
      await refreshSummaries(true);
    } catch (error) {
      toast.error(getErrorMessage(error));
    }
  }

  async function handleExportSelected() {
    if (!selectedBatch || selectedItemIds.length === 0) {
      toast.error("Hãy chọn ít nhất một dòng để xuất.");
      return;
    }

    setExporting(true);
    try {
      const folder = await chooseFolder();
      const exported = await exportTtsBatch(selectedBatch.id, selectedItemIds, folder.path);
      toast.success(`Đã xuất ${exported.exportedCount} tệp.`);
      if (exported.exportedCount > 0) {
        await openFolder(exported.destinationDir);
      }
    } catch (error) {
      toast.error(getErrorMessage(error));
    } finally {
      setExporting(false);
    }
  }

  async function handleRetryItem(itemId: string) {
    if (!selectedBatch) {
      return;
    }

    setRetryingItemId(itemId);
    try {
      const detail = await retryTtsItem(selectedBatch.id, itemId);
      startTransition(() => {
        setSelectedBatch(detail);
        setSelectedBatchId(detail.id);
        setSelectedItemIds((current) => current.filter((value) => value !== itemId));
        setManuallyDeselectedItemIds((current) => current.filter((value) => value !== itemId));
      });
      toast.success("Đã bắt đầu chạy lại dòng này.");
      await refreshSummaries(true);
    } catch (error) {
      toast.error(getErrorMessage(error));
    } finally {
      setRetryingItemId(null);
    }
  }

  function toggleItemSelection(itemId: string, checked: boolean) {
    setSelectedItemIds((current) => {
      if (checked) {
        return current.includes(itemId) ? current : [...current, itemId];
      }
      return current.filter((value) => value !== itemId);
    });
    setManuallyDeselectedItemIds((current) => {
      if (checked) {
        return current.filter((value) => value !== itemId);
      }
      return current.includes(itemId) ? current : [...current, itemId];
    });
  }

  function selectAllCompletedRows() {
    setSelectedItemIds(completedItems.map((item) => item.id));
    setManuallyDeselectedItemIds([]);
  }

  function clearSelection() {
    setSelectedItemIds([]);
    setManuallyDeselectedItemIds(completedItems.map((item) => item.id));
  }

  function handleClearTable() {
    startTransition(() => {
      setPreview(null);
      setSelectedBatch(null);
      setSelectedBatchId(null);
      setSelectedItemIds([]);
      setManuallyDeselectedItemIds([]);
    });
  }

  return (
    <div className={cn("min-w-0 grid lg:grid-cols-[minmax(22rem,28rem)_minmax(0,1fr)]", TAB_CARD_GAP_CLASS)}>
      {errorMessage ? (
        <Alert className="lg:col-span-2" variant="destructive">
          <AlertTitle>Lỗi luồng TTS</AlertTitle>
          <AlertDescription>{errorMessage}</AlertDescription>
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
              onClick={() => void handleOpenLogin()}
            >
              {sessionStatus?.authenticated && (
                <span className="size-1.5 rounded-full bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.6)]" />
              )}
              {sessionStatus?.authenticated ? "Đã đăng nhập" : "Đăng nhập"}
            </Button>
          </div>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="size-7 hover:bg-muted/80 rounded-full border border-border/40"
            onClick={() => void handleRefreshSession()}
            disabled={sessionRefreshing}
            title="Làm mới phiên"
          >
            {sessionRefreshing ? (
              <Loader2 className="size-3 animate-spin" />
            ) : (
              <RefreshCw className="size-3" />
            )}
          </Button>
        </div>
        <CardContent className="flex min-h-0 min-w-0 flex-1 flex-col gap-6 lg:overflow-x-hidden lg:overflow-y-auto p-4 pt-2">
          <SessionStatusAlert
            authenticated={Boolean(sessionStatus?.authenticated)}
            notReadyTitle={"Phiên ElevenLabs chưa sẵn sàng"}
            message={sessionStatus?.message ?? "Mở ElevenLabs trên trình duyệt cục bộ, đăng nhập rồi quay lại làm mới phiên."}
          />

          <FieldGroup>
            <Field>
              <TooltipFieldLabel
                htmlFor="tts-sheet-url"
                tooltip="Dán liên kết Google Sheets chứa các dòng văn bản cần tạo giọng đọc."
              >
                URL Google Sheets
              </TooltipFieldLabel>
              <div className="flex items-center gap-1 p-1 pl-3 rounded-full border border-border/70 bg-muted/20 focus-within:ring-1 focus-within:ring-primary/30 focus-within:border-primary/50 transition-all">
                <input
                  id="tts-sheet-url"
                  value={sheetUrl}
                  onChange={(event) => {
                    setSheetUrl(event.target.value);
                    setPreview(null);
                    setErrorMessage("");
                  }}
                  type="url"
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
                  onClick={() => {
                    if (!navigator.clipboard?.readText) {
                      toast.error("Không hỗ trợ truy cập clipboard tại đây.");
                      return;
                    }
                    void navigator.clipboard
                      .readText()
                      .then((value) => value.trim())
                      .then((value) => {
                        if (!value) {
                          throw new Error("Clipboard đang trống.");
                        }
                        setSheetUrl(value);
                        setPreview(null);
                      })
                      .catch((error: unknown) => {
                        toast.error(getErrorMessage(error));
                      });
                  }}
                >
                  Dán
                </Button>
              </div>
            </Field>

            <Field>
              <TooltipFieldLabel
                htmlFor="tts-text-column"
                tooltip="Chọn cột trong bảng tính chứa nội dung văn bản gửi tới ElevenLabs."
              >
                Cột văn bản
              </TooltipFieldLabel>
              <Select
                value={textColumn || "__auto__"}
                onValueChange={(value) => setTextColumn(value === "__auto__" ? "" : value)}
              >
                <SelectTrigger id="tts-text-column" className="h-8 rounded-lg bg-muted/20 border-border/70 text-xs">
                  <SelectValue placeholder="Tự nhận diện cột bình luận" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="__auto__">Tự nhận diện cột bình luận</SelectItem>
                  {(preview?.availableColumns ?? []).map((column) => (
                    <SelectItem key={column} value={column}>
                      {column}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Field>

            <Field>
              <TooltipFieldLabel
                htmlFor="tts-voice-query"
                tooltip="Chỉ hiển thị các giọng thuộc My Voice trong phiên ElevenLabs hiện tại."
              >
                Giọng My Voice
              </TooltipFieldLabel>
              <div className="flex items-center gap-2">
                <Select
                  value={voiceQuery || ""}
                  onValueChange={setVoiceQuery}
                >
                  <SelectTrigger className="h-8 rounded-full bg-muted/20 border-border/70 text-xs flex-1">
                    <SelectValue placeholder="Chọn giọng đọc..." />
                  </SelectTrigger>
                  <SelectContent>
                    {voices.map((v) => (
                      <SelectItem key={v.voiceId} value={v.voiceId}>
                        <div className="flex items-center gap-2">
                          {v.previewUrl && (
                            <div className="size-4 rounded-full overflow-hidden border border-border/50">
                              <img src={v.previewUrl} alt="" className="size-full object-cover" />
                            </div>
                          )}
                          <span className="truncate">{v.name}</span>
                        </div>
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="size-8 hover:bg-muted/40 rounded-full border border-border/70 bg-muted/20 shrink-0"
                  onClick={() => void loadVoices({ refresh: true })}
                  disabled={voicesLoading}
                  title="Quét lại danh sách giọng"
                >
                  <RefreshCw className={cn("size-4", voicesLoading && "animate-spin")} />
                </Button>
              </div>
            </Field>

            <div className="grid items-start gap-4 md:grid-cols-4">
              <Field>
                <TooltipFieldLabel
                  htmlFor="tts-model-family"
                  tooltip="Chọn dòng model của ElevenLabs. v3 tạo hai kết quả cho mỗi lượt tạo."
                >
                  Mô hình
                </TooltipFieldLabel>
                <Select
                  value={modelFamily}
                  onValueChange={(value) => setModelFamily(value as "v2" | "v3")}
                >
                  <SelectTrigger id="tts-model-family" className="h-8 rounded-lg bg-muted/20 border-border/70 text-xs">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="v2">v2</SelectItem>
                    <SelectItem value="v3">v3</SelectItem>
                  </SelectContent>
                </Select>
              </Field>

              <Field>
                <TooltipFieldLabel
                  htmlFor="tts-take-count"
                  tooltip="Số lượt tạo cho mỗi dòng. Với v3, mỗi lượt tạo sẽ sinh hai tệp như 1.1 và 1.2."
                >
                  Lượt tạo
                </TooltipFieldLabel>
                <Input
                  id="tts-take-count"
                  type="number"
                  min={1}
                  max={5}
                  inputMode="numeric"
                  value={takeCount}
                  className="h-8 rounded-lg bg-muted/20 border-border/70 text-xs"
                  onChange={(event) =>
                    setTakeCount(clampNumber(Number(event.target.value), 1, 5))
                  }
                />
              </Field>

              <Field>
                <TooltipFieldLabel
                  htmlFor="tts-retry-count"
                  tooltip="Số lần thử lại tự động sau khi tạo thất bại."
                >
                  Thử lại
                </TooltipFieldLabel>
                <Input
                  id="tts-retry-count"
                  type="number"
                  min={0}
                  max={5}
                  inputMode="numeric"
                  value={retryCount}
                  className="h-8 rounded-lg bg-muted/20 border-border/70 text-xs"
                  onChange={(event) =>
                    setRetryCount(clampNumber(Number(event.target.value), 0, 5))
                  }
                />
              </Field>

              <Field>
                <TooltipFieldLabel
                  htmlFor="tts-worker-count"
                  tooltip="Số worker trình duyệt chạy cùng lúc. Giá trị cao sẽ dùng nhiều cửa sổ và tài nguyên hơn."
                >
                  Số luồng
                </TooltipFieldLabel>
                <Input
                  id="tts-worker-count"
                  type="number"
                  min={1}
                  max={6}
                  inputMode="numeric"
                  value={workerCount}
                  className="h-8 rounded-lg bg-muted/20 border-border/70 text-xs"
                  onChange={(event) =>
                    setWorkerCount(clampNumber(Number(event.target.value), 1, 6))
                  }
                />
              </Field>
            </div>

            <Field>
              <TooltipFieldLabel
                htmlFor="tts-tag-text"
                tooltip="Tiền tố tùy chọn thêm trước mọi prompt v3, ví dụ [excited] hoặc [laugh]."
              >
                Tag toàn cục
              </TooltipFieldLabel>
              <Input
                id="tts-tag-text"
                value={tagText}
                className="h-8 rounded-lg bg-muted/20 border-border/70 text-xs"
                onChange={(event) => setTagText(event.target.value)}
                placeholder="[excited] hoặc tiền tố prompt bạn muốn"
                disabled={modelFamily !== "v3"}
              />
            </Field>

            <Field>
              <TooltipFieldLabel
                htmlFor="tts-channel-prefix"
                tooltip="Tiền tố tên kênh để ghép thành channel.stt (ví dụ: theoof.1.1). Nếu để trống, file sẽ chỉ dùng stt."
              >
                Tên kênh
              </TooltipFieldLabel>
              <Input
                id="tts-channel-prefix"
                value={channelPrefix}
                className="h-8 rounded-lg bg-muted/20 border-border/70 text-xs"
                onChange={(event) => setChannelPrefix(event.target.value)}
                placeholder="Ví dụ: theoof"
              />
            </Field>

            <FieldGroup className="md:grid md:grid-cols-[minmax(0,12rem)_minmax(0,1fr)_minmax(0,1fr)]">
              <Field>
                <TooltipFieldLabel
                  htmlFor="tts-range-mode"
                  tooltip="Chọn gen toàn bộ hoặc chỉ preview/gen theo khoảng STT."
                >
                  Phạm vi STT
                </TooltipFieldLabel>
                <Select
                  value={sequenceRangeMode}
                  onValueChange={(value) => {
                    setSequenceRangeMode(value as SequenceRangeMode);
                    setPreview(null);
                    setErrorMessage("");
                  }}
                >
                  <SelectTrigger id="tts-range-mode" className="h-8 rounded-lg bg-muted/20 border-border/70 text-xs">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">Gen hết</SelectItem>
                    <SelectItem value="range">Theo khoảng STT</SelectItem>
                  </SelectContent>
                </Select>
              </Field>

              <Field>
                <TooltipFieldLabel
                  htmlFor="tts-range-start"
                  tooltip="Nhập STT bắt đầu. Có thể để trống nếu chỉ muốn đến STT kết thúc."
                >
                  Từ STT
                </TooltipFieldLabel>
                <Input
                  id="tts-range-start"
                  type="number"
                  min={1}
                  className="h-8 rounded-lg bg-muted/20 border-border/70 text-xs"
                  inputMode="numeric"
                  value={sequenceStart}
                  onChange={(event) => {
                    setSequenceStart(event.target.value);
                    setPreview(null);
                    setErrorMessage("");
                  }}
                  disabled={sequenceRangeMode !== "range"}
                  placeholder="Ví dụ: 10"
                />
              </Field>

              <Field>
                <TooltipFieldLabel
                  htmlFor="tts-range-end"
                  tooltip="Nhập STT kết thúc. Có thể để trống nếu chỉ muốn từ STT bắt đầu trở đi."
                >
                  Đến STT
                </TooltipFieldLabel>
                <Input
                  id="tts-range-end"
                  type="number"
                  min={1}
                  className="h-8 rounded-lg bg-muted/20 border-border/70 text-xs"
                  inputMode="numeric"
                  value={sequenceEnd}
                  onChange={(event) => {
                    setSequenceEnd(event.target.value);
                    setPreview(null);
                    setErrorMessage("");
                  }}
                  disabled={sequenceRangeMode !== "range"}
                  placeholder="Ví dụ: 30"
                />
              </Field>
            </FieldGroup>
            <Field>
              <div className="flex items-center justify-between gap-4 rounded-full border border-border/70 px-3 h-8 bg-muted/20">
                <TooltipFieldLabel
                  tooltip="Nếu bật, trình duyệt sẽ chạy ngầm. Nếu tắt, bạn có thể xem quá trình gen trực tiếp."
                  className="text-muted-foreground font-medium"
                >
                  Chạy nền (headless)
                </TooltipFieldLabel>
                <Switch
                  id="tts-headless"
                  checked={headless}
                  onCheckedChange={setHeadless}
                  aria-label="Bật tắt chế độ headless"
                  className="scale-90"
                />
              </div>
            </Field>
          </FieldGroup>

        </CardContent>
        <CardFooter className="border-t border-border/70 pt-4">
          <div className="flex flex-wrap gap-2">
            <Button type="button" variant="outline" onClick={() => void handlePreview()} disabled={previewLoading || startLoading}>
              {previewLoading ? "Đang kiểm tra..." : "Xem trước"}
            </Button>
            <Button
              type="button"
              onClick={() => void handleStart()}
              disabled={startLoading || previewLoading || !sessionStatus?.dependencies_ready}
            >
              {startLoading ? "Đang bắt đầu..." : "Bắt đầu"}
            </Button>
          </div>
        </CardFooter>
      </Card>

      <Card className={`border-border/70 shadow-[0_24px_90px_rgba(15,23,42,0.08)] ${TAB_VIEWPORT_CARD_HEIGHT_CLASS} lg:overflow-hidden`}>
        <CardContent className="flex min-h-0 flex-1 flex-col gap-5">
          <div className="flex flex-wrap items-center gap-2">
            {selectedBatch ? (
              <>
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => selectAllCompletedRows()}
                  disabled={completedItems.length === 0}
                >
                  Chọn các dòng hoàn tất
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => clearSelection()}
                  disabled={selectedItemIds.length === 0}
                >
                  Bỏ chọn
                </Button>
                <Button
                  type="button"
                  onClick={() => void handleExportSelected()}
                  disabled={selectedItemIds.length === 0 || exporting}
                >
                  {exporting ? "Đang xuất..." : `Xuất mục đã chọn (${selectedItemIds.length})`}
                </Button>
                {selectedBatch.status === "running" || selectedBatch.status === "queued" ? (
                  <Button type="button" variant="secondary" onClick={() => void handlePauseBatch()}>
                    Tạm dừng
                  </Button>
                ) : null}
                {selectedBatch.status === "paused" ? (
                  <Button type="button" variant="default" onClick={() => void handleResumeBatch()}>
                    Tiếp tục
                  </Button>
                ) : null}
                {ACTIVE_BATCH_STATUSES.has(selectedBatch.status) || selectedBatch.status === "paused" ? (
                  <Button type="button" variant="destructive" onClick={() => void handleCancelBatch()}>
                    Dừng
                  </Button>
                ) : null}
              </>
            ) : null}
            <Button
              type="button"
              variant="outline"
              disabled={!showingPreview && !selectedBatch}
              onClick={handleClearTable}
            >
              Xóa bảng
            </Button>
          </div>

          {showingPreview && preview ? (
            <div className="min-h-[22rem] overflow-auto rounded-xl border border-border/70 p-4 lg:flex-1 lg:min-h-0">
              <div className="space-y-3">
                {preview.rows.map((row) => (
                  <div
                    key={`${row.rowNumber}-${row.sequenceLabel}`}
                    className="rounded-xl border border-border/70 p-4"
                  >
                    <div className="flex items-baseline gap-2">
                      <span className="shrink-0 text-sm font-medium">{row.sequenceLabel}</span>
                      <p className="text-sm text-muted-foreground">{row.text}</p>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ) : selectedBatch ? (
            <>
              <div className="min-h-[22rem] overflow-auto rounded-xl border border-border/70 p-4 lg:flex-1 lg:min-h-0">
                <div className="space-y-4">
                  {detailLoading && !selectedBatch.items.length ? (
                    <Card className="border-border/70">
                      <CardContent className="pt-6 text-sm text-muted-foreground">
                        Đang tải chi tiết batch...
                      </CardContent>
                    </Card>
                  ) : null}

                  {selectedBatch.items.map((item) => (
                    <TtsItemCard
                      key={item.id}
                      item={item}
                      selected={selectedItemIds.includes(item.id)}
                      canRetry={item.status === "failed" && !selectedBatchActive}
                      retrying={retryingItemId === item.id}
                      onPickTake={(takeId) => void handlePickTake(item.id, takeId)}
                      onToggleExport={() => handleToggleExportFromTakeCard(item.id)}
                      onRetry={() => void handleRetryItem(item.id)}
                    />
                  ))}
                </div>
              </div>
            </>
          ) : (
            <div className="flex min-h-[22rem] items-center justify-center px-6 text-center lg:flex-1 lg:min-h-0">
              <div className="max-w-md space-y-3">
                <p className="text-2xl font-semibold tracking-tight text-foreground">
                  Chưa chọn xem trước hoặc hàng đợi
                </p>
                <p className="text-sm leading-7 text-muted-foreground">
                  Xem trước một sheet để điền dữ liệu vào bảng ngay, hoặc chọn một batch TTS đã lưu để nghe và xuất từng lượt tạo.
                </p>
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function TtsItemCard({
  item,
  selected,
  canRetry,
  retrying,
  onPickTake,
  onToggleExport,
  onRetry,
}: {
  item: TtsItem;
  selected: boolean;
  canRetry: boolean;
  retrying: boolean;
  onPickTake: (takeId: string) => void;
  onToggleExport: () => void;
  onRetry: () => void;
}) {
  return (
    <Card className="border-border/70">
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <CardTitle className="flex items-baseline gap-2 text-base">
              <span className="shrink-0">{item.sequenceLabel}</span>
              <span className="truncate text-sm font-normal text-muted-foreground">{item.text}</span>
            </CardTitle>
          </div>
          <Badge variant={ttsStatusVariant(item.status)}>{ttsStatusLabel(item.status)}</Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-wrap items-center gap-2">
          {canRetry ? (
            <Button type="button" size="sm" variant="outline" onClick={onRetry} disabled={retrying}>
              {retrying ? "Đang thử lại..." : "Thử lại"}
            </Button>
          ) : null}
        </div>
        <div className="grid gap-4 md:grid-cols-2">
          {item.takes.map((take) => {
            const picked = item.pickedTakeId === take.id;
            const selectable = take.status === "completed";
            const exportSelectable = picked && selectable;
            return (
              <div
                key={take.id}
                className={cn(
                  "rounded-xl border p-4 transition-colors",
                  picked && selected ? "border-primary bg-primary/5" : "border-border/70",
                  picked && !selected ? "bg-muted/10" : "",
                  selectable ? "cursor-pointer hover:border-primary/70 hover:bg-primary/5" : "",
                )}
                role={selectable ? "button" : undefined}
                tabIndex={selectable ? 0 : undefined}
                onClick={
                  selectable
                    ? () => {
                        if (exportSelectable) {
                          onToggleExport();
                          return;
                        }
                        onPickTake(take.id);
                      }
                    : undefined
                }
                onKeyDown={
                  selectable
                    ? (event) => {
                        if (event.key === "Enter" || event.key === " ") {
                          event.preventDefault();
                          if (exportSelectable) {
                            onToggleExport();
                            return;
                          }
                          onPickTake(take.id);
                        }
                      }
                    : undefined
                }
              >
                <div className="flex items-center justify-between gap-3">
                  <div className="flex items-center gap-2">
                    <p className="text-sm font-medium">Lượt {take.takeLabel}</p>
                    {picked ? <Badge variant="secondary">{selected ? "Đã chọn" : "Bỏ chọn"}</Badge> : null}
                  </div>
                  <Badge variant={ttsStatusVariant(take.status)}>{ttsStatusLabel(take.status)}</Badge>
                </div>

                {take.previewUrl ? (
                  <audio
                    className="mt-3 w-full"
                    controls
                    preload="none"
                    src={take.previewUrl}
                    onClick={(event) => event.stopPropagation()}
                  />
                ) : (
                  <p className="mt-3 text-sm text-muted-foreground">
                    {take.error ?? "Bản xem trước âm thanh sẽ xuất hiện sau khi tạo xong."}
                  </p>
                )}
              </div>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
}
