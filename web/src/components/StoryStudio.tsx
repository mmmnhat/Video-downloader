import React, { useState, useEffect, useCallback, useMemo, useTransition } from "react";
import { 
  RefreshCw, Play, Pause, ChevronRight, ChevronDown, Trash2,
  Loader2, X, FileText, Video as VideoIcon, History as HistoryIcon,
  Layers, RotateCcw, Brain, Zap, Sparkles, Maximize2
} from "lucide-react";
import { cn } from "@/lib/utils";
import { 
  Card, CardContent, CardHeader, CardTitle, CardDescription 
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Field, FieldGroup } from "@/components/ui/field";
import { Switch } from "@/components/ui/switch";
import { TooltipFieldLabel } from "@/components/ui/tooltip-field-label";
import { 
  Select, SelectContent, SelectItem, 
  SelectTrigger, SelectValue 
} from "@/components/ui/select";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { toast } from "sonner";
import { 
  getStorySessionStatus, openStoryLogin, scanStoryFolder, 
  listStoryVideos, getStoryVideo, applyStoryAction, 
  updateStorySettings, getStoryBootstrap, getStoryAssetUrl,
  updateStoryGlobalPrompt, listStoryGems, controlStoryQueue,
  chooseFolder, openFolder, clearStoryVideos, exportStorySelected
} from "@/lib/api";
import {
  TAB_CARD_GAP_CLASS,
  TAB_STICKY_TOP_CLASS,
  TAB_VIEWPORT_CARD_HEIGHT_CLASS,
} from "@/lib/layout";

// Local types to ensure compatibility
export type StorySettings = {
  output_root: string;
  max_parallel_videos: number;
  generation_backend: string;
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
  mode: string;
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
};

export type StoryVideoSummary = {
  id: string;
  name: string;
  status: string;
  stepTotal: number;
  completedSteps: number;
  reviewSteps: number;
  previewPath?: string | null;
  resultPreviewPath?: string | null;
  acceptedSteps?: {
    videoId: string;
    videoName: string;
    markerIndex: number;
    stepId: string;
    stepIndex: number;
    previewPath: string;
    stepTitle: string;
  }[];
  error: string | null;
};

export type StoryVideoDetail = StoryVideoSummary & {
  videoPrompt: string;
  markers: StoryMarker[];
};

const POLL_INTERVAL = 3000;
const GEMINI_DEFAULT_URL = "https://gemini.google.com/app";

function storyStatusLabel(status: string | undefined | null) {
  if (!status) return "Chờ";
  const s = status.toLowerCase();
  if (s === "idle") return "Chờ";
  if (s === "queued") return "Đợi";
  if (s === "running") return "Chạy";
  if (s === "review") return "Duyệt";
  if (s === "done" || s === "completed") return "Xong";
  if (s === "error" || s === "failed") return "Lỗi";
  if (s === "paused") return "Dừng";
  return status;
}

function storyStatusTone(status: string | undefined | null): { variant: "default" | "secondary" | "outline" | "destructive", className?: string } {
  if (!status) return { variant: "outline" };
  const s = status.toLowerCase();
  switch (s) {
    case "running": return { variant: "default", className: "bg-blue-500 hover:bg-blue-600 animate-pulse" };
    case "review": return { variant: "default", className: "bg-amber-500 hover:bg-amber-600 shadow-[0_0_10px_rgba(245,158,11,0.4)]" };
    case "done":
    case "completed": return { variant: "default", className: "bg-emerald-500 hover:bg-emerald-600" };
    case "error":
    case "failed": return { variant: "destructive" };
    case "paused": return { variant: "secondary", className: "bg-slate-400 text-white" };
    default: return { variant: "outline" };
  }
}

function selectionKey(action: string, markerId: string, stepId: string) {
  return `${action}:${markerId}:${stepId}`;
}

function getErrorMessage(error: any) {
  if (error instanceof Error) return error.message;
  if (typeof error === "string") return error;
  return "Đã xảy ra lỗi không xác định.";
}

const VideoThumb = React.memo(({ path, alt, className, onClick }: { path: string; alt?: string; className?: string; onClick?: () => void }) => {
  return (
    <img
      src={getStoryAssetUrl(path)}
      alt={alt || "Thumbnail"}
      className={cn("w-full h-full object-cover rounded-lg border border-border/50", className)}
      loading="lazy"
      onClick={onClick}
    />
  );
});

VideoThumb.displayName = "VideoThumb";

export function StoryStudio() {
  const [selectedExportKeys, setSelectedExportKeys] = useState<Set<string>>(new Set());
  const [exportingCollection, setExportingCollection] = useState(false);
  const [bootLoading, setBootLoading] = useState(true);
  const [sessionStatus, setSessionStatus] = useState<StorySessionStatus | null>(null);
  const [videoSummaries, setVideoSummaries] = useState<StoryVideoSummary[]>([]);
  const [selectedVideoId, setSelectedVideoId] = useState<string | null>(null);
  const [selectedVideo, setSelectedVideo] = useState<StoryVideoDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [actionBusyKey, setActionBusyKey] = useState<string | null>(null);

  const [settingsDraft, setSettingsDraft] = useState<StorySettings | null>(null);
  const [sourceFolderPath, setSourceFolderPath] = useState("");
  const [availableGems, setAvailableGems] = useState<{name: string, url: string}[]>([]);

  const [globalPrompt, setGlobalPrompt] = useState("");
  const [globalPromptDraft, setGlobalPromptDraft] = useState("");
  const [savingPrompt, setSavingPrompt] = useState(false);

  const [videoPromptDraft, setVideoPromptDraft] = useState("");
  const [savingVideoPrompt, setSavingVideoPrompt] = useState(false);

  const [leftPanelTab, setLeftPanelTab] = useState<"gemini" | "prompt">("gemini");
  const [mainPanelTab, setMainPanelTab] = useState<"videos" | "collection" | "history">("videos");
  const [queueFilter, setQueueFilter] = useState<"all" | "running" | "review" | "queued">("all");

  const [selectedMarkerId, setSelectedMarkerId] = useState<string | null>(null);
  const [selectedStepId, setSelectedStepId] = useState<string | null>(null);
  const [selectedAttemptId, setSelectedAttemptId] = useState<string | null>(null);
  const [expandedMarkerIds, setExpandedMarkerIds] = useState<string[]>([]);
  const [sessionRefreshing, setSessionRefreshing] = useState(false);

  const [showRefinePrompt, setShowRefinePrompt] = useState(false);
  const [refinePromptDraft, setRefinePromptDraft] = useState("");
  const [previewDialogPath, setPreviewDialogPath] = useState<string | null>(null);

  const [, startTransition] = useTransition();

  const refreshSummaries = useCallback(async (silent = false) => {
    try {
      const summaries = await listStoryVideos();
      startTransition(() => {
        setVideoSummaries(summaries);
      });
    } catch (e) {
      if (!silent) toast.error("Không thể tải danh sách video.");
    }
  }, [startTransition]);

  const loadVideoDetail = useCallback(async (videoId: string, options: { silent?: boolean } = {}) => {
    if (!options.silent) setDetailLoading(true);
    try {
      const detail = await getStoryVideo(videoId);
      startTransition(() => {
        setSelectedVideo(detail);
        setVideoPromptDraft(detail.videoPrompt || "");
        if (!selectedMarkerId && detail.markers.length > 0) {
          const firstInReview = detail.markers.find(m => m.status === 'review') || detail.markers[0];
          setSelectedMarkerId(firstInReview.id);
          setExpandedMarkerIds(curr => curr.includes(firstInReview.id) ? curr : [...curr, firstInReview.id]);
          if (firstInReview.steps.length > 0) {
            const firstStepInReview = firstInReview.steps.find(s => s.status === 'review') || firstInReview.steps[0];
            setSelectedStepId(firstStepInReview.id);
            if (!selectedAttemptId) {
              setSelectedAttemptId(firstStepInReview.attempts.at(-1)?.id || null);
            }
          }
        }
      });
    } catch (e) {
      if (!options.silent) toast.error("Không thể tải chi tiết video.");
    } finally {
      if (!options.silent) setDetailLoading(false);
    }
  }, [selectedAttemptId, selectedMarkerId, startTransition]);

  useEffect(() => {
    const init = async () => {
      try {
        const bootstrap = await getStoryBootstrap();
        setSessionStatus(bootstrap.sessionStatus);
        setVideoSummaries(bootstrap.videoSummaries);
        setSettingsDraft(bootstrap.settings);
        setGlobalPrompt(bootstrap.globalPrompt || "");
        setGlobalPromptDraft(bootstrap.globalPrompt || "");
        
        // Fetch gems
        const gems = await listStoryGems();
        setAvailableGems(gems);
      } catch (e) {
        toast.error("Lỗi khởi tạo Tạo ảnh.");
      } finally {
        setBootLoading(false);
      }
    };
    init();
  }, []);

  useEffect(() => {
    const timer = setInterval(() => {
      void refreshSummaries(true);
      if (selectedVideoId) {
        void loadVideoDetail(selectedVideoId, { silent: true });
      }
    }, POLL_INTERVAL);
    return () => clearInterval(timer);
  }, [loadVideoDetail, refreshSummaries, selectedVideoId]);

  const handleOpenLogin = useCallback(async () => {
    try {
      await openStoryLogin();
      toast.info("Đang mở trình duyệt để đăng nhập...");
    } catch (e) {
      toast.error(getErrorMessage(e));
    }
  }, []);

  const handleRefreshSession = useCallback(async () => {
    setSessionRefreshing(true);
    try {
      const status = await getStorySessionStatus(true);
      setSessionStatus(status);
      toast.success("Đã cập nhật trạng thái Gemini.");
    } catch (e) {
      toast.error("Không thể cập nhật session.");
    } finally {
      setSessionRefreshing(false);
    }
  }, []);

  const handleSaveSettings = useCallback(async (partial: Partial<StorySettings>) => {
    if (!settingsDraft) return;
    try {
      const next = await updateStorySettings({ ...settingsDraft, ...partial });
      setSettingsDraft(next);
      toast.success("Đã lưu cài đặt.");
    } catch (e) {
      toast.error(getErrorMessage(e));
    }
  }, [settingsDraft]);

  const handleChooseOutputFolder = useCallback(async () => {
    try {
      const { path } = await chooseFolder();
      if (!path) return;
      await handleSaveSettings({ output_root: path });
    } catch (error) {
      toast.error(getErrorMessage(error));
    }
  }, [handleSaveSettings]);

  const handleOpenOutputFolder = useCallback(async () => {
    if (!settingsDraft?.output_root) return;
    try {
      await openFolder(settingsDraft.output_root);
    } catch (error) {
      toast.error("Không thể mở thư mục.");
    }
  }, [settingsDraft?.output_root]);

  const handleImportSourceFolder = useCallback(async (path: string) => {
    if (!path.trim()) return;
    try {
      await scanStoryFolder(path);
      await refreshSummaries(true);
      toast.success("Đã cập nhật danh sách video.");
    } catch (error) {
      toast.error(getErrorMessage(error));
    }
  }, [refreshSummaries]);

  const handleChooseSourceFolder = useCallback(async () => {
    try {
      const { path } = await chooseFolder();
      if (!path) return;
      setSourceFolderPath(path);
      await handleImportSourceFolder(path);
    } catch (error) {
      toast.error(getErrorMessage(error));
    }
  }, [handleImportSourceFolder]);

  const handleSaveGlobalPrompt = useCallback(async () => {
    setSavingPrompt(true);
    try {
      const result = await updateStoryGlobalPrompt(globalPromptDraft);
      setGlobalPrompt(result.globalPrompt);
      setGlobalPromptDraft(result.globalPrompt);
      toast.success("Đã cập nhật prompt tổng.");
    } catch (error) {
      toast.error(getErrorMessage(error));
    } finally {
      setSavingPrompt(false);
    }
  }, [globalPromptDraft]);

  const handleSaveVideoPrompt = useCallback(async () => {
    if (!selectedVideoId) return;
    setSavingVideoPrompt(true);
    try {
      const detail = await applyStoryAction({
        action: "update_video_prompt",
        video_id: selectedVideoId,
        prompt: videoPromptDraft
      });
      setSelectedVideo(detail);
      toast.success("Đã cập nhật prompt riêng cho video.");
    } catch (error) {
      toast.error(getErrorMessage(error));
    } finally {
      setSavingVideoPrompt(false);
    }
  }, [selectedVideoId, videoPromptDraft]);

  const handleLocalAction = useCallback(async (action: "run" | "pause" | "cancel", videoId: string) => {
    setActionBusyKey(`local:${action}:${videoId}`);
    try {
      const detail = await applyStoryAction({ action, video_id: videoId });
      if (selectedVideoId === videoId) setSelectedVideo(detail);
      await refreshSummaries(true);
      const labels = { run: "chạy", pause: "tạm dừng", cancel: "dừng" };
      toast.success(`Đã ${labels[action]} video.`);
    } catch (error) {
      toast.error(getErrorMessage(error));
    } finally {
      setActionBusyKey(null);
    }
  }, [refreshSummaries, selectedVideoId]);


  const handleGlobalControl = useCallback(async (action: "run" | "pause" | "resume" | "cancel") => {
    setActionBusyKey(`global:${action}`);
    try {
      const result = await controlStoryQueue(action);
      await refreshSummaries(false);
      if (selectedVideoId) await loadVideoDetail(selectedVideoId, { silent: true });
      const labels = { run: "chạy", pause: "tạm dừng", resume: "tiếp tục", cancel: "dừng" };
      toast.success(result.count > 0 ? `Đã ${labels[action]} ${result.count} video.` : "Không có video nào khả dụng.");
    } catch (error) {
      toast.error(getErrorMessage(error));
    } finally {
      setActionBusyKey(null);
    }
  }, [loadVideoDetail, refreshSummaries, selectedVideoId]);

  const handleClearVideos = useCallback(async () => {
    try {
      await clearStoryVideos();
      await refreshSummaries(false);
      setSelectedVideo(null);
      setSelectedVideoId(null);
      toast.success("Đã xóa toàn bộ video.");
    } catch (error) {
      toast.error(getErrorMessage(error));
    }
  }, [refreshSummaries]);

  const handleRefineSelectedStep = useCallback(async () => {
    if (!selectedVideoId || !selectedMarkerId || !selectedStepId) return;
    const prompt = refinePromptDraft.trim();
    if (!prompt) {
      toast.error("Hãy nhập yêu cầu tinh chỉnh.");
      return;
    }
    setActionBusyKey(selectionKey("refine", selectedMarkerId, selectedStepId));
    try {
      const detail = await applyStoryAction({
        action: "refine",
        video_id: selectedVideoId,
        marker_id: selectedMarkerId,
        step_id: selectedStepId,
        prompt
      });
      setSelectedVideo(detail);
      const newStep = detail.markers.find((m: any) => m.id === selectedMarkerId)?.steps.find((s: any) => s.id === selectedStepId);
      if (newStep && newStep.attempts && newStep.attempts.length > 0) {
        setSelectedAttemptId(newStep.attempts.at(-1)!.id);
      }
      setShowRefinePrompt(false);
      setRefinePromptDraft("");
      toast.success("Đã gửi yêu cầu tinh chỉnh.");
    } catch (error) {
      toast.error(getErrorMessage(error));
    } finally {
      setActionBusyKey(null);
    }
  }, [refinePromptDraft, selectedMarkerId, selectedStepId, selectedVideoId]);

  const handleAcceptAndNext = useCallback(async () => {
    if (!selectedVideoId || !selectedMarkerId || !selectedStepId) return;
    setActionBusyKey("step:accept");
    try {
      const detail = await applyStoryAction({
        action: "accept",
        video_id: selectedVideoId,
        marker_id: selectedMarkerId,
        step_id: selectedStepId,
        attempt_id: selectedAttemptId || undefined,
      });
      setSelectedVideo(detail);
      toast.success("Đã duyệt biến thể này.");
    } catch (error) {
      toast.error(getErrorMessage(error));
    } finally {
      setActionBusyKey(null);
    }
  }, [selectedAttemptId, selectedMarkerId, selectedStepId, selectedVideoId]);

  const runStepAction = useCallback(async (action: any, markerId: string, stepId: string) => {
    if (!selectedVideoId) return;
    setActionBusyKey(selectionKey(action, markerId, stepId));
    try {
      const detail = await applyStoryAction({ action, video_id: selectedVideoId, marker_id: markerId, step_id: stepId });
      setSelectedVideo(detail);
      const newStep = detail.markers.find((m: any) => m.id === markerId)?.steps.find((s: any) => s.id === stepId);
      if (newStep && newStep.attempts && newStep.attempts.length > 0) {
        setSelectedAttemptId(newStep.attempts.at(-1)!.id);
      }
      toast.success(`Đã thực hiện thao tác.`);
    } catch (error) {
      toast.error(getErrorMessage(error));
    } finally {
      setActionBusyKey(null);
    }
  }, [selectedVideoId]);

  const handleToggleExportSelection = useCallback((key: string) => {
    setSelectedExportKeys(prev => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }, []);

  const handleExportCollection = useCallback(async () => {
    if (selectedExportKeys.size === 0) {
      toast.error("Hãy chọn ít nhất một ảnh để xuất.");
      return;
    }
    if (!settingsDraft?.output_root) {
      toast.error("Hãy cài đặt thư mục đầu ra trước.");
      return;
    }

    setExportingCollection(true);
    try {
      // Group by videoId
      const groups: Record<string, string[]> = {};
      selectedExportKeys.forEach(key => {
        const [videoId, stepId] = key.split(":");
        if (!groups[videoId]) groups[videoId] = [];
        groups[videoId].push(stepId);
      });

      let totalExported = 0;
      for (const videoId in groups) {
        try {
          const result = await exportStorySelected(videoId, settingsDraft.output_root, groups[videoId]);
          totalExported += result.exportedCount;
        } catch (err) {
          console.error(`Export failed for ${videoId}:`, err);
        }
      }
      toast.success(`Đã xuất ${totalExported} ảnh vào thư mục đầu ra.`);
      setSelectedExportKeys(new Set());
    } catch (error) {
      toast.error(getErrorMessage(error));
    } finally {
      setExportingCollection(false);
    }
  }, [selectedExportKeys, settingsDraft?.output_root]);

  const filteredVideoSummaries = useMemo(() => {
    if (queueFilter === "all") return videoSummaries;
    return videoSummaries.filter(v => v.status.toLowerCase() === queueFilter);
  }, [videoSummaries, queueFilter]);

  const queueCounts = useMemo(() => ({
    all: videoSummaries.length,
    running: videoSummaries.filter(v => v.status.toLowerCase() === "running").length,
    review: videoSummaries.filter(v => v.status.toLowerCase() === "review").length,
    queued: videoSummaries.filter(v => v.status.toLowerCase() === "queued").length,
  }), [videoSummaries]);

  const globalQueueCounts = useMemo(() => ({
    queued: videoSummaries.filter(v => ["idle", "queued", "paused", "failed"].includes(v.status.toLowerCase())).length,
    running: videoSummaries.filter(v => v.status.toLowerCase() === "running").length,
    paused: videoSummaries.filter(v => v.status.toLowerCase() === "paused").length,
    stoppable: videoSummaries.filter(v => ["running", "queued", "paused"].includes(v.status.toLowerCase())).length,
  }), [videoSummaries]);

  const selectedMarker = selectedVideo?.markers.find(m => m.id === selectedMarkerId);
  const selectedStep = selectedMarker?.steps.find(s => s.id === selectedStepId);
  const currentAttempt = selectedStep?.attempts.find(a => a.id === selectedAttemptId) || selectedStep?.attempts.at(-1);

  const allAcceptedSteps = useMemo(() => {
    return videoSummaries.flatMap(v => (v.acceptedSteps || []).map(step => ({
      ...step,
      key: `${v.id}:${step.stepId}`
    })));
  }, [videoSummaries]);

  const progressPercent = (v: StoryVideoSummary | StoryVideoDetail) => 
    v.stepTotal > 0 ? Math.round((v.completedSteps / v.stepTotal) * 100) : 0;

  if (bootLoading) {
    return (
      <Card className="border-border/70 shadow-sm">
        <CardContent className="flex items-center justify-center gap-3 py-16 text-sm text-muted-foreground">
          <Loader2 className="size-4 animate-spin" />
          Khởi tạo Tạo ảnh...
        </CardContent>
      </Card>
    );
  }

  return (
    <div className={cn("grid lg:grid-cols-[22rem_minmax(0,1fr)]", TAB_CARD_GAP_CLASS)}>
      {/* -------------------- LEFT PANEL (STICKY CONFIG) -------------------- */}
      <aside className="relative flex flex-col min-w-0">
        <Card className={cn("relative flex flex-col border-border/70 shadow-[0_24px_90px_rgba(15,23,42,0.08)] lg:sticky", TAB_STICKY_TOP_CLASS, TAB_VIEWPORT_CARD_HEIGHT_CLASS, "lg:overflow-hidden")}>
          <div className="flex items-center justify-between px-4 pt-0 pb-2 shrink-0">
            <Tabs value={leftPanelTab} onValueChange={v => setLeftPanelTab(v as any)} className="flex items-center">
              <TabsList className="h-8 bg-muted/20 p-0.5 border border-border/40">
                <TabsTrigger value="gemini" className="h-7 px-3 text-[11px] font-medium uppercase tracking-wider">Gemini</TabsTrigger>
                <TabsTrigger value="prompt" className="h-7 px-3 text-[11px] font-medium uppercase tracking-wider">Prompt</TabsTrigger>
              </TabsList>
            </Tabs>
            
            <div className="flex items-center gap-1.5">
              <div className="relative">
                <Button variant="ghost" size="sm" className="h-7 text-[10px] font-bold uppercase tracking-wider px-2.5 hover:bg-muted/80 rounded-full border border-border/40 flex items-center gap-2" onClick={handleOpenLogin}>
                  {sessionStatus?.authenticated && (
                    <span className="size-1.5 rounded-full bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.6)]" />
                  )}
                  {sessionStatus?.authenticated ? "Đã đăng nhập" : "Đăng nhập"}
                </Button>
              </div>
              <Button variant="ghost" size="icon" className="size-8 hover:bg-muted/80 rounded-full border border-border/40 shrink-0" onClick={handleRefreshSession} disabled={sessionRefreshing}>
                <RefreshCw className={cn("size-3", sessionRefreshing && "animate-spin")} />
              </Button>
          </div>
          </div>

          <CardContent className="flex flex-col min-h-0 flex-1 gap-5 pt-2 overflow-y-auto">
            <Tabs value={leftPanelTab} className="flex flex-col flex-1">
              <TabsContent value="gemini" className="flex-1 mt-0">
                {settingsDraft && (
                  <FieldGroup className="gap-4">
                    <Field>
                      <TooltipFieldLabel tooltip="Thư mục chứa các file video để quét marker XMP.">Nhập video</TooltipFieldLabel>
                      <div className="flex items-center gap-2 p-1 pl-3 rounded-full border border-border/70 bg-muted/20">
                        <span className="text-xs flex-1 truncate text-muted-foreground">{sourceFolderPath || "Chưa chọn..."}</span>
                        <Button variant="ghost" size="sm" className="h-7 px-3 text-xs hover:bg-background/50 rounded-full" onClick={handleChooseSourceFolder}>Chọn</Button>
                      </div>
                    </Field>

                    <Field>
                      <TooltipFieldLabel tooltip="Thư mục lưu trữ các hình ảnh đã tạo và xuất bản.">Thư mục đầu ra</TooltipFieldLabel>
                      <div className="flex items-center gap-1 p-1 pl-3 rounded-full border border-border/70 bg-muted/20">
                        <span className="text-xs flex-1 truncate text-muted-foreground">{settingsDraft.output_root || "Chưa chọn..."}</span>
                        <div className="flex gap-1 shrink-0">
                          <Button variant="ghost" size="sm" className="h-7 px-3 text-xs hover:bg-background/50 rounded-full" onClick={handleChooseOutputFolder}>Chọn</Button>
                          <Button variant="ghost" size="sm" className="h-7 px-3 text-xs hover:bg-background/50 rounded-full" onClick={handleOpenOutputFolder}>Mở</Button>
                        </div>
                      </div>
                    </Field>

                    <Field>
                      <TooltipFieldLabel tooltip="Tên Gem hoặc URL Gemini App muốn sử dụng.">Gemini App / Gem</TooltipFieldLabel>
                      <div className="flex items-center gap-2">
                        <Select value={settingsDraft.gemini_base_url} onValueChange={v => handleSaveSettings({ gemini_base_url: v })}>
                          <SelectTrigger className="h-8 rounded-full bg-muted/20 border-border/70 text-xs flex-1">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value={GEMINI_DEFAULT_URL}>Gemini mặc định</SelectItem>
                            {availableGems.map(gem => (
                              <SelectItem key={gem.url} value={gem.url}>{gem.name}</SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="size-8 hover:bg-muted/40 rounded-full border border-border/70 bg-muted/20 shrink-0"
                          onClick={handleRefreshSession}
                          disabled={sessionRefreshing}
                        >
                          <RefreshCw className={cn("size-3", sessionRefreshing && "animate-spin")} />
                        </Button>
                      </div>
                    </Field>

                    <FieldGroup className="gap-4 pt-1">
                      <Field>
                        <TooltipFieldLabel tooltip="Chọn model Gemini để tối ưu hóa giữa tốc độ và chất lượng.">Model</TooltipFieldLabel>
                        <Select value={settingsDraft.gemini_model || "flash"} onValueChange={v => handleSaveSettings({ gemini_model: v })}>
                          <SelectTrigger className="w-full h-8 text-xs"><SelectValue /></SelectTrigger>
                          <SelectContent>
                            <SelectItem value="flash"><div className="flex items-center gap-2"><Zap className="size-3.5 text-yellow-500" /><span>Nhanh (Flash)</span></div></SelectItem>
                            <SelectItem value="thinking"><div className="flex items-center gap-2"><Brain className="size-3.5 text-blue-500" /><span>Tư duy (Thinking)</span></div></SelectItem>
                            <SelectItem value="pro"><div className="flex items-center gap-2"><Sparkles className="size-3.5 text-purple-500" /><span>Mạnh mẽ (Pro)</span></div></SelectItem>
                          </SelectContent>
                        </Select>
                      </Field>

                      <Field>
                        <div className="flex items-center justify-between gap-4 rounded-full border border-border/70 px-3 h-8 bg-muted/20">
                          <TooltipFieldLabel
                            tooltip="Nếu bật, trình duyệt sẽ chạy ngầm. Nếu tắt, bạn có thể xem quá trình xử lý trực tiếp trên Gemini."
                            className="text-muted-foreground font-medium"
                          >
                            Chạy nền (headless)
                          </TooltipFieldLabel>
                          <Switch
                            checked={settingsDraft.gemini_headless}
                            onCheckedChange={(val) => handleSaveSettings({ gemini_headless: val })}
                            className="scale-75 origin-right"
                          />
                        </div>
                      </Field>

                      <Field>
                        <TooltipFieldLabel tooltip="Số lượng video được xử lý đồng thời để tăng tốc độ.">Số luồng</TooltipFieldLabel>
                        <Input type="number" min="1" max="10" value={settingsDraft.max_parallel_videos} onChange={(e: React.ChangeEvent<HTMLInputElement>) => handleSaveSettings({ max_parallel_videos: parseInt(e.target.value) || 1 })} className="h-8 text-xs" />
                      </Field>
                    </FieldGroup>
                  </FieldGroup>
                )}
              </TabsContent>

              <TabsContent value="prompt" className="flex-1 space-y-6">
                <div className="space-y-3">
                  <div className="flex items-center gap-2"><Badge variant="outline">Global</Badge><span className="text-xs font-bold uppercase text-muted-foreground">Prompt tổng</span></div>
                  <Textarea value={globalPromptDraft} onChange={e => setGlobalPromptDraft(e.target.value)} className="min-h-[100px] text-xs" placeholder="Prompt áp dụng cho mọi video..." />
                  <Button variant="outline" size="sm" className="w-full text-xs" onClick={handleSaveGlobalPrompt} disabled={savingPrompt || globalPromptDraft === globalPrompt}>Lưu prompt tổng</Button>
                </div>

                <div className="space-y-3 pt-2">
                  <div className="flex items-center gap-2"><FileText className="size-4 text-emerald-500" /><span className="text-xs font-bold uppercase text-muted-foreground">Prompt video</span></div>
                  <Textarea value={videoPromptDraft} onChange={e => setVideoPromptDraft(e.target.value)} className="min-h-[150px] text-xs" placeholder="Prompt riêng cho video đã chọn..." disabled={!selectedVideo} />
                  <Button variant="outline" size="sm" className="w-full text-xs bg-emerald-500/5 hover:bg-emerald-500/10 text-emerald-600 border-emerald-500/20" onClick={handleSaveVideoPrompt} disabled={!selectedVideo || savingVideoPrompt || videoPromptDraft === (selectedVideo?.videoPrompt || "")}>Lưu prompt video</Button>
                </div>
              </TabsContent>
            </Tabs>
          </CardContent>
        </Card>
      </aside>

      {/* -------------------- MAIN PANEL -------------------- */}
      <Card className={cn("flex flex-col border-border/70 shadow-[0_24px_90px_rgba(15,23,42,0.08)]", TAB_VIEWPORT_CARD_HEIGHT_CLASS, "lg:overflow-hidden")}>
        <div className="flex items-center justify-end px-4 pt-0 pb-2 flex-none">
          <Tabs value={mainPanelTab} onValueChange={v => setMainPanelTab(v as any)}>
            <TabsList className="h-8 bg-muted/20 p-0.5 border border-border/40">
              <TabsTrigger value="videos" className="h-7 px-3 text-[11px] font-medium uppercase tracking-wider">Tiến trình</TabsTrigger>
              <TabsTrigger value="collection" className="h-7 px-3 text-[11px] font-medium uppercase tracking-wider">Bộ sưu tập</TabsTrigger>
              <TabsTrigger value="history" className="h-7 px-3 text-[11px] font-medium uppercase tracking-wider">Lịch sử</TabsTrigger>
            </TabsList>
          </Tabs>
        </div>

        <CardContent className="flex-1 flex flex-col min-h-0 gap-4 p-4 pt-2 overflow-hidden">
          <Tabs value={mainPanelTab} className="flex-1 flex flex-col min-h-0">
            <TabsContent value="videos" className="flex-1 flex flex-col gap-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Badge variant="secondary">{videoSummaries.length} video</Badge>
              <Select value={queueFilter} onValueChange={v => setQueueFilter(v as any)}>
                <SelectTrigger className="h-8 text-xs px-2 w-[110px] rounded-lg bg-muted/20 border-border/70">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">Tất cả ({queueCounts.all})</SelectItem>
                  <SelectItem value="running">Đang chạy ({queueCounts.running})</SelectItem>
                  <SelectItem value="review">Chờ duyệt ({queueCounts.review})</SelectItem>
                </SelectContent>
              </Select>
            </div>
            
            <div className="flex items-center gap-1.5">
                <div className="flex items-center gap-2">
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-8 gap-2 rounded-full border border-border/40 hover:bg-muted/50 text-destructive/80 hover:text-destructive"
                    onClick={handleClearVideos}
                    disabled={videoSummaries.length === 0}
                  >
                    <Trash2 className="size-3" />
                    Xóa tất cả
                  </Button>
                  <Button variant="ghost" size="sm" className="h-8 gap-2 rounded-full border border-border/40 hover:bg-muted/50" onClick={() => void refreshSummaries()}>
                    <RefreshCw className={cn("size-3", actionBusyKey === "workspace:refresh" && "animate-spin")} />
                    Làm mới
                  </Button>
                </div>
              <div className="h-4 w-px bg-border mx-1" />
              <Button variant="secondary" size="sm" className="h-8 text-xs rounded-full" onClick={() => handleGlobalControl("run")} disabled={globalQueueCounts.queued === 0}><Play className="size-3 mr-1" /> Chạy hết</Button>
              <Button variant="outline" size="sm" className="h-8 text-xs rounded-full" onClick={() => handleGlobalControl("pause")} disabled={globalQueueCounts.running === 0}><Pause className="size-3 mr-1" /> Tạm dừng</Button>
              <Button variant="outline" size="sm" className="h-8 text-xs rounded-full" onClick={() => handleGlobalControl("resume")} disabled={globalQueueCounts.paused === 0}><RotateCcw className="size-3 mr-1" /> Tiếp tục</Button>
              <Button variant="destructive" size="sm" className="h-8 text-xs rounded-full" onClick={() => handleGlobalControl("cancel")} disabled={globalQueueCounts.stoppable === 0}><X className="size-3 mr-1" /> Dừng hết</Button>
            </div>
          </div>

          <div className="grid grid-cols-[16rem_1fr] gap-4 flex-1 min-h-0 overflow-hidden">
            <Card className="flex flex-col overflow-hidden border-border/70 shadow-sm">
              <CardContent className="p-2 space-y-1.5 overflow-y-auto">
                {filteredVideoSummaries.map(v => (
                  <Button
                    key={v.id}
                    variant="ghost"
                    onClick={() => { setSelectedVideoId(v.id); loadVideoDetail(v.id); }}
                    className={cn(
                      "w-full justify-start h-16 p-2 border border-transparent transition-all",
                      selectedVideoId === v.id
                        ? "bg-primary/10 border-primary/20 text-foreground"
                        : "hover:bg-muted text-muted-foreground hover:text-foreground"
                    )}
                  >
                    <div className="flex items-center w-full gap-3 min-w-0">
                      <div className="size-12 shrink-0 rounded-lg overflow-hidden bg-muted border border-border/40">
                        {v.previewPath ? (
                          <VideoThumb path={v.previewPath} className="w-full h-full" />
                        ) : (
                          <div className="w-full h-full flex items-center justify-center bg-muted/50">
                            <VideoIcon className="size-4 opacity-20" />
                          </div>
                        )}
                      </div>
                      <div className="flex flex-col flex-1 gap-1.5 min-w-0">
                        <div className="flex justify-between items-center w-full min-w-0">
                          <span className="font-bold text-[11px] truncate uppercase tracking-tight pr-2">
                            {v.name || v.id}
                          </span>
                          <div className={cn(
                            "shrink-0 size-1.5 rounded-full shadow-[0_0_5px_rgba(0,0,0,0.1)]",
                            v.status === "completed" ? "bg-emerald-500 shadow-emerald-500/30" :
                            v.status === "failed" ? "bg-destructive shadow-destructive/30" :
                            v.status === "running" ? "bg-primary animate-pulse" :
                            "bg-muted-foreground/30"
                          )} />
                        </div>
                        <div className="h-1 w-full bg-muted/40 rounded-full overflow-hidden">
                          <div
                            className="h-full bg-primary/60 transition-all duration-500"
                            style={{ width: `${progressPercent(v)}%` }}
                          />
                        </div>
                      </div>
                    </div>
                  </Button>
                ))}
                {videoSummaries.length === 0 && !actionBusyKey && (
                  <div className="py-8 text-center text-xs text-muted-foreground italic">Trống.</div>
                )}
              </CardContent>
            </Card>

            <Card className="flex flex-col overflow-hidden relative border-border/70 shadow-sm">
              {detailLoading || actionBusyKey === "workspace:refresh" ? <div className="absolute inset-0 flex items-center justify-center bg-background/50 z-20"><Loader2 className="size-6 animate-spin" /></div> : null}
              {selectedVideo ? (
                <>
                  <CardHeader className="py-3 px-4 border-b bg-muted/5 flex-row items-center justify-between flex-none">
                    <div><CardTitle className="text-sm font-bold">{selectedVideo.name || selectedVideo.id}</CardTitle><CardDescription className="text-xs">{selectedVideo.completedSteps}/{selectedVideo.stepTotal} bước hoàn thành</CardDescription></div>
                    <div className="flex gap-2">
                      <Button variant="outline" size="sm" className="h-8 text-xs" onClick={() => handleLocalAction("pause", selectedVideo.id)} disabled={selectedVideo.status.toLowerCase() === "paused"}><Pause className="size-3 mr-1" /> Tạm dừng</Button>
                      <Button variant="outline" size="sm" className="h-8 text-xs" onClick={() => handleLocalAction("run", selectedVideo.id)} disabled={selectedVideo.status.toLowerCase() === "running"}><Play className="size-3 mr-1" /> Chạy</Button>
                    </div>
                  </CardHeader>
                  <CardContent className="flex-1 p-0 flex overflow-hidden">
                    <ScrollArea className="w-[220px] border-r bg-muted/5">
                      <div className="p-3 space-y-3">
                        {selectedVideo.markers.map((m: any) => (
                          <div key={m.id} className="space-y-1">
                            <button onClick={() => setExpandedMarkerIds(curr => curr.includes(m.id) ? curr.filter(id => id !== m.id) : [...curr, m.id])} className={cn("w-full flex items-center justify-between p-1.5 rounded hover:bg-muted text-[11px] font-bold uppercase text-muted-foreground", selectedMarkerId === m.id && "text-foreground")}>
                              <span className="truncate">Marker {m.index}</span>
                              {expandedMarkerIds.includes(m.id) ? <ChevronDown className="size-3" /> : <ChevronRight className="size-3" />}
                            </button>
                            {expandedMarkerIds.includes(m.id) && m.steps.map((s: any) => (
                              <button key={s.id} onClick={() => { setSelectedMarkerId(m.id); setSelectedStepId(s.id); setSelectedAttemptId(s.attempts.at(-1)?.id || null); }} className={cn("w-full text-left pl-6 pr-2 py-1 text-[11px] rounded hover:text-primary", selectedStepId === s.id ? "text-primary font-bold" : "text-muted-foreground")}>
                                Bước {s.index} ({storyStatusLabel(s.status)})
                              </button>
                            ))}
                          </div>
                        ))}
                      </div>
                    </ScrollArea>
                    <div className="flex-1 flex flex-col p-4 space-y-4 overflow-y-auto">
                      {selectedStep ? (
                        <>
                          <div className="flex items-center justify-between">
                            <div className="flex items-center gap-2">
                              <Layers className="size-4 text-muted-foreground" />
                              <span className="text-[11px] font-bold uppercase text-muted-foreground">Biến thể:</span>
                              <div className="flex gap-1">
                                {selectedStep.attempts.map((a, i) => (
                                  <Button key={a.id} variant={selectedAttemptId === a.id ? "default" : "outline"} size="sm" className="size-7 p-0 text-[10px]" onClick={() => setSelectedAttemptId(a.id)}>
                                    {i + 1}
                                  </Button>
                                ))}
                              </div>
                            </div>
                            {currentAttempt?.mode === "refine" && <Badge variant="outline" className="bg-indigo-50 text-indigo-600 border-indigo-200 text-[10px]">Đã tinh chỉnh</Badge>}
                          </div>

                          <div className="grid grid-cols-2 gap-4">
                            <div className="space-y-1.5"><label className="text-[10px] font-bold uppercase text-muted-foreground">Gốc</label><div className="aspect-video bg-muted rounded-lg overflow-hidden border relative group">{selectedMarker?.inputFramePath && <VideoThumb path={selectedMarker.inputFramePath} className="cursor-zoom-in" onClick={() => setPreviewDialogPath(selectedMarker.inputFramePath)} />}<div className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity"><Button size="icon" variant="secondary" className="size-7 rounded-full shadow-lg" onClick={() => setPreviewDialogPath(selectedMarker?.inputFramePath || null)}><Maximize2 className="size-3.5" /></Button></div></div></div>
                            <div className="space-y-1.5"><label className="text-[10px] font-bold uppercase text-muted-foreground">Kết quả ({currentAttempt?.mode || "gen"})</label><div className="aspect-video bg-muted rounded-lg overflow-hidden border relative group">{currentAttempt?.previewPath && <VideoThumb path={currentAttempt.previewPath} className="cursor-zoom-in" onClick={() => setPreviewDialogPath(currentAttempt?.previewPath || null)} />}<div className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity"><Button size="icon" variant="secondary" className="size-7 rounded-full shadow-lg" onClick={() => setPreviewDialogPath(currentAttempt?.previewPath || null)}><Maximize2 className="size-3.5" /></Button></div></div></div>
                          </div>
                          
                          {showRefinePrompt && (
                            <div className="p-4 rounded-xl bg-muted/30 border border-border/50 space-y-3 animate-in slide-in-from-top-2">
                              <div className="flex items-center gap-2 mb-1">
                                <Sparkles className="size-3.5 text-primary" />
                                <label className="text-[11px] font-bold uppercase tracking-wider text-foreground">Tinh chỉnh kết quả</label>
                              </div>
                              <Textarea 
                                value={refinePromptDraft} 
                                onChange={e => setRefinePromptDraft(e.target.value)} 
                                placeholder="Nhập yêu cầu thay đổi (ví dụ: làm màu rực rỡ hơn, thêm ánh nắng...)" 
                                className="text-xs min-h-[80px] bg-background/50 border-border/50 focus:ring-primary/20" 
                              />
                              <div className="flex justify-end gap-2">
                                <Button variant="ghost" size="sm" className="text-[11px] h-8 font-bold uppercase" onClick={() => setShowRefinePrompt(false)}>Huỷ</Button>
                                <Button size="sm" className="h-8 text-[11px] font-bold uppercase px-4 bg-primary hover:bg-primary/90" onClick={handleRefineSelectedStep}>Gửi yêu cầu</Button>
                              </div>
                            </div>
                          )}

                          {(selectedStep?.status === "review" || selectedStep?.status === "failed" || selectedStep?.status === "completed") && (
                            <div className="p-3 rounded-xl bg-card border border-border shadow-sm flex items-center justify-between animate-in fade-in slide-in-from-bottom-2 duration-300">
                              <div className="flex items-center gap-2">
                                <div className="size-2 rounded-full bg-emerald-500 animate-pulse" />
                                <span className="text-[11px] font-bold uppercase tracking-wider text-foreground">Duyệt kết quả này?</span>
                              </div>
                              <div className="flex gap-1.5">
                                <Button size="sm" className="h-8 text-[11px] px-4 font-bold uppercase tracking-wide bg-emerald-600 hover:bg-emerald-500 text-white" onClick={handleAcceptAndNext}>Duyệt</Button>
                                <Button size="sm" variant="outline" className="h-8 text-[11px] font-bold uppercase tracking-wide border-border/70 hover:bg-muted/50" onClick={() => runStepAction("regenerate", selectedMarkerId!, selectedStepId!)}>Tạo lại</Button>
                                <Button size="sm" variant="outline" className="h-8 text-[11px] font-bold uppercase tracking-wide border-border/70 hover:bg-muted/50" onClick={() => {
                                  setRefinePromptDraft(selectedStep?.modifierPrompt || "");
                                  setShowRefinePrompt(true);
                                }}>Tinh chỉnh</Button>
                              </div>
                            </div>
                          )}
                          <div className="space-y-1.5"><label className="text-[10px] font-bold uppercase text-muted-foreground">Log chi tiết</label><div className="p-3 bg-muted/30 rounded border font-mono text-[10px] min-h-[60px] whitespace-pre-wrap leading-relaxed">{currentAttempt?.error || "Không có nhật ký cho biến thể này."}</div></div>
                        </>
                      ) : <div className="flex-1 flex items-center justify-center text-muted-foreground text-sm italic">Chọn một bước để xem kết quả</div>}
                    </div>
                  </CardContent>
                </>
              ) : <div className="flex-1 flex items-center justify-center text-muted-foreground text-sm italic">Chọn video để bắt đầu làm việc</div>}
            </Card>
          </div>
        </TabsContent>

        <TabsContent value="collection" className="flex-1 min-h-0 flex flex-col gap-4">
          <div className="flex items-center justify-between px-1">
            <div className="flex items-center gap-3">
              <Badge variant="outline" className="h-6">{selectedExportKeys.size} / {allAcceptedSteps.length} đã chọn</Badge>
              {allAcceptedSteps.length > 0 && (
                <Button 
                  variant="ghost" 
                  size="sm" 
                  className="h-7 text-[10px] font-bold uppercase tracking-wider px-2 hover:bg-muted/50"
                  onClick={() => setSelectedExportKeys(prev => prev.size === allAcceptedSteps.length ? new Set() : new Set(allAcceptedSteps.map(s => s.key)))}
                >
                  {selectedExportKeys.size === allAcceptedSteps.length ? "Bỏ chọn hết" : "Chọn tất cả"}
                </Button>
              )}
            </div>
            <Button 
              size="sm" 
              className="h-8 gap-2 bg-emerald-600 hover:bg-emerald-500 text-white font-bold uppercase text-[11px] px-4 shadow-sm"
              disabled={selectedExportKeys.size === 0 || exportingCollection}
              onClick={handleExportCollection}
            >
              {exportingCollection ? <Loader2 className="size-3.5 animate-spin" /> : <Play className="size-3.5" />}
              Xuất ảnh ({selectedExportKeys.size})
            </Button>
          </div>

          <div className="flex-1 overflow-y-auto pr-1">
            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4 p-1">
             {allAcceptedSteps.map(s => (
               <Card 
                 key={s.key} 
                 className={cn(
                   "overflow-hidden transition-all cursor-pointer shadow-sm relative group",
                   selectedExportKeys.has(s.key) ? "ring-2 ring-primary bg-primary/5" : "hover:ring-2 ring-primary/50"
                 )}
                 onClick={() => handleToggleExportSelection(s.key)}
               >
                 <div className="absolute top-2 right-2 z-10">
                    <div className={cn(
                      "size-5 rounded-full border-2 flex items-center justify-center transition-all",
                      selectedExportKeys.has(s.key) ? "bg-primary border-primary text-primary-foreground" : "bg-black/20 border-white/50 group-hover:border-white"
                    )}>
                      {selectedExportKeys.has(s.key) && <ChevronRight className="size-3.5 rotate-90" />}
                    </div>
                 </div>
                 
                 <div className="aspect-video bg-muted relative">
                    <VideoThumb path={s.previewPath} className="w-full h-full" />
                    <div className="absolute top-2 left-2">
                       <Badge className="bg-emerald-500 text-[9px] px-2 h-4 uppercase font-bold tracking-wider">Duyệt</Badge>
                    </div>
                 </div>
                 <CardContent className="p-2.5">
                   <div className="text-[10px] font-bold text-muted-foreground truncate mb-0.5">{s.videoName}</div>
                   <div className="text-[11px] font-medium truncate">Cảnh {s.markerIndex} - {s.stepTitle}</div>
                 </CardContent>
               </Card>
             ))}
             {allAcceptedSteps.length === 0 && (
               <div className="col-span-full py-20 text-center text-muted-foreground text-sm border-2 border-dashed rounded-2xl bg-muted/5">Chưa có ảnh nào được duyệt. Hãy bấm Duyệt ở các bước xử lý để đưa ảnh vào đây.</div>
             )}
           </div>
        </div>
      </TabsContent>

        <TabsContent value="history" className="flex-1 min-h-0 overflow-y-auto">
           <Card className="border-border/70 shadow-sm overflow-hidden">
             <CardHeader className="py-3 px-4 border-b bg-muted/5">
                <div className="flex items-center gap-2 text-muted-foreground">
                  <HistoryIcon className="size-4" />
                  <span className="text-xs font-bold uppercase tracking-wider">Lịch sử tiến trình</span>
                </div>
             </CardHeader>
             <CardContent className="p-0">
               <div className="divide-y">
                 {videoSummaries.map(v => (
                    <div key={v.id} className="p-4 hover:bg-muted/30 cursor-pointer transition-colors" onClick={() => { setMainPanelTab("videos"); setSelectedVideoId(v.id); loadVideoDetail(v.id); }}>
                      <div className="flex items-center justify-between mb-2">
                        <span className="text-sm font-bold">{v.name || v.id}</span>
                        <Badge variant={storyStatusTone(v.status).variant} className="text-[9px] px-2 h-4 uppercase">{storyStatusLabel(v.status)}</Badge>
                      </div>
                      <div className="flex items-center gap-6 text-[10px] text-muted-foreground font-medium uppercase tracking-wide">
                        <span className="flex items-center gap-1.5"><div className="size-1 rounded-full bg-primary" /> Tiến độ: {progressPercent(v)}%</span>
                        <span>Hoàn thành: {v.completedSteps}/{v.stepTotal}</span>
                        {v.reviewSteps > 0 && <span className="text-amber-600 font-bold">Chờ duyệt: {v.reviewSteps}</span>}
                      </div>
                    </div>
                 ))}
               </div>
             </CardContent>
           </Card>
            </TabsContent>
          </Tabs>
        </CardContent>
      </Card>

      <Dialog open={!!previewDialogPath} onOpenChange={v => !v && setPreviewDialogPath(null)}>
        <DialogContent className="max-w-[90vw] max-h-[90vh] p-0 border-0 bg-black/40 backdrop-blur-sm flex items-center justify-center">
          {previewDialogPath && <img src={getStoryAssetUrl(previewDialogPath)} alt="Preview Large" className="max-w-full max-h-full object-contain rounded-xl shadow-[0_0_50px_rgba(0,0,0,0.5)] border border-white/10" />}
        </DialogContent>
      </Dialog>
    </div>
  );
}

export default StoryStudio;
