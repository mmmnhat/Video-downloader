import { useCallback } from "react";
import type { Settings } from "@/lib/api";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";

const PLATFORMS = [
  { id: "youtube", name: "YouTube", desc: "For Age-Restricted & Private Videos (Export from youtube.com)" },
  { id: "dumpert", name: "Dumpert", desc: "For 18+ or logged-in videos (Export from dumpert.nl)" },
  { id: "facebook", name: "Facebook", desc: "For private groups and posts (Export from facebook.com)" },
  { id: "instagram", name: "Instagram", desc: "For private accounts (Export from instagram.com)" },
  { id: "tiktok", name: "TikTok", desc: "For login-restricted clips (Export from tiktok.com)" },
  { id: "x", name: "X (Twitter)", desc: "For age-restricted tweets (Export from x.com)" },
];

interface CookiesManagerProps {
  settings: Settings;
  onSettingsChange: (val: React.SetStateAction<Settings>) => void;
}

export default function CookiesManager({
  settings,
  onSettingsChange,
}: CookiesManagerProps) {
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

  return (
    <div className="mx-auto w-full max-w-4xl space-y-6">
      <div className="mb-8 space-y-2">
        <h1 className="text-3xl font-bold tracking-tight">Cookies Manager</h1>
        <p className="text-muted-foreground">
          Manage platform-specific Netscape cookie files. Use the 'Get cookies.txt LOCALLY' 
          browser extension to export cookies from your browser and paste them below to download private content.
        </p>
      </div>

      <div className="grid gap-6 md:grid-cols-2">
        {PLATFORMS.map((platform) => {
          const value = settings.cookies_map?.[platform.id] || "";
          
          return (
            <Card key={platform.id} className="flex flex-col">
              <CardHeader className="pb-3">
                <CardTitle className="text-base">{platform.name}</CardTitle>
                <CardDescription>{platform.desc}</CardDescription>
              </CardHeader>
              <CardContent className="flex-1">
                <Textarea
                  className="min-h-[120px] resize-y font-mono text-xs"
                  placeholder={`# Netscape HTTP Cookie File...\n# Paste ${platform.name} cookies here`}
                  value={value}
                  onChange={(e) => updateCookie(platform.id, e.target.value)}
                />
              </CardContent>
            </Card>
          );
        })}
      </div>
      
      <Card className="mt-6 border-dashed bg-muted/30">
         <CardHeader>
             <CardTitle className="text-sm">Default / Other Platforms</CardTitle>
             <CardDescription>If a platform is not listed above, yt-dlp will fallback to these cookies.</CardDescription>
         </CardHeader>
         <CardContent>
            <Textarea
                className="min-h-[100px] resize-y font-mono text-xs"
                placeholder="# Netscape HTTP Cookie File..."
                value={settings.cookies_map?.["default"] || ""}
                onChange={(e) => updateCookie("default", e.target.value)}
            />
         </CardContent>
      </Card>
    </div>
  );
}
