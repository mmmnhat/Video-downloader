import { startTransition, useCallback, useEffect, useMemo, useState } from "react";
import { Archive, CircleHelp, FolderOpen, Loader2, RefreshCw, Trash2 } from "lucide-react";
import { toast } from "sonner";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { TAB_CARD_GAP_CLASS } from "@/lib/layout";
import { cn } from "@/lib/utils";
import {
  clearCache,
  getCacheBootstrap,
  openFolder,
  type CacheBootstrapPayload,
  type CacheGroup,
} from "@/lib/api";

function getErrorMessage(error: unknown) {
  return error instanceof Error ? error.message : "Yêu cầu thất bại.";
}

function formatBytes(value: number) {
  if (!Number.isFinite(value) || value <= 0) {
    return "0 B";
  }
  const units = ["B", "KB", "MB", "GB", "TB"];
  let size = value;
  let unitIndex = 0;
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024;
    unitIndex += 1;
  }
  return `${size >= 100 || unitIndex === 0 ? size.toFixed(0) : size.toFixed(1)} ${units[unitIndex]}`;
}

function featureLabel(feature: string) {
  if (feature === "story") {
    return "Tạo ảnh AI";
  }
  if (feature === "tts") {
    return "Lồng tiếng (TTS)";
  }
  return feature;
}

export default function CacheManager() {
  const [payload, setPayload] = useState<CacheBootstrapPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async (silent = false) => {
    if (!silent) {
      setLoading(true);
    }
    setError("");
    try {
      const next = await getCacheBootstrap();
      startTransition(() => setPayload(next));
    } catch (loadError) {
      const message = getErrorMessage(loadError);
      setError(message);
      if (silent) {
        toast.error(message);
      }
    } finally {
      if (!silent) {
        setLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    void load(false);
  }, [load]);

  const featureGroups = useMemo(() => {
    const groups = payload?.groups ?? [];
    return {
      story: groups.filter((group) => group.feature === "story"),
      tts: groups.filter((group) => group.feature === "tts"),
    };
  }, [payload?.groups]);

  const handleOpen = useCallback(async (group: CacheGroup) => {
    try {
      await openFolder(group.openPath);
    } catch (openError) {
      toast.error(getErrorMessage(openError));
    }
  }, []);

  const handleClear = useCallback(async (cacheId: string) => {
    setBusyId(cacheId);
    try {
      const result = await clearCache(cacheId);
      startTransition(() => setPayload(result.bootstrap));
      if (result.cleared.length > 0) {
        toast.success(`Đã giải phóng ${formatBytes(result.removedBytes)} cache.`);
      } else {
        toast.info("Không có cache nào được xoá.");
      }
      if (result.skipped.length > 0) {
        toast.warning("Một số nhóm cache đang được sử dụng nên chưa thể xoá.");
      }
    } catch (clearError) {
      toast.error(getErrorMessage(clearError));
    } finally {
      setBusyId(null);
    }
  }, []);

  if (loading) {
    return (
      <Card className="border-border/70 shadow-[0_24px_90px_rgba(15,23,42,0.08)]">
        <CardContent className="flex items-center justify-center gap-3 py-16 text-sm text-muted-foreground">
          <Loader2 className="size-4 animate-spin" />
          Đang tải thông tin cache...
        </CardContent>
      </Card>
    );
  }

  return (
    <div className={`flex flex-col ${TAB_CARD_GAP_CLASS}`}>
      {error ? (
        <Alert variant="destructive">
          <AlertTitle>Không tải được cache</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_22rem]">
        <Card className="border-border/70 shadow-[0_24px_90px_rgba(15,23,42,0.08)]">
          <CardHeader className="flex flex-row items-start justify-between gap-4 space-y-0">
            <div className="space-y-1">
              <CardTitle className="flex items-center gap-2">
                <Archive className="size-4" />
                Quản lý bộ nhớ đệm
              </CardTitle>
            </div>
            <div className="flex gap-2">
              <Button type="button" variant="outline" onClick={() => void load(true)} disabled={busyId !== null}>
                <RefreshCw className="size-4" />
                Làm mới
              </Button>
              <Button
                type="button"
                variant="destructive"
                onClick={() => void handleClear("all")}
                disabled={busyId !== null}
              >
                {busyId === "all" ? <Loader2 className="size-4 animate-spin" /> : <Trash2 className="size-4" />}
                Xoá tất cả
              </Button>
            </div>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="grid gap-3 sm:grid-cols-3">
              <div className="rounded-xl border border-border/70 bg-muted/20 p-3">
                <div className="text-xs text-muted-foreground">Tổng dung lượng</div>
                <div className="mt-1 text-lg font-semibold">
                  {formatBytes(payload?.summary.totalSizeBytes ?? 0)}
                </div>
              </div>
              <div className="rounded-xl border border-border/70 bg-muted/20 p-3">
                <div className="text-xs text-muted-foreground">Tổng tệp</div>
                <div className="mt-1 text-lg font-semibold">
                  {(payload?.summary.totalFileCount ?? 0).toLocaleString("en-US")}
                </div>
              </div>
              <div className="rounded-xl border border-border/70 bg-muted/20 p-3">
                <div className="text-xs text-muted-foreground">Nhóm tồn tại</div>
                <div className="mt-1 text-lg font-semibold">
                  {payload?.summary.existingGroupCount ?? 0}/{payload?.summary.groupCount ?? 0}
                </div>
              </div>
            </div>

            <div className="rounded-xl border border-border/70 bg-muted/20 p-3 text-sm">
              <div className="text-xs text-muted-foreground uppercase tracking-wider font-bold">Thư mục gốc</div>
              <div className="mt-1 break-all font-mono text-xs opacity-80">{payload?.rootPath}</div>
            </div>
          </CardContent>
        </Card>

        <Card className="border-border/70 shadow-[0_24px_90px_rgba(15,23,42,0.08)]">
          <CardHeader>
            <CardTitle className="text-base">Lưu ý</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm text-muted-foreground">
            <p>- `Story Generated`: Ảnh trong quy trình tạo, không phải ảnh đã xuất.</p>
            <p>- `TTS Batches`: Âm thanh đã tạo; xóa xong sẽ không thể nghe lại hoặc xuất tệp cũ.</p>
            <p>- Nếu một nhóm đang được sử dụng, hệ thống sẽ chặn thao tác xóa để bảo vệ quy trình đang chạy.</p>
          </CardContent>
        </Card>
      </div>

      {(["story", "tts"] as const).map((feature) => {
        const groups = featureGroups[feature];
        return (
          <div key={feature} className="space-y-3">
            <div className="flex items-center gap-2">
              <h2 className="text-sm font-semibold">{featureLabel(feature)}</h2>
              <Badge variant="outline">{groups.length}</Badge>
            </div>
            <div className="grid gap-4 lg:grid-cols-2">
              {groups.map((group) => (
                <Card key={group.id} className="border-border/70 shadow-[0_24px_90px_rgba(15,23,42,0.08)]">
                  <CardHeader className="space-y-3">
                    <div className="flex items-start justify-between gap-3">
                      <div className="group/cache-tooltip relative inline-flex cursor-help items-center gap-1.5">
                        <CardTitle className="text-base">{group.title}</CardTitle>
                        <CircleHelp
                          className="size-3.5 shrink-0 text-muted-foreground/80 transition-colors group-hover/cache-tooltip:text-foreground"
                          aria-hidden="true"
                        />
                        <span
                          className={cn(
                            "pointer-events-none absolute left-0 top-full z-20 mt-2 w-64 rounded-md border border-border/80 bg-popover px-3 py-2 text-xs font-normal text-popover-foreground shadow-lg opacity-0 transition-opacity duration-150",
                            "group-hover/cache-tooltip:opacity-100"
                          )}
                          role="tooltip"
                        >
                          {group.description}
                        </span>
                      </div>
                      {group.active ? (
                        <Badge variant="secondary">Đang sử dụng</Badge>
                      ) : group.exists ? (
                        <Badge variant="outline">Sẵn sàng</Badge>
                      ) : (
                        <Badge variant="outline">Trống</Badge>
                      )}
                    </div>
                    <div className="grid grid-cols-3 gap-2 text-sm">
                      <div className="rounded-lg border border-border/70 bg-muted/20 p-2">
                        <div className="text-[11px] text-muted-foreground">Dung lượng</div>
                        <div className="mt-1 font-medium">{formatBytes(group.sizeBytes)}</div>
                      </div>
                      <div className="rounded-lg border border-border/70 bg-muted/20 p-2">
                        <div className="text-[11px] text-muted-foreground">Tệp</div>
                        <div className="mt-1 font-medium">{group.fileCount.toLocaleString("en-US")}</div>
                      </div>
                      <div className="rounded-lg border border-border/70 bg-muted/20 p-2">
                        <div className="text-[11px] text-muted-foreground">Thư mục</div>
                        <div className="mt-1 font-medium">{group.dirCount.toLocaleString("en-US")}</div>
                      </div>
                    </div>
                  </CardHeader>
                  <CardContent className="space-y-3">
                    <div className="rounded-xl border border-border/70 bg-muted/20 p-3">
                      <div className="text-[11px] text-muted-foreground uppercase tracking-wider font-bold">Đường dẫn</div>
                      <div className="mt-1 break-all font-mono text-xs opacity-80">{group.path}</div>
                    </div>
                    <div className="flex gap-2">
                      <Button type="button" variant="outline" onClick={() => void handleOpen(group)}>
                        <FolderOpen className="size-4" />
                        Mở
                      </Button>
                      <Button
                        type="button"
                        variant="destructive"
                        disabled={!group.canDelete || busyId !== null}
                        onClick={() => void handleClear(group.id)}
                      >
                        {busyId === group.id ? (
                          <Loader2 className="size-4 animate-spin" />
                        ) : (
                          <Trash2 className="size-4" />
                        )}
                        Xoá
                      </Button>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}
