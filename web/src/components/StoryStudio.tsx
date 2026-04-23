import { startTransition, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import {
  AlertCircle,
  Check,
  ChevronRight,
  Clapperboard,
  FolderOpen,
  Loader2,
  Pause,
  Play,
  RefreshCw,
  RotateCcw,
  Sparkles,
  Upload,
} from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
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
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import {
  applyStoryAction,
  getStoryAssetUrl,
  getStoryBootstrap,
  getStorySessionStatus,
  getStoryVideo,
  importStoryManifest,
  listStoryVideos,
  openFolder,
  openStoryLogin,
  pauseStoryVideo,
  runStoryVideo,
  updateStoryGlobalPrompt,
  updateStorySettings,
  type StoryBootstrapPayload,
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

const STORY_SSE_EVENTS = [
  "connected",
  "story.video.created",
  "story.video.updated",
  "story.step.updated",
  "story.settings.updated",
  "story.global_prompt.updated",
];

function getErrorMessage(error: unknown) {
  if (error instanceof Error) {
    return error.message;
  }
  return "Yeu cau that bai.";
}

function storyStatusLabel(status: string) {
  switch (status) {
    case "queued":
      return "QUEUE";
    case "running":
      return "RUN";
    case "review":
      return "REVIEW";
    case "completed":
      return "DONE";
    case "paused":
      return "PAUSE";
    case "failed":
      return "FAILED";
    default:
      return status.toUpperCase();
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

function formatTimestampMs(value: number) {
  const totalSeconds = Math.max(0, Math.floor(value / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

function orderedMarkers(markers: StoryMarker[]) {
  return [...markers].sort((a, b) => a.index - b.index);
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
        no preview
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
  const [bootError, setBootError] = useState("");

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

  const [manifestPath, setManifestPath] = useState("");
  const [savingPrompt, setSavingPrompt] = useState(false);
  const [savingSettings, setSavingSettings] = useState(false);
  const [sessionRefreshing, setSessionRefreshing] = useState(false);
  const [importingManifest, setImportingManifest] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [actionBusyKey, setActionBusyKey] = useState<string | null>(null);
  const [queueFilter, setQueueFilter] = useState<QueueFilter>("all");

  const [videoThumbs, setVideoThumbs] = useState<Record<string, string>>({});
  const thumbInflightRef = useRef<Set<string>>(new Set());
  const lastStoryEventIdRef = useRef(0);
  const sseRefreshTimerRef = useRef<number | null>(null);

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
    setBootError("");
    try {
      const payload: StoryBootstrapPayload = await getStoryBootstrap();
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
    } catch (error) {
      setBootError(getErrorMessage(error));
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
            toast("Story video moi da vao queue.");
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
    const maxWorkers = Math.max(1, settingsDraft?.max_parallel_videos ?? 2);
    const runningVideos = videoSummaries.filter((video) => video.status === "running");
    return Array.from({ length: maxWorkers }, (_, index) => runningVideos[index] ?? null);
  }, [settingsDraft?.max_parallel_videos, videoSummaries]);

  const pendingVideoCount = useMemo(
    () => videoSummaries.filter((video) => video.status === "queued").length,
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
        toast.success("Gemini session san sang.");
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
      toast.success("Da mo trinh duyet de dang nhap Gemini.");
    } catch (error) {
      toast.error(getErrorMessage(error));
    }
  }, []);

  const handleOpenOutputFolder = useCallback(async () => {
    const outputRoot = settingsDraft?.output_root?.trim() ?? "";
    if (!outputRoot) {
      toast.error("Chua co output_root trong Story settings.");
      return;
    }
    try {
      await openFolder(outputRoot);
      toast.success("Da mo thu muc output.");
    } catch (error) {
      toast.error(getErrorMessage(error));
    }
  }, [settingsDraft?.output_root]);

  const handleSaveSettings = useCallback(async () => {
    if (!settingsDraft) {
      return;
    }
    setSavingSettings(true);
    try {
      const next = await updateStorySettings(settingsDraft);
      startTransition(() => {
        setSettingsDraft(next);
      });
      toast.success("Da luu Story settings.");
      await handleRefreshSession();
    } catch (error) {
      toast.error(getErrorMessage(error));
    } finally {
      setSavingSettings(false);
    }
  }, [handleRefreshSession, settingsDraft]);

  const handleSaveGlobalPrompt = useCallback(async () => {
    setSavingPrompt(true);
    try {
      const result = await updateStoryGlobalPrompt(globalPromptDraft);
      startTransition(() => {
        setGlobalPrompt(result.globalPrompt);
        setGlobalPromptDraft(result.globalPrompt);
      });
      toast.success("Da cap nhat Global prompt.");
    } catch (error) {
      toast.error(getErrorMessage(error));
    } finally {
      setSavingPrompt(false);
    }
  }, [globalPromptDraft]);

  const handleImportManifest = useCallback(async () => {
    const trimmedPath = manifestPath.trim();
    if (!trimmedPath) {
      toast.error("Can nhap duong dan manifest JSON.");
      return;
    }
    setImportingManifest(true);
    try {
      const imported = await importStoryManifest({ manifestPath: trimmedPath });
      if (imported.length === 0) {
        toast.error("Manifest khong co video hop le.");
        return;
      }
      applyVideoDetail(imported[0]);
      await refreshSummaries(true);
      toast.success(`Da import ${imported.length} video vao queue.`);
    } catch (error) {
      toast.error(getErrorMessage(error));
    } finally {
      setImportingManifest(false);
    }
  }, [applyVideoDetail, manifestPath, refreshSummaries]);

  const handleRunVideo = useCallback(async () => {
    if (!selectedVideoId) {
      return;
    }
    setActionBusyKey("video:run");
    try {
      const detail = await runStoryVideo(selectedVideoId);
      applyVideoDetail(detail);
      toast.success("Da chay video.");
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
      toast.success("Da tam dung video.");
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
        toast.success(`Da thuc hien ${action.toUpperCase()}.`);
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
      toast.success("Da ACCEPT va chuyen step tiep theo.");
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
          Dang tai Story Pipeline...
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="grid gap-4 lg:grid-cols-[19rem_minmax(0,1fr)_22rem]">
      {bootError ? (
        <Alert className="lg:col-span-3" variant="destructive">
          <AlertTitle>Khong tai duoc Story bootstrap</AlertTitle>
          <AlertDescription>{bootError}</AlertDescription>
        </Alert>
      ) : null}

      <Card className="border-border/70 shadow-[0_24px_90px_rgba(15,23,42,0.08)]">
        <CardHeader className="gap-3 border-b border-border/70">
          <CardTitle className="flex items-center justify-between text-base">
            <span className="flex items-center gap-2">
              <Clapperboard className="size-4 text-primary" />
              Video Queue
            </span>
            <Badge variant="outline">{videoSummaries.length}</Badge>
          </CardTitle>
          <div className="rounded-lg border border-border/70 bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
            Pending {pendingVideoCount} video
          </div>
          <div className="grid grid-cols-4 gap-1">
            {[
              { value: "all", label: "ALL" },
              { value: "running", label: "RUN" },
              { value: "review", label: "REVIEW" },
              { value: "queued", label: "QUEUE" },
            ].map((item) => (
              <Button
                key={item.value}
                type="button"
                size="sm"
                variant={queueFilter === item.value ? "secondary" : "outline"}
                className="h-7 px-2 text-[11px]"
                onClick={() => setQueueFilter(item.value as QueueFilter)}
              >
                {item.label}
              </Button>
            ))}
          </div>
        </CardHeader>
        <CardContent className="flex h-[calc(100dvh-10rem)] flex-col gap-4 pt-4">
          <div className="flex-1 overflow-auto">
            <div className="flex flex-col gap-2">
              {filteredVideoSummaries.map((video) => {
                const tone = storyStatusTone(video.status);
                const selected = selectedVideoId === video.id;
                const progress = progressPercent(video);
                return (
                  <button
                    key={video.id}
                    type="button"
                    onClick={() => void handleSelectVideo(video.id)}
                    className={cn(
                      "w-full rounded-xl border px-2 py-2 text-left transition-colors",
                      selected
                        ? "border-primary/60 bg-primary/10"
                        : "border-border/70 bg-card/50 hover:bg-muted/35",
                    )}
                  >
                    <div className="flex items-start gap-2">
                      <VideoThumb
                        path={videoThumbs[video.id]}
                        alt={video.name}
                        className="size-12 shrink-0"
                      />
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-sm font-medium text-foreground">
                          {video.name}
                        </div>
                        <div className="mt-1 flex items-center gap-2">
                          <Badge variant={tone.variant} className={tone.className}>
                            {storyStatusLabel(video.status)}
                          </Badge>
                          <span className="text-[11px] text-muted-foreground tabular-nums">
                            {video.completedSteps}/{video.stepTotal}
                          </span>
                        </div>
                      </div>
                    </div>
                    <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-muted">
                      <div
                        className="h-full rounded-full bg-primary"
                        style={{ width: `${progress}%` }}
                      />
                    </div>
                  </button>
                );
              })}
              {filteredVideoSummaries.length === 0 ? (
                <div className="rounded-lg border border-dashed border-border/70 px-3 py-4 text-xs text-muted-foreground">
                  Khong co video phu hop filter {storyStatusLabel(queueFilter)}.
                </div>
              ) : null}
            </div>
          </div>

          <Separator />

          <div className="flex flex-col gap-2">
            <div className="text-xs font-medium uppercase text-muted-foreground">
              Workers
            </div>
            <div className="flex flex-col gap-2">
              {workerSlots.map((video, index) => (
                <div
                  key={`worker-${index + 1}`}
                  className="flex items-center justify-between rounded-lg border border-border/70 bg-muted/30 px-2 py-2 text-xs"
                >
                  <span className="text-muted-foreground">W{index + 1}</span>
                  <span className="max-w-[11rem] truncate text-right text-foreground">
                    {video ? video.name : "Idle"}
                  </span>
                </div>
              ))}
            </div>
          </div>

          <Button
            type="button"
            variant="outline"
            size="sm"
            className="w-full"
            disabled={!settingsDraft?.output_root?.trim()}
            onClick={() => void handleOpenOutputFolder()}
          >
            <FolderOpen className="size-4" />
            Open output folder
          </Button>
        </CardContent>
      </Card>

      <Card className="border-border/70 shadow-[0_24px_90px_rgba(15,23,42,0.08)]">
        <CardHeader className="gap-2 border-b border-border/70">
          <CardTitle className="flex items-center justify-between text-base">
            <span>{selectedVideo?.name ?? "Timeline Marker"}</span>
            {selectedVideo ? (
              <Badge variant="outline" className={storyStatusTone(selectedVideo.status).className}>
                {storyStatusLabel(selectedVideo.status)}
              </Badge>
            ) : null}
          </CardTitle>
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <span>Mode: {selectedVideo?.mode ?? "-"}</span>
            {detailLoading ? (
              <span className="inline-flex items-center gap-1">
                <Loader2 className="size-3 animate-spin" />
                syncing
              </span>
            ) : null}
          </div>
        </CardHeader>
        <CardContent className="flex h-[calc(100dvh-10rem)] flex-col gap-4 pt-4">
          <div className="flex-1 overflow-auto pr-1">
            {!selectedVideo ? (
              <div className="rounded-xl border border-border/70 bg-muted/20 px-4 py-5 text-sm text-muted-foreground">
                Chua co video. Hay import manifest de bat dau.
              </div>
            ) : (
              <div className="flex flex-col gap-4">
                {[
                  { key: "active", title: "Active", markers: markerGroups.active },
                  { key: "queued", title: "Queued", markers: markerGroups.queued },
                  { key: "done", title: "Done", markers: markerGroups.done },
                ].map((group) => (
                  <div key={group.key} className="flex flex-col gap-2">
                    <div className="text-xs font-medium uppercase text-muted-foreground">
                      {group.title}
                    </div>
                    <div className="flex flex-col gap-2">
                      {group.markers.length === 0 ? (
                        <div className="rounded-lg border border-dashed border-border/70 px-3 py-2 text-xs text-muted-foreground">
                          Khong co marker
                        </div>
                      ) : null}
                      {group.markers.map((marker) => {
                        const expanded = expandedMarkerIds.includes(marker.id);
                        const markerTone = storyStatusTone(marker.status);
                        return (
                          <div
                            key={marker.id}
                            className={cn(
                              "rounded-xl border border-border/70 bg-card/40",
                              marker.id === selectedMarkerId ? "border-primary/60 bg-primary/8" : "",
                            )}
                          >
                            <button
                              type="button"
                              onClick={() => {
                                setSelectedMarkerId(marker.id);
                                handleToggleMarker(marker.id);
                              }}
                              className="flex w-full items-center justify-between px-3 py-2 text-left"
                            >
                              <div className="min-w-0">
                                <div className="truncate text-sm font-medium text-foreground">
                                  M{String(marker.index).padStart(3, "0")} · {marker.label}
                                </div>
                                <div className="mt-0.5 text-xs text-muted-foreground tabular-nums">
                                  {formatTimestampMs(marker.timestampMs)}
                                </div>
                              </div>
                              <Badge variant={markerTone.variant} className={markerTone.className}>
                                {storyStatusLabel(marker.status)}
                              </Badge>
                            </button>

                            {expanded ? (
                              <div className="border-t border-border/60 px-3 py-3">
                                <div className="flex overflow-x-auto pb-1">
                                  <div className="flex min-w-max items-start gap-2">
                                    {orderedSteps(marker.steps).map((step, index, allSteps) => {
                                      const latestAttempt = step.attempts.at(-1);
                                      const inputPath = latestAttempt?.inputImagePath ?? marker.inputFramePath;
                                      const outputPath = latestAttempt?.previewPath ?? latestAttempt?.normalizedPath ?? null;
                                      const normalizedReady = Boolean(latestAttempt?.normalizedPath);
                                      const stepBusyAccept =
                                        actionBusyKey === selectionKey("accept", marker.id, step.id);
                                      const stepBusyRegen =
                                        actionBusyKey === selectionKey("regenerate", marker.id, step.id);
                                      const stepBusyRefine =
                                        actionBusyKey === selectionKey("refine", marker.id, step.id);
                                      const stepSelected =
                                        selectedMarkerId === marker.id && selectedStepId === step.id;
                                      return (
                                        <div key={step.id} className="flex items-start gap-2">
                                          <div
                                            className={cn(
                                              "w-64 rounded-lg border border-border/70 bg-background/55 p-2",
                                              stepSelected ? "border-primary/60 bg-primary/8" : "",
                                            )}
                                          >
                                            <button
                                              type="button"
                                              onClick={() => {
                                                setSelectedMarkerId(marker.id);
                                                setSelectedStepId(step.id);
                                                setSelectedAttemptId(
                                                  step.selectedAttemptId ?? step.attempts.at(-1)?.id ?? null,
                                                );
                                              }}
                                              className="mb-2 w-full rounded-md px-1 py-1 text-left text-sm font-medium text-foreground hover:bg-muted/40"
                                            >
                                              {step.title}
                                            </button>
                                            <div className="grid grid-cols-2 gap-2">
                                              <VideoThumb
                                                path={inputPath}
                                                alt={`${step.title} input`}
                                                className="h-20 w-full"
                                              />
                                              <div className="relative">
                                                <VideoThumb
                                                  path={outputPath}
                                                  alt={`${step.title} output`}
                                                  className="h-20 w-full"
                                                />
                                                {normalizedReady ? (
                                                  <span className="absolute right-1 top-1 inline-flex items-center gap-1 rounded-full border border-emerald-300/40 bg-emerald-500/20 px-2 py-0.5 text-[10px] text-emerald-100">
                                                    <Check className="size-3" />
                                                    norm
                                                  </span>
                                                ) : null}
                                              </div>
                                            </div>
                                            <div className="mt-2 flex gap-1">
                                              <Button
                                                type="button"
                                                size="sm"
                                                className="flex-1"
                                                disabled={step.status !== "review" || stepBusyAccept}
                                                onClick={() =>
                                                  void runStepAction(
                                                    "accept",
                                                    marker.id,
                                                    step.id,
                                                    step.selectedAttemptId ?? step.attempts.at(-1)?.id,
                                                  )
                                                }
                                              >
                                                {stepBusyAccept ? (
                                                  <Loader2 className="size-3 animate-spin" />
                                                ) : (
                                                  "Accept"
                                                )}
                                              </Button>
                                              <Button
                                                type="button"
                                                size="sm"
                                                variant="outline"
                                                disabled={step.status !== "review" || stepBusyRegen}
                                                onClick={() => void runStepAction("regenerate", marker.id, step.id)}
                                              >
                                                {stepBusyRegen ? (
                                                  <Loader2 className="size-3 animate-spin" />
                                                ) : (
                                                  <RotateCcw className="size-3" />
                                                )}
                                              </Button>
                                              <Button
                                                type="button"
                                                size="sm"
                                                variant="outline"
                                                disabled={
                                                  step.status !== "review" ||
                                                  !step.attempts.at(-1)?.normalizedPath ||
                                                  stepBusyRefine
                                                }
                                                onClick={() =>
                                                  void runStepAction(
                                                    "refine",
                                                    marker.id,
                                                    step.id,
                                                    step.attempts.at(-1)?.id,
                                                  )
                                                }
                                              >
                                                {stepBusyRefine ? (
                                                  <Loader2 className="size-3 animate-spin" />
                                                ) : (
                                                  <Sparkles className="size-3" />
                                                )}
                                              </Button>
                                            </div>
                                          </div>
                                          {selectedVideo?.mode === "chain" && index < allSteps.length - 1 ? (
                                            <div className="pt-24 text-muted-foreground">
                                              <ChevronRight className="size-4" />
                                            </div>
                                          ) : null}
                                        </div>
                                      );
                                    })}
                                  </div>
                                </div>
                              </div>
                            ) : null}
                          </div>
                        );
                      })}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          <Separator />
          <div className="rounded-lg border border-border/70 bg-muted/35 px-3 py-2 text-xs text-muted-foreground">
            {selectedVideo ? (
              <span className="tabular-nums">
                {selectedVideo.name} &gt; M{selectedMarker ? String(selectedMarker.index).padStart(3, "0") : "---"} &gt;{" "}
                {selectedStep?.title ?? "Step"} · Attempt {selectedAttempt?.index ?? 0}
              </span>
            ) : (
              "No active selection"
            )}
          </div>
        </CardContent>
      </Card>

      <Card className="border-border/70 shadow-[0_24px_90px_rgba(15,23,42,0.08)]">
        <CardHeader className="gap-2 border-b border-border/70">
          <CardTitle className="text-base">Prompt + Control</CardTitle>
        </CardHeader>
        <CardContent className="flex h-[calc(100dvh-10rem)] flex-col gap-4 pt-4">
          <div className="flex-1 overflow-auto pr-1">
            <div className="flex flex-col gap-4">
              <Alert>
                <AlertTitle className="flex items-center gap-2">
                  {sessionStatus?.authenticated ? "Gemini Ready" : "Gemini Chua Ready"}
                  {sessionStatus?.authenticated ? (
                    <Badge variant="outline" className="border-emerald-400/40 bg-emerald-500/12 text-emerald-100">
                      connected
                    </Badge>
                  ) : (
                    <Badge variant="outline">offline</Badge>
                  )}
                </AlertTitle>
                <AlertDescription className="text-xs">
                  {sessionStatus?.message ?? "Chua co thong tin session."}
                </AlertDescription>
              </Alert>

              <div className="grid grid-cols-2 gap-2">
                <Button type="button" variant="outline" onClick={() => void handleOpenLogin()}>
                  Open Login
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  disabled={sessionRefreshing}
                  onClick={() => void handleRefreshSession()}
                >
                  {sessionRefreshing ? (
                    <Loader2 className="size-4 animate-spin" />
                  ) : (
                    <RefreshCw className="size-4" />
                  )}
                  Refresh
                </Button>
              </div>

              <div className="rounded-xl border border-border/70 bg-muted/20 p-3">
                <div className="mb-2 text-xs font-medium uppercase text-muted-foreground">
                  Import Manifest
                </div>
                <div className="flex gap-2">
                  <Input
                    value={manifestPath}
                    onChange={(event) => setManifestPath(event.target.value)}
                    placeholder="D:\\projects\\story\\markers.json"
                  />
                  <Button
                    type="button"
                    variant="outline"
                    disabled={importingManifest}
                    onClick={() => void handleImportManifest()}
                  >
                    {importingManifest ? (
                      <Loader2 className="size-4 animate-spin" />
                    ) : (
                      <Upload className="size-4" />
                    )}
                  </Button>
                </div>
              </div>

              {settingsDraft ? (
                <div className="rounded-xl border border-border/70 bg-muted/20 p-3">
                  <div className="mb-2 text-xs font-medium uppercase text-muted-foreground">
                    Scheduler
                  </div>
                  <div className="flex flex-col gap-3">
                    <div className="flex flex-col gap-1">
                      <label className="text-xs text-muted-foreground" htmlFor="story-workers">
                        Max workers
                      </label>
                      <Input
                        id="story-workers"
                        type="number"
                        min={1}
                        max={8}
                        value={settingsDraft.max_parallel_videos}
                        onChange={(event) =>
                          setSettingsDraft((current) =>
                            current
                              ? {
                                  ...current,
                                  max_parallel_videos: Math.min(
                                    8,
                                    Math.max(1, Number(event.target.value) || 1),
                                  ),
                                }
                              : current,
                          )
                        }
                      />
                    </div>

                    <div className="flex flex-col gap-1">
                      <label className="text-xs text-muted-foreground">Backend</label>
                      <Select
                        value={settingsDraft.generation_backend}
                        onValueChange={(value) =>
                          setSettingsDraft((current) =>
                            current
                              ? {
                                  ...current,
                                  generation_backend: value,
                                }
                              : current,
                          )
                        }
                      >
                        <SelectTrigger>
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectGroup>
                            <SelectLabel>Generation</SelectLabel>
                            <SelectItem value="local_preview">local_preview</SelectItem>
                            <SelectItem value="gemini_web">gemini_web</SelectItem>
                          </SelectGroup>
                        </SelectContent>
                      </Select>
                    </div>

                    <div className="flex items-center justify-between rounded-lg border border-border/70 px-3 py-2">
                      <span className="text-sm text-foreground">Selector debug</span>
                      <Switch
                        checked={settingsDraft.gemini_selector_debug}
                        onCheckedChange={(checked) =>
                          setSettingsDraft((current) =>
                            current
                              ? {
                                  ...current,
                                  gemini_selector_debug: checked,
                                }
                              : current,
                          )
                        }
                      />
                    </div>

                    <div className="flex flex-col gap-1">
                      <label className="text-xs text-muted-foreground" htmlFor="debug-dir">
                        Debug dir
                      </label>
                      <Input
                        id="debug-dir"
                        value={settingsDraft.gemini_selector_debug_dir}
                        onChange={(event) =>
                          setSettingsDraft((current) =>
                            current
                              ? {
                                  ...current,
                                  gemini_selector_debug_dir: event.target.value,
                                }
                              : current,
                          )
                        }
                        placeholder="D:\\gemini-debug"
                      />
                    </div>

                    <Button
                      type="button"
                      disabled={savingSettings}
                      variant="outline"
                      onClick={() => void handleSaveSettings()}
                    >
                      {savingSettings ? (
                        <Loader2 className="size-4 animate-spin" />
                      ) : (
                        "Save settings"
                      )}
                    </Button>
                  </div>
                </div>
              ) : null}

              <div className="flex flex-col gap-3 rounded-xl border border-border/70 bg-muted/20 p-3">
                <div className="flex items-center gap-2 text-xs font-medium uppercase text-muted-foreground">
                  <Badge className="bg-primary/85 text-primary-foreground">Global</Badge>
                  base prompt
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
                  {savingPrompt ? <Loader2 className="size-4 animate-spin" /> : "Save global prompt"}
                </Button>
              </div>

              <div className="flex flex-col gap-3 rounded-xl border border-border/70 bg-muted/20 p-3">
                <div className="flex items-center gap-2 text-xs font-medium uppercase text-muted-foreground">
                  <Badge className="bg-indigo-500/80 text-indigo-50">Video</Badge>
                  context prompt
                </div>
                <Textarea value={selectedVideo?.videoPrompt ?? ""} readOnly className="min-h-16" />
              </div>

              <div className="flex flex-col gap-3 rounded-xl border border-border/70 bg-muted/20 p-3">
                <div className="flex items-center gap-2 text-xs font-medium uppercase text-muted-foreground">
                  <Badge className="bg-amber-500/80 text-amber-50">Step</Badge>
                  seed + modifier
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
                <div className="text-xs font-medium uppercase text-muted-foreground">
                  Merged prompt preview
                </div>
                <Textarea value={mergedPrompt} readOnly className="min-h-24 text-xs" />
              </div>

              <div className="flex flex-col gap-3 rounded-xl border border-border/70 bg-muted/20 p-3">
                <div className="text-xs font-medium uppercase text-muted-foreground">
                  Attempt history
                </div>
                <div className="flex gap-2 overflow-x-auto pb-1">
                  {selectedStep?.attempts
                    ?.slice()
                    .reverse()
                    .map((attempt) => {
                      const selected = selectedAttempt?.id === attempt.id;
                      return (
                        <button
                          key={attempt.id}
                          type="button"
                          onClick={() => setSelectedAttemptId(attempt.id)}
                          className={cn(
                            "w-24 shrink-0 rounded-lg border p-1.5 text-left",
                            selected
                              ? "border-primary/70 bg-primary/12"
                              : "border-border/70 bg-background/50",
                          )}
                        >
                          <VideoThumb
                            path={attempt.previewPath ?? attempt.normalizedPath}
                            alt={`Attempt ${attempt.index}`}
                            className="h-14 w-full"
                          />
                          <div className="mt-1 truncate text-[11px] text-foreground">
                            A{attempt.index} · {attempt.mode}
                          </div>
                        </button>
                      );
                    })}
                  {!selectedStep || selectedStep.attempts.length === 0 ? (
                    <div className="rounded-lg border border-dashed border-border/70 px-3 py-4 text-xs text-muted-foreground">
                      Chua co attempt.
                    </div>
                  ) : null}
                </div>
              </div>
            </div>
          </div>

          <Separator />
          <div className="flex flex-col gap-2">
            <div className="grid grid-cols-2 gap-2">
              <Button
                type="button"
                variant="outline"
                disabled={!selectedVideoId || actionBusyKey === "video:run"}
                onClick={() => void handleRunVideo()}
              >
                {actionBusyKey === "video:run" ? (
                  <Loader2 className="size-4 animate-spin" />
                ) : (
                  <Play className="size-4" />
                )}
                Run
              </Button>
              <Button
                type="button"
                variant="outline"
                disabled={!selectedVideoId || actionBusyKey === "video:pause"}
                onClick={() => void handlePauseVideo()}
              >
                {actionBusyKey === "video:pause" ? (
                  <Loader2 className="size-4 animate-spin" />
                ) : (
                  <Pause className="size-4" />
                )}
                Pause
              </Button>
              <Button
                type="button"
                variant="outline"
                disabled={
                  !selectedMarkerId ||
                  !selectedStepId ||
                  selectedStep?.status !== "review" ||
                  actionBusyKey === selectionKey("regenerate", selectedMarkerId, selectedStepId)
                }
                onClick={() => {
                  if (!selectedMarkerId || !selectedStepId) {
                    return;
                  }
                  void runStepAction("regenerate", selectedMarkerId, selectedStepId);
                }}
              >
                <RotateCcw className="size-4" />
                Regen
              </Button>
              <Button
                type="button"
                variant="outline"
                disabled={
                  !selectedMarkerId ||
                  !selectedStepId ||
                  !selectedAttempt?.id ||
                  selectedStep?.status !== "review" ||
                  actionBusyKey === selectionKey("refine", selectedMarkerId, selectedStepId)
                }
                onClick={() => {
                  if (!selectedMarkerId || !selectedStepId || !selectedAttempt?.id) {
                    return;
                  }
                  void runStepAction("refine", selectedMarkerId, selectedStepId, selectedAttempt.id);
                }}
              >
                <Sparkles className="size-4" />
                Refine
              </Button>
            </div>

            <Button
              type="button"
              className="w-full"
              disabled={!selectedMarkerId || !selectedStepId || selectedStep?.status !== "review" || actionBusyKey === "step:accept-next"}
              onClick={() => void handleAcceptAndNext()}
            >
              {actionBusyKey === "step:accept-next" ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <Check className="size-4" />
              )}
              Accept & Next
            </Button>

            <Button
              type="button"
              variant="ghost"
              className="w-full"
              disabled={!selectedMarkerId || !selectedStepId}
              onClick={() => {
                if (!selectedMarkerId || !selectedStepId) {
                  return;
                }
                void runStepAction("skip", selectedMarkerId, selectedStepId);
              }}
            >
              <AlertCircle className="size-4" />
              Skip Step
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
