import { useCallback, useEffect, useState } from "react";
import {
  CheckCircle2,
  Download,
  Info,
  Loader2,
  RefreshCw,
  ServerCrash,
} from "lucide-react";
import { toast } from "sonner";

import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { applyUpdate, checkUpdate, type UpdateStatus } from "@/lib/api";

type UpdateProgressEvent = {
  percent: number;
  message: string;
};

type UpdateErrorEvent = {
  error: string;
};

function getErrorMessage(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback;
}

export default function UpdaterDialog() {
  const [open, setOpen] = useState(false);
  const [status, setStatus] = useState<UpdateStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [applying, setApplying] = useState(false);
  const [error, setError] = useState("");
  const [progress, setProgress] = useState(0);
  const [progressMsg, setProgressMsg] = useState("");

  const handleCheck = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const data = await checkUpdate();
      setStatus(data);
    } catch (loadError) {
      setError(
        getErrorMessage(loadError, "Không thể kiểm tra bản cập nhật"),
      );
      toast.error("Không thể kết nối máy chủ cập nhật");
    } finally {
      setLoading(false);
    }
  }, []);

  const handleOpenInfo = useCallback(() => {
    void handleCheck();
    setOpen(true);
  }, [handleCheck]);

  useEffect(() => {
    if (!applying) {
      return;
    }

    const source = new EventSource("/api/events");

    const handleProgress = (event: Event) => {
      const messageEvent = event as MessageEvent<string>;
      const data = JSON.parse(messageEvent.data) as UpdateProgressEvent;
      setProgress(data.percent);
      setProgressMsg(data.message);

      if (data.percent >= 100) {
        window.setTimeout(() => source.close(), 1000);
      }
    };

    const handleUpdateError = (event: Event) => {
      const messageEvent = event as MessageEvent<string>;
      const data = JSON.parse(messageEvent.data) as UpdateErrorEvent;
      setError(data.error);
      setApplying(false);
      source.close();
    };

    source.addEventListener("update.progress", handleProgress);
    source.addEventListener("update.error", handleUpdateError);

    source.onerror = () => {
      if (progress < 100) {
        source.close();
      }
    };

    return () => {
      source.removeEventListener("update.progress", handleProgress);
      source.removeEventListener("update.error", handleUpdateError);
      source.close();
    };
  }, [applying, progress]);

  const handleApply = useCallback(async () => {
    if (!status?.downloadUrl) {
      return;
    }
    setApplying(true);
    setError("");
    setProgress(0);
    setProgressMsg("Đang bắt đầu...");

    try {
      await applyUpdate(status.downloadUrl);
    } catch (applyError) {
      setError(
        getErrorMessage(applyError, "Không thể cài đặt bản cập nhật"),
      );
      setApplying(false);
    }
  }, [status]);

  return (
    <AlertDialog open={open} onOpenChange={setOpen}>
      <AlertDialogTrigger asChild>
        <Button
          variant="ghost"
          className="w-full justify-center text-muted-foreground hover:text-foreground"
          onClick={handleOpenInfo}
          title="Thông tin và cập nhật"
        >
          <Info className="h-4 w-4" />
          <span className="sr-only">Thông tin và cập nhật</span>
        </Button>
      </AlertDialogTrigger>

      <AlertDialogContent className="sm:max-w-[425px]">
        <AlertDialogTitle>Thông tin hệ thống</AlertDialogTitle>
        <AlertDialogDescription>
          Kiểm tra các tính năng và bản vá mới nhất.
        </AlertDialogDescription>

        <div className="space-y-4 py-4">
          <div className="flex flex-col gap-1.5">
            <span className="text-sm font-semibold">Phiên bản hiện tại</span>
            <Badge variant="outline" className="w-fit">
              {status?.currentVersion || "..."}
            </Badge>
          </div>

          {error ? (
            <Alert variant="destructive">
              <ServerCrash className="h-4 w-4" />
              <AlertTitle>Lỗi</AlertTitle>
              <AlertDescription className="text-xs">{error}</AlertDescription>
            </Alert>
          ) : null}

          {status?.isPlaceholder ? (
            <Alert className="border-yellow-200 bg-yellow-50 text-yellow-900">
              <AlertTitle>Chế độ Placeholder</AlertTitle>
              <AlertDescription className="text-xs">
                Tự động cập nhật hiện đang tắt vì chưa cấu hình repository
                GitHub. Hãy chỉnh runtime config để liên kết repository.
              </AlertDescription>
            </Alert>
          ) : null}

          {status && !status.isPlaceholder && status.updateAvailable && !applying ? (
            <div className="space-y-3 rounded-lg border border-emerald-200 bg-emerald-50 p-4 text-emerald-900">
              <div className="flex items-center gap-2 font-bold">
                <Download className="h-4 w-4" />
                Có bản cập nhật mới: {status.latestVersion}
              </div>
              {status.releaseNotes ? (
                <div className="max-h-32 overflow-y-auto whitespace-pre-line text-xs opacity-80">
                  {status.releaseNotes}
                </div>
              ) : null}
            </div>
          ) : null}

          {applying ? (
            <div className="space-y-4 rounded-lg border bg-slate-50 p-4">
              <div className="mb-1 flex items-center justify-between text-sm">
                <span className="flex items-center gap-2 font-medium text-slate-700">
                  <Loader2 className="h-3 w-3 animate-spin" />
                  {progressMsg || "Đang xử lý..."}
                </span>
                <span className="text-slate-500">{progress}%</span>
              </div>
              <Progress value={progress} className="h-2" />
              <p className="text-[10px] italic text-slate-400">
                Vui lòng không đóng ứng dụng trong khi đang cập nhật.
              </p>
            </div>
          ) : null}

          {status && !status.isPlaceholder && !status.updateAvailable ? (
            <div className="flex items-center gap-2 rounded-md border bg-muted p-3 text-sm text-muted-foreground">
              <CheckCircle2 className="h-4 w-4 text-emerald-500" />
              Bạn đang dùng phiên bản mới nhất.
            </div>
          ) : null}
        </div>

        <div className="mt-4 flex flex-col justify-end gap-2 sm:flex-row">
          <AlertDialogCancel disabled={applying}>Đóng</AlertDialogCancel>
          {!status?.updateAvailable ? (
            <Button disabled={loading || applying} onClick={() => void handleCheck()}>
              {loading ? (
                <RefreshCw className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <RefreshCw className="mr-2 h-4 w-4" />
              )}
              Kiểm tra lại
            </Button>
          ) : (
            <Button disabled={loading || applying} onClick={() => void handleApply()}>
              {applying ? (
                <RefreshCw className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                "Cài đặt và khởi động lại"
              )}
            </Button>
          )}
        </div>
      </AlertDialogContent>
    </AlertDialog>
  );
}
