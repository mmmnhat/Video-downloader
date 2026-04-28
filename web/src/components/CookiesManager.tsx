import { useCallback, useState, useMemo } from "react";
import type { Settings } from "@/lib/api";
import {
  Card,
  CardContent,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import {
  Search,
  Trash2,
  RefreshCw,
  Check,
  ClipboardPaste,
} from "lucide-react";
import { toast } from "sonner";

const PLATFORMS = [
  { id: "youtube", name: "YouTube", desc: "Dùng cho video giới hạn độ tuổi hoặc riêng tư (Xuất từ youtube.com)" },
  { id: "facebook", name: "Facebook", desc: "Dùng cho nhóm và bài đăng riêng tư (Xuất từ facebook.com)" },
  { id: "instagram", name: "Instagram", desc: "Dùng cho tài khoản riêng tư (Xuất từ instagram.com)" },
  { id: "tiktok", name: "TikTok", desc: "Dùng cho video yêu cầu đăng nhập (Xuất từ tiktok.com)" },
  { id: "threads", name: "Threads", desc: "Dùng cho nội dung Threads (Xuất từ threads.net)" },
  { id: "x", name: "X (Twitter)", desc: "Dùng cho tweet giới hạn độ tuổi (Xuất từ x.com)" },
  { id: "telegram", name: "Telegram", desc: "Dùng cho bài đăng kênh riêng tư (Xuất từ t.me)" },
  { id: "dailymotion", name: "Dailymotion", desc: "Dùng cho nội dung bị hạn chế (Xuất từ dailymotion.com)" },
  { id: "reddit", name: "Reddit", desc: "Dùng cho subreddit NSFW hoặc riêng tư (Xuất từ reddit.com)" },
  { id: "dumpert", name: "Dumpert", desc: "Dùng cho video 18+ hoặc cần đăng nhập (Xuất từ dumpert.nl)" },
  { id: "snapchat", name: "Snapchat", desc: "Dùng cho video Snapchat (Xuất từ snapchat.com)" },
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
  const [pastingStates, setPastingStates] = useState<Record<string, boolean>>({});

  const updateCookie = useCallback(
    (platform: string, text: string) => {
      onSettingsChange((prev) => ({
        ...prev,
        cookies_map: (() => {
          const nextMap = { ...(prev.cookies_map || {}) };
          const normalized = text.trim();

          if (normalized) {
            nextMap[platform] = text;
          } else {
            delete nextMap[platform];
          }

          return nextMap;
        })(),
      }));
    },
    [onSettingsChange],
  );

  const handlePasteFromClipboard = async (platformId: string, platformName: string) => {
    setPastingStates((prev) => ({ ...prev, [platformId]: true }));
    try {
      if (!navigator.clipboard?.readText) {
        toast.error("Trình duyệt này không hỗ trợ truy cập clipboard.");
        return;
      }

      const clipboardText = (await navigator.clipboard.readText()).trim();
      if (!clipboardText) {
        toast.error("Clipboard đang trống.");
        return;
      }

      updateCookie(platformId, clipboardText);
      toast.success(`Đã dán cookie cho ${platformName}.`);
    } catch (error) {
      toast.error(`Không đọc được clipboard: ${error instanceof Error ? error.message : "Lỗi không xác định"}`);
    } finally {
      setPastingStates((prev) => ({ ...prev, [platformId]: false }));
    }
  };

  const handleClearAll = () => {
    if (confirm("Bạn chắc chắn muốn xóa TOÀN BỘ cookie thủ công? Không thể hoàn tác.")) {
      onSettingsChange((prev) => ({
        ...prev,
        cookies_map: {},
      }));
      toast.success("Đã xóa toàn bộ cookie.");
    }
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
      <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-end">
        <div className="flex flex-wrap gap-2">
          <Button variant="destructive" size="sm" onClick={handleClearAll}>
            <Trash2 className="mr-2 h-4 w-4" />
            Xóa tất cả
          </Button>
        </div>
      </div>

      <div className="relative">
        <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          placeholder="Lọc nền tảng theo tên hoặc mô tả"
          className="pl-10"
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
        />
      </div>

      <div className="grid gap-3 lg:grid-cols-2 xl:grid-cols-3">
        {filteredPlatforms.map((platform) => {
          const value = settings.cookies_map?.[platform.id] || "";
          const hasCookies = Boolean(value.trim());
          const isPasting = pastingStates[platform.id];
          
          return (
            <Card
              key={platform.id}
              title={platform.desc}
              className={[
                "rounded-lg border py-0 transition-all hover:ring-1 hover:ring-primary/20",
                hasCookies ? "border-emerald-500/30 bg-emerald-500/5" : "border-border/80",
              ].join(" ")}
            >
              <CardContent className="px-4 py-3">
                <div className="flex min-h-[88px] flex-col justify-center gap-3">
                  <div className="flex items-center justify-between gap-3">
                    <CardTitle className="text-sm" title={platform.desc}>{platform.name}</CardTitle>
                  {hasCookies ? (
                    <div className="flex items-center text-[10px] font-bold uppercase tracking-wider text-emerald-400">
                      <Check className="mr-1 h-3 w-3" /> Đã lưu
                    </div>
                  ) : (
                    <div className="flex items-center text-[10px] uppercase tracking-wider text-muted-foreground font-medium">
                      Trống
                    </div>
                  )}
                  </div>
                  <div className="flex items-center justify-center gap-2">
                    <Button
                      variant="secondary"
                      size="sm"
                      className="h-8 text-xs"
                      onClick={() => {
                        if (hasCookies) {
                          updateCookie(platform.id, "");
                          return;
                        }
                        void handlePasteFromClipboard(platform.id, platform.name);
                      }}
                      disabled={isPasting}
                    >
                      {isPasting ? (
                        <RefreshCw className="mr-2 h-3 w-3 animate-spin" />
                      ) : hasCookies ? (
                        <Trash2 className="mr-2 h-3 w-3" />
                      ) : (
                        <ClipboardPaste className="mr-2 h-3 w-3" />
                      )}
                      {hasCookies ? "Xóa" : "Dán"}
                    </Button>
                  </div>
                </div>
              </CardContent>
            </Card>
          );
        })}
      </div>
    </div>
  );
}
