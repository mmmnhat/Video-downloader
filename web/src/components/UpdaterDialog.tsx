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
      setError(err.message || "Failed to check for updates");
      toast.error("Could not reach update server");
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
      toast.success("Update downloaded! App will restart in 5 seconds...");
      setOpen(false);
    } catch (err: any) {
      setError(err.message || "Failed to install update");
    } finally {
      setApplying(false);
    }
  }, [status]);

  return (
    <AlertDialog open={open} onOpenChange={setOpen}>
      <AlertDialogTrigger asChild>
        <Button 
            variant="ghost" 
            className="w-full justify-center lg:justify-start lg:text-muted-foreground hover:lg:text-foreground"
            onClick={handleOpenInfo}
        >
          <Info className="w-4 h-4 lg:mr-2" />
          <span className="hidden lg:block">App Info & Updates</span>
        </Button>
      </AlertDialogTrigger>
      
      <AlertDialogContent className="sm:max-w-[425px]">
        <AlertDialogTitle>System Information</AlertDialogTitle>
        <AlertDialogDescription>
          Check for the latest features and patches.
        </AlertDialogDescription>

        <div className="py-4 space-y-4">
          <div className="flex flex-col gap-1.5">
             <span className="text-sm font-semibold">Current Version</span>
             <Badge variant="outline" className="w-fit">{status?.currentVersion || "..."}</Badge>
          </div>

          {error && (
             <Alert variant="destructive">
               <ServerCrash className="w-4 h-4" />
               <AlertTitle>Error</AlertTitle>
               <AlertDescription className="text-xs">{error}</AlertDescription>
             </Alert>
          )}

          {status?.isPlaceholder && (
               <Alert className="bg-yellow-50 text-yellow-900 border-yellow-200">
               <AlertTitle>Placeholder Mode</AlertTitle>
               <AlertDescription className="text-xs">
                  Auto-update is currently deactivated because the GitHub repository has not been set up. Edit the runtime config to link a repository.
               </AlertDescription>
             </Alert>
          )}

          {status && !status.isPlaceholder && status.updateAvailable && (
             <div className="p-4 rounded-lg bg-emerald-50 border border-emerald-200 text-emerald-900 space-y-3">
                <div className="flex items-center gap-2 font-bold">
                   <Download className="w-4 h-4" />
                   New update available: {status.latestVersion}
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
                You are on the latest version.
             </div>
          )}
        </div>

        <div className="flex flex-col sm:flex-row gap-2 justify-end mt-4">
          <AlertDialogCancel disabled={applying}>Close</AlertDialogCancel>
          {!status?.updateAvailable ? (
              <Button disabled={loading || applying} onClick={handleCheck}>
                {loading ? <RefreshCw className="w-4 h-4 mr-2 animate-spin" /> : <RefreshCw className="w-4 h-4 mr-2" />}
                Check Again
              </Button>
          ) : (
              <Button disabled={loading || applying} onClick={handleApply}>
                {applying ? <RefreshCw className="w-4 h-4 mr-2 animate-spin" /> : "Install & Restart"}
              </Button>
          )}
        </div>
      </AlertDialogContent>
    </AlertDialog>
  );
}
