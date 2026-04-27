import { useState, useCallback } from "react";
import { Info, RefreshCw, Download, ServerCrash } from "lucide-react";
import { toast } from "sonner";
import { checkUpdate, applyUpdate, type UpdateStatus } from "@/lib/api";
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Alert, AlertTitle, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

export default function UpdaterDialog() {
  const [open, setOpen] = useState(false);
  const [status, setStatus] = useState<UpdateStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [applying, setApplying] = useState(false);
  const [error, setError] = useState("");

  const handleCheck = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const data = await checkUpdate();
      setStatus(data);
    } catch (err: any) {
      setError(err.message || "Không thể kiểm tra bản cập nhật");
      toast.error("Không thể kết nối máy chủ cập nhật");
    } finally {
      setLoading(false);
    }
  }, []);

  const handleOpenInfo = useCallback(() => {
    handleCheck();
    setOpen(true);
  }, [handleCheck]);

  const handleApply = useCallback(async () => {
    if (!status?.downloadUrl) return;
    setApplying(true);
    setError("");
    try {
      await applyUpdate(status.downloadUrl);
      toast.success("Đã tải bản cập nhật! Ứng dụng sẽ khởi động lại sau 5 giây...");
      setOpen(false);
    } catch (err: any) {
      setError(err.message || "Không thể cài đặt bản cập nhật");
    } finally {
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
            title="Thông tin & Cập nhật"
        >
          <Info className="w-4 h-4" />
          <span className="sr-only">Thông tin & Cập nhật</span>
        </Button>
      </AlertDialogTrigger>
      
      <AlertDialogContent className="sm:max-w-[425px]">
        <AlertDialogTitle>Thông tin hệ thống</AlertDialogTitle>
        <AlertDialogDescription>
          Kiểm tra các tính năng và bản vá mới nhất.
        </AlertDialogDescription>

        <div className="py-4 space-y-4">
          <div className="flex flex-col gap-1.5">
             <span className="text-sm font-semibold">Phiên bản hiện tại</span>
             <Badge variant="outline" className="w-fit">{status?.currentVersion || "..."}</Badge>
          </div>

          {error && (
             <Alert variant="destructive">
               <ServerCrash className="w-4 h-4" />
               <AlertTitle>Lỗi</AlertTitle>
               <AlertDescription className="text-xs">{error}</AlertDescription>
             </Alert>
          )}

          {status?.isPlaceholder && (
               <Alert className="bg-yellow-50 text-yellow-900 border-yellow-200">
               <AlertTitle>Chế độ Placeholder</AlertTitle>
               <AlertDescription className="text-xs">
                  Tự động cập nhật hiện đang tắt vì chưa cấu hình repository GitHub. Hãy chỉnh runtime config để liên kết repository.
               </AlertDescription>
             </Alert>
          )}

          {status && !status.isPlaceholder && status.updateAvailable && (
             <div className="p-4 rounded-lg bg-emerald-50 border border-emerald-200 text-emerald-900 space-y-3">
                <div className="flex items-center gap-2 font-bold">
                   <Download className="w-4 h-4" />
                   Có bản cập nhật mới: {status.latestVersion}
                </div>
                {status.releaseNotes && (
                    <div className="text-xs opacity-80 whitespace-pre-line max-h-32 overflow-y-auto">
                        {status.releaseNotes}
                    </div>
                )}
             </div>
          )}

          {status && !status.isPlaceholder && !status.updateAvailable && (
             <div className="text-sm text-muted-foreground p-3 bg-muted rounded-md border">
                Bạn đang dùng phiên bản mới nhất.
             </div>
          )}
        </div>

        <div className="flex flex-col sm:flex-row gap-2 justify-end mt-4">
          <AlertDialogCancel disabled={applying}>Đóng</AlertDialogCancel>
          {!status?.updateAvailable ? (
              <Button disabled={loading || applying} onClick={handleCheck}>
                {loading ? <RefreshCw className="w-4 h-4 mr-2 animate-spin" /> : <RefreshCw className="w-4 h-4 mr-2" />}
                Kiểm tra lại
              </Button>
          ) : (
              <Button disabled={loading || applying} onClick={handleApply}>
                {applying ? <RefreshCw className="w-4 h-4 mr-2 animate-spin" /> : "Cài đặt & Khởi động lại"}
              </Button>
          )}
        </div>
      </AlertDialogContent>
    </AlertDialog>
  );
}
