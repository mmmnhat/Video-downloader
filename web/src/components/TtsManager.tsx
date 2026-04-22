import { startTransition, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Field, FieldGroup } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import {
  InputGroup,
  InputGroupAddon,
  InputGroupButton,
  InputGroupInput,
} from "@/components/ui/input-group";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { TooltipFieldLabel } from "@/components/ui/tooltip-field-label";
import { VoicePicker } from "@/components/ui/voice-picker";
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
  retryTtsItem,
  type TtsBatchDetail,
  type TtsBatchSummary,
  type TtsItem,
  type TtsPreview,
  type TtsSessionStatus,
  type TtsVoice,
} from "@/lib/api";
import { useLocalStorage } from "@/hooks/use-local-storage";


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
  const [sessionChecking, setSessionChecking] = useState(false);
  const [voicesLoading, setVoicesLoading] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [retryingItemId, setRetryingItemId] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState("");
  const sessionRefreshInFlightRef = useRef(false);
  const voicesLoadInFlightRef = useRef(false);

  const hasActiveBatch = batchSummaries.some((summary) =>
    ACTIVE_BATCH_STATUSES.has(summary.status),
  );
  const showingPreview = preview !== null;
  const completedItems = useMemo(
    () => selectedBatch?.items.filter((item) => isExportableItem(item)) ?? [],
    [selectedBatch],
  );
  const selectedVoice = useMemo(
    () => voices.find((voice) => voice.voiceId === voiceQuery),
    [voiceQuery, voices],
  );
  const selectedBatchActive = selectedBatch ? ACTIVE_BATCH_STATUSES.has(selectedBatch.status) : false;
  const voiceFieldLoading = sessionChecking || voicesLoading;
  const voiceFieldPlaceholder = voiceFieldLoading
    ? "Đang tải danh sách giọng đọc..."
    : "Chọn giọng từ phiên hiện tại...";

  useEffect(() => {
    void bootstrap();
  }, []);

  useEffect(() => {
    if (!selectedBatchId || showingPreview) {
      return;
    }
    void loadBatch(selectedBatchId, { silent: false });
  }, [selectedBatchId, showingPreview]);

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
  }, [hasActiveBatch, selectedBatch, selectedBatchId, showingPreview]);

  useEffect(() => {
    if (!sessionStatus?.authenticated || !sessionStatus.dependencies_ready) {
      setVoices([]);
      setVoicesLoading(false);
      return;
    }
    void loadVoices({ silent: true });
  }, [sessionStatus?.authenticated, sessionStatus?.dependencies_ready]);

  useEffect(() => {
    if (!sessionStatus?.dependencies_ready) {
      return;
    }
    if (sessionStatus.authenticated && voices.length > 0) {
      return;
    }

    void refreshSessionStatus({ silent: true, loadVoices: true });
    const intervalId = window.setInterval(() => {
      void refreshSessionStatus({ silent: true, loadVoices: true });
    }, 4000);

    return () => window.clearInterval(intervalId);
  }, [sessionStatus?.authenticated, sessionStatus?.dependencies_ready, voices.length]);

  async function bootstrap() {
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
  }

  async function refreshSummaries(silent = false) {
    try {
      const summaries = await listTtsBatches();
      startTransition(() => setBatchSummaries(summaries));
    } catch (error) {
      if (!silent) {
        toast.error(getErrorMessage(error));
      }
    }
  }

  async function loadVoices(options?: { silent?: boolean }) {
    const silent = options?.silent ?? false;
    if (voicesLoadInFlightRef.current) {
      return;
    }
    voicesLoadInFlightRef.current = true;
    setVoicesLoading(true);
    try {
      const nextVoices = await listTtsVoices();
      startTransition(() => {
        setVoices(nextVoices);
        if (voiceQuery && !nextVoices.some((voice) => voice.voiceId === voiceQuery)) {
          const matchedByName = nextVoices.find(
            (voice) => voice.name.toLowerCase() === voiceQuery.trim().toLowerCase(),
          );
          if (matchedByName) {
            setVoiceQuery(matchedByName.voiceId);
          }
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
  }

  async function refreshSessionStatus(options?: { silent?: boolean; loadVoices?: boolean }) {
    const silent = options?.silent ?? false;
    const shouldLoadVoices = options?.loadVoices ?? false;
    if (sessionRefreshInFlightRef.current) {
      return;
    }
    sessionRefreshInFlightRef.current = true;
    setSessionChecking(true);
    if (!silent) {
      setSessionRefreshing(true);
    }
    try {
      const status = await getTtsSessionStatus(true);
      startTransition(() => setSessionStatus(status));
      if (status.authenticated && shouldLoadVoices) {
        await loadVoices({ silent: true });
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
      setSessionChecking(false);
      if (!silent) {
        setSessionRefreshing(false);
      }
    }
  }

  async function loadBatch(batchId: string, options?: { silent?: boolean }) {
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
  }

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

    setPreviewLoading(true);
    setErrorMessage("");
    try {
      const nextPreview = await previewTtsSheet(trimmedSheetUrl, textColumn || undefined);
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
    if (!voiceQuery.trim()) {
      setErrorMessage("Hãy nhập từ khóa hoặc ID giọng đọc.");
      return;
    }

    setStartLoading(true);
    setErrorMessage("");
    try {
      const detail = await createTtsBatch({
        sheetUrl: trimmedSheetUrl,
        textColumn: textColumn || undefined,
        voiceQuery,
        voiceId: selectedVoice?.voiceId,
        voiceName: selectedVoice?.name,
        modelFamily,
        tagText: modelFamily === "v3" ? tagText : "",
        takeCount,
        retryCount,
        workerCount,
        headless,
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
    <div className="grid gap-6 lg:grid-cols-[minmax(22rem,28rem)_minmax(0,1fr)]">
      {errorMessage ? (
        <Alert className="lg:col-span-2" variant="destructive">
          <AlertTitle>Lỗi luồng TTS</AlertTitle>
          <AlertDescription>{errorMessage}</AlertDescription>
        </Alert>
      ) : null}

      <Card className="border-border/70 shadow-[0_24px_90px_rgba(15,23,42,0.08)] lg:sticky lg:top-6 lg:h-[calc(100dvh-3rem)] lg:overflow-hidden">
        <CardContent className="flex flex-col gap-6 pt-6 lg:h-full lg:overflow-auto">
          <Alert>
            <AlertTitle>
              {sessionStatus?.authenticated ? "Phiên ElevenLabs đã sẵn sàng" : "Phiên ElevenLabs chưa sẵn sàng"}
            </AlertTitle>
            <AlertDescription>
              {sessionStatus?.message ??
                "Mở ElevenLabs trên trình duyệt cục bộ, đăng nhập rồi quay lại làm mới phiên."}
            </AlertDescription>
          </Alert>

          <div className="flex flex-wrap gap-2">
            <Button type="button" variant="outline" onClick={() => void handleOpenLogin()}>
              Mở đăng nhập ElevenLabs
            </Button>
            <Button
              type="button"
              variant="outline"
              onClick={() => void handleRefreshSession()}
              disabled={sessionRefreshing}
            >
              {sessionRefreshing ? "Đang làm mới..." : "Làm mới phiên"}
            </Button>
          </div>

          <FieldGroup>
            <Field>
              <TooltipFieldLabel
                htmlFor="tts-sheet-url"
                tooltip="Dán liên kết Google Sheets chứa các dòng văn bản cần tạo giọng đọc."
              >
                URL Google Sheets
              </TooltipFieldLabel>
              <InputGroup>
                <InputGroupInput
                  id="tts-sheet-url"
                  value={sheetUrl}
                  onChange={(event) => {
                    setSheetUrl(event.target.value);
                    setPreview(null);
                    setErrorMessage("");
                  }}
                  type="url"
                  inputMode="url"
                  spellCheck={false}
                  autoComplete="off"
                  placeholder="https://docs.google.com/spreadsheets/d/..."
                />
                <InputGroupAddon align="inline-end">
                  <InputGroupButton
                    type="button"
                    variant="outline"
                    size="sm"
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
                  </InputGroupButton>
                </InputGroupAddon>
              </InputGroup>
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
                <SelectTrigger id="tts-text-column">
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
                tooltip="Chọn một giọng từ phiên hiện tại hoặc nhập tên/ID giọng ElevenLabs."
              >
                Từ khóa / ID giọng đọc
              </TooltipFieldLabel>
              {voices.length > 0 ? (
                <VoicePicker
                  voices={voices}
                  value={voiceQuery || undefined}
                  onValueChange={(value) => setVoiceQuery(value)}
                  disabled={voiceFieldLoading}
                  placeholder={voiceFieldPlaceholder}
                />
              ) : (
                <Input
                  id="tts-voice-query"
                  value={voiceQuery}
                  onChange={(event) => setVoiceQuery(event.target.value)}
                  disabled={voiceFieldLoading}
                  placeholder={voiceFieldLoading ? voiceFieldPlaceholder : "Ví dụ: Adam, Rachel, voice_abc..."}
                />
              )}
            </Field>

            <div className="grid items-start gap-4 md:grid-cols-4">
              <Field>
                <TooltipFieldLabel
                  className="min-h-10 items-start"
                  htmlFor="tts-model-family"
                  tooltip="Chọn dòng model của ElevenLabs. v3 tạo hai kết quả cho mỗi lượt tạo."
                >
                  Mô hình
                </TooltipFieldLabel>
                <Select
                  value={modelFamily}
                  onValueChange={(value) => setModelFamily(value as "v2" | "v3")}
                >
                  <SelectTrigger id="tts-model-family">
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
                  className="min-h-10 items-start"
                  htmlFor="tts-take-count"
                  tooltip="Số lượt tạo cho mỗi dòng. Với v3, mỗi lượt tạo sẽ sinh hai tệp như 1.1 và 1.2."
                >
                  Lượt tạo mỗi dòng
                </TooltipFieldLabel>
                <Input
                  id="tts-take-count"
                  type="number"
                  min={1}
                  max={5}
                  inputMode="numeric"
                  value={takeCount}
                  onChange={(event) =>
                    setTakeCount(clampNumber(Number(event.target.value), 1, 5))
                  }
                />
              </Field>

              <Field>
                <TooltipFieldLabel
                  className="min-h-10 items-start"
                  htmlFor="tts-retry-count"
                  tooltip="Số lần thử lại tự động sau khi tạo thất bại."
                >
                  Số lần tự thử lại
                </TooltipFieldLabel>
                <Input
                  id="tts-retry-count"
                  type="number"
                  min={0}
                  max={5}
                  inputMode="numeric"
                  value={retryCount}
                  onChange={(event) =>
                    setRetryCount(clampNumber(Number(event.target.value), 0, 5))
                  }
                />
              </Field>

              <Field>
                <TooltipFieldLabel
                  className="min-h-10 items-start"
                  htmlFor="tts-worker-count"
                  tooltip="Số worker trình duyệt chạy cùng lúc. Giá trị cao sẽ dùng nhiều cửa sổ và tài nguyên hơn."
                >
                  Tab song song
                </TooltipFieldLabel>
                <Input
                  id="tts-worker-count"
                  type="number"
                  min={1}
                  max={6}
                  inputMode="numeric"
                  value={workerCount}
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
                onChange={(event) => setTagText(event.target.value)}
                placeholder="[excited] hoặc tiền tố prompt bạn muốn"
                disabled={modelFamily !== "v3"}
              />
            </Field>

            <Field>
              <div className="flex items-center justify-between gap-4 rounded-xl border border-border/70 px-4 py-3">
                <div className="space-y-1">
                  <TooltipFieldLabel
                    htmlFor="tts-headless"
                    tooltip="Chạy trình duyệt nền mà không hiển thị cửa sổ."
                  >
                    Chế độ headless
                  </TooltipFieldLabel>
                </div>
                <Switch
                  id="tts-headless"
                  checked={headless}
                  onCheckedChange={setHeadless}
                  aria-label="Bật tắt chế độ headless"
                />
              </div>
            </Field>
          </FieldGroup>

          <div className="flex flex-wrap gap-2">
            <Button type="button" variant="outline" onClick={() => void handlePreview()} disabled={previewLoading || startLoading}>
              {previewLoading ? "Đang kiểm tra..." : "Xem trước dòng"}
            </Button>
            <Button
              type="button"
              onClick={() => void handleStart()}
              disabled={startLoading || previewLoading || !sessionStatus?.dependencies_ready}
            >
              {startLoading ? "Đang bắt đầu..." : "Bắt đầu TTS"}
            </Button>
          </div>

        </CardContent>
      </Card>

      <Card className="border-border/70 shadow-[0_24px_90px_rgba(15,23,42,0.08)] lg:h-[calc(100dvh-3rem)] lg:overflow-hidden">
        <CardContent className="flex flex-col gap-5 pt-6 lg:h-full lg:min-h-0">
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
                {ACTIVE_BATCH_STATUSES.has(selectedBatch.status) ? (
                  <Button type="button" variant="destructive" onClick={() => void handleCancelBatch()}>
                    Dừng batch
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
