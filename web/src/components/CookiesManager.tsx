import { useCallback, useState, useMemo } from "react";
import type { Settings } from "@/lib/api";
import { scrapePlatformCookies } from "@/lib/api";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import {
  Search,
  Download,
  Trash2,
  RefreshCw,
  Info,
  Check,
  AlertCircle,
} from "lucide-react";
import { toast } from "sonner";

const PLATFORMS = [
  { id: "youtube", name: "YouTube", desc: "For Age-Restricted & Private Videos (Export from youtube.com)" },
  { id: "facebook", name: "Facebook", desc: "For private groups and posts (Export from facebook.com)" },
  { id: "instagram", name: "Instagram", desc: "For private accounts (Export from instagram.com)" },
  { id: "tiktok", name: "TikTok", desc: "For login-restricted clips (Export from tiktok.com)" },
  { id: "threads", name: "Threads", desc: "For Threads-specific media (Export from threads.net)" },
  { id: "x", name: "X (Twitter)", desc: "For age-restricted tweets (Export from x.com)" },
  { id: "telegram", name: "Telegram", desc: "For private channel posts (Export from t.me)" },
  { id: "dailymotion", name: "Dailymotion", desc: "For restricted content (Export from dailymotion.com)" },
  { id: "reddit", name: "Reddit", desc: "For NSFW or private subreddits (Export from reddit.com)" },
  { id: "dumpert", name: "Dumpert", desc: "For 18+ or logged-in videos (Export from dumpert.nl)" },
];

interface CookiesManagerProps {
  settings: Settings;
  onSettingsChange: (val: React.SetStateAction<Settings>) => void;
}

export default function CookiesManager({
  settings,
  onSettingsChange,
}: CookiesManagerProps) {
  const [searchTerm, setSearchTerm] = useState("");
  const [importingStates, setImportingStates] = useState<Record<string, boolean>>({});

  const updateCookie = useCallback(
    (platform: string, text: string) => {
      onSettingsChange((prev) => ({
        ...prev,
        cookies_map: {
          ...prev.cookies_map,
          [platform]: text,
        },
      }));
    },
    [onSettingsChange],
  );

  const handleImportFromBrowser = async (platformId: string, platformName: string) => {
    setImportingStates((prev) => ({ ...prev, [platformId]: true }));
    try {
      const result = await scrapePlatformCookies(platformId);
      if (result.cookies) {
        updateCookie(platformId, result.cookies);
        toast.success(`Successfully imported ${platformName} cookies from browser!`);
      } else {
        toast.error(`No cookies found for ${platformName} in your active browser profile.`);
      }
    } catch (error) {
      toast.error(`Failed to import cookies: ${error instanceof Error ? error.message : "Unknown error"}`);
    } finally {
      setImportingStates((prev) => ({ ...prev, [platformId]: false }));
    }
  };

  const handleClearAll = () => {
    if (confirm("Are you sure you want to clear ALL manual cookies? This cannot be undone.")) {
      onSettingsChange((prev) => ({
        ...prev,
        cookies_map: {},
      }));
      toast.success("All cookies cleared.");
    }
  };

  const handleMassImport = async () => {
    const activePlatforms = PLATFORMS.filter(p => !settings.cookies_map?.[p.id]);
    if (activePlatforms.length === 0) {
      toast.info("All platforms already have cookies or list is empty.");
      return;
    }

    toast.promise(
      Promise.all(activePlatforms.map(async (p) => {
        try {
          const res = await scrapePlatformCookies(p.id);
          if (res.cookies) updateCookie(p.id, res.cookies);
        } catch (e) { /* ignore individual errors */ }
      })),
      {
        loading: "Attempting to import cookies for all platforms...",
        success: "Mass import step complete. Check individual cards for results.",
        error: "Mass import failed.",
      }
    );
  };

  const filteredPlatforms = useMemo(() => {
    return PLATFORMS.filter(
      (p) =>
        p.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
        p.desc.toLowerCase().includes(searchTerm.toLowerCase())
    );
  }, [searchTerm]);

  return (
    <div className="mx-auto w-full max-w-6xl space-y-6">
      <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
        <div className="space-y-2">
          <h1 className="text-3xl font-bold tracking-tight">Cookies Manager</h1>
          <p className="max-w-2xl text-muted-foreground">
            Manage Netscape cookie files. Use the 'Get cookies.txt LOCALLY' 
            extension to export manually, or use <strong>"Import from Browser"</strong> 
            to grab them directly from your local browser profile.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
           <Button variant="outline" size="sm" onClick={handleMassImport}>
            <Download className="mr-2 h-4 w-4" />
            Auto-Import All
          </Button>
          <Button variant="destructive" size="sm" onClick={handleClearAll}>
            <Trash2 className="mr-2 h-4 w-4" />
            Clear All
          </Button>
        </div>
      </div>

      <div className="relative">
        <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          placeholder="Filter platforms by name or description..."
          className="pl-10"
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
        />
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {filteredPlatforms.map((platform) => {
          const value = settings.cookies_map?.[platform.id] || "";
          const isImporting = importingStates[platform.id];
          
          return (
            <Card key={platform.id} className="flex flex-col overflow-hidden transition-all hover:ring-1 hover:ring-primary/20">
              <CardHeader className="bg-muted/30 pb-3">
                <div className="flex items-center justify-between">
                  <CardTitle className="text-base">{platform.name}</CardTitle>
                  {value ? (
                    <div className="flex items-center text-[10px] uppercase tracking-wider text-green-500 font-bold">
                      <Check className="mr-1 h-3 w-3" /> Active
                    </div>
                  ) : (
                    <div className="flex items-center text-[10px] uppercase tracking-wider text-muted-foreground font-medium">
                      Offline
                    </div>
                  )}
                </div>
                <CardDescription className="line-clamp-1 text-xs">{platform.desc}</CardDescription>
              </CardHeader>
              <CardContent className="flex flex-1 flex-col gap-3 pt-4">
                <div className="relative flex-1">
                  <Textarea
                    className="h-full min-h-[140px] resize-none font-mono text-[10px] leading-tight"
                    placeholder={`# Netscape HTTP Cookie File...\n# Paste ${platform.name} cookies here`}
                    value={value}
                    onChange={(e) => updateCookie(platform.id, e.target.value)}
                  />
                  {!value && (
                    <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center space-y-2 opacity-20">
                      <Info className="h-8 w-8" />
                      <span className="text-xs">No cookies saved</span>
                    </div>
                  )}
                </div>
                <div className="flex gap-2">
                  <Button 
                    variant="secondary" 
                    size="sm" 
                    className="flex-1 text-xs" 
                    onClick={() => handleImportFromBrowser(platform.id, platform.name)}
                    disabled={isImporting}
                  >
                    {isImporting ? (
                      <RefreshCw className="mr-2 h-3 w-3 animate-spin" />
                    ) : (
                      <Download className="mr-2 h-3 w-3" />
                    )}
                    Import from Browser
                  </Button>
                  {value && (
                    <Button 
                      variant="ghost" 
                      size="icon" 
                      className="h-9 w-9 text-muted-foreground hover:text-destructive"
                      onClick={() => updateCookie(platform.id, "")}
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  )}
                </div>
              </CardContent>
            </Card>
          );
        })}
      </div>
      
      <Card className="mt-6 border-dashed bg-muted/20">
         <CardHeader className="pb-2">
             <div className="flex items-center gap-2">
                <AlertCircle className="h-4 w-4 text-primary" />
                <CardTitle className="text-sm font-medium">Default / Fallback Cookies</CardTitle>
             </div>
             <CardDescription className="text-xs">
                If a platform is not listed above, yt-dlp will fallback to these cookies for all requests.
             </CardDescription>
         </CardHeader>
         <CardContent>
            <Textarea
                className="min-h-[80px] resize-y font-mono text-[10px]"
                placeholder="# Netscape HTTP Cookie File (Global Fallback)"
                value={settings.cookies_map?.["default"] || ""}
                onChange={(e) => updateCookie("default", e.target.value)}
            />
         </Content>
      </Card>
    </div>
  );
}
