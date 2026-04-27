import { startTransition, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import {
  Loader2,
  Pause,
  Play,
  RefreshCw,
  RotateCcw,
  Plus,
  X,
  FolderOpen,
  FileVideo,
  Image as ImageIcon,
  Video as VideoIcon,
  MessageSquare,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogTitle, AlertDialogTrigger } from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Switch } from "@/components/ui/switch";
import { ScrollArea } from "@/components/ui/scroll-area";
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
import { Textarea } from "@/components/ui/textarea";
import { TooltipFieldLabel } from "@/components/ui/tooltip-field-label";
import {
  TAB_CARD_GAP_CLASS,
} from "@/lib/layout";
import { cn } from "@/lib/utils";
import {
  applyStoryAction,
  getStoryAssetUrl,
  getStoryBootstrap,
  getStorySessionStatus,
  getStoryVideo,
  chooseFolder,
  listStoryGems,
  listStoryVideos,
  cancelStoryVideo,
  scanStoryFolder,
  openFolder,
  openStoryLogin,
  pauseStoryVideo,
  runStoryVideo,
  updateStoryGlobalPrompt,
  updateStorySettings,
  type StoryMarker,
  type StorySessionStatus,
  type StorySettings,
  type StoryStep,
  type StoryVideoDetail,
  type StoryVideoSummary,
} from "@/lib/api";

type StoryActionType = "accept" | "regenerate" | "refine" | "skip";

type StepSelection = {
  markerId: string;
  stepId: string;
  attemptId: string | null;
};

type QueueFilter = "all" | "running" | "review" | "queued";
type GemOption = { name: string; url: string };



const STORY_SSE_EVENTS = [
  "connected",
  "story.video.created",
  "story.video.updated",
  "story.step.updated",
  "story.settings.updated",
  "story.global_prompt.updated",
];
const GEMINI_DEFAULT_URL = "https://gemini.google.com/app";

function getErrorMessage(error: unknown) {
  if (error instanceof Error) {
    return error.message;
  }
  return "Yêu cầu thất bại.";
}

function hasGemOption(gems: GemOption[], url: string) {
  const normalizedUrl = url.trim();
  return normalizedUrl === GEMINI_DEFAULT_URL || gems.some((gem) => gem.url === normalizedUrl);
}

function sanitizeGeminiSettings(settings: StorySettings, gems: GemOption[]) {
  if (!settings.gemini_base_url || hasGemOption(gems, settings.gemini_base_url)) {
    return settings;
  }
  return {
    ...settings,
    gemini_base_url: GEMINI_DEFAULT_URL,
  };
}

function storyStatusLabel(status: string) {
  switch (status) {
    case "all":
      return "Tất cả";
    case "queued":
      return "Chờ";
    case "running":
      return "Chạy";
    case "review":
      return "Duyệt";
    case "completed":
      return "Xong";
    case "paused":
      return "Tạm dừng";
    case "failed":
      return "Lỗi";
    default:
      return status.toUpperCase();
  }
}

function storyActionLabel(action: StoryActionType) {
  switch (action) {
    case "accept":
      return "duyệt";
    case "regenerate":
      return "tạo lại";
    case "refine":
      return "tinh chỉnh";
    case "skip":
      return "bỏ qua";
    default:
      return action;
  }
}

function storyStatusTone(status: string): { variant: "default" | "secondary" | "destructive" | "outline"; className: string } {
  if (status === "running") {
    return {
      variant: "outline",
      className: "border-emerald-400/40 bg-emerald-500/12 text-emerald-100",
    };
  }
  if (status === "queued") {
    return {
      variant: "outline",
      className: "border-indigo-400/40 bg-indigo-500/12 text-indigo-100",
    };
  }
  if (status === "review") {
    return {
      variant: "outline",
      className: "border-amber-300/45 bg-amber-500/14 text-amber-50",
    };
  }
  if (status === "completed") {
    return {
      variant: "outline",
      className: "border-slate-300/30 bg-slate-400/12 text-slate-200",
    };
  }
  if (status === "failed") {
    return {
      variant: "destructive",
      className: "",
    };
  }
  return {
    variant: "outline",
    className: "",
  };
}

function progressPercent(summary: StoryVideoSummary) {
  if (summary.stepTotal <= 0) {
    return 0;
  }
  return Math.round((summary.completedSteps / summary.stepTotal) * 100);
}


function orderedMarkers(markers: StoryMarker[]) {
  return [...markers].sort((a, b) => a.index - b.index);
}

function composeMergedPrompt(
  globalPrompt: string,
  videoPrompt: string,
  markerSeed: string,
  stepPrompt: string,
) {
  return [globalPrompt, videoPrompt, markerSeed, stepPrompt]
    .map((part) => part.trim())
    .filter(Boolean)
    .join("\n\n");
}

function orderedSteps(steps: StoryStep[]) {
  return [...steps].sort((a, b) => a.index - b.index);
}

function findMarker(video: StoryVideoDetail, markerId: string) {
  return video.markers.find((marker) => marker.id === markerId) ?? null;
}

function findStep(marker: StoryMarker, stepId: string) {
  return marker.steps.find((step) => step.id === stepId) ?? null;
}


function extractVideoThumbnail(video: StoryVideoDetail) {
  for (const marker of orderedMarkers(video.markers)) {
    for (const step of orderedSteps(marker.steps)) {
      const lastAttempt = step.attempts.at(-1);
      if (lastAttempt?.previewPath) {
        return lastAttempt.previewPath;
      }
      if (lastAttempt?.normalizedPath) {
        return lastAttempt.normalizedPath;
      }
    }
    if (marker.inputFramePath) {
      return marker.inputFramePath;
    }
  }
  return "";
}

function selectStep(video: StoryVideoDetail, preferred?: Partial<StepSelection>): StepSelection | null {
  const markers = orderedMarkers(video.markers);
  if (markers.length === 0) {
    return null;
  }

  if (preferred?.markerId && preferred.stepId) {
    const marker = findMarker(video, preferred.markerId);
    if (marker) {
      const step = findStep(marker, preferred.stepId);
      if (step) {
        const attemptId =
          preferred.attemptId && step.attempts.some((attempt) => attempt.id === preferred.attemptId)
            ? preferred.attemptId
            : (step.selectedAttemptId ?? step.attempts.at(-1)?.id ?? null);
        return {
          markerId: marker.id,
          stepId: step.id,
          attemptId,
        };
      }
    }
  }

  const statusPriority = ["review", "running", "queued", "failed", "completed", "skipped"];
  for (const status of statusPriority) {
    for (const marker of markers) {
      for (const step of orderedSteps(marker.steps)) {
        if (step.status !== status) {
          continue;
        }
        return {
          markerId: marker.id,
          stepId: step.id,
          attemptId: step.selectedAttemptId ?? step.attempts.at(-1)?.id ?? null,
        };
      }
    }
  }

  const firstMarker = markers[0];
  const firstStep = orderedSteps(firstMarker.steps)[0];
  if (!firstStep) {
    return null;
  }
  return {
    markerId: firstMarker.id,
    stepId: firstStep.id,
    attemptId: firstStep.selectedAttemptId ?? firstStep.attempts.at(-1)?.id ?? null,
  };
}

function findNextStep(video: StoryVideoDetail, currentMarkerId: string, currentStepId: string) {
  const sequence: Array<{ markerId: string; stepId: string }> = [];
  for (const marker of orderedMarkers(video.markers)) {
    for (const step of orderedSteps(marker.steps)) {
      sequence.push({ markerId: marker.id, stepId: step.id });
    }
  }
  const index = sequence.findIndex(
    (item) => item.markerId === currentMarkerId && item.stepId === currentStepId,
  );
  if (index === -1 || index + 1 >= sequence.length) {
    return null;
  }
  return sequence[index + 1];
}

function selectionKey(action: StoryActionType, markerId: string, stepId: string) {
  return `${action}:${markerId}:${stepId}`;
}

function VideoThumb({
  path,
  alt,
  className,
}: {
  path: string | null | undefined;
  alt: string;
  className?: string;
}) {
  if (!path) {
    return (
      <div className={cn("flex items-center justify-center rounded-md border border-border/70 bg-muted/35 text-xs text-muted-foreground", className)}>
        không có xem trước
      </div>
    );
  }
  return (
    <img
      src={getStoryAssetUrl(path)}
      alt={alt}
      className={cn("rounded-md border border-border/70 object-cover", className)}
      loading="lazy"
    />
  );
}

export default function StoryStudio() {
  const [bootLoading, setBootLoading] = useState(true);


  const [settingsDraft, setSettingsDraft] = useState<StorySettings | null>(null);
  const [globalPrompt, setGlobalPrompt] = useState("");
  const [globalPromptDraft, setGlobalPromptDraft] = useState("");
  const [sessionStatus, setSessionStatus] = useState<StorySessionStatus | null>(null);

  const [videoSummaries, setVideoSummaries] = useState<StoryVideoSummary[]>([]);
  const [activeVideoId, setActiveVideoId] = useState<string | null>(null);
  const [selectedVideoId, setSelectedVideoId] = useState<string | null>(null);
  const [selectedVideo, setSelectedVideo] = useState<StoryVideoDetail | null>(null);

  const [selectedMarkerId, setSelectedMarkerId] = useState<string | null>(null);
  const [selectedStepId, setSelectedStepId] = useState<string | null>(null);
  const [selectedAttemptId, setSelectedAttemptId] = useState<string | null>(null);
  const [expandedMarkerIds, setExpandedMarkerIds] = useState<string[]>([]);

  const [savingPrompt, setSavingPrompt] = useState(false);
  const [, setSavingSettings] = useState(false);
  const [choosingOutputFolder, setChoosingOutputFolder] = useState(false);
  const [sourceFolderPath, setSourceFolderPath] = useState("");
  const [choosingSourceFolder, setChoosingSourceFolder] = useState(false);
  const [importingSourceFolder, setImportingSourceFolder] = useState(false);
  const [sessionRefreshing, setSessionRefreshing] = useState(false);
  const [availableGems, setAvailableGems] = useState<GemOption[]>([]);
  const [fetchingGems, setFetchingGems] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [actionBusyKey, setActionBusyKey] = useState<string | null>(null);
  const [queueFilter, setQueueFilter] = useState<QueueFilter>("all");
  const [leftPanelTab, setLeftPanelTab] = useState<"gemini" | "prompt">("prompt");
  const [mainPanelTab, setMainPanelTab] = useState<"videos" | "collection" | "history" | "workers">("videos");


  const [videoThumbs, setVideoThumbs] = useState<Record<string, string>>({});
  const thumbInflightRef = useRef<Set<string>>(new Set());
  const lastStoryEventIdRef = useRef(0);
  const sseRefreshTimerRef = useRef<number | null>(null);
  const lastSavedSettingsRef = useRef<string | null>(null);
  const lastFailedSettingsRef = useRef<string | null>(null);

  const applyVideoDetail = useCallback(
    (video: StoryVideoDetail, options?: { preferred?: Partial<StepSelection> }) => {
      const selection = selectStep(video, options?.preferred);
      const thumbnail = extractVideoThumbnail(video);

      startTransition(() => {
        setSelectedVideo(video);
        setSelectedVideoId(video.id);
        setActiveVideoId(video.id);
        setVideoSummaries((current) => {
          const next = current.map((summary) =>
            summary.id === video.id
              ? {
                  ...summary,
                  status: video.status,
                  mode: video.mode,
                  markerCount: video.markerCount,
                  stepTotal: video.stepTotal,
                  completedSteps: video.completedSteps,
                  reviewSteps: video.reviewSteps,
                  error: video.error,
                  lastUpdatedAt: video.lastUpdatedAt,
                }
              : summary,
          );
          if (next.some((summary) => summary.id === video.id)) {
            return next;
          }
          return [video, ...next];
        });
        if (thumbnail) {
          setVideoThumbs((current) => ({ ...current, [video.id]: thumbnail }));
        }
        if (selection) {
          setSelectedMarkerId(selection.markerId);
          setSelectedStepId(selection.stepId);
          setSelectedAttemptId(selection.attemptId);
        } else {
          setSelectedMarkerId(null);
          setSelectedStepId(null);
          setSelectedAttemptId(null);
        }
        setExpandedMarkerIds((current) => {
          const merged = new Set(current);
          if (selection) {
            merged.add(selection.markerId);
          }
          for (const marker of video.markers) {
            if (marker.status === "running" || marker.status === "review") {
              merged.add(marker.id);
            }
          }
          return Array.from(merged);
        });
      });
    },
    [],
  );

  const loadVideoDetail = useCallback(
    async (videoId: string, options?: { silent?: boolean; preferred?: Partial<StepSelection> }) => {
      const silent = options?.silent ?? false;
      if (!silent) {
        setDetailLoading(true);
      }
      try {
        const detail = await getStoryVideo(videoId);
        applyVideoDetail(detail, { preferred: options?.preferred });
      } catch (error) {
        if (!silent) {
          toast.error(getErrorMessage(error));
        }
      } finally {
        if (!silent) {
          setDetailLoading(false);
        }
      }
    },
    [applyVideoDetail],
  );

  const bootstrap = useCallback(async () => {
    setBootLoading(true);
    try {
      const payload = await getStoryBootstrap();
      lastSavedSettingsRef.current = JSON.stringify(payload.settings);
      lastFailedSettingsRef.current = null;
      const initialVideoId = payload.activeVideoId ?? payload.videoSummaries[0]?.id ?? null;
      startTransition(() => {
        setSettingsDraft(payload.settings);
        setGlobalPrompt(payload.globalPrompt);
        setGlobalPromptDraft(payload.globalPrompt);
        setVideoSummaries(payload.videoSummaries);
        setActiveVideoId(payload.activeVideoId);
        setSessionStatus(payload.sessionStatus);
      });
      if (initialVideoId) {
        await loadVideoDetail(initialVideoId, { silent: true });
      }
      
      // Auto-refresh session status if it's currently checking or not ready
      if (payload.sessionStatus && !payload.sessionStatus.dependencies_ready) {
        void getStorySessionStatus(true).then((status) => {
          startTransition(() => {
            setSessionStatus(status);
          });
        }).catch(console.error);
      }
    } catch (error) {
      console.error(getErrorMessage(error));
    } finally {
      setBootLoading(false);
    }
  }, [loadVideoDetail]);

  const refreshSummaries = useCallback(
    async (silent = true) => {
      try {
        const summaries = await listStoryVideos();
        startTransition(() => setVideoSummaries(summaries));

        const targetId = selectedVideoId ?? activeVideoId ?? summaries[0]?.id ?? null;
        if (!targetId) {
          startTransition(() => {
            setSelectedVideo(null);
            setSelectedVideoId(null);
            setSelectedMarkerId(null);
            setSelectedStepId(null);
            setSelectedAttemptId(null);
          });
          return;
        }

        const summary = summaries.find((item) => item.id === targetId);
        if (!summary) {
          const fallbackId = summaries[0]?.id ?? null;
          if (fallbackId) {
            await loadVideoDetail(fallbackId, { silent: true });
          } else {
            startTransition(() => {
              setSelectedVideo(null);
              setSelectedVideoId(null);
              setSelectedMarkerId(null);
              setSelectedStepId(null);
              setSelectedAttemptId(null);
            });
          }
          return;
        }

        if (
          !selectedVideo ||
          selectedVideo.id !== targetId ||
          selectedVideo.lastUpdatedAt !== summary.lastUpdatedAt ||
          selectedVideo.status !== summary.status
        ) {
          await loadVideoDetail(targetId, { silent: true });
        }
      } catch (error) {
        if (!silent) {
          toast.error(getErrorMessage(error));
        }
      }
    },
    [activeVideoId, loadVideoDetail, selectedVideo, selectedVideoId],
  );

  useEffect(() => {
    void bootstrap();
  }, [bootstrap]);

  useEffect(() => {
    const suffix =
      lastStoryEventIdRef.current > 0
        ? `?lastEventId=${lastStoryEventIdRef.current}`
        : "";
    const source = new EventSource(`/api/story/events${suffix}`);

    const scheduleRefresh = () => {
      if (sseRefreshTimerRef.current !== null) {
        return;
      }
      sseRefreshTimerRef.current = window.setTimeout(() => {
        sseRefreshTimerRef.current = null;
        void refreshSummaries(true);
      }, 250);
    };

    const handleEvent = (event: Event) => {
      const messageEvent = event as MessageEvent<string>;
      const eventId = Number(messageEvent.lastEventId);
      if (Number.isFinite(eventId) && eventId > 0) {
        lastStoryEventIdRef.current = eventId;
      }

      if (messageEvent.data) {
        try {
          const payload = JSON.parse(messageEvent.data) as { type?: string };
          if (payload.type === "story.video.created") {
            toast("Video Story mới đã vào hàng đợi.");
          }
        } catch {
          // no-op
        }
      }
      scheduleRefresh();
    };

    STORY_SSE_EVENTS.forEach((eventName) =>
      source.addEventListener(eventName, handleEvent as EventListener),
    );
    source.onerror = () => {
      scheduleRefresh();
    };

    return () => {
      if (sseRefreshTimerRef.current !== null) {
        window.clearTimeout(sseRefreshTimerRef.current);
        sseRefreshTimerRef.current = null;
      }
      STORY_SSE_EVENTS.forEach((eventName) =>
        source.removeEventListener(eventName, handleEvent as EventListener),
      );
      source.close();
    };
  }, [refreshSummaries]);

  useEffect(() => {
    for (const summary of videoSummaries.slice(0, 10)) {
      if (videoThumbs[summary.id] || thumbInflightRef.current.has(summary.id)) {
        continue;
      }
      thumbInflightRef.current.add(summary.id);
      void getStoryVideo(summary.id)
        .then((detail) => {
          const thumbnail = extractVideoThumbnail(detail);
          if (!thumbnail) {
            return;
          }
          startTransition(() => {
            setVideoThumbs((current) => ({ ...current, [summary.id]: thumbnail }));
          });
        })
        .catch(() => undefined)
        .finally(() => {
          thumbInflightRef.current.delete(summary.id);
        });
    }
  }, [videoSummaries, videoThumbs]);

  const markers = useMemo(
    () => (selectedVideo ? orderedMarkers(selectedVideo.markers) : []),
    [selectedVideo],
  );

  const selectedMarker = useMemo(() => {
    if (!selectedVideo || !selectedMarkerId) {
      return null;
    }
    return findMarker(selectedVideo, selectedMarkerId);
  }, [selectedMarkerId, selectedVideo]);

  const selectedStep = useMemo(() => {
    if (!selectedMarker || !selectedStepId) {
      return null;
    }
    return findStep(selectedMarker, selectedStepId);
  }, [selectedMarker, selectedStepId]);

  const selectedAttempt = useMemo(() => {
    if (!selectedStep) {
      return null;
    }
    if (selectedAttemptId) {
      return selectedStep.attempts.find((attempt) => attempt.id === selectedAttemptId) ?? selectedStep.attempts.at(-1) ?? null;
    }
    return selectedStep.attempts.at(-1) ?? null;
  }, [selectedAttemptId, selectedStep]);

  useEffect(() => {
    if (!selectedStep) {
      setSelectedAttemptId(null);
      return;
    }
    const stillExists = selectedAttemptId
      ? selectedStep.attempts.some((attempt) => attempt.id === selectedAttemptId)
      : false;
    if (stillExists) {
      return;
    }
    setSelectedAttemptId(selectedStep.selectedAttemptId ?? selectedStep.attempts.at(-1)?.id ?? null);
  }, [selectedAttemptId, selectedStep]);

  const mergedPrompt = useMemo(
    () =>
      composeMergedPrompt(
        globalPromptDraft,
        selectedVideo?.videoPrompt ?? "",
        selectedMarker?.seedPrompt ?? "",
        selectedStep?.modifierPrompt ?? "",
      ),
    [globalPromptDraft, selectedMarker?.seedPrompt, selectedStep?.modifierPrompt, selectedVideo?.videoPrompt],
  );

  const markerGroups = useMemo(() => {
    const done: StoryMarker[] = [];
    const active: StoryMarker[] = [];
    const queued: StoryMarker[] = [];
    for (const marker of markers) {
      if (marker.status === "completed") {
        done.push(marker);
        continue;
      }
      if (
        marker.status === "running" ||
        marker.status === "review" ||
        marker.status === "failed" ||
        marker.id === selectedMarkerId
      ) {
        active.push(marker);
        continue;
      }
      queued.push(marker);
    }
    return { done, active, queued };
  }, [markers, selectedMarkerId]);

  const workerSlots = useMemo(() => {
    const maxWorker = Math.max(1, settingsDraft?.max_parallel_videos ?? 2);
    const runningVideos = videoSummaries.filter((video) => video.status === "running");
    return Array.from({ length: maxWorker }, (_, index) => runningVideos[index] ?? null);
  }, [settingsDraft?.max_parallel_videos, videoSummaries]);

  const queueCounts = useMemo(
    () => ({
      all: videoSummaries.length,
      running: videoSummaries.filter((video) => video.status === "running").length,
      review: videoSummaries.filter((video) => video.status === "review").length,
      queued: videoSummaries.filter((video) => video.status === "queued").length,
    }),
    [videoSummaries],
  );
  const filteredVideoSummaries = useMemo(() => {
    if (queueFilter === "all") {
      return videoSummaries;
    }
    return videoSummaries.filter((video) => video.status === queueFilter);
  }, [queueFilter, videoSummaries]);

  const handleRefreshSession = useCallback(async () => {
    setSessionRefreshing(true);
    try {
      const status = await getStorySessionStatus(true);
      startTransition(() => setSessionStatus(status));
      if (status.authenticated) {
        toast.success("Phiên Gemini đã sẵn sàng.");
      }
    } catch (error) {
      toast.error(getErrorMessage(error));
    } finally {
      setSessionRefreshing(false);
    }
  }, []);

  const handleOpenLogin = useCallback(async () => {
    try {
      await openStoryLogin();
      toast.success("Đã mở trình duyệt để đăng nhập Gemini.");
    } catch (error) {
      toast.error(getErrorMessage(error));
    }
  }, []);

  const handleOpenOutputFolder = useCallback(async () => {
    const outputRoot = settingsDraft?.output_root?.trim() ?? "";
    if (!outputRoot) {
      toast.error("Chưa có thư mục output trong cài đặt Story.");
      return;
    }
    try {
      await openFolder(outputRoot);
      toast.success("Đã mở thư mục output.");
    } catch (error) {
      toast.error(getErrorMessage(error));
    }
  }, [settingsDraft?.output_root]);

  const handleChooseOutputFolder = useCallback(async () => {
    if (!settingsDraft) {
      return;
    }
    setChoosingOutputFolder(true);
    try {
      const { path } = await chooseFolder();
      if (!path) {
        return;
      }
      const next = await updateStorySettings({
        ...settingsDraft,
        output_root: path,
      });
      lastSavedSettingsRef.current = JSON.stringify(next);
      lastFailedSettingsRef.current = null;
      startTransition(() => {
        setSettingsDraft(next);
      });
      toast.success("Đã cập nhật thư mục output.");
    } catch (error) {
      toast.error(getErrorMessage(error));
    } finally {
      setChoosingOutputFolder(false);
    }
  }, [settingsDraft]);

  const handleImportSourceFolder = useCallback(async (pathOverride?: string) => {
    const folderPath = (typeof pathOverride === "string" ? pathOverride : sourceFolderPath).trim();
    if (!folderPath) {
      toast.error("Hãy chọn thư mục video trước.");
      return;
    }
    setImportingSourceFolder(true);
    try {
      const importedVideos = await scanStoryFolder(folderPath);
      const latestVideo = importedVideos.at(-1) ?? null;
      startTransition(() => {
        setVideoSummaries((current) => {
          const importedMap = new Map(importedVideos.map((v) => [v.id, v]));
          const preserved = current.filter((v) => !importedMap.has(v.id));
          return [...importedVideos, ...preserved].sort((a, b) =>
            b.createdAt.localeCompare(a.createdAt),
          );
        });
      });
      if (latestVideo) {
        applyVideoDetail(latestVideo);
      }
      await refreshSummaries(true);
      toast.success(
        importedVideos.length === 1
          ? "Đã nhập 1 video từ thư mục."
          : `Đã nhập ${importedVideos.length} video từ thư mục.`,
      );
    } catch (error) {
      toast.error(getErrorMessage(error));
    } finally {
      setImportingSourceFolder(false);
    }
  }, [applyVideoDetail, refreshSummaries, sourceFolderPath]);

  const handleChooseSourceFolder = useCallback(async () => {
    setChoosingSourceFolder(true);
    try {
      const { path } = await chooseFolder();
      if (!path) return;
      setSourceFolderPath(path);
      await handleImportSourceFolder(path);
    } catch (error) {
      toast.error(getErrorMessage(error));
    } finally {
      setChoosingSourceFolder(false);
    }
  }, [handleImportSourceFolder]);

  const handleSaveGlobalPrompt = useCallback(async () => {
    setSavingPrompt(true);
    try {
      const result = await updateStoryGlobalPrompt(globalPromptDraft);
      startTransition(() => {
        setGlobalPrompt(result.globalPrompt);
        setGlobalPromptDraft(result.globalPrompt);
      });
      toast.success("Đã cập nhật prompt tổng.");
    } catch (error) {
      toast.error(getErrorMessage(error));
    } finally {
      setSavingPrompt(false);
    }
  }, [globalPromptDraft]);


  const handleFetchGems = useCallback(async () => {
    setFetchingGems(true);
    try {
      const gems = await listStoryGems();
      startTransition(() => {
        setAvailableGems(gems);
        setSettingsDraft((current) => (current ? sanitizeGeminiSettings(current, gems) : current));
      });
      if (gems.length > 0) {
        toast.success(`Đã quét được ${gems.length} Gem.`);
      } else {
        toast.info("Không tìm thấy Gem nào. Hãy bảo đảm bạn đã đăng nhập Gemini.");
      }
    } catch {
      toast.error("Lỗi khi quét danh sách Gem.");
    } finally {
      setFetchingGems(false);
    }
  }, []);

  const currentGemUrl = settingsDraft?.gemini_base_url?.trim() ?? "";
  const showStoredGemOption =
    currentGemUrl.length > 0 && !hasGemOption(availableGems, currentGemUrl);

  useEffect(() => {
    if (!settingsDraft || choosingOutputFolder) {
      return;
    }

    const draftSnapshot = JSON.stringify(settingsDraft);
    if (
      draftSnapshot === lastSavedSettingsRef.current ||
      draftSnapshot === lastFailedSettingsRef.current
    ) {
      return;
    }

    const timeoutId = window.setTimeout(() => {
      void (async () => {
        setSavingSettings(true);
        try {
          const next = await updateStorySettings(settingsDraft);
          lastSavedSettingsRef.current = JSON.stringify(next);
          lastFailedSettingsRef.current = null;
          startTransition(() => {
            setSettingsDraft((current) => {
              if (!current) {
                return current;
              }
              return JSON.stringify(current) === draftSnapshot ? next : current;
            });
          });
        } catch (error) {
          lastFailedSettingsRef.current = draftSnapshot;
          toast.error(getErrorMessage(error));
        } finally {
          setSavingSettings(false);
        }
      })();
    }, 500);

    return () => window.clearTimeout(timeoutId);
  }, [choosingOutputFolder, settingsDraft]);

  const handleRunVideo = useCallback(async () => {
    if (!selectedVideoId) {
      return;
    }
    setActionBusyKey("video:run");
    try {
      const detail = await runStoryVideo(selectedVideoId);
      applyVideoDetail(detail);
      toast.success("Đã chạy video.");
    } catch (error) {
      toast.error(getErrorMessage(error));
    } finally {
      setActionBusyKey(null);
    }
  }, [applyVideoDetail, selectedVideoId]);

  const handlePauseVideo = useCallback(async () => {
    if (!selectedVideoId) {
      return;
    }
    setActionBusyKey("video:pause");
    try {
      const detail = await pauseStoryVideo(selectedVideoId);
      applyVideoDetail(detail);
      toast.success("Đã tạm dừng video.");
    } catch (error) {
      toast.error(getErrorMessage(error));
    } finally {
      setActionBusyKey(null);
    }
  }, [applyVideoDetail, selectedVideoId]);

  const runStepAction = useCallback(
    async (action: StoryActionType, markerId: string, stepId: string, attemptId?: string | null) => {
      if (!selectedVideoId) {
        return;
      }
      const busyKey = selectionKey(action, markerId, stepId);
      setActionBusyKey(busyKey);
      try {
        const detail = await applyStoryAction({
          action,
          videoId: selectedVideoId,
          markerId,
          stepId,
          attemptId: attemptId ?? undefined,
        });
        applyVideoDetail(detail, {
          preferred: {
            markerId,
            stepId,
            attemptId: attemptId ?? null,
          },
        });
        toast.success(`Đã ${storyActionLabel(action)}.`);
      } catch (error) {
        toast.error(getErrorMessage(error));
      } finally {
        setActionBusyKey(null);
      }
    },
    [applyVideoDetail, selectedVideoId],
  );

  const handleAcceptAndNext = useCallback(async () => {
    if (!selectedVideoId || !selectedVideo || !selectedMarkerId || !selectedStepId) {
      return;
    }
    setActionBusyKey("step:accept-next");
    const nextStep = findNextStep(selectedVideo, selectedMarkerId, selectedStepId);
    try {
      let detail = await applyStoryAction({
        action: "accept",
        videoId: selectedVideoId,
        markerId: selectedMarkerId,
        stepId: selectedStepId,
        attemptId: selectedAttemptId ?? undefined,
      });
      if (detail.status === "queued") {
        detail = await runStoryVideo(detail.id);
      }
      applyVideoDetail(detail, {
        preferred: nextStep ?? undefined,
      });
      toast.success("Đã duyệt và chuyển sang bước tiếp theo.");
    } catch (error) {
      toast.error(getErrorMessage(error));
    } finally {
      setActionBusyKey(null);
    }
  }, [applyVideoDetail, selectedAttemptId, selectedMarkerId, selectedStepId, selectedVideo, selectedVideoId]);

  const handleSelectVideo = useCallback(
    async (videoId: string) => {
      setSelectedVideoId(videoId);
      await loadVideoDetail(videoId, { silent: true });
    },
    [loadVideoDetail],
  );

  const handleToggleMarker = useCallback((markerId: string) => {
    setExpandedMarkerIds((current) => {
      if (current.includes(markerId)) {
        return current.filter((id) => id !== markerId);
      }
      return [...current, markerId];
    });
  }, []);

  if (bootLoading) {
    return (
      <Card className="border-border/70 shadow-[0_24px_90px_rgba(15,23,42,0.08)]">
        <CardContent className="flex items-center justify-center gap-3 py-16 text-sm text-muted-foreground">
          <Loader2 className="size-4 animate-spin" />
          Đang tải Story Pipeline...
        </CardContent>
      </Card>
    );
  }

  return (
    <div className={cn("grid lg:grid-cols-[22rem_minmax(0,1fr)]", TAB_CARD_GAP_CLASS)}>
      {/* -------------------- LEFT PANEL: Cài đặt -------------------- */}
      <Tabs value={leftPanelTab} onValueChange={(v) => setLeftPanelTab(v as any)} className="flex flex-col min-h-0">
        {/* Header: trạng thái session + nút điều khiển */}
        <div className="flex items-center gap-2 mb-4 flex-none">
          {/* Chấm xanh trạng thái */}
          <div
            className={cn(
              "size-2.5 rounded-full flex-none transition-colors",
              sessionStatus?.authenticated
                ? "bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.5)]"
                : "bg-muted-foreground/30"
            )}
            title={sessionStatus?.authenticated ? "Đã kết nối Gemini" : "Chưa kết nối"}
          />
          {/* Nút đăng nhập */}
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="h-8 text-xs font-semibold flex-1"
            onClick={() => void handleOpenLogin()}
          >
            Đăng nhập
          </Button>
          {/* Nút làm mới phiên */}
          <Button
            type="button"
            variant="outline"
            size="icon"
            className="size-8 flex-none"
            onClick={() => void handleRefreshSession()}
            disabled={sessionRefreshing}
            title="Làm mới phiên"
          >
            {sessionRefreshing ? (
              <Loader2 className="size-3.5 animate-spin" />
            ) : (
              <RefreshCw className="size-3.5" />
            )}
          </Button>
          {/* Tab Gemini | Prompt */}
          <TabsList className="h-8 flex-none">
            <TabsTrigger value="gemini" className="text-xs px-2">Gemini</TabsTrigger>
            <TabsTrigger value="prompt" className="text-xs px-2">Prompt</TabsTrigger>
          </TabsList>
        </div>

        <TabsContent value="gemini" className="flex-1 min-h-0 m-0 outline-none flex flex-col gap-4 overflow-y-auto pr-1">
          {settingsDraft ? (
            <>
              {/* Nhập video */}
              <div className="flex flex-col gap-3 rounded-xl border border-border/70 bg-muted/20 p-3">
                <div className="flex flex-col gap-1">
                  <TooltipFieldLabel
                    tooltip="Chọn thư mục chứa video và file XMP để import vào Story Pipeline."
                    className="text-sm font-medium text-foreground"
                  >
                    Nhập video
                  </TooltipFieldLabel>
                  <div className="flex gap-2">
                    <Input
                      value={sourceFolderPath}
                      onChange={(e) => setSourceFolderPath(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") {
                          e.preventDefault();
                          void handleImportSourceFolder();
                        }
                      }}
                      placeholder="Dán đường dẫn hoặc chọn thư mục..."
                      className="text-xs"
                    />
                    <Button
                      type="button"
                      variant="outline"
                      size="icon"
                      disabled={choosingSourceFolder || importingSourceFolder}
                      onClick={() => void handleChooseSourceFolder()}
                      title="Chọn thư mục video"
                    >
                      {choosingSourceFolder || importingSourceFolder ? (
                        <Loader2 className="size-4 animate-spin" />
                      ) : (
                        <FolderOpen className="size-4" />
                      )}
                    </Button>
                  </div>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="mt-1"
                    disabled={!sourceFolderPath.trim() || importingSourceFolder}
                    onClick={() => void handleImportSourceFolder()}
                  >
                    {importingSourceFolder ? (
                      <Loader2 className="size-3.5 mr-2 animate-spin" />
                    ) : (
                      <Plus className="size-3.5 mr-2" />
                    )}
                    Nhập video từ thư mục
                  </Button>
                </div>
              </div>

              {/* Thư mục output và số luồng */}
              <div className="flex flex-col gap-3 rounded-xl border border-border/70 bg-muted/20 p-3">
                <div className="flex flex-col gap-1">
                  <TooltipFieldLabel
                    tooltip="Thư mục xuất file video và hình ảnh."
                    className="text-sm font-medium text-foreground"
                  >
                    Thư mục output
                  </TooltipFieldLabel>
                  <div className="flex gap-2">
                    <Input
                      value={settingsDraft.output_root}
                      readOnly
                      placeholder="Chọn thư mục output..."
                      className="text-xs"
                    />
                    <Button
                      type="button"
                      variant="outline"
                      size="icon"
                      disabled={choosingOutputFolder}
                      onClick={() => void handleChooseOutputFolder()}
                      title="Chọn thư mục output"
                    >
                      {choosingOutputFolder ? (
                        <Loader2 className="size-4 animate-spin" />
                      ) : (
                        <FolderOpen className="size-4" />
                      )}
                    </Button>
                  </div>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="mt-1"
                    disabled={!settingsDraft.output_root.trim()}
                    onClick={() => void handleOpenOutputFolder()}
                  >
                    <FolderOpen className="size-4 mr-2" />
                    Mở thư mục output
                  </Button>
                </div>

                <div className="flex flex-col gap-1 mt-2">
                  <TooltipFieldLabel
                    htmlFor="story-workers"
                    tooltip="Số video tối đa được xử lý đồng thời trong Story Pipeline."
                    className="text-sm font-medium text-foreground"
                  >
                    Số luồng tối đa
                  </TooltipFieldLabel>
                  <Input
                    id="story-workers"
                    type="number"
                    min={1}
                    max={10}
                    value={settingsDraft.max_parallel_videos}
                    onChange={(event) =>
                      setSettingsDraft((current) =>
                        current
                          ? {
                              ...current,
                              max_parallel_videos: Math.min(
                                10,
                                Math.max(1, Number(event.target.value) || 1),
                              ),
                            }
                          : current,
                      )
                    }
                  />
                </div>
              </div>

              {/* Mô hình và Headless */}
              <div className="flex flex-col gap-3 rounded-xl border border-border/70 bg-muted/20 p-3">
                <div className="flex flex-col gap-1">
                  <TooltipFieldLabel
                    tooltip="Chọn tốc độ xử lý: Nhanh tối ưu tốc độ, Tư duy cân bằng suy luận, Pro ưu tiên chất lượng."
                    className="text-sm font-medium text-foreground"
                  >
                    Mô hình
                  </TooltipFieldLabel>
                  <Select
                    value={settingsDraft.gemini_model ?? "gemini-2.5-flash"}
                    onValueChange={(value) =>
                      setSettingsDraft((current) => current ? { ...current, gemini_model: value } : null)
                    }
                  >
                    <SelectTrigger>
                      <SelectValue placeholder="Chọn mô hình..." />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectGroup>
                        <SelectLabel>Tốc độ / Chất lượng</SelectLabel>
                        <SelectItem value="gemini-2.5-flash">⚡ Nhanh — Gemini 2.5 Flash</SelectItem>
                        <SelectItem value="gemini-2.5-flash-thinking">🧠 Tư duy — Gemini 2.5 Flash Thinking</SelectItem>
                        <SelectItem value="gemini-2.5-pro">🎯 Pro — Gemini 2.5 Pro</SelectItem>
                      </SelectGroup>
                    </SelectContent>
                  </Select>
                </div>

                <div className="flex items-center justify-between gap-4 mt-1">
                  <TooltipFieldLabel
                    tooltip="Chạy trình duyệt ẩn danh không hiển thị UI."
                    className="text-sm font-medium text-foreground mb-0"
                  >
                    Chạy nền (headless)
                  </TooltipFieldLabel>
                  <Switch
                    checked={settingsDraft.gemini_headless ?? true}
                    onCheckedChange={(checked) =>
                      setSettingsDraft((current) => current ? { ...current, gemini_headless: checked } : null)
                    }
                  />
                </div>
              </div>

              {/* Gem (base URL) */}
              <div className="flex flex-col gap-3 rounded-xl border border-border/70 bg-muted/20 p-3">
                <div className="flex flex-col gap-1">
                  <TooltipFieldLabel
                    tooltip="Chọn Gem để điều hướng prompt. Bấm làm mới để quét lại danh sách từ trình duyệt."
                    className="text-sm font-medium text-foreground"
                  >
                    Gem
                  </TooltipFieldLabel>
                  <div className="flex gap-2">
                    <Select
                      value={currentGemUrl || GEMINI_DEFAULT_URL}
                      onValueChange={(value) =>
                        setSettingsDraft((current) =>
                          current ? { ...current, gemini_base_url: value } : current
                        )
                      }
                    >
                      <SelectTrigger className="flex-1">
                        <SelectValue placeholder="Chọn một Gem..." />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectGroup>
                          <SelectLabel>Gem khả dụng</SelectLabel>
                          <SelectItem value={GEMINI_DEFAULT_URL}>Gemini mặc định</SelectItem>
                          {showStoredGemOption ? (
                            <SelectItem value={currentGemUrl}>Gem đang lưu</SelectItem>
                          ) : null}
                          {availableGems.map((gem) => (
                            <SelectItem key={gem.url} value={gem.url}>
                              {gem.name}
                            </SelectItem>
                          ))}
                        </SelectGroup>
                      </SelectContent>
                    </Select>
                    <Button
                      type="button"
                      variant="outline"
                      size="icon"
                      disabled={fetchingGems}
                      onClick={() => void handleFetchGems()}
                      title="Làm mới danh sách Gem"
                    >
                      {fetchingGems ? (
                        <Loader2 className="size-4 animate-spin" />
                      ) : (
                        <RefreshCw className="size-4" />
                      )}
                    </Button>
                  </div>
                </div>
              </div>
            </>
          ) : null}
        </TabsContent>

        <TabsContent value="prompt" className="flex-1 min-h-0 m-0 outline-none flex flex-col gap-4 overflow-y-auto pr-1">
          <div className="flex flex-col gap-3 rounded-xl border border-border/70 bg-muted/20 p-3">
            <div className="flex items-center gap-2">
              <Badge className="bg-primary/85 text-primary-foreground">Global</Badge>
              <TooltipFieldLabel
                tooltip="Prompt tổng áp dụng cho toàn bộ quy trình Story Pipeline."
                className="text-sm font-medium text-foreground"
              >
                Prompt tổng
              </TooltipFieldLabel>
            </div>
            <Textarea
              value={globalPromptDraft}
              onChange={(event) => setGlobalPromptDraft(event.target.value)}
              className="min-h-20"
            />
            <Button
              type="button"
              variant="outline"
              disabled={savingPrompt || globalPromptDraft.trim() === globalPrompt.trim()}
              onClick={() => void handleSaveGlobalPrompt()}
            >
              {savingPrompt ? <Loader2 className="size-4 animate-spin" /> : "Lưu prompt tổng"}
            </Button>
          </div>

          {selectedVideo ? (
            <>
              <div className="flex flex-col gap-3 rounded-xl border border-border/70 bg-muted/20 p-3">
                <div className="flex items-center gap-2">
                  <Badge className="bg-indigo-500/80 text-indigo-50">Video</Badge>
                  <TooltipFieldLabel
                    tooltip="Ngữ cảnh prompt riêng của video đang chọn."
                    className="text-sm font-medium text-foreground"
                  >
                    Prompt ngữ cảnh
                  </TooltipFieldLabel>
                </div>
                <Textarea value={selectedVideo?.videoPrompt ?? ""} readOnly className="min-h-16" />
              </div>

              <div className="flex flex-col gap-3 rounded-xl border border-border/70 bg-muted/20 p-3">
                <div className="flex items-center gap-2">
                  <Badge className="bg-amber-500/80 text-amber-50">Step</Badge>
                  <TooltipFieldLabel
                    tooltip="Gồm seed prompt của marker và modifier prompt của bước hiện tại."
                    className="text-sm font-medium text-foreground"
                  >
                    Seed và modifier
                  </TooltipFieldLabel>
                </div>
                <Textarea
                  value={[
                    selectedMarker?.seedPrompt ?? "",
                    selectedStep?.modifierPrompt ?? "",
                  ]
                    .filter(Boolean)
                    .join("\n\n")}
                  readOnly
                  className="min-h-20"
                />
              </div>

              <div className="flex flex-col gap-3 rounded-xl border border-border/70 bg-muted/20 p-3">
                <TooltipFieldLabel
                  tooltip="Bản ghép cuối cùng của prompt tổng, prompt video và prompt bước."
                  className="text-sm font-medium text-foreground"
                >
                  Xem trước prompt gộp
                </TooltipFieldLabel>
                <Textarea value={mergedPrompt} readOnly className="min-h-24 text-xs" />
              </div>
            </>
          ) : (
            <div className="flex-1 flex items-center justify-center text-muted-foreground text-sm border border-dashed rounded-lg py-8">
              Chọn video để xem chi tiết prompt
            </div>
          )}
        </TabsContent>
      </Tabs>

      {/* -------------------- MAIN PANEL -------------------- */}
      <Tabs value={mainPanelTab} onValueChange={(v) => setMainPanelTab(v as any)} className="flex flex-col min-h-0 lg:col-span-1">
        <div className="flex items-center justify-between mb-4 flex-none">
          <h2 className="text-lg font-semibold tracking-tight text-foreground">Không gian làm việc</h2>
          <TabsList className="h-9">
            <TabsTrigger value="videos" className="text-xs">Tiến trình</TabsTrigger>
            <TabsTrigger value="collection" className="text-xs">Bộ sưu tập</TabsTrigger>
            <TabsTrigger value="history" className="text-xs">Lịch sử</TabsTrigger>
            <TabsTrigger value="workers" className="text-xs">Luồng</TabsTrigger>
          </TabsList>
        </div>

        <TabsContent value="videos" className="flex-1 min-h-0 m-0 outline-none flex flex-col">
          <div className="flex-none flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              <Badge variant="secondary" className="bg-muted/50 text-muted-foreground font-medium">
                {videoSummaries.length} video
              </Badge>
              <Select value={queueFilter} onValueChange={(val) => setQueueFilter(val as any)}>
                <SelectTrigger className="h-7 text-xs px-2 w-[110px] bg-background border-border/60">
                  <SelectValue placeholder="Lọc" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">Tất cả ({queueCounts.all})</SelectItem>
                  <SelectItem value="running">Đang chạy ({queueCounts.running})</SelectItem>
                  <SelectItem value="review">Chờ duyệt ({queueCounts.review})</SelectItem>
                  <SelectItem value="queued">Hàng đợi ({queueCounts.queued})</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="flex items-center gap-2">
              <Button variant="outline" size="sm" className="h-8 gap-1.5" onClick={() => void refreshSummaries(false)}>
                <RefreshCw className="size-3.5" />
                Làm mới
              </Button>
              <Button size="sm" className="h-8 gap-1.5" onClick={() => toast.info("Tính năng tạo video mới đang phát triển")}>
                <Plus className="size-3.5" />
                Video mới
              </Button>
            </div>
          </div>

          <div className="grid grid-cols-[16rem_1fr] gap-4 flex-1 min-h-0 overflow-hidden">
            {/* Sidebar danh sách video */}
            <Card className="border-border/70 shadow-sm flex flex-col overflow-hidden">
              <CardContent className="p-0 flex-1 overflow-y-auto">
                <div className="flex flex-col p-2 gap-1.5">
                  {filteredVideoSummaries.map((summary) => {
                    const isSelected = selectedVideoId === summary.id;
                    const tone = storyStatusTone(summary.status);
                    return (
                      <button
                        key={summary.id}
                        type="button"
                        onClick={() => void handleSelectVideo(summary.id)}
                        className={cn(
                          "flex flex-col gap-1.5 rounded-lg px-3 py-2.5 text-left text-sm transition-all border",
                          isSelected
                            ? "bg-accent/80 text-accent-foreground border-accent-foreground/20 shadow-sm"
                            : "bg-transparent text-muted-foreground border-transparent hover:bg-muted/50 hover:text-foreground",
                        )}
                      >
                        <div className="flex items-start justify-between gap-2">
                          <span className="font-medium truncate flex-1 leading-snug">
                            {summary.id}
                          </span>
                          <Badge variant={tone.variant} className={cn("text-[10px] uppercase font-bold px-1.5 py-0 h-4 leading-none tracking-wider", tone.className)}>
                            {storyStatusLabel(summary.status)}
                          </Badge>
                        </div>
                        <div className="flex items-center gap-2 w-full">
                          <div className="h-1 flex-1 bg-muted rounded-full overflow-hidden">
                            <div
                              className={cn("h-full rounded-full transition-all duration-500", isSelected ? "bg-primary" : "bg-primary/40")}
                              style={{ width: `${progressPercent(summary)}%` }}
                            />
                          </div>
                          <span className="text-xs font-mono opacity-60 flex-none">{progressPercent(summary)}%</span>
                        </div>
                      </button>
                    );
                  })}
                  {filteredVideoSummaries.length === 0 && (
                    <div className="py-8 text-center text-sm text-muted-foreground">
                      Không có video nào.
                    </div>
                  )}
                </div>
              </CardContent>
            </Card>

            {/* Chi tiết Video được chọn */}
            <Card className="border-border/70 shadow-sm flex flex-col overflow-hidden">
              {detailLoading ? (
                <div className="flex-1 flex items-center justify-center text-muted-foreground">
                  <Loader2 className="size-5 animate-spin mr-2" />
                  Đang tải...
                </div>
              ) : selectedVideo ? (
                <>
                  <CardHeader className="py-4 px-5 border-b border-border/50 bg-muted/10 flex-row items-center justify-between">
                    <div>
                      <CardTitle className="text-base truncate flex items-center gap-2">
                        <FileVideo className="size-4 text-muted-foreground" />
                        {selectedVideo.id}
                      </CardTitle>
                      <CardDescription className="mt-1 flex items-center gap-3 text-xs">
                        <span className="flex items-center gap-1.5"><ImageIcon className="size-3" /> {selectedVideo.completedSteps}/{selectedVideo.stepTotal}</span>
                        <span className="opacity-50">·</span>
                        <span className="flex items-center gap-1.5"><MessageSquare className="size-3" /> {selectedVideo.reviewSteps} cần duyệt</span>
                      </CardDescription>
                    </div>
                    <div className="flex items-center gap-2">
                      <Button variant="outline" size="sm" onClick={handlePauseVideo} disabled={selectedVideo.status === "paused"}>
                        <Pause className="size-3.5 mr-1.5" />
                        Tạm dừng
                      </Button>
                      <Button variant="outline" size="sm" onClick={handleRunVideo} disabled={selectedVideo.status === "running"}>
                        <Play className="size-3.5 mr-1.5" />
                        Tiếp tục
                      </Button>
                      <AlertDialog>
                        <AlertDialogTrigger asChild>
                          <Button variant="outline" size="sm" className="text-destructive hover:bg-destructive/10 border-destructive/20">
                            <X className="size-3.5 mr-1.5" />
                            Dừng
                          </Button>
                        </AlertDialogTrigger>
                        <AlertDialogContent>
                          <div className="flex flex-col gap-2 mb-4">
                            <AlertDialogTitle>Dừng tiến trình?</AlertDialogTitle>
                            <AlertDialogDescription>
                              Video đang được xử lý sẽ bị dừng lại. Bạn có thể tiếp tục sau.
                            </AlertDialogDescription>
                          </div>
                          <div className="flex justify-end gap-2 mt-4">
                            <AlertDialogCancel>Huỷ</AlertDialogCancel>
                            <AlertDialogAction onClick={async () => {
                               try {
                                 const detail = await cancelStoryVideo(selectedVideoId!);
                                 applyVideoDetail(detail);
                                 toast.success("Đã dừng video");
                               } catch(e) {
                                 toast.error(getErrorMessage(e));
                               }
                            }}>Xác nhận dừng</AlertDialogAction>
                          </div>
                        </AlertDialogContent>
                      </AlertDialog>
                    </div>
                  </CardHeader>
                  <CardContent className="flex-1 overflow-hidden p-0 flex">
                    {/* Danh sách Markers */}
                    <ScrollArea className="w-[300px] border-r border-border/50 bg-muted/5">
                      <div className="p-3 space-y-4">
                        {markerGroups.active.length > 0 && (
                          <div className="space-y-1.5">
                            <h4 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider px-1">Đang xử lý / Lỗi</h4>
                            {markerGroups.active.map((marker) => (
                              <MarkerItem
                                key={marker.id}
                                marker={marker}
                                isExpanded={expandedMarkerIds.includes(marker.id)}
                                isSelected={selectedMarkerId === marker.id}
                                selectedStepId={selectedStepId}
                                onToggle={() => handleToggleMarker(marker.id)}
                                onSelectStep={(stepId) => {
                                  setSelectedMarkerId(marker.id);
                                  setSelectedStepId(stepId);
                                }}
                              />
                            ))}
                          </div>
                        )}
                        {markerGroups.queued.length > 0 && (
                          <div className="space-y-1.5">
                            <h4 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider px-1">Hàng đợi ({markerGroups.queued.length})</h4>
                            {markerGroups.queued.slice(0, 5).map((marker) => (
                              <MarkerItem
                                key={marker.id}
                                marker={marker}
                                isExpanded={expandedMarkerIds.includes(marker.id)}
                                isSelected={selectedMarkerId === marker.id}
                                selectedStepId={selectedStepId}
                                onToggle={() => handleToggleMarker(marker.id)}
                                onSelectStep={(stepId) => {
                                  setSelectedMarkerId(marker.id);
                                  setSelectedStepId(stepId);
                                }}
                              />
                            ))}
                          </div>
                        )}
                        {markerGroups.done.length > 0 && (
                          <div className="space-y-1.5">
                            <h4 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider px-1">Đã xong ({markerGroups.done.length})</h4>
                            {markerGroups.done.slice(-5).map((marker) => (
                              <MarkerItem
                                key={marker.id}
                                marker={marker}
                                isExpanded={expandedMarkerIds.includes(marker.id)}
                                isSelected={selectedMarkerId === marker.id}
                                selectedStepId={selectedStepId}
                                onToggle={() => handleToggleMarker(marker.id)}
                                onSelectStep={(stepId) => {
                                  setSelectedMarkerId(marker.id);
                                  setSelectedStepId(stepId);
                                }}
                              />
                            ))}
                          </div>
                        )}
                      </div>
                    </ScrollArea>
                    
                    {/* Chi tiết Step được chọn */}
                    <div className="flex-1 flex flex-col bg-background min-w-0">
                      {selectedStep ? (
                        <div className="flex-1 flex flex-col p-5 gap-5 overflow-y-auto">
                          <div className="flex items-center justify-between">
                            <div className="flex items-center gap-2">
                              <Badge variant="outline" className="text-xs font-mono">STEP {selectedStep.index}</Badge>
                              <Badge variant={storyStatusTone(selectedStep.status).variant} className={storyStatusTone(selectedStep.status).className}>
                                {storyStatusLabel(selectedStep.status)}
                              </Badge>
                            </div>
                            <div className="text-sm font-medium">Attempt: {selectedAttempt?.index ?? "-"}</div>
                          </div>
                          
                          <div className="grid grid-cols-2 gap-4">
                            <div className="space-y-2">
                              <label className="text-xs font-semibold text-muted-foreground">Input / Source</label>
                              <div className="aspect-video bg-muted/30 rounded-lg border flex items-center justify-center overflow-hidden">
                                {selectedMarker?.inputFramePath ? (
                                  <VideoThumb path={selectedMarker.inputFramePath} alt="Input" className="w-full h-full rounded-none border-0" />
                                ) : (
                                  <ImageIcon className="size-8 text-muted-foreground/30" />
                                )}
                              </div>
                            </div>
                            <div className="space-y-2">
                              <label className="text-xs font-semibold text-muted-foreground">Output / Preview</label>
                              <div className="aspect-video bg-muted/30 rounded-lg border flex items-center justify-center overflow-hidden relative group">
                                {selectedAttempt?.previewPath || selectedAttempt?.normalizedPath ? (
                                  <>
                                    <VideoThumb path={selectedAttempt.previewPath || selectedAttempt.normalizedPath} alt="Preview" className="w-full h-full rounded-none border-0" />
                                    <div className="absolute inset-0 bg-black/40 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center">
                                      <Button size="icon" variant="secondary" className="rounded-full size-10">
                                        <Play className="size-4" />
                                      </Button>
                                    </div>
                                  </>
                                ) : (
                                  <VideoIcon className="size-8 text-muted-foreground/30" />
                                )}
                              </div>
                            </div>
                          </div>

                          {selectedStep.status === "review" && (
                            <div className="p-4 rounded-lg bg-amber-500/10 border border-amber-500/20 flex flex-col gap-3">
                              <p className="text-sm font-medium text-amber-600/90 dark:text-amber-400">
                                Output cần được duyệt trước khi tiếp tục.
                              </p>
                              <div className="flex gap-2">
                                <Button size="sm" onClick={handleAcceptAndNext} disabled={Boolean(actionBusyKey)}>
                                  <Play className="size-3.5 mr-1.5" /> Duyệt & Tiếp tục
                                </Button>
                                <Button size="sm" variant="outline" onClick={() => runStepAction("regenerate", selectedMarker!.id, selectedStep.id)} disabled={Boolean(actionBusyKey)}>
                                  <RotateCcw className="size-3.5 mr-1.5" /> Tạo lại
                                </Button>
                              </div>
                            </div>
                          )}

                          <div className="space-y-2">
                            <label className="text-xs font-semibold text-muted-foreground">Log / Output</label>
                            <div className="bg-muted/40 rounded-lg p-3 border font-mono text-xs text-muted-foreground max-h-[150px] overflow-y-auto whitespace-pre-wrap">
                              {selectedAttempt?.error || "Không có lỗi hoặc log."}
                            </div>
                          </div>
                        </div>
                      ) : (
                        <div className="flex-1 flex items-center justify-center text-muted-foreground text-sm">
                          Chọn một step bên trái để xem chi tiết
                        </div>
                      )}
                    </div>
                  </CardContent>
                </>
              ) : (
                <div className="flex-1 flex items-center justify-center text-muted-foreground">
                  Chọn một video bên trái để xem chi tiết
                </div>
              )}
            </Card>
          </div>
        </TabsContent>

        <TabsContent value="collection" className="flex-1 min-h-0 m-0 outline-none">
           <div className="flex items-center justify-center h-full text-muted-foreground border border-border/70 rounded-lg bg-card shadow-sm">
             Tính năng Bộ sưu tập đang được cập nhật
           </div>
        </TabsContent>

        <TabsContent value="history" className="flex-1 min-h-0 m-0 outline-none">
           <div className="flex items-center justify-center h-full text-muted-foreground border border-border/70 rounded-lg bg-card shadow-sm">
             Tính năng Lịch sử đang được cập nhật
           </div>
        </TabsContent>

        <TabsContent value="workers" className="flex-1 min-h-0 m-0 outline-none flex flex-col">
           <div className="grid grid-cols-2 gap-4">
             {workerSlots.map((video, idx) => (
               <Card key={idx} className="border-border/70">
                 <CardHeader className="py-3 px-4 bg-muted/30 border-b border-border/50">
                   <CardTitle className="text-sm flex items-center gap-2">
                     <div className="size-2 rounded-full bg-emerald-500 animate-pulse" />
                     Worker {idx + 1}
                   </CardTitle>
                 </CardHeader>
                 <CardContent className="p-4">
                   {video ? (
                     <div className="text-sm">
                       <span className="font-medium text-foreground">{video.id}</span>
                       <div className="text-muted-foreground mt-1">Đang chạy... ({progressPercent(video)}%)</div>
                     </div>
                   ) : (
                     <div className="text-sm text-muted-foreground italic">Đang chờ việc...</div>
                   )}
                 </CardContent>
               </Card>
             ))}
           </div>
        </TabsContent>
      </Tabs>
    </div>
  );
}

function MarkerItem({ marker, isExpanded, isSelected, selectedStepId, onToggle, onSelectStep }: {
  marker: StoryMarker;
  isExpanded: boolean;
  isSelected: boolean;
  selectedStepId: string | null;
  onToggle: () => void;
  onSelectStep: (stepId: string) => void;
}) {
  const tone = storyStatusTone(marker.status);
  return (
    <div className="flex flex-col border border-border/50 rounded-md overflow-hidden bg-background">
      <button
        type="button"
        className={cn("flex items-center justify-between p-2 text-left hover:bg-muted/30 transition-colors", isSelected && "bg-muted/50")}
        onClick={onToggle}
      >
        <div className="flex items-center gap-2 overflow-hidden">
          <Badge variant="outline" className="text-[10px] px-1 h-4 flex-none">{marker.index}</Badge>
          <span className="text-xs font-medium truncate">{marker.id}</span>
        </div>
        <Badge variant={tone.variant} className={cn("text-[9px] px-1 h-3.5 flex-none", tone.className)}>
          {storyStatusLabel(marker.status)}
        </Badge>
      </button>
      {isExpanded && marker.steps.length > 0 && (
        <div className="flex flex-col gap-[1px] bg-border/40 border-t border-border/50">
          {orderedSteps(marker.steps).map((step) => {
            const stepTone = storyStatusTone(step.status);
            const isStepSelected = isSelected && selectedStepId === step.id;
            return (
              <button
                key={step.id}
                type="button"
                className={cn(
                  "flex items-center justify-between px-3 py-1.5 text-left text-[11px] bg-background hover:bg-muted/40 transition-colors",
                  isStepSelected && "bg-accent/10 text-accent-foreground font-medium"
                )}
                onClick={() => onSelectStep(step.id)}
              >
                <span>Step {step.index}</span>
                <span className={cn("text-[10px]", stepTone.className || "text-muted-foreground")}>{storyStatusLabel(step.status)}</span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
