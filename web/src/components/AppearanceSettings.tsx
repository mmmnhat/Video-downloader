import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Upload, Trash2 } from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";
import { Field, FieldGroup } from "@/components/ui/field";
import { TooltipFieldLabel } from "@/components/ui/tooltip-field-label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Slider } from "@/components/ui/slider";
import { cn } from "@/lib/utils";
import { getThumbnailBootstrap, updateThumbnailSettings, type ThumbnailSettings } from "@/lib/api";

const STUDIO_LABEL_CLASS = "text-xs font-semibold text-foreground/90 tracking-wide";
const STUDIO_INPUT_CLASS = "h-9 rounded-xl bg-muted/20 border-border/70 text-xs shadow-sm hover:border-primary/50 transition-colors focus-visible:ring-1 focus-visible:ring-primary/30";

export default function AppearanceSettings() {
 const [settings, setSettings] = useState<ThumbnailSettings | null>(null);

 useEffect(() => {
  let active = true;
  getThumbnailBootstrap()
   .then((payload) => {
    if (active) setSettings(payload.settings);
   })
   .catch((err) => {
    console.error("Failed to load thumbnail settings:", err);
   });
  return () => { active = false; };
 }, []);

 async function handleSave(partial: Partial<ThumbnailSettings>) {
  if (!settings) return;
  try {
   const next = await updateThumbnailSettings({ ...settings, ...partial });
   setSettings(next);

   // Apply app theme directly when changed here
   if (partial.app_theme) {
    const isDark = partial.app_theme === "dark" || (partial.app_theme === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
    document.documentElement.classList.toggle("dark", isDark);
   }

  } catch (error) {
   toast.error(error instanceof Error ? error.message : "Cập nhật thất bại");
  }
 }

 if (!settings) {
  return (
   <Card className="border-border/70 shadow-[0_24px_90px_rgba(15,23,42,0.08)]">
    <CardContent className="py-12 text-center text-sm text-muted-foreground">
     Đang tải cấu hình...
    </CardContent>
   </Card>
  );
 }

 return (
  <div className="space-y-6">
   <Card className="border-border/70 shadow-[0_24px_90px_rgba(15,23,42,0.08)]">
    <CardContent className="p-6 space-y-6">
     <div>
      <div className={cn(STUDIO_LABEL_CLASS, "mb-3 text-[13px] text-foreground/80")}>Cấu hình Ứng dụng</div>
      <FieldGroup className="gap-5">
       <Field>
        <TooltipFieldLabel tooltip="Chọn giao diện sáng, tối, hoặc theo hệ thống." className={STUDIO_LABEL_CLASS}>Giao diện</TooltipFieldLabel>
        <Select value={settings.app_theme || "dark"} onValueChange={(v) => void handleSave({ app_theme: v })}>
         <SelectTrigger className={STUDIO_INPUT_CLASS}>
          <SelectValue />
         </SelectTrigger>
         <SelectContent>
          <SelectItem value="dark">Tối (Dark)</SelectItem>
          <SelectItem value="light">Sáng (Light)</SelectItem>
          <SelectItem value="system">Hệ thống (System)</SelectItem>
         </SelectContent>
        </Select>
       </Field>
      </FieldGroup>
     </div>
    </CardContent>
   </Card>

   <Card className="border-border/70 shadow-[0_24px_90px_rgba(15,23,42,0.08)]">
    <CardContent className="p-6 space-y-6">
     <div>
      <div className={cn(STUDIO_LABEL_CLASS, "mb-3 text-[13px] text-foreground/80")}>Cấu hình nền Canvas (Thumbnail)</div>
      <FieldGroup className="gap-5">
       <Field>
        <TooltipFieldLabel tooltip="Thay đổi nền của vùng Canvas" className={STUDIO_LABEL_CLASS}>Dạng nền</TooltipFieldLabel>
        <Select value={settings.canvas_bg_type || "solid"} onValueChange={(v) => void handleSave({ canvas_bg_type: v })}>
         <SelectTrigger className={STUDIO_INPUT_CLASS}>
          <SelectValue />
         </SelectTrigger>
         <SelectContent>
          <SelectItem value="solid">Màu trơn</SelectItem>
          <SelectItem value="grid">Lưới (Grid)</SelectItem>
          <SelectItem value="dot">Chấm (Dot)</SelectItem>
          <SelectItem value="custom">Ảnh tuỳ chỉnh</SelectItem>
         </SelectContent>
        </Select>
       </Field>

       {settings.canvas_bg_type === "custom" ? (
         <>
          <Field>
           <TooltipFieldLabel tooltip="Upload ảnh làm nền Canvas" className={STUDIO_LABEL_CLASS}>Ảnh nền</TooltipFieldLabel>
           <div className="flex gap-2">
            <Button variant="outline" className="flex-1 h-9 rounded-xl border-border/50 bg-background/50 text-xs" onClick={() => {
              const input = document.createElement("input");
              input.type = "file";
              input.accept = "image/*";
              input.onchange = (e) => {
               const file = (e.target as HTMLInputElement).files?.[0];
               if (file) {
                const reader = new FileReader();
                reader.onload = (ev) => void handleSave({ canvas_bg_image: ev.target?.result as string });
                reader.readAsDataURL(file);
               }
              };
              input.click();
            }}>
             <Upload className="size-3 mr-2" /> Tải ảnh lên
            </Button>
            {settings.canvas_bg_image && (
             <Button variant="ghost" size="icon" className="size-9 rounded-xl border border-border/50 bg-background/50 hover:bg-destructive/10 hover:text-destructive shrink-0" onClick={() => void handleSave({ canvas_bg_image: "" })}>
              <Trash2 className="size-3" />
             </Button>
            )}
           </div>
          </Field>
          <Field>
           <TooltipFieldLabel tooltip="Cách ảnh nền vừa vặn" className={STUDIO_LABEL_CLASS}>Chế độ hiển thị</TooltipFieldLabel>
           <Select value={settings.canvas_bg_fit || "cover"} onValueChange={(v) => void handleSave({ canvas_bg_fit: v })}>
            <SelectTrigger className={STUDIO_INPUT_CLASS}>
             <SelectValue />
            </SelectTrigger>
            <SelectContent>
             <SelectItem value="cover">Lấp đầy (Cover)</SelectItem>
             <SelectItem value="contain">Vừa vặn (Contain)</SelectItem>
             <SelectItem value="fill">Kéo giãn (Fill)</SelectItem>
            </SelectContent>
           </Select>
          </Field>
         </>
       ) : (
         <Field>
          <TooltipFieldLabel tooltip="Màu nền của Canvas" className={STUDIO_LABEL_CLASS}>Màu nền</TooltipFieldLabel>
          <div className="flex gap-2">
           <input
            type="color"
            value={settings.canvas_bg_color || "#0f0f0f"}
            onChange={(e) => void handleSave({ canvas_bg_color: e.target.value })}
            className="size-9 rounded-xl cursor-pointer"
           />
           <Input
            value={settings.canvas_bg_color || "#0f0f0f"}
            onChange={(e) => void handleSave({ canvas_bg_color: e.target.value })}
            className={STUDIO_INPUT_CLASS}
           />
          </div>
         </Field>
       )}

       <Field>
        <TooltipFieldLabel tooltip="Độ mờ của nền" className={STUDIO_LABEL_CLASS}>Độ mờ ({settings.canvas_bg_opacity ?? 100}%)</TooltipFieldLabel>
        <Slider
         value={[settings.canvas_bg_opacity ?? 100]}
         min={0} max={100} step={1}
         onValueChange={(v) => void handleSave({ canvas_bg_opacity: v[0] })}
        />
       </Field>

       <Field>
        <TooltipFieldLabel tooltip="Độ sáng của nền" className={STUDIO_LABEL_CLASS}>Độ sáng ({settings.canvas_bg_brightness ?? 100}%)</TooltipFieldLabel>
        <Slider
         value={[settings.canvas_bg_brightness ?? 100]}
         min={0} max={200} step={1}
         onValueChange={(v) => void handleSave({ canvas_bg_brightness: v[0] })}
        />
       </Field>
      </FieldGroup>
     </div>
    </CardContent>
   </Card>
  </div>
 );
}
