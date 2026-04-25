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
      setError(err.message || "KhÃ´ng thá»ƒ kiá»ƒm tra báº£n cáº­p nháº­t");
      toast.error("KhÃ´ng thá»ƒ káº¿t ná»‘i mÃ¡y chá»§ cáº­p nháº­t");
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
      toast.success("ÄÃ£ táº£i báº£n cáº­p nháº­t! á»¨ng dá»¥ng sáº½ khá»Ÿi Ä‘á»™ng láº¡i sau 5 giÃ¢y...");
      setOpen(false);
    } catch (err: any) {
      setError(err.message || "KhÃ´ng thá»ƒ cÃ i Ä‘áº·t báº£n cáº­p nháº­t");
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
        <AlertDialogTitle>ThÃ´ng tin há»‡ thá»‘ng</AlertDialogTitle>
        <AlertDialogDescription>
          Kiá»ƒm tra cÃ¡c tÃ­nh nÄƒng vÃ  báº£n vÃ¡ má»›i nháº¥t.
        </AlertDialogDescription>

        <div className="py-4 space-y-4">
          <div className="flex flex-col gap-1.5">
             <span className="text-sm font-semibold">PhiÃªn báº£n hiá»‡n táº¡i</span>
             <Badge variant="outline" className="w-fit">{status?.currentVersion || "..."}</Badge>
          </div>

          {error && (
             <Alert variant="destructive">
               <ServerCrash className="w-4 h-4" />
               <AlertTitle>Lá»—i</AlertTitle>
               <AlertDescription className="text-xs">{error}</AlertDescription>
             </Alert>
          )}

          {status?.isPlaceholder && (
               <Alert className="bg-yellow-50 text-yellow-900 border-yellow-200">
               <AlertTitle>Cháº¿ Ä‘á»™ Placeholder</AlertTitle>
               <AlertDescription className="text-xs">
                  Tá»± Ä‘á»™ng cáº­p nháº­t hiá»‡n Ä‘ang táº¯t vÃ¬ chÆ°a cáº¥u hÃ¬nh repository GitHub. HÃ£y chá»‰nh runtime config Ä‘á»ƒ liÃªn káº¿t repository.
               </AlertDescription>
             </Alert>
          )}

          {status && !status.isPlaceholder && status.updateAvailable && (
             <div className="p-4 rounded-lg bg-emerald-50 border border-emerald-200 text-emerald-900 space-y-3">
                <div className="flex items-center gap-2 font-bold">
                   <Download className="w-4 h-4" />
                   CÃ³ báº£n cáº­p nháº­t má»›i: {status.latestVersion}
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
                Báº¡n Ä‘ang dÃ¹ng phiÃªn báº£n má»›i nháº¥t.
             </div>
          )}
        </div>

        <div className="flex flex-col sm:flex-row gap-2 justify-end mt-4">
          <AlertDialogCancel disabled={applying}>ÄÃ³ng</AlertDialogCancel>
          {!status?.updateAvailable ? (
              <Button disabled={loading || applying} onClick={handleCheck}>
                {loading ? <RefreshCw className="w-4 h-4 mr-2 animate-spin" /> : <RefreshCw className="w-4 h-4 mr-2" />}
                Kiá»ƒm tra láº¡i
              </Button>
          ) : (
              <Button disabled={loading || applying} onClick={handleApply}>
                {applying ? <RefreshCw className="w-4 h-4 mr-2 animate-spin" /> : "CÃ i Ä‘áº·t & Khá»Ÿi Ä‘á»™ng láº¡i"}
              </Button>
          )}
        </div>
      </AlertDialogContent>
    </AlertDialog>
  );
}

