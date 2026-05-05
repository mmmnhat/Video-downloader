import { useEffect, useState, useTransition, useMemo, useRef, useCallback } from "react";
import type { ChangeEvent } from "react";
import {
 Brain, Download, Loader2,
 Play, Plus, Search,
 Layers, Trash2, Pin, PinOff,
 Save, X, ChevronDown, ChevronUp, Edit3, RefreshCw, SplitSquareVertical, Pencil, Sparkles, Upload, Zap,
 Paintbrush, Frame, Square, Eraser, Crop, Circle,
} from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Slider } from "@/components/ui/slider";
import { Field, FieldGroup } from "@/components/ui/field";
import { SessionStatusAlert } from "@/components/ui/session-status-alert";
import { TooltipFieldLabel } from "@/components/ui/tooltip-field-label";
import {
 Dialog,
 DialogTrigger,
 DialogContent,
 DialogHeader,
 DialogTitle,
 DialogFooter,
 DialogClose,
} from "@/components/ui/dialog";
import {
 chooseFolder,
 createThumbnailButton,
 createThumbnailProfile,
 createThumbnailProject,
 deleteThumbnailButton,
 deleteThumbnailProfile,
 deleteThumbnailProject,
 exportThumbnailImage,
 exportThumbnailButtonPreset,
 exportThumbnailProfilePreset,
 listThumbnailGems,
 togglePinThumbnailButton,
 togglePinThumbnailProfile,
 getThumbnailAssetUrl,
 getThumbnailBootstrap,
 getThumbnailProject,
 getThumbnailSessionStatus,
 openThumbnailLogin,
 openFolder,
 runThumbnailGenerationBatch,
 selectThumbnailVersion,
 commitThumbnailCrop,
 deleteThumbnailVersion,
 renameThumbnailProject,
 ApiError,
 type ThumbnailBootstrapPayload,
 type ThumbnailButton,
 type ThumbnailButtonField,
 type ThumbnailSettings,
 type ThumbnailRequiredTool,
 type ThumbnailProfile,
 type ThumbnailProfileEffect,
 type ThumbnailProjectDetail,
 updateThumbnailSettings,
} from "../lib/api";
import MaskCanvas, { type CanvasGuide } from "./MaskCanvas";

import { useLocalStorage } from "@/hooks/use-local-storage";
import { cn } from "@/lib/utils";

type CanvasShapeTool = Extract<ThumbnailRequiredTool, "rect" | "ellipse">;

function fieldValueMap(fields: ThumbnailButtonField[]) {
 return Object.fromEntries(fields.map((field) => [field.key, field.value])) as Record<string, string | number | boolean | string[]>;
}

function getErrorMessage(error: unknown) {
 return error instanceof Error ? error.message : "Yêu cầu thất bại.";
}

function isLikelyGeminiAuthMessage(message: string) {
 const normalized = String(message || "").toLowerCase();
 return (
  normalized.includes("guest")
  || normalized.includes("dang nhap")
  || normalized.includes("session gemini")
  || normalized.includes("profile rieng cua app")
 );
}

function numericCanvasValue(value: ThumbnailButtonField["value"]) {
 const next = Number(value);
 return Number.isFinite(next) ? next : null;
}

function normalizeCanvasShapeTool(value: ThumbnailButtonField["value"]): CanvasShapeTool | null {
 const normalized = String(value ?? "").trim().toLowerCase();
 if (!normalized) return null;
 if (["ellipse", "oval", "circle", "hinh tron", "hình tròn", "elip"].some((marker) => normalized.includes(marker))) {
  return "ellipse";
 }
 if (["rect", "rectangle", "square", "hinh vuong", "hình vuông", "hinh chu nhat", "hình chữ nhật"].some((marker) => normalized.includes(marker))) {
  return "rect";
 }
 return null;
}



async function readJsonFile(file: File) {
 const raw = await file.text();
 return JSON.parse(raw) as unknown;
}

function downloadJsonFile(fileName: string, payload: object) {
 const blob = new Blob([`${JSON.stringify(payload, null, 2)}\n`], { type: "application/json;charset=utf-8" });
 const downloadUrl = URL.createObjectURL(blob);
 const anchor = document.createElement("a");
 anchor.href = downloadUrl;
 anchor.download = fileName || "preset.json";
 anchor.rel = "noopener";
 document.body.appendChild(anchor);
 anchor.click();
 anchor.remove();
 window.setTimeout(() => URL.revokeObjectURL(downloadUrl), 0);
}

function extractButtonPresetPayloads(payload: unknown): ThumbnailButton[] {
 if (!payload || typeof payload !== "object") {
  throw new ApiError("Preset button không hợp lệ.");
 }
 const data = payload as Record<string, unknown>;
 if (Array.isArray(data.buttons)) {
  const buttons = data.buttons.filter((item): item is ThumbnailButton => !!item && typeof item === "object");
  if (buttons.length === 0) {
   throw new ApiError("Preset button không có dữ liệu hợp lệ.");
  }
  return buttons;
 }
 if (data.button && typeof data.button === "object") {
  return [data.button as ThumbnailButton];
 }
 if ("promptTemplate" in data || "prompt_template" in data) {
  return [data as unknown as ThumbnailButton];
 }
 throw new ApiError("Không nhận diện được preset button.");
}

function extractProfilePresetPayload(payload: unknown): {
 profile: ThumbnailProfile;
 buttons: ThumbnailButton[];
} {
 if (!payload || typeof payload !== "object") {
  throw new ApiError("Preset profile không hợp lệ.");
 }
 const data = payload as Record<string, unknown>;
 if (data.profile && typeof data.profile === "object") {
  return {
   profile: data.profile as ThumbnailProfile,
   buttons: Array.isArray(data.buttons)
    ? data.buttons.filter((item): item is ThumbnailButton => !!item && typeof item === "object")
    : [],
  };
 }
 if ("effects" in data || "items" in data) {
  return {
   profile: data as unknown as ThumbnailProfile,
   buttons: [],
  };
 }
 throw new ApiError("Không nhận diện được preset profile.");
}

function normalizeButtonForSave(button: ThumbnailButton) {
 return {
  id: button.id,
  name: button.name,
  icon: button.icon,
  category: button.category,
  promptTemplate: (button as ThumbnailButton & { prompt_template?: string }).promptTemplate
   ?? (button as ThumbnailButton & { prompt_template?: string }).prompt_template
   ?? "",
  requiresMask: (button as ThumbnailButton & { requires_mask?: boolean }).requiresMask
   ?? (button as ThumbnailButton & { requires_mask?: boolean }).requires_mask
   ?? false,
  createNewChat: button.createNewChat ?? true,
  allowRegenerate: button.allowRegenerate ?? true,
  requiredTools: normalizeRequiredTools(button.requiredTools, button.requiresMask),
  fields: Array.isArray(button.fields) ? button.fields : [],
 };
}

function normalizeProfileForSave(profile: ThumbnailProfile) {
 const rawEffects = Array.isArray(profile.effects) ? profile.effects : [];
 return {
  id: profile.id,
  name: profile.name,
  icon: profile.icon,
  description: profile.description ?? "",
  effects: rawEffects.map((effect) => ({
   buttonId: (effect as ThumbnailProfileEffect & { button_id?: string }).buttonId
    ?? (effect as ThumbnailProfileEffect & { button_id?: string }).button_id
    ?? "",
   fields: Array.isArray(effect.fields) ? effect.fields : [],
  })).filter((effect) => effect.buttonId),
 };
}

function stringifyPromptValue(value: ThumbnailButtonField["value"]) {
 if (Array.isArray(value)) return value.join(", ");
 if (typeof value === "boolean") return value ? "true" : "false";
 if (value === null || value === undefined) return "";
 return String(value);
}

function buildPromptPreview(promptTemplate: string, fields: ThumbnailButtonField[]) {
 let prompt = promptTemplate ?? "";
 for (const field of fields) {
  prompt = prompt.split(`{${field.key}}`).join(stringifyPromptValue(field.value));
 }
 return prompt.trim();
}

function buildEffectsPromptPreview(
 effects: Array<{ buttonId: string; fields: ThumbnailButtonField[] }>,
 buttons: ThumbnailButton[],
) {
 const instructions = effects
  .map((effect) => {
   const button = buttons.find((item) => item.id === effect.buttonId);
   if (!button) return null;
   return buildPromptPreview(button.promptTemplate, effect.fields);
  })
  .filter((instruction): instruction is string => Boolean(instruction));

 if (instructions.length === 0) return "";
 if (instructions.length === 1) return instructions[0];

 return [
  "Perform the following improvements simultaneously:",
  ...instructions.map((instruction, index) => `${index + 1}. ${instruction}`),
  "",
  "Keep the overall composition and all unmentioned details consistent with the original image.",
 ].join("\n");
}

function getButtonRequiredTools(button: Pick<ThumbnailButton, "requiredTools" | "requiresMask">) {
 return normalizeRequiredTools(button.requiredTools, button.requiresMask);
}

/**
 * Logic to check if a field should be visible based on visibleIf metadata
 */
function isFieldVisible(field: ThumbnailButtonField, allFields: ThumbnailButtonField[]): boolean {
 if (!field.visibleIf) return true;

 if (typeof field.visibleIf === "string") {
  // Support "key=value" syntax (e.g. "body=Average" or "if {body}=Average")
  let condition = field.visibleIf.trim();
  // Strip "if " prefix and curly braces if present to match user expectation
  condition = condition.replace(/^if\s+/i, "").replace(/[\{\}]/g, "");

  if (condition.includes("=")) {
   const [key, val] = condition.split("=").map(s => s.trim());
   const parent = allFields.find(f => f.key === key);
   if (!parent) return false;

   const parentVal = parent.value;
   // Handle different value types
   if (typeof parentVal === "number") return parentVal === Number(val);
   if (typeof parentVal === "boolean") return String(parentVal) === val.toLowerCase();
   if (Array.isArray(parentVal)) return parentVal.includes(val);

   return String(parentVal ?? "") === val;
  }

  // Fallback to legacy "key has value" check
  const parent = allFields.find(f => f.key === field.visibleIf);
  return !!parent?.value;
 }

 if (typeof field.visibleIf === "object") {
  for (const [key, val] of Object.entries(field.visibleIf)) {
   const parent = allFields.find(f => f.key === key);
   if (parent?.value !== val) return false;
  }
  return true;
 }
 return true;
}

function ThumbnailFieldRenderer({ field, allFields, onChange }: { field: ThumbnailButtonField, allFields: ThumbnailButtonField[], onChange: (val: any) => void }) {
 if (!isFieldVisible(field, allFields)) return null;

 const label = (
  <div className="flex items-center justify-between mb-2">
   <div className={STUDIO_LABEL_CLASS}>
    {field.label} {field.required && <span className="text-destructive">*</span>}
   </div>
   {field.type === "slider" && <span className="text-xs font-mono font-semibold text-primary">{field.value}</span>}
  </div>
 );

 switch (field.type) {
  case "multi-select":
  // multiSelect merged into multi-select above
   const selectedValues = Array.isArray(field.value) ? field.value : [];
   return (
    <Field>
     {label}
     <div className="flex flex-wrap gap-2 p-1">
      {field.options?.map(opt => {
       const isSelected = selectedValues.includes(opt);
       return (
        <Button
         key={opt}
         variant={isSelected ? "default" : "outline"}
         size="sm"
         className={cn(
          "h-8 rounded-xl text-[11px] font-bold transition-all",
          isSelected ? "bg-primary text-primary-foreground shadow-md" : "bg-muted/5 border-border/50 text-muted-foreground hover:bg-muted/10"
         )}
         onClick={() => {
          if (isSelected) {
           onChange(selectedValues.filter(v => v !== opt));
          } else {
           onChange([...selectedValues, opt]);
          }
         }}
        >
         {opt}
        </Button>
       );
      })}
     </div>
    </Field>
   );
  case "text":
   return (
    <Field>
     {label}
     <Input
      value={field.value as string}
      onChange={e => onChange(e.target.value)}
      placeholder={`Nhập ${field.label.toLowerCase()}...`}
      className="h-10 bg-muted/10 border-border/50 text-sm font-medium focus-visible:ring-primary/30"
     />
    </Field>
   );
  case "textarea":
   return (
    <Field>
     {label}
     <Textarea
      value={field.value as string}
      onChange={e => onChange(e.target.value)}
      placeholder={`Nhập ${field.label.toLowerCase()}...`}
      className="min-h-[80px] bg-muted/10 border-border/50 text-sm focus-visible:ring-primary/30"
     />
    </Field>
   );
  case "select":
   return (
    <Field>
     {label}
     <Select value={field.value as string} onValueChange={onChange}>
      <SelectTrigger className="h-10 bg-muted/10 border-border/50 text-sm font-medium">
       <SelectValue placeholder={`Chọn ${field.label.toLowerCase()}`} />
      </SelectTrigger>
      <SelectContent>
       {field.options?.map(opt => (
        <SelectItem key={opt} value={opt} className="text-sm">{opt}</SelectItem>
       ))}
      </SelectContent>
     </Select>
    </Field>
   );
  case "toggle":
   return (
    <div className="flex items-center justify-between p-3 rounded-2xl bg-muted/5 border border-border/30">
     <div
      className={cn(STUDIO_LABEL_CLASS, "text-foreground/80")}
     >
      {field.label}
     </div>
     <Switch checked={!!field.value} onCheckedChange={onChange} />
    </div>
   );
  case "slider":
   return (
    <Field>
     {label}
     <div className="px-1 pt-2 pb-1">
      <Slider
       value={[field.value as number]}
       min={field.min ?? 0}
       max={field.max ?? 10}
       step={1}
       onValueChange={([v]) => onChange(v)}
       className="py-4"
      />
     </div>
    </Field>
   );
  case "number":
   return (
    <Field>
     {label}
     <Input
      type="number"
      value={field.value as number}
      onChange={e => onChange(Number(e.target.value))}
      min={field.min ?? undefined}
      max={field.max ?? undefined}
      className="h-10 bg-muted/10 border-border/50 text-sm font-bold"
     />
    </Field>
   );
  case "color":
   return (
    <Field>
     {label}
     <div className="flex gap-2">
      <Input
       type="color"
       value={field.value as string}
       onChange={e => onChange(e.target.value)}
       className="h-10 w-12 p-1 bg-muted/10 border-border/50 rounded-lg cursor-pointer"
      />
      <Input
       value={field.value as string}
       onChange={e => onChange(e.target.value)}
       placeholder="#000000"
       className="h-10 flex-1 bg-muted/10 border-border/50 text-sm font-mono "
      />
     </div>
    </Field>
   );
  default:
   return (
    <Field>
     {label}
     <Input
      value={field.value as string}
      onChange={e => onChange(e.target.value)}
      placeholder={`Nhập ${field.label.toLowerCase()}...`}
      className="h-10 bg-muted/10 border-border/50 text-sm font-medium focus-visible:ring-primary/30"
     />
    </Field>
   );
 }
}

type PickerItem = {
 value: string;
 keywords: string[];
};

const ICON_PICKER_GROUPS: Array<{ category: string; items: PickerItem[] }> = [
 {
  category: "Phổ biến",
  items: [
   { value: "✨", keywords: ["sparkle", "magic", "shine"] },
   { value: "🎨", keywords: ["paint", "color", "art"] },
   { value: "🖼️", keywords: ["image", "frame", "canvas"] },
   { value: "📸", keywords: ["photo", "camera", "snapshot"] },
   { value: "🎬", keywords: ["video", "film", "cinema"] },
   { value: "🔥", keywords: ["hot", "fire", "viral"] },
   { value: "⚡", keywords: ["fast", "energy", "electric"] },
   { value: "💥", keywords: ["impact", "boom", "burst"] },
   { value: "🌟", keywords: ["star", "highlight", "premium"] },
   { value: "💎", keywords: ["diamond", "luxury", "gem"] },
   { value: "🚀", keywords: ["launch", "boost", "growth"] },
   { value: "🎯", keywords: ["target", "focus", "goal"] },
   { value: "🪄", keywords: ["wand", "magic", "edit"] },
   { value: "🤖", keywords: ["robot", "ai", "automation"] },
   { value: "🧠", keywords: ["brain", "smart", "idea"] },
  ],
 },
 {
  category: "Biểu cảm",
  items: [
   { value: "😀", keywords: ["happy", "smile", "joy"] },
   { value: "😂", keywords: ["laugh", "funny", "lol"] },
   { value: "😍", keywords: ["love", "heart", "cute"] },
   { value: "😎", keywords: ["cool", "style", "swag"] },
   { value: "🤩", keywords: ["wow", "starstruck", "amazing"] },
   { value: "😮", keywords: ["surprise", "shock", "open mouth"] },
   { value: "🤯", keywords: ["mind blown", "crazy", "extreme"] },
   { value: "😱", keywords: ["scream", "fear", "shocked"] },
   { value: "😭", keywords: ["cry", "sad", "tears"] },
   { value: "😡", keywords: ["angry", "mad", "rage"] },
   { value: "🥳", keywords: ["party", "celebrate", "fun"] },
   { value: "🤔", keywords: ["think", "question", "hmm"] },
   { value: "👻", keywords: ["ghost", "spooky", "halloween"] },
   { value: "🤡", keywords: ["clown", "meme", "funny"] },
   { value: "😴", keywords: ["sleep", "lazy", "tired"] },
  ],
 },
 {
  category: "Đồ vật",
  items: [
   { value: "🚗", keywords: ["car", "vehicle", "auto"] },
   { value: "🏍️", keywords: ["motorbike", "bike", "vehicle"] },
   { value: "🚲", keywords: ["bicycle", "bike", "ride"] },
   { value: "✈️", keywords: ["plane", "travel", "flight"] },
   { value: "🏠", keywords: ["house", "home", "real estate"] },
   { value: "📱", keywords: ["phone", "mobile", "device"] },
   { value: "💻", keywords: ["laptop", "computer", "tech"] },
   { value: "⌚", keywords: ["watch", "time", "wearable"] },
   { value: "🎮", keywords: ["game", "controller", "gaming"] },
   { value: "🎧", keywords: ["headphones", "music", "audio"] },
   { value: "📦", keywords: ["box", "package", "preset"] },
   { value: "🛍️", keywords: ["shopping", "bag", "store"] },
   { value: "💡", keywords: ["idea", "light", "insight"] },
   { value: "🔒", keywords: ["lock", "secure", "privacy"] },
   { value: "🧲", keywords: ["magnet", "pull", "hook"] },
  ],
 },
 {
  category: "Thiên nhiên",
  items: [
   { value: "🌈", keywords: ["rainbow", "colorful", "spectrum"] },
   { value: "☀️", keywords: ["sun", "bright", "day"] },
   { value: "🌙", keywords: ["moon", "night", "dark"] },
   { value: "⭐", keywords: ["star", "space", "highlight"] },
   { value: "☁️", keywords: ["cloud", "sky", "weather"] },
   { value: "🌊", keywords: ["wave", "water", "sea"] },
   { value: "❄️", keywords: ["snow", "ice", "cold"] },
   { value: "🌸", keywords: ["flower", "spring", "pink"] },
   { value: "🌳", keywords: ["tree", "forest", "nature"] },
   { value: "🍀", keywords: ["leaf", "lucky", "green"] },
   { value: "🌋", keywords: ["volcano", "lava", "hot"] },
   { value: "🌪️", keywords: ["storm", "wind", "tornado"] },
   { value: "🪐", keywords: ["planet", "space", "orbit"] },
   { value: "🦄", keywords: ["unicorn", "fantasy", "magic"] },
   { value: "🦋", keywords: ["butterfly", "soft", "nature"] },
  ],
 },
 {
  category: "UI & Symbols",
  items: [
   { value: "★", keywords: ["star", "favorite", "premium"] },
   { value: "☆", keywords: ["star outline", "favorite", "light"] },
   { value: "✓", keywords: ["check", "done", "success"] },
   { value: "✔", keywords: ["check", "ok", "approve"] },
   { value: "✕", keywords: ["close", "cancel", "x"] },
   { value: "✖", keywords: ["remove", "error", "delete"] },
   { value: "➜", keywords: ["arrow", "next", "forward"] },
   { value: "➤", keywords: ["play", "arrow", "direction"] },
   { value: "⬆", keywords: ["up", "arrow", "top"] },
   { value: "⬇", keywords: ["down", "arrow", "bottom"] },
   { value: "⬅", keywords: ["left", "arrow", "back"] },
   { value: "➡", keywords: ["right", "arrow", "next"] },
   { value: "◆", keywords: ["diamond", "shape", "badge"] },
   { value: "■", keywords: ["square", "block", "shape"] },
   { value: "▲", keywords: ["triangle", "up", "shape"] },
  ],
 },
 {
  category: "Media & Social",
  items: [
   { value: "▶", keywords: ["play", "video", "start"] },
   { value: "⏸", keywords: ["pause", "media", "stop"] },
   { value: "⏺", keywords: ["record", "capture", "live"] },
   { value: "⏩", keywords: ["fast forward", "skip", "speed"] },
   { value: "🔊", keywords: ["volume", "sound", "audio"] },
   { value: "🎵", keywords: ["music", "note", "audio"] },
   { value: "🎤", keywords: ["microphone", "voice", "sing"] },
   { value: "📢", keywords: ["announce", "broadcast", "loud"] },
   { value: "📰", keywords: ["news", "headline", "article"] },
   { value: "💬", keywords: ["chat", "comment", "message"] },
   { value: "🔔", keywords: ["notification", "alert", "bell"] },
   { value: "❤️", keywords: ["love", "heart", "like"] },
   { value: "👍", keywords: ["thumbs up", "like", "ok"] },
   { value: "👀", keywords: ["look", "watch", "attention"] },
   { value: "📈", keywords: ["growth", "analytics", "chart"] },
  ],
 },
];

const TOOL_REQUIREMENT_OPTIONS: Array<{
 id: ThumbnailRequiredTool;
 label: string;
 shortLabel: string;
 icon: any;
}> = [
 { id: "brush", label: "Brush (Cọ vẽ)", shortLabel: "Brush", icon: Paintbrush },
 { id: "eraser", label: "Eraser (Tẩy)", shortLabel: "Eraser", icon: Eraser },
 { id: "crop", label: "Crop (Cắt ảnh)", shortLabel: "Crop", icon: Crop },
 { id: "artboard", label: "Artboard (Khung)", shortLabel: "Artboard", icon: Frame },
 { id: "rect", label: "Hình vuông", shortLabel: "Rect", icon: Square },
 { id: "ellipse", label: "Hình tròn", shortLabel: "Ellipse", icon: Circle },
];

const LEGACY_REQUIRED_TOOL_MAP: Record<string, ThumbnailRequiredTool | null> = {
 paint: "brush",
 frame: "artboard",
 shape: "rect",
 pointer: "brush",
 transform: "artboard",
};

const THUMBNAIL_DEFAULT_GEM_URL = "https://gemini.google.com/app";
const STUDIO_TOP_TABS_CLASS = "h-8 bg-muted/20 p-0.5 border border-border/40";
const STUDIO_TAB_TRIGGER_CLASS = "h-7 px-3 text-[11px] font-bold rounded-lg";
const STUDIO_ROUND_SELECT_CLASS = "h-8 rounded-full bg-muted/20 border-border/70 text-xs";
const STUDIO_INPUT_CLASS = "h-8 rounded-lg bg-muted/20 border-border/70 text-xs";
const STUDIO_BUTTON_CLASS = "h-8 rounded-full px-3 text-xs";
const STUDIO_LABEL_CLASS = "text-[11px] font-bold text-muted-foreground/90";
const STUDIO_LIBRARY_GRID_CLASS = "grid gap-3 items-stretch [grid-template-columns:repeat(auto-fit,minmax(15rem,1fr))]";
const STUDIO_CARD_META_BADGE_CLASS = "rounded-full border border-border/50 bg-background/70 px-2 py-1 text-[10px] font-bold text-muted-foreground";
const STUDIO_LIBRARY_CARD_CLASS = "flex h-full w-full flex-col rounded-2xl border border-border/50 bg-card p-2 text-left transition-all hover:bg-muted/50 active:scale-[0.98]";
const STUDIO_LIBRARY_CARD_ACTIONS_CLASS = "absolute inset-x-1 top-1 z-10 flex items-center justify-between gap-1 p-0.5";
const STUDIO_LIBRARY_CARD_ICON_CLASS = "flex size-7 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-xs text-primary shadow-sm";

function normalizeRequiredTools(
 requiredTools: Array<ThumbnailRequiredTool | string> | undefined,
 requiresMask = false,
) {
 const fallback: Array<ThumbnailRequiredTool | string> = requiresMask ? ["brush"] : [];
 const source = requiredTools && requiredTools.length > 0 ? requiredTools : fallback;
 const normalized: ThumbnailRequiredTool[] = [];
 const VALID_TOOLS: ThumbnailRequiredTool[] = ["brush", "eraser", "crop", "artboard", "rect", "ellipse"];

 source.forEach((tool) => {
  const value = String(tool).trim().toLowerCase();
  if (!value) return;
  const mapped = LEGACY_REQUIRED_TOOL_MAP[value] ?? value;
  if (VALID_TOOLS.includes(mapped as ThumbnailRequiredTool) && !normalized.includes(mapped as ThumbnailRequiredTool)) {
   normalized.push(mapped as ThumbnailRequiredTool);
  }
 });

 return normalized;
}

function formatFieldPreviewValue(field: ThumbnailButtonField, buttonFields?: ThumbnailButtonField[]) {
 const options = (field.options && field.options.length > 0)
  ? field.options
  : (buttonFields?.find(f => f.key === field.key)?.options || []);

 if (field.type === "multi-select") {
  const arr = Array.isArray(field.value) ? field.value : [];
  if (arr.length > 0) return arr.join(", ");
  if (options.length > 0) return `${options.length} lựa chọn: ${options.slice(0, 3).join(", ")}${options.length > 3 ? "..." : ""}`;
  return "Chưa có giá trị";
 }
 if (field.type === "select") {
  const v = String(field.value ?? "").trim();
  if (v) return v;
  if (options.length > 0) return `${options.length} tùy chọn: ${options.slice(0, 3).join(", ")}${options.length > 3 ? "..." : ""}`;
  return "Chưa có giá trị";
 }
 const normalized = stringifyPromptValue(field.value).trim();
 return normalized || "Chưa có giá trị";
}

function renderToolRequirementBadges(toolIds: Array<ThumbnailRequiredTool | string> | undefined, requiresMask = false) {
 return normalizeRequiredTools(toolIds, requiresMask).map((toolId) => {
  const toolMeta = TOOL_REQUIREMENT_OPTIONS.find((option) => option.id === toolId);
  if (!toolMeta) return null;
  const ToolIcon = toolMeta.icon;
  return (
   <span
    key={toolId}
    className={cn("inline-flex items-center gap-1", STUDIO_CARD_META_BADGE_CLASS)}
   >
    <ToolIcon className="size-3" />
    {toolMeta.shortLabel}
   </span>
  );
 });
}

function EffectControlPreviewCard({
 icon,
 name,
 fields,
 requiredTools,
 requiresMask = false,
}: {
 icon: string;
 name: string;
 fields: ThumbnailButtonField[];
 requiredTools?: Array<ThumbnailRequiredTool | string>;
 requiresMask?: boolean;
}) {
 return (
  <div className="rounded-2xl border border-border/50 bg-card/50 overflow-hidden shadow-sm">
   <div className="px-4 py-2 bg-muted/30 border-b border-border/30 flex items-center justify-between gap-3">
    <div className="flex min-w-0 items-center gap-2">
     <div className="size-6 shrink-0 rounded bg-primary/10 flex items-center justify-center text-xs text-primary">
      {icon || "✨"}
     </div>
     <span className="truncate text-xs font-semibold  text-primary/80">{name}</span>
    </div>
    <div className="flex flex-wrap justify-end gap-1">
     {renderToolRequirementBadges(requiredTools ?? [], requiresMask)}
    </div>
   </div>
   <div className="p-4 space-y-2.5">
    {fields.length > 0 ? (
     fields.map((field) => (
      <div key={field.key} className="rounded-xl border border-border/40 bg-background/60 px-3 py-2">
       <div className="flex items-center justify-between gap-3">
        <span className={STUDIO_LABEL_CLASS}>{field.label}</span>
        {field.required && (
         <Badge variant="outline" className="h-5 px-2 text-[11px] border-primary/30 text-primary bg-primary/5">
          Required
         </Badge>
        )}
       </div>
       <p className="mt-1 text-[11px] font-medium leading-relaxed text-foreground break-words whitespace-pre-wrap">
        {formatFieldPreviewValue(field)}
       </p>
      </div>
     ))
    ) : (
     <div className="rounded-xl border border-dashed border-border/50 px-3 py-5 text-center text-xs text-muted-foreground">
      Button này chưa có tham số đầu vào.
     </div>
    )}
    {requiresMask && (
     <div className="rounded-xl border border-primary/20 bg-primary/5 px-3 py-2 text-xs text-primary">
      Button này yêu cầu user vẽ mask trước khi chạy thật.
     </div>
    )}
   </div>
  </div>
 );
}

function EmojiPicker({ selected, onSelect, className }: { selected: string, onSelect: (e: string) => void, className?: string }) {
 const [search, setSearch] = useState("");
 const query = search.trim().toLowerCase();
 const filtered = ICON_PICKER_GROUPS.map(cat => ({
  ...cat,
  items: cat.items.filter((item) => {
   if (!query) return true;
   return item.value.includes(search) || item.keywords.some((keyword) => keyword.includes(query));
  })
 })).filter(cat => cat.items.length > 0);

 return (
  <div className={cn("p-4 space-y-4 bg-popover border border-border rounded-2xl shadow-2xl min-w-[300px]", className)}>
   <Input
    placeholder="Tìm icon hoặc emoji..."
    value={search}
    onChange={e => setSearch(e.target.value)}
    className="h-9 bg-muted/20 border-border/50 rounded-xl"
   />
   <ScrollArea className="h-[250px]">
    <div className="space-y-4 pr-3">
     {filtered.map(cat => (
      <div key={cat.category} className="space-y-2">
       <h4 className="text-xs font-semibold  text-muted-foreground">{cat.category}</h4>
       <div className="grid grid-cols-6 gap-1.5">
        {cat.items.map(item => (
         <button
          key={`${cat.category}-${item.value}`}
          onClick={() => onSelect(item.value)}
          className={cn(
           "size-10 flex items-center justify-center rounded-xl hover:bg-primary/20 transition-all text-lg",
           selected === item.value && "bg-primary text-primary-foreground shadow-lg scale-110"
          )}
          title={item.keywords.join(", ")}
         >
          {item.value}
         </button>
        ))}
       </div>
      </div>
     ))}
    </div>
   </ScrollArea>
  </div>
 );
}


type LeftPanelTab = "buttons" | "profiles" | "projects";
type MainPanelTab = "canvas" | "config";
type ConfigPanelTab = "button" | "profile";
type EffectPanelTab = "effects" | "gemini" | "app";
type EffectControlEffect = { id: string; buttonId: string; fields: ThumbnailButtonField[] };

// ─── Version Comparator Component ──────────────────────────────────────────────
function VersionComparator({
 beforeUrl, afterUrl, beforeLabel, afterLabel, onClose,
}: {
 beforeUrl: string; afterUrl: string; beforeLabel: string; afterLabel: string; onClose: () => void;
}) {
 const [sliderPos, setSliderPos] = useState(50);
 const containerRef = useRef<HTMLDivElement>(null);
 const isDragging = useRef(false);

 const updateSlider = useCallback((clientX: number) => {
  if (!containerRef.current) return;
  const rect = containerRef.current.getBoundingClientRect();
  const pct = Math.max(2, Math.min(98, ((clientX - rect.left) / rect.width) * 100));
  setSliderPos(pct);
 }, []);

 useEffect(() => {
  const onMove = (e: MouseEvent) => { if (isDragging.current) updateSlider(e.clientX); };
  const onUp = () => { isDragging.current = false; };
  const onTouchMove = (e: TouchEvent) => { if (isDragging.current) updateSlider(e.touches[0].clientX); };
  window.addEventListener("mousemove", onMove);
  window.addEventListener("mouseup", onUp);
  window.addEventListener("touchmove", onTouchMove);
  window.addEventListener("touchend", onUp);
  return () => {
   window.removeEventListener("mousemove", onMove);
   window.removeEventListener("mouseup", onUp);
   window.removeEventListener("touchmove", onTouchMove);
   window.removeEventListener("touchend", onUp);
  };
 }, [updateSlider]);

 const startDrag = useCallback((clientX: number) => {
  isDragging.current = true;
  updateSlider(clientX);
 }, [updateSlider]);

 return (
  <div className="fixed inset-0 z-50 bg-background/95 backdrop-blur-md flex flex-col items-center justify-center p-6 gap-5">
   {/* Header */}
   <div className="flex items-center justify-between w-full max-w-5xl">
    <div className="flex items-center gap-3">
     <SplitSquareVertical className="size-5 text-primary" />
     <span className="text-sm font-black text-foreground">So sánh phiên bản</span>
     <div className="rounded-full bg-muted/50 px-2.5 py-1 text-xs font-semibold text-muted-foreground">Kéo thanh để so sánh</div>
    </div>
    <button
     onClick={onClose}
     className="size-9 flex items-center justify-center rounded-xl bg-muted/50 hover:bg-muted text-foreground transition-all hover:scale-105"
    >
     <X className="size-5" />
    </button>
   </div>

   {/* Comparator canvas */}
   <div
    ref={containerRef}
    className="relative w-full max-w-5xl rounded-2xl overflow-hidden border border-border/50 shadow-2xl select-none"
    style={{ aspectRatio: "16/9", cursor: "col-resize" }}
    onMouseDown={(e) => { startDrag(e.clientX); e.preventDefault(); }}
    onTouchStart={(e) => { startDrag(e.touches[0].clientX); }}
   >
    {/* After image (full width, right side) */}
    <img src={afterUrl} alt={afterLabel} className="absolute inset-0 size-full object-contain bg-black" draggable={false} />

    {/* Before image (clipped to left side) */}
    <div className="absolute inset-0 overflow-hidden" style={{ width: `${sliderPos}%` }}>
     <img
      src={beforeUrl} alt={beforeLabel} draggable={false}
      className="absolute inset-0 object-contain bg-black/80"
      style={{ width: `${(100 / sliderPos) * 100}%`, maxWidth: "none", height: "100%" }}
     />
    </div>

    {/* Divider line */}
    <div
     className="absolute top-0 bottom-0 w-[2px] bg-white/90 shadow-[0_0_16px_rgba(255,255,255,0.7)]"
     style={{ left: `${sliderPos}%`, transform: "translateX(-50%)" }}
    >
     {/* Handle */}
     <div
      className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 size-10 rounded-full bg-white shadow-2xl flex items-center justify-center cursor-col-resize border-2 border-white/50"
      onMouseDown={(e) => { e.stopPropagation(); isDragging.current = true; e.preventDefault(); }}
     >
      <div className="flex gap-1 items-center">
       <div className="w-0.5 h-5 bg-gray-500 rounded-full" />
       <div className="w-0.5 h-5 bg-gray-500 rounded-full" />
      </div>
     </div>
    </div>

    {/* Labels */}
    {sliderPos > 12 && (
     <div className="absolute bottom-4 left-4 px-3 py-1 rounded-full bg-black/70 backdrop-blur-sm text-white text-[11px] font-bold transition-opacity">
      ← {beforeLabel}
     </div>
    )}
    {sliderPos < 88 && (
     <div className="absolute bottom-4 right-4 px-3 py-1 rounded-full bg-black/70 backdrop-blur-sm text-white text-[11px] font-bold transition-opacity">
      {afterLabel} →
     </div>
    )}
   </div>

   {/* Slider range input (keyboard / touch fallback) */}
   <div className="w-full max-w-5xl flex items-center gap-4">
    <span className="w-20 truncate text-right text-xs font-semibold text-white/40">{beforeLabel}</span>
    <input
     type="range" min={2} max={98} value={Math.round(sliderPos)}
     onChange={(e) => setSliderPos(Number(e.target.value))}
     className="flex-1 h-1 accent-white cursor-pointer"
    />
    <span className="w-20 truncate text-xs font-semibold text-white/40">{afterLabel}</span>
   </div>
  </div>
 );
}

function ZoomableGalleryImage({ src, alt, badge, badgeClass }: { src: string; alt: string; badge?: React.ReactNode; badgeClass?: string }) {
  const [scale, setScale] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [isDragging, setIsDragging] = useState(false);
  const dragStart = useRef({ x: 0, y: 0 });
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setScale(1);
    setPan({ x: 0, y: 0 });
  }, [src]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const handleWheel = (e: WheelEvent) => {
      e.preventDefault();
      setScale(s => Math.min(Math.max(0.2, s - e.deltaY * 0.005), 10));
    };
    container.addEventListener('wheel', handleWheel, { passive: false });
    return () => container.removeEventListener('wheel', handleWheel);
  }, []);

  const handleMouseDown = (e: React.MouseEvent) => {
    e.preventDefault();
    setIsDragging(true);
    dragStart.current = { x: e.clientX - pan.x, y: e.clientY - pan.y };
  };

  const handleMouseMove = (e: React.MouseEvent) => {
    if (!isDragging) return;
    setPan({ x: e.clientX - dragStart.current.x, y: e.clientY - dragStart.current.y });
  };

  const handleMouseUp = () => setIsDragging(false);

  return (
    <div 
      ref={containerRef}
      className="relative flex-1 rounded-2xl overflow-hidden border border-border/50 shadow-2xl min-h-0 flex items-center justify-center bg-background/50 cursor-grab active:cursor-grabbing group/zoom"
      onMouseDown={handleMouseDown}
      onMouseMove={handleMouseMove}
      onMouseUp={handleMouseUp}
      onMouseLeave={handleMouseUp}
    >
      <img
        src={src}
        alt={alt}
        style={{ transform: `translate(${pan.x}px, ${pan.y}px) scale(${scale})`, transition: isDragging ? 'none' : 'transform 0.1s ease-out' }}
        className="max-h-full max-w-full object-contain select-none"
        draggable={false}
      />
      {badge && (
        <div className={cn("absolute top-3 left-3 px-3 py-1 rounded-full text-xs font-black shadow-lg", badgeClass)}>
          {badge}
        </div>
      )}
      <div className="absolute bottom-3 right-3 flex items-center gap-2 bg-background/80 backdrop-blur-md px-2 py-1 rounded-lg border border-border/50 text-xs opacity-0 group-hover/zoom:opacity-100 transition-opacity">
        <button onClick={(e) => { e.stopPropagation(); setScale(s => Math.max(0.2, s - 0.5)); }} className="hover:text-primary w-6 h-6 flex items-center justify-center rounded-md hover:bg-muted">-</button>
        <span className="w-10 text-center font-mono">{Math.round(scale * 100)}%</span>
        <button onClick={(e) => { e.stopPropagation(); setScale(s => Math.min(10, s + 0.5)); }} className="hover:text-primary w-6 h-6 flex items-center justify-center rounded-md hover:bg-muted">+</button>
        <button onClick={(e) => { e.stopPropagation(); setScale(1); setPan({x:0, y:0}); }} className="ml-1 hover:text-primary w-6 h-6 flex items-center justify-center rounded-md hover:bg-muted" title="Reset"><RefreshCw className="size-3"/></button>
      </div>
    </div>
  );
}

type ThumbnailStudioProps = {
 isActive?: boolean;
};

export default function ThumbnailStudio({ isActive = true }: ThumbnailStudioProps) {
 const [bootLoading, setBootLoading] = useState(true);
 const [submitting, setSubmitting] = useState(false);
 const [runStatus, setRunStatus] = useState<string>("");
 const [draggedEffectId, setDraggedEffectId] = useState<string | null>(null);

 const [buttonSearchQuery, setButtonSearchQuery] = useState("");
 const [profileSearchQuery, setProfileSearchQuery] = useState("");
 const [projectSearchQuery, setProjectSearchQuery] = useState("");

 const submittingRef = useRef(false);
 const buttonPresetInputRef = useRef<HTMLInputElement>(null);
 const profilePresetInputRef = useRef<HTMLInputElement>(null);
 const imageInputRef = useRef<HTMLInputElement>(null);
 const [exporting, setExporting] = useState(false);
 const [bootstrap, setBootstrap] = useState<ThumbnailBootstrapPayload | null>(null);
 const [thumbnailSettingsDraft, setThumbnailSettingsDraft] = useState<ThumbnailSettings | null>(null);
 const [availableGems, setAvailableGems] = useState<Array<{ name: string; url: string }>>([]);
 const [gemsRefreshing, setGemsRefreshing] = useState(false);
 const [activeProject, setActiveProject] = useState<ThumbnailProjectDetail | null>(null);
 const [maskBase64, setMaskBase64] = useState<string | null>(null);
 const [showComparator, setShowComparator] = useState(false);
 const [showExportDialog, setShowExportDialog] = useState(false);
 const [sessionStatus, setSessionStatus] = useState<ThumbnailBootstrapPayload["sessionStatus"] | null>(null);
 const [refreshingSession, setRefreshingSession] = useState(false);

 const persistSessionErrorMessage = useCallback((message: string) => {
   if (!isLikelyGeminiAuthMessage(message)) {
     return;
   }
   setSessionStatus((current) => ({
     backend: current?.backend ?? "gemini_web",
     dependencies_ready: current?.dependencies_ready ?? true,
     authenticated: false,
     browser: current?.browser ?? null,
     profileDir: current?.profileDir ?? "",
     message,
   }));
 }, []);

 const refreshSessionStatus = useCallback(async (refresh = false) => {
   if (refresh) setRefreshingSession(true);
   try {
     const status = await getThumbnailSessionStatus(refresh);
     setSessionStatus(status);
     if (refresh && status.authenticated) {
       toast.success("Phiên Gemini đã được làm mới.");
     }
   } catch (error) {
     console.error("Failed to refresh thumbnail session status:", error);
   } finally {
     if (refresh) setRefreshingSession(false);
   }
 }, []);

 const handleOpenLogin = async () => {
   try {
     await openThumbnailLogin();
     toast.info("Đang mở cửa sổ đăng nhập Gemini...");
     // Poll for status after opening login
     setTimeout(() => void refreshSessionStatus(false), 2000);
   } catch (error) {
     toast.error(getErrorMessage(error));
   }
 };
 // Gallery preview: null = closed, string = versionId currently being previewed
 const [galleryPreviewVersionId, setGalleryPreviewVersionId] = useState<string | null>(null);
 const [canvasGuide, setCanvasGuide] = useState<CanvasGuide | null>(null);

 const hasBootstrappedRef = useRef(false);
 // Free-pick comparison: A and B are version IDs chosen by the user
 const [compareVersionAId, setCompareVersionAId] = useState<string | null>(null);
 const [compareVersionBId, setCompareVersionBId] = useState<string | null>(null);

 const [selectedMode] = useState<"preset" | "custom" | "mask">("preset");
 const [leftPanelTab, setLeftPanelTab] =
  useLocalStorage<LeftPanelTab>("thumbnail.leftPanelTab", "buttons");
 const [mainPanelTab, setMainPanelTab] = useState<MainPanelTab>("canvas");
 const [configPanelTab, setConfigPanelTab] =
  useLocalStorage<ConfigPanelTab>("thumbnail.configPanelTab", "button");
 const [effectTab, setEffectTab] =
  useLocalStorage<EffectPanelTab>("thumbnail.effectTab", "effects");
 const regenerateMode = "new-chat" as const;

 // Effect Control State
 const [activeEffects, setActiveEffects] = useState<EffectControlEffect[]>([]);
 const [canvasToolRequest, setCanvasToolRequest] = useState<{
  toolGroup: ThumbnailRequiredTool;
  nonce: number;
  } | null>(null);
 const [canvasGuideRequest, setCanvasGuideRequest] = useState<{ guide: Partial<CanvasGuide>; nonce: number } | null>(null);
 const [canvasSyncNonce, setCanvasSyncNonce] = useState(0);
 const [canvasBrushSize, setCanvasBrushSize] = useState<number | undefined>(undefined);
 const [canvasBrushColor, setCanvasBrushColor] = useState<string | undefined>(undefined);
 const [canvasShapeTool, setCanvasShapeTool] = useState<CanvasShapeTool | undefined>(undefined);
 const [canvasShapeFill, setCanvasShapeFill] = useState<string | undefined>(undefined);
 const [canvasShapeOpacity, setCanvasShapeOpacity] = useState<number | undefined>(undefined);
 const [canvasShapeHardness, setCanvasShapeHardness] = useState<number | undefined>(undefined);
 const [canvasShapeSize, setCanvasShapeSize] = useState<number | undefined>(undefined);

 // Button Builder State
 const [buttonBuilderName, setButtonBuilderName] = useState("");
 const [buttonBuilderCategory, setButtonBuilderCategory] = useState("Custom");
 const [buttonBuilderPrompt, setButtonBuilderPrompt] = useState("");
 const builderCreateNewChat = true;
 const [buttonRequiredTools, setButtonRequiredTools] = useState<ThumbnailRequiredTool[]>([]);
 const [builderFields, setBuilderFields] = useState<ThumbnailButtonField[]>([]);

 // Profile Builder State
 const [profileName, setProfileName] = useState("");
 const [profileDesc, setProfileDesc] = useState("");
 const [profileIcon, setProfileIcon] = useState("📦");

 // Editing State
 const [editingButtonId, setEditingButtonId] = useState<string | null>(null);
 const [editingProfileId, setEditingProfileId] = useState<string | null>(null);
 const [collapsedEffects, setCollapsedEffects] = useState<Set<string>>(new Set());
 const [buttonIcon, setButtonIcon] = useState("✨");
 // Builder: New Field State
 const [newFieldKey, setNewFieldKey] = useState("");
 const [newFieldLabel, setNewFieldLabel] = useState("");
 const [newFieldType, setNewFieldType] = useState<ThumbnailButtonField["type"]>("text");
 const [editingFieldIndex, setEditingFieldIndex] = useState<number | null>(null);
 const [newFieldDefault, setNewFieldDefault] = useState<any>("");
 const [newFieldOptions, setNewFieldOptions] = useState("");
 const [newFieldMin, setNewFieldMin] = useState<number | null>(null);
 const [newFieldMax, setNewFieldMax] = useState<number | null>(null);
 const [newFieldRequired, setNewFieldRequired] = useState(false);
 const [newFieldVisibleIf, setNewFieldVisibleIf] = useState("");
 const [newFieldBindToCanvas, setNewFieldBindToCanvas] = useState<"none" | "artboard_ratio" | "crop_ratio" | "brush_size" | "brush_color" | "shape_type" | "shape_color" | "shape_opacity" | "shape_hardness" | "shape_size" | null>(null);
 const [isFieldDialogOpen, setIsFieldDialogOpen] = useState(false);

 // Export State
 const [exportFolder, setExportFolder] = useLocalStorage<string>("thumbnail.exportFolder", "");
 const [exportName, setExportName] = useState("thumbnail_final");
 const [importingButtonPreset, setImportingButtonPreset] = useState(false);
 const [importingProfilePreset, setImportingProfilePreset] = useState(false);
 const [exportingButtonPresetId, setExportingButtonPresetId] = useState<string | null>(null);
  const selectedVersion = activeProject?.currentVersion || null; const [exportingProfilePresetId, setExportingProfilePresetId] = useState<string | null>(null);

 const applyCanvasStateToFields = useCallback((
  fields: ThumbnailButtonField[],
  canvasState: {
   guide?: CanvasGuide | null;
   brush?: { size: number; color: string };
   shape?: { type?: CanvasShapeTool; fill: string; opacity: number; hardness: number; size?: number };
  },
 ) => {
  let changed = false;
  const { guide, brush, shape } = canvasState;
  const nextFields = fields.map((field) => {
   if (field.bindToCanvas === "artboard_ratio" && guide?.mode === "artboard" && guide.ratioLabel) {
    if (field.value !== guide.ratioLabel) {
     changed = true;
     return { ...field, value: guide.ratioLabel };
    }
   }
   if (field.bindToCanvas === "crop_ratio" && guide?.mode === "crop" && guide.ratioLabel) {
    if (field.value !== guide.ratioLabel) {
     changed = true;
     return { ...field, value: guide.ratioLabel };
    }
   }
   if (field.bindToCanvas === "brush_size" && brush) {
    if (Number(field.value) !== brush.size) {
     changed = true;
     return { ...field, value: brush.size };
    }
   }
   if (field.bindToCanvas === "brush_color" && brush) {
    if (String(field.value) !== brush.color) {
     changed = true;
     return { ...field, value: brush.color };
    }
   }
   if (field.bindToCanvas === "shape_color" && shape) {
    if (String(field.value) !== shape.fill) {
     changed = true;
     return { ...field, value: shape.fill };
    }
   }
   if (field.bindToCanvas === "shape_type" && shape?.type) {
    if (String(field.value) !== shape.type) {
     changed = true;
     return { ...field, value: shape.type };
    }
   }
   if (field.bindToCanvas === "shape_opacity" && shape) {
    if (Number(field.value) !== shape.opacity) {
     changed = true;
     return { ...field, value: shape.opacity };
    }
   }
   if (field.bindToCanvas === "shape_hardness" && shape) {
    if (Number(field.value) !== shape.hardness) {
     changed = true;
     return { ...field, value: shape.hardness };
    }
   }
   if (field.bindToCanvas === "shape_size" && shape?.size !== undefined) {
    if (Number(field.value) !== shape.size) {
     changed = true;
     return { ...field, value: shape.size };
    }
   }
   if (field.key === "artboard_hint" && guide?.mode === "artboard" && guide.ratioLabel) {
    const artboardHint = `Respect the ${guide.ratioLabel} artboard guide and keep the subject balanced inside the new frame.`;
    if (field.value !== artboardHint) {
     changed = true;
     return { ...field, value: artboardHint };
    }
   }
   return field;
  });
  return changed ? nextFields : fields;
 }, []);

  const updateActiveButtonFields = useCallback((updateFn: (fields: ThumbnailButtonField[]) => ThumbnailButtonField[]) => {
    if (!selectedVersion) return;
    setActiveEffects(curr => {
      let changed = false;
      const next = curr.map(eff => {
        const nextFields = updateFn(eff.fields);
        if (nextFields !== eff.fields) {
          changed = true;
          return { ...eff, fields: nextFields };
        }
        return eff;
      });
      return changed ? next : curr;
    });
  }, [selectedVersion]);

  const handleCanvasGuideChange = useCallback((guide: CanvasGuide | null) => {
    setCanvasGuide(guide);
    setCanvasGuideRequest(null);
    updateActiveButtonFields((fields) => applyCanvasStateToFields(fields, { guide }));
   }, [updateActiveButtonFields, applyCanvasStateToFields]);

  const handleCanvasBrushChange = useCallback((brush: { size: number; color: string }) => {
    setCanvasBrushSize(brush.size);
    setCanvasBrushColor(brush.color);
    updateActiveButtonFields((fields) => applyCanvasStateToFields(fields, { brush }));
   }, [updateActiveButtonFields, applyCanvasStateToFields]);

  const handleCanvasShapeChange = useCallback((shape: {
    type: CanvasShapeTool;
    fill: string;
    opacity: number;
    hardness: number;
    size: number;
   }) => {
    setCanvasShapeTool(shape.type);
    setCanvasShapeFill(shape.fill);
    setCanvasShapeOpacity(shape.opacity);
    setCanvasShapeHardness(shape.hardness);
    setCanvasShapeSize(shape.size);
    updateActiveButtonFields((fields) => applyCanvasStateToFields(fields, { shape }));
   }, [updateActiveButtonFields, applyCanvasStateToFields]);

 const [, startTransition] = useTransition();

 function mergeButtons(nextButtons: ThumbnailButton[]) {
  setBootstrap((current) => {
   if (!current) return current;
   const merged = new Map(current.buttons.map((button) => [button.id, button]));
   nextButtons.forEach((button) => merged.set(button.id, button));
   return { ...current, buttons: Array.from(merged.values()) };
  });
 }

 function mergeProfiles(nextProfiles: ThumbnailProfile[]) {
  setBootstrap((current) => {
   if (!current) return current;
   const merged = new Map(current.profiles.map((profile) => [profile.id, profile]));
   nextProfiles.forEach((profile) => merged.set(profile.id, profile));
   return { ...current, profiles: Array.from(merged.values()) };
  });
 }

 useEffect(() => {
  const handleGlobalPaste = (e: ClipboardEvent) => {
   const items = e.clipboardData?.items;
   if (!items) return;
   for (const item of Array.from(items)) {
    if (item.type.startsWith("image/")) {
     const blob = item.getAsFile();
     if (blob) void processImageFile(blob);
     return;
    }
   }
  };
  window.addEventListener("paste", handleGlobalPaste);
  return () => window.removeEventListener("paste", handleGlobalPaste);
 }, [activeProject]);

 useEffect(() => {
  if (!thumbnailSettingsDraft?.app_theme) return;
  const theme = thumbnailSettingsDraft.app_theme;
  const isDark = theme === "dark" || (theme === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.classList.toggle("dark", isDark);
 }, [thumbnailSettingsDraft?.app_theme]);

  useEffect(() => {
    if (bootstrap?.sessionStatus) {
      setSessionStatus(bootstrap.sessionStatus);
    }
  }, [bootstrap?.sessionStatus]);

  useEffect(() => {
    if (!isActive) return;
    const timer = setInterval(() => {
      void refreshSessionStatus();
    }, 30000);
    return () => clearInterval(timer);
  }, [isActive, refreshSessionStatus]);

  useEffect(() => {
    // Reset comparison state when switching projects to avoid cross-project conflicts
    setCompareVersionAId(null);
    setCompareVersionBId(null);
    setShowComparator(false);
  }, [activeProject?.id]);

 useEffect(() => {
  if (!isActive || hasBootstrappedRef.current) return;
  hasBootstrappedRef.current = true;

  let cancelled = false;
  void (async () => {
   setBootLoading(true);
   try {
    const payload = await getThumbnailBootstrap();
    if (cancelled) return;
    startTransition(() => {
     setBootstrap(payload);
     setThumbnailSettingsDraft(payload.settings);
     setActiveProject(payload.activeProject);
    });
    if ((payload.settings.gemini_base_url || THUMBNAIL_DEFAULT_GEM_URL) !== THUMBNAIL_DEFAULT_GEM_URL) {
     void listThumbnailGems()
      .then((gems) => {
       if (!cancelled) {
        setAvailableGems(gems);
       }
      })
      .catch(() => undefined);
    }
   } catch (error) {
    hasBootstrappedRef.current = false;
    if (cancelled) return;
    toast.error(getErrorMessage(error));
   } finally {
    if (!cancelled) {
     setBootLoading(false);
    }
   }
  })();
  return () => {
   cancelled = true;
  };
 }, [isActive, startTransition]);

 const handleRefreshGems = useCallback(async () => {
  try {
   setGemsRefreshing(true);
   toast.info("Đang quét và làm mới danh sách Gem...");
   const gems = await listThumbnailGems();
   setAvailableGems(gems);
   toast.success(`Đã làm mới, tìm thấy ${gems.length} Gem.`);
  } catch (error) {
   const message = getErrorMessage(error);
   persistSessionErrorMessage(message);
   toast.error(message);
  } finally {
   setGemsRefreshing(false);
  }
 }, [persistSessionErrorMessage]);

 const handleSaveThumbnailSettings = useCallback(async (partial: Partial<ThumbnailSettings>) => {
  if (!thumbnailSettingsDraft) return;
  try {
   const next = await updateThumbnailSettings(partial);
   setThumbnailSettingsDraft(next);
   setBootstrap((current) => (
    current
     ? {
       ...current,
       settings: next,
       sessionStatus: {
        ...current.sessionStatus,
        baseUrl: next.gemini_base_url,
       },
      }
     : current
   ));
  } catch (error) {
   toast.error(getErrorMessage(error));
  }
 }, [thumbnailSettingsDraft]);
 const currentGemSelection = thumbnailSettingsDraft?.gemini_base_url?.trim() || THUMBNAIL_DEFAULT_GEM_URL;
 const gemOptions = useMemo(() => {
  const next = [...availableGems];
  if (
   currentGemSelection !== THUMBNAIL_DEFAULT_GEM_URL
   && !next.some((gem) => gem.url === currentGemSelection)
  ) {
   next.unshift({
    name: "Gem hiện tại",
    url: currentGemSelection,
   });
  }
  return next;
 }, [availableGems, currentGemSelection]);

 const thumbnailGeminiSettingsPanel = thumbnailSettingsDraft ? (
  <div className="rounded-2xl border border-border/50 bg-card/70 p-5 shadow-sm">
   <FieldGroup className="gap-5">
    <Field>
     <TooltipFieldLabel tooltip="Chọn Gemini mặc định hoặc một Gem đã lưu để Thumbnail Studio dùng khi chạy.">
      Gemini App / Gem
     </TooltipFieldLabel>
     <div className="flex items-center gap-2">
      <Select
       value={thumbnailSettingsDraft.gemini_base_url || THUMBNAIL_DEFAULT_GEM_URL}
       onValueChange={(value) => void handleSaveThumbnailSettings({ gemini_base_url: value })}
      >
       <SelectTrigger className={cn(STUDIO_ROUND_SELECT_CLASS, "flex-1")}>
        <SelectValue />
       </SelectTrigger>
       <SelectContent>
        <SelectItem value={THUMBNAIL_DEFAULT_GEM_URL}>Gemini mặc định</SelectItem>
        {gemOptions.map((gem) => (
         <SelectItem key={gem.url} value={gem.url}>
          {gem.name}
         </SelectItem>
        ))}
       </SelectContent>
      </Select>
      <Button
       variant="ghost"
       size="icon"
       className={cn("size-9 shrink-0 rounded-xl border border-border/70 bg-muted/20 hover:bg-muted/40", gemsRefreshing && "pointer-events-none")}
       onClick={() => void handleRefreshGems()}
       aria-label="Làm mới danh sách gem"
       title="Làm mới danh sách gem"
      >
       <RefreshCw className={cn("size-4", gemsRefreshing && "animate-spin")} />
      </Button>
     </div>
    </Field>

    <div className="grid grid-cols-2 gap-4 items-end">
     <Field>
      <TooltipFieldLabel tooltip="Chọn model Gemini để cân bằng giữa tốc độ và chất lượng đầu ra.">
       Model
      </TooltipFieldLabel>
      <Select
       value={thumbnailSettingsDraft.gemini_model || "flash"}
       onValueChange={(value) => void handleSaveThumbnailSettings({ gemini_model: value })}
      >
       <SelectTrigger className={cn(STUDIO_INPUT_CLASS, "h-9 rounded-xl")}>
        <SelectValue />
       </SelectTrigger>
       <SelectContent>
        <SelectItem value="flash">
         <div className="flex items-center gap-2">
          <Zap className="size-3 text-yellow-500" />
          <span>Nhanh (Flash)</span>
         </div>
        </SelectItem>
        <SelectItem value="thinking">
         <div className="flex items-center gap-2">
          <Brain className="size-3 text-blue-500" />
          <span>Tư duy (Thinking)</span>
         </div>
        </SelectItem>
        <SelectItem value="pro">
         <div className="flex items-center gap-2">
          <Sparkles className="size-3 text-fuchsia-500" />
          <span>Mạnh hơn (Pro)</span>
         </div>
        </SelectItem>
       </SelectContent>
      </Select>
     </Field>

     <div className="flex h-9 items-center justify-between gap-3 rounded-xl border border-border/70 bg-muted/20 px-3 pb-0.5">
      <span className="text-[11px] font-bold text-muted-foreground tracking-tight">Chạy nền</span>
      <Switch
       checked={thumbnailSettingsDraft.gemini_headless}
       onCheckedChange={(value) => void handleSaveThumbnailSettings({ gemini_headless: value })}
       className="scale-75 origin-right"
      />
     </div>
    </div>
   </FieldGroup>
  </div>
 ) : null;

 const buttons = bootstrap?.buttons ?? [];
 const profiles = bootstrap?.profiles ?? [];
 const sortedButtons = useMemo(
  () => buttons.slice()
   .filter(b => b.name.toLowerCase().includes(buttonSearchQuery.toLowerCase()))
   .sort((a, b) => (b.isPinned ? 1 : 0) - (a.isPinned ? 1 : 0)),
  [buttons, buttonSearchQuery],
 );
 const sortedProfiles = useMemo(
  () => profiles.slice()
   .filter(p => p.name.toLowerCase().includes(profileSearchQuery.toLowerCase()))
   .sort((a, b) => (b.isPinned ? 1 : 0) - (a.isPinned ? 1 : 0)),
  [profiles, profileSearchQuery],
 );
 const sortedProjects = useMemo(
  () => (bootstrap?.projects ?? [])
   .filter(p => p.name.toLowerCase().includes(projectSearchQuery.toLowerCase()))
   .sort((a, b) => new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime()),
  [bootstrap?.projects, projectSearchQuery]
 );

 const versions = activeProject?.versions ?? [];
 const showProjectLibraryTab = mainPanelTab !== "config";
 const effectiveLeftPanelTab = !showProjectLibraryTab && leftPanelTab === "projects" ? "buttons" : leftPanelTab;
 const buttonPreviewPrompt = buildPromptPreview(buttonBuilderPrompt, builderFields);
 const runPromptPreview = useMemo(
  () => buildEffectsPromptPreview(activeEffects, buttons),
  [activeEffects, buttons],
 );
 const profilePreviewEffects = useMemo(
  () =>
   activeEffects
    .map((effect) => {
     const button = buttons.find((item) => item.id === effect.buttonId);
     if (!button) return null;
     return {
      id: effect.id,
      icon: button.icon,
      name: button.name,
      fields: effect.fields,
      requiredTools: getButtonRequiredTools(button),
      requiresMask: button.requiresMask,
     };
    })
    .filter((effect): effect is {
     id: string;
     icon: string;
     name: string;
     fields: ThumbnailButtonField[];
     requiredTools: ThumbnailRequiredTool[];
     requiresMask: boolean;
    } => effect !== null),
  [activeEffects, buttons],
 );

 const applyCanvasFieldBinding = useCallback((
  field: ThumbnailButtonField,
  nextValue: ThumbnailButtonField["value"],
  nonce = Date.now() + Math.random(),
 ): ThumbnailRequiredTool | null => {
  const binding = field.bindToCanvas;
  if (!binding || binding === "none") return null;

  if (binding === "artboard_ratio" || binding === "crop_ratio") {
   const ratioLabel = String(nextValue ?? "").trim();
   if (!ratioLabel) return null;
   const toolGroup = binding === "artboard_ratio" ? "artboard" : "crop";
   setCanvasGuideRequest({ guide: { mode: toolGroup, ratioLabel }, nonce });
   return toolGroup;
  }

  if (binding === "brush_size") {
   const value = numericCanvasValue(nextValue);
   if (value !== null) {
    setCanvasBrushSize(value);
    setCanvasSyncNonce(nonce);
   }
   return "brush";
  }

  if (binding === "brush_color") {
   setCanvasBrushColor(String(nextValue ?? ""));
   setCanvasSyncNonce(nonce);
   return "brush";
  }

  if (binding === "shape_type") {
   const shapeTool = normalizeCanvasShapeTool(nextValue);
   if (!shapeTool) return null;
   setCanvasShapeTool(shapeTool);
   setCanvasSyncNonce(nonce);
   return shapeTool;
  }

  if (binding === "shape_color") {
   setCanvasShapeFill(String(nextValue ?? ""));
   setCanvasSyncNonce(nonce);
   return canvasShapeTool || null;
  }

  if (binding === "shape_opacity") {
   const value = numericCanvasValue(nextValue);
   if (value !== null) {
    setCanvasShapeOpacity(value);
    setCanvasSyncNonce(nonce);
   }
   return canvasShapeTool || null;
  }

  if (binding === "shape_hardness") {
   const value = numericCanvasValue(nextValue);
   if (value !== null) {
    setCanvasShapeHardness(value);
    setCanvasSyncNonce(nonce);
   }
   return canvasShapeTool || null;
  }

  if (binding === "shape_size") {
   const value = numericCanvasValue(nextValue);
   if (value !== null) {
    setCanvasShapeSize(value);
    setCanvasSyncNonce(nonce);
   }
   return canvasShapeTool || null;
  }

  return null;
 }, [canvasShapeTool]);

 const requestCanvasToolFromButton = useCallback((button: ThumbnailButton, fields = button.fields) => {
  const nonce = Date.now() + Math.random();
  let boundTool: ThumbnailRequiredTool | null = null;
  fields.forEach((field) => {
   boundTool = applyCanvasFieldBinding(field, field.value, nonce) ;
  });

  const requiredTools = getButtonRequiredTools(button); const fallbackTool = requiredTools.length > 0 ? requiredTools[0] : null;
  const toolGroup = boundTool || fallbackTool;
  if (toolGroup) {
   setCanvasToolRequest({ toolGroup, nonce });
  }
 }, [applyCanvasFieldBinding]);

 useEffect(() => {
  if (!showProjectLibraryTab && leftPanelTab === "projects") {
   setLeftPanelTab("buttons");
  }
 }, [leftPanelTab, setLeftPanelTab, showProjectLibraryTab]);

 const beforeVersion = useMemo(() => {
  if (!activeProject || !selectedVersion) return null;
  if (selectedVersion.parentVersionId) {
   return activeProject.versions.find(v => v.id === selectedVersion.parentVersionId) || activeProject.versions[0];
  }
  return activeProject.versions[0];
 }, [activeProject, selectedVersion]);


 useEffect(() => {
  if (canvasGuide?.mode !== "artboard") return;
  setActiveEffects((current) => {
   let changed = false;
   const next = current.map((effect) => {
    const nextFields = applyCanvasStateToFields(effect.fields, { guide: canvasGuide });
    if (nextFields !== effect.fields) {
     changed = true;
     return { ...effect, fields: nextFields };
    }
    return effect;
   });
   return changed ? next : current;
  });
 }, [applyCanvasStateToFields, canvasGuide]);

 const buildEffectFromButton = useCallback((
  button: ThumbnailBootstrapPayload["buttons"][number],
  savedValues?: Record<string, any>,
 ) => {
  const nextFields = button.fields.map((field) => {
   const raw = savedValues?.[field.key] ?? field.value;
   // Đảm bảo multi-select luôn là mảng
   const value = field.type === "multi-select"
    ? (Array.isArray(raw) ? raw : (raw ? [raw] : []))
    : raw;
   return { ...field, value };
  });
  return {
   id: Math.random().toString(36).substr(2, 9),
   buttonId: button.id,
   fields: applyCanvasStateToFields(nextFields, { guide: canvasGuide }),
  };
 }, [applyCanvasStateToFields, canvasGuide]);

 const addButtonToEffectControl = useCallback((button: ThumbnailButton) => {
  const nextEffect = buildEffectFromButton(button);
  setActiveEffects((current) => [...current, nextEffect]);
  requestCanvasToolFromButton(button, nextEffect.fields);
  toast.success(`Đã thêm ${button.name}`);
 }, [buildEffectFromButton, requestCanvasToolFromButton]);

 const buildEffectFromProfileEffect = useCallback((effect: ThumbnailProfileEffect): EffectControlEffect | null => {
  const button = buttons.find((item) => item.id === effect.buttonId);
  if (!button) return null;

  const savedFields = effect.fields ?? [];
  const savedFieldMap = new Map(savedFields.map((field) => [field.key, field]));
  const mergedFields = button.fields.map((field) => {
   const savedField = savedFieldMap.get(field.key);
   return savedField ? { ...field, ...savedField, value: savedField.value } : { ...field };
  });
  const extraFields = savedFields
   .filter((field) => !button.fields.some((buttonField) => buttonField.key === field.key))
   .map((field) => ({ ...field }));

  return {
   id: Math.random().toString(36).substr(2, 9),
   buttonId: effect.buttonId,
   fields: applyCanvasStateToFields([...mergedFields, ...extraFields ], { guide: canvasGuide } ),
  };
 }, [applyCanvasStateToFields, buttons, canvasGuide]);

 const applyProfileToEffectControl = useCallback((profile: ThumbnailProfile, options?: { silent?: boolean }) => {
  const nextEffects = profile.effects
   .map(buildEffectFromProfileEffect)
   .filter((effect): effect is EffectControlEffect => effect !== null);
  setActiveEffects(nextEffects);
  if (!options?.silent) {
   const firstMatchingEffect = nextEffects.find((effect) => {
    const button = buttons.find((item) => item.id === effect.buttonId);
    return Boolean(button && getButtonRequiredTools(button).length > 0);
   });
   if (firstMatchingEffect) {
    const button = buttons.find((item) => item.id === firstMatchingEffect.buttonId);
    if (button) requestCanvasToolFromButton(button, firstMatchingEffect.fields);
   }
   if (nextEffects.length === profile.effects.length) {
    toast.success(`Đã áp dụng Profile: ${profile.name}`);
   } else {
    toast.warning(`Đã áp dụng Profile: ${profile.name}. Một số effect không còn button tương ứng nên bị bỏ qua.`);
   }
  }
 }, [buildEffectFromProfileEffect, buttons, requestCanvasToolFromButton]);

 function syncProject(project: ThumbnailProjectDetail) {
  startTransition(() => {
   setActiveProject(project);
   setBootstrap((current) => {
    if (!current) return current;
    const updatedProjects = current.projects.some((item) => item.id === project.id)
     ? current.projects.map((item) => (item.id === project.id ? { ...item, ...project, versionCount: project.versions.length } : item))
     : [...current.projects, { ...project, versionCount: project.versions.length }];
    return { ...current, activeProjectId: project.id, activeProject: project, projects: updatedProjects };
   });
  });
 }

 function beginSubmit() {
  if (submittingRef.current) return false;
  submittingRef.current = true;
  setSubmitting(true);
  return true;
 }

 function endSubmit() {
  submittingRef.current = false;
  setSubmitting(false);
 }

 function handleEditButton(button: any) {
  setEditingButtonId(button.id);
  setButtonBuilderName(button.name);
  setButtonBuilderCategory(button.category);
  setButtonBuilderPrompt(button.promptTemplate);
  setButtonRequiredTools(normalizeRequiredTools(button.requiredTools, !!button.requiresMask));
  setButtonIcon(button.icon || "✨");
  setBuilderFields(button.fields.map((f: any) => ({ ...f })));
  setMainPanelTab("config");
  setConfigPanelTab("button");
  toast.info(`Đang sửa Button: ${button.name}`);
 }

 function handleEditProfile(profile: ThumbnailProfile) {
  setEditingProfileId(profile.id);
  setProfileName(profile.name);
  setProfileDesc(profile.description);
  setProfileIcon(profile.icon || "📦");

  applyProfileToEffectControl(profile, { silent: true });
  setMainPanelTab("config");
  setConfigPanelTab("profile");
  toast.info(`Đang sửa Profile: ${profile.name}`);
 }

 function handleCancelEdit() {
  setEditingButtonId(null);
  setEditingProfileId(null);

  // Reset Button Builder
  setButtonBuilderName("");
  setButtonBuilderCategory("Custom");
  setButtonBuilderPrompt("");
  setButtonRequiredTools([]);
  setBuilderFields([]);

  // Reset Profile Builder
  setProfileName("");
  setProfileDesc("");
  setProfileIcon("📦");
  setButtonIcon("✨");
  // We don't reset activeEffects here because it might be being used for generation
 }

 function toggleEffectCollapse(id: string) {
  setCollapsedEffects(curr => {
   const next = new Set(curr);
   if (next.has(id)) next.delete(id);
   else next.add(id);
   return next;
  });
  const eff = activeEffects.find(e => e.id === id);
  if (eff) {
   const button = buttons.find(btn => btn.id === eff.buttonId);
   if (button) requestCanvasToolFromButton(button, eff.fields);
  }
 }

 function handleEffectFieldChange(effectId: string, key: string, nextValue: any) {
  const targetEffect = activeEffects.find((effect) => effect.id === effectId);
  const targetField = targetEffect?.fields.find((field) => field.key === key);
  if (targetField) {
   const nonce = Date.now() + Math.random();
   const toolGroup = applyCanvasFieldBinding(targetField, nextValue, nonce);
   if (toolGroup) {
    setCanvasToolRequest({ toolGroup, nonce });
   }
  }

  setActiveEffects((current) =>
   current.map((eff) => {
    if (eff.id === effectId) {
     const nextFields = eff.fields.map((f) => {
      if (f.key === key) {
       return { ...f, value: nextValue };
      }
      return f;
     });
     return { ...eff, fields: nextFields };
    }
    return eff;
   })
  );
 }

 async function handleRun() {
  const isRegenerate = false;
  if (!activeProject || activeEffects.length === 0) return toast.error("Hãy chọn ảnh và thêm ít nhất một hiệu ứng (button).");
  if (!beginSubmit()) return;

  setRunStatus("Đang tải ảnh...");

  // Giả lập tiến trình (do API gọi theo dạng blocking)
  const progressInterval = setInterval(() => {
   setRunStatus(prev => {
    if (prev === "Đang tải ảnh...") return "Đã tải ảnh, đang chuẩn bị gửi...";
    if (prev === "Đã tải ảnh, đang chuẩn bị gửi...") return "Đã gửi yêu cầu...";
    if (prev === "Đã gửi yêu cầu...") return "Đang phân tích và xử lý (có thể mất 15-30s)...";
    if (prev === "Đang phân tích và xử lý (có thể mất 15-30s)...") return "Đang tạo ảnh...";
    if (prev === "Đang tạo ảnh...") return "Đang tải preview...";
    return prev;
   });
  }, 4000);

  try {
   const requiresMask = activeEffects.some(eff => {
    const btn = buttons.find(b => b.id === eff.buttonId);
    return btn?.requiresMask;
   });
   const maskMode = selectedMode === "mask" ? "red" : (requiresMask ? "selected" : "none");

   const currentProject = await runThumbnailGenerationBatch({
    projectId: activeProject.id,
    effects: activeEffects.map(eff => ({
     buttonId: eff.buttonId,
     fieldValues: fieldValueMap(eff.fields),
    })),
    selectedMode: selectedMode,
    regenerateMode: regenerateMode,
    maskMode: maskMode,
    isRegenerate: isRegenerate,
    maskBase64: maskBase64 || undefined,
    canvasGuide: canvasGuide ? {
     mode: canvasGuide.mode,
     ratioLabel: canvasGuide.ratioLabel,
     rect: { ...canvasGuide.rect },
    } : undefined,
   });

   clearInterval(progressInterval);
   setRunStatus("Hoàn tất!");
   syncProject(currentProject);
   toast.success("Đã hoàn thành tạo ảnh với các hiệu ứng đã chọn.");
  } catch (error) {
   clearInterval(progressInterval);
   const message = getErrorMessage(error);
   persistSessionErrorMessage(message);
   toast.error(message);
  } finally {
   clearInterval(progressInterval);
   setRunStatus("");
   endSubmit();
  }
 }

 async function handleSaveProfile() {
  if (activeEffects.length === 0) return toast.error("Cần có ít nhất một hiệu ứng để lưu profile.");
  if (!beginSubmit()) return;

  try {
   const payload = {
    id: editingProfileId || undefined,
    name: profileName || "Profile mới",
    icon: profileIcon || "📦",
    description: profileDesc || `Combo ${activeEffects.length} hiệu ứng`,
    effects: activeEffects.map(eff => ({
     buttonId: eff.buttonId,
     fields: eff.fields.map(field => ({ ...field }))
    }))
   };
   const newProfile = await createThumbnailProfile(payload);
   setBootstrap(prev => prev ? { ...prev, profiles: [...prev.profiles.filter(p => p.id !== newProfile.id), newProfile] } : prev);
   toast.success(editingProfileId ? "Đã cập nhật profile thành công." : "Đã lưu profile mới thành công.");
   setEditingProfileId(newProfile.id);
  } catch (error) {
   toast.error(getErrorMessage(error));
  } finally {
   endSubmit();
  }
 }

 async function handleSaveButton() {
  if (!buttonBuilderName || !buttonBuilderPrompt) return toast.error("Vui lòng nhập tên và mẫu prompt.");
  if (!beginSubmit()) return;
  try {
   const button = await createThumbnailButton({
    id: editingButtonId || undefined,
    name: buttonBuilderName,
    icon: buttonIcon,
    category: buttonBuilderCategory,
    promptTemplate: buttonBuilderPrompt,
    requiresMask: false,
    createNewChat: builderCreateNewChat,
    allowRegenerate: true,
    requiredTools: normalizeRequiredTools(buttonRequiredTools, false),
    fields: builderFields,
   });
    startTransition(() => {
     setBootstrap((current) =>
      current ? { ...current, buttons: [...current.buttons.filter((item) => item.id !== button.id), button] } : current,
     );
     toast.success(editingButtonId ? "Đã cập nhật hành động." : "Đã lưu hành động mới.");
     setEditingButtonId(button.id);
    });  } catch (error) {
   toast.error(getErrorMessage(error));
  } finally {
   endSubmit();
  }
 }

 async function handleDeleteButton(id: string) {
  if (!confirm("Bạn có chắc muốn xoá button này?")) return;
  try {
   await deleteThumbnailButton(id);
   setBootstrap(curr => curr ? { ...curr, buttons: curr.buttons.filter(b => b.id !== id) } : curr);
   toast.success("Đã xoá button.");
  } catch (err) {
   toast.error(getErrorMessage(err));
  }
 }

 async function handleTogglePinButton(id: string) {
  try {
   const updated = await togglePinThumbnailButton(id);
   setBootstrap(curr => curr ? {
    ...curr,
    buttons: curr.buttons.map(b => b.id === id ? updated : b)
   } : curr);
  } catch (err) {
   toast.error(getErrorMessage(err));
  }
 }

 async function handleDeleteProfile(id: string) {
  if (!confirm("Bạn có chắc muốn xoá profile này?")) return;
  try {
   await deleteThumbnailProfile(id);
   setBootstrap(curr => curr ? { ...curr, profiles: curr.profiles.filter(p => p.id !== id) } : curr);
   toast.success("Đã xoá profile.");
  } catch (err) {
   toast.error(getErrorMessage(err));
  }
 }

 async function handleTogglePinProfile(id: string) {
  try {
   const updated = await togglePinThumbnailProfile(id);
   setBootstrap(curr => curr ? {
    ...curr,
    profiles: curr.profiles.map(p => p.id === id ? updated : p)
   } : curr);
  } catch (err) {
   toast.error(getErrorMessage(err));
  }
 }

 async function handleImportButtonPreset() {
  try {
   buttonPresetInputRef.current?.click();
  } catch (err) {
   toast.error(getErrorMessage(err));
  }
 }

 async function handleButtonPresetFileChange(event: ChangeEvent<HTMLInputElement>) {
  const file = event.target.files?.[0];
  event.target.value = "";
  if (!file) return;

  setImportingButtonPreset(true);
  try {
   const payload = await readJsonFile(file);
   const presetButtons = extractButtonPresetPayloads(payload);
   const savedButtons = await Promise.all(
    presetButtons.map((button) =>
     createThumbnailButton(normalizeButtonForSave(button)),
    ),
   );
   mergeButtons(savedButtons);
   toast.success(
    savedButtons.length > 1
     ? `Đã nhập ${savedButtons.length} button preset từ ${file.name}`
     : `Đã nhập preset button: ${savedButtons[0]?.name || "Preset mới"}`,
   );
  } catch (err) {
   toast.error(getErrorMessage(err));
  } finally {
   setImportingButtonPreset(false);
  }
 }

 async function handleExportButtonPreset(id: string) {
  setExportingButtonPresetId(id);
  try {
   const { path: destinationDir } = await chooseFolder();
   if (!destinationDir) return;
   const result = await exportThumbnailButtonPreset({ id, destinationDir });
   if (result.path) {
    toast.success(`Đã xuất preset button "${result.button.name}" ra ${result.path}`);
   } else {
    downloadJsonFile(result.suggestedFileName, result.payload);
    toast.success(`Đã tải preset button "${result.button.name}" xuống ${result.suggestedFileName}`);
   }
  } catch (err) {
   toast.error(getErrorMessage(err));
  } finally {
   setExportingButtonPresetId((current) => (current === id ? null : current));
  }
 }

 async function handleImportProfilePreset() {
  try {
   profilePresetInputRef.current?.click();
  } catch (err) {
   toast.error(getErrorMessage(err));
  }
 }

 async function handleProfilePresetFileChange(event: ChangeEvent<HTMLInputElement>) {
  const file = event.target.files?.[0];
  event.target.value = "";
  if (!file) return;

  setImportingProfilePreset(true);
  try {
   const payload = await readJsonFile(file);
   const preset = extractProfilePresetPayload(payload);
   const savedButtons = await Promise.all(
    preset.buttons.map((button) =>
     createThumbnailButton(normalizeButtonForSave(button)),
    ),
   );
   const savedProfile = await createThumbnailProfile(normalizeProfileForSave(preset.profile));
   if (savedButtons.length > 0) {
    mergeButtons(savedButtons);
   }
   mergeProfiles([savedProfile]);
   toast.success(`Đã nhập preset profile: ${savedProfile.name}`);
  } catch (err) {
   toast.error(getErrorMessage(err));
  } finally {
   setImportingProfilePreset(false);
  }
 }

 async function handleExportProfilePreset(id: string) {
  setExportingProfilePresetId(id);
  try {
   const { path: destinationDir } = await chooseFolder();
   if (!destinationDir) return;
   const result = await exportThumbnailProfilePreset({ id, destinationDir });
   if (result.path) {
    toast.success(`Đã xuất preset profile "${result.profile.name}" ra ${result.path}`);
   } else {
    downloadJsonFile(result.suggestedFileName, result.payload);
    toast.success(`Đã tải preset profile "${result.profile.name}" xuống ${result.suggestedFileName}`);
   }
  } catch (err) {
   toast.error(getErrorMessage(err));
  } finally {
   setExportingProfilePresetId((current) => (current === id ? null : current));
  }
 }

 async function handleSelectProject(projectId: string) {
  try {
   const project = await getThumbnailProject(projectId);
   syncProject(project);
  } catch (error) {
   toast.error(getErrorMessage(error));
  }
 }

 async function handleDeleteProject(projectId: string) {
  if (!confirm("Bạn có chắc muốn xoá dự án này? Toàn bộ lịch sử sẽ bị mất.")) return;
  try {
   await deleteThumbnailProject(projectId);
   setBootstrap(curr => {
    if (!curr) return curr;
    const nextProjects = curr.projects.filter(p => p.id !== projectId);
    let nextActiveProject = curr.activeProject;
    let nextActiveProjectId = curr.activeProjectId;

    if (curr.activeProjectId === projectId) {
     nextActiveProject = null;
     nextActiveProjectId = null;
     setActiveProject(null);
    }

    return {
     ...curr,
     projects: nextProjects,
     activeProject: nextActiveProject,
     activeProjectId: nextActiveProjectId
    };
   });
   toast.success("Đã xoá dự án.");
  } catch (err) {
   toast.error(getErrorMessage(err));
  }
 }

 async function handleRenameProject(projectId: string, currentName: string) {
  const newName = prompt("Nhập tên mới cho dự án:", currentName);
  if (!newName || newName.trim() === "" || newName === currentName) return;
  try {
   const updated = await renameThumbnailProject(projectId, newName);
   syncProject(updated);
   toast.success("Đã đổi tên dự án.");
  } catch (err) {
   toast.error(getErrorMessage(err));
  }
 }


 async function handleSelectVersion(versionId: string) {
  if (!activeProject) return;
  try {
   const project = await selectThumbnailVersion(activeProject.id, versionId);
   syncProject(project);
  } catch (error) {
   toast.error(getErrorMessage(error));
  }
 }

 async function handleDeleteVersion(versionId: string) {
  if (!activeProject) return;
  const isLastVersion = versions.length <= 1;
  const confirmMsg = isLastVersion
   ? "Đây là phiên bản cuối cùng. Xoá sẽ xoá luôn cả dự án. Tiếp tục?"
   : "Bạn có chắc muốn xoá phiên bản này? Hành động này không thể hoàn tác.";
  if (!confirm(confirmMsg)) return;
  try {
   const result = await deleteThumbnailVersion(activeProject.id, versionId) as any;
   if (result.projectDeleted) {
    // The whole project was deleted (last version)
    setActiveProject(null);
    setBootstrap(curr => curr ? { ...curr, projects: curr.projects.filter(p => p.id !== activeProject.id) } : curr);
    toast.success("Đã xoá phiên bản và dự án.");
   } else {
    syncProject(result);
    toast.success("Đã xoá phiên bản.");
   }
  } catch (error) {
   toast.error(getErrorMessage(error));
  }
 }

 async function handleExport() {
  if (!activeProject || !selectedVersion) return toast.error("Chưa có phiên bản nào để xuất.");
  setExporting(true);
  try {
   const result = await exportThumbnailImage({
    projectId: activeProject.id,
    versionId: selectedVersion.id,
    destinationDir: exportFolder,
    fileName: exportName,
    format: "PNG",
    size: "original",
   });
   toast.success("Đã xuất ảnh thành công.");
   await openFolder(exportFolder || result.path);
  } catch (error) {
   toast.error(getErrorMessage(error));
  } finally {
   setExporting(false);
  }
 }
async function requestExportFolder() {
  const result = await chooseFolder();
  setExportFolder(result.path);
  return result.path;
 }



 async function handleChooseExportFolder() {
  try {
   await requestExportFolder();
  } catch (error) {
   toast.error(getErrorMessage(error));
  }
 }

 const handleCanvasImageChange = async (base64: string) => {
  if (!activeProject) return;
  try {
   const project = await commitThumbnailCrop(activeProject.id, base64);
   syncProject(project);
   toast.success("Đã lưu phiên bản Croped!");
  } catch (error) {
   toast.error(getErrorMessage(error));
  }
 };

 const processImageFile = async (file: File) => {
  const reader = new FileReader();
  reader.onload = async (e) => {
   const base64Image = e.target?.result as string;
   if (!base64Image) return;

   setSubmitting(true);
   try {
    const project = await createThumbnailProject({
     name: "Dự án mới",
     folder: "",
     base64Image,
    });
    setActiveEffects([]);
    setMaskBase64(null);
    syncProject(project);
    toast.success("Đã tạo dự án mới.");
     setMainPanelTab("canvas");
     setConfigPanelTab("button");
   } catch (error) {
    toast.error(getErrorMessage(error));
   } finally {
    setSubmitting(false);
   }
  };
  reader.readAsDataURL(file);
 };

 const handlePasteFromClipboard = async () => {
  try {
   const items = await navigator.clipboard.read();
   for (const item of items) {
    const imageTypes = item.types.filter(t => t.startsWith("image/"));
    if (imageTypes.length > 0) {
     const blob = await item.getType(imageTypes[0]);
     const file = new File([blob], "pasted_image.png", { type: imageTypes[0] });
     await processImageFile(file);
     return;
    }
   }
   toast.error("Không tìm thấy ảnh trong Clipboard.");
  } catch (err) {
   toast.error("Không thể đọc Clipboard. Hãy thử dùng Ctrl+V.");
  }
 };

 if (bootLoading) {
  return (
   <Card className="border-border/70 shadow-sm">
    <CardContent className="flex items-center justify-center gap-3 py-16 text-sm text-muted-foreground">
     <Loader2 className="size-4 animate-spin" />
     Khởi tạo Studio...
    </CardContent>
   </Card>
  );
 }

 return (
  <div
   className={cn(
    "flex min-h-0 flex-col gap-4 lg:h-[calc(100dvh-4rem)]",
    "lg:grid lg:grid-cols-[20rem_minmax(0,1fr)_22rem] lg:grid-rows-[auto_minmax(0,1fr)]",
   )}
  >
    <input
     ref={imageInputRef}
     type="file"
     id="imageInput"
     accept="image/*"
     className="hidden"
     onChange={e => { if (e.target.files?.[0]) void processImageFile(e.target.files[0]); }}
    />
   <input
    ref={buttonPresetInputRef}
    type="file"
    accept=".json,application/json"
    className="hidden"
    onChange={(event) => void handleButtonPresetFileChange(event)}
   />
   <input
    ref={profilePresetInputRef}
    type="file"
    accept=".json,application/json"
    className="hidden"
    onChange={(event) => void handleProfilePresetFileChange(event)}
   />

   <div className="flex flex-col gap-3 rounded-2xl border border-border/70 bg-card pt-1.5 pb-2.5 px-3 shadow-sm xl:flex-row xl:items-center xl:justify-between xl:px-5 lg:col-[2/4] lg:row-start-1">
    <div className="flex items-center gap-6 flex-1">

     <Tabs value={mainPanelTab} onValueChange={(v) => setMainPanelTab(v as MainPanelTab)} className="w-fit">
      <TabsList className={STUDIO_TOP_TABS_CLASS}>
       <TabsTrigger value="canvas" className={STUDIO_TAB_TRIGGER_CLASS}>Canvas</TabsTrigger>
       <TabsTrigger value="config" className={STUDIO_TAB_TRIGGER_CLASS}>Thiết lập</TabsTrigger>
      </TabsList>
     </Tabs>
    </div>

    <div className="flex flex-wrap items-center justify-end gap-3">
      {activeProject && (
       <div className="flex items-center gap-3 rounded-2xl border border-border/50 bg-muted/20 px-3 py-1.5">
         <div className="flex items-center">
          <span className="text-sm font-semibold text-foreground leading-none">{activeProject.name}</span>
         </div>
         <div className="w-px h-6 bg-border/50" />
         {beforeVersion && (
          <Button
           variant="ghost" size="icon"
           className={cn("size-8 rounded-full", showComparator ? "bg-primary/10 text-primary" : "text-muted-foreground hover:text-primary")}
           title="So sánh phiên bản"
           onClick={() => setShowComparator(v => !v)}
          >
           <SplitSquareVertical className="size-4" />
          </Button>
         )}
         <Button variant="ghost" size="icon" className="size-8 rounded-full text-primary" onClick={() => setShowExportDialog(true)}>
          <Download className="size-4" />
         </Button>
       </div>
      )}

      {sessionStatus && (
       <div className="flex items-center gap-1.5">
        <div className="relative">
         <Button
           variant="ghost"
           size="sm"
           className="h-7 text-[10px] font-bold px-2.5 hover:bg-muted/80 rounded-full border border-border/40 flex items-center gap-2"
           onClick={() => void handleOpenLogin()}
         >
           {sessionStatus.authenticated && (
             <span className="size-1.5 rounded-full bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.6)]" />
           )}
           {sessionStatus.authenticated ? "Đã đăng nhập" : "Đăng nhập"}
         </Button>
        </div>
        <Button
          variant="ghost"
          size="icon"
          className="size-8 hover:bg-muted/80 rounded-full border border-border/40 shrink-0"
          onClick={() => void refreshSessionStatus(true)}
          disabled={refreshingSession}
        >
         <RefreshCw className={cn("size-3", refreshingSession && "animate-spin")} />
        </Button>
       </div>
      )}

     </div>
    </div>

   {/* EXPORT DIALOG */}
   <Dialog open={showExportDialog} onOpenChange={setShowExportDialog}>
    <DialogContent className="sm:max-w-md">
     <DialogHeader>
      <DialogTitle className="text-sm font-bold tracking-tight">Xuất ảnh Thumbnail</DialogTitle>
     </DialogHeader>
     <div className="space-y-4 py-4">
      <Field>
       <TooltipFieldLabel tooltip="Tên tệp tin khi xuất.">Tên tệp</TooltipFieldLabel>
       <Input value={exportName} onChange={e => setExportName(e.target.value)} placeholder="thumbnail_final" className="h-9 bg-muted/20" />
      </Field>
      <Field>
       <TooltipFieldLabel tooltip="Thư mục để lưu tệp ảnh xuất.">Thư mục lưu</TooltipFieldLabel>
       <div className="flex items-center gap-2 p-1 pl-3 rounded-xl border border-border/70 bg-muted/20">
        <span className="text-xs flex-1 truncate text-muted-foreground">{exportFolder || "Chưa chọn..."}</span>
        <Button variant="secondary" size="sm" className={cn(STUDIO_BUTTON_CLASS, "rounded-lg font-medium ")} onClick={() => void handleChooseExportFolder()}>Chọn thư mục</Button>
       </div>
      </Field>
     </div>
     <DialogFooter>
      <Button variant="ghost" size="sm" onClick={() => { setShowExportDialog(false); }}>Hủy</Button>
      <Button size="sm" onClick={() => { void handleExport(); setShowExportDialog(false); }} disabled={exporting || !selectedVersion}>
       {exporting ? <Loader2 className="size-4 animate-spin mr-2" /> : <Download className="size-4 mr-2" />}
       Bắt đầu xuất
      </Button>
     </DialogFooter>
    </DialogContent>
   </Dialog>

   {/* BEFORE/AFTER COMPARATOR OVERLAY — supports any two versions */}
   {showComparator && (() => {
    const vA = compareVersionAId
     ? versions.find(v => v.id === compareVersionAId)
     : (beforeVersion ?? null);
    const vB = compareVersionBId
     ? versions.find(v => v.id === compareVersionBId)
     : (selectedVersion ?? null);
    if (!vA?.outputImagePath || !vB?.outputImagePath || vA.id === vB.id) return null;
    return (
     <VersionComparator
      beforeUrl={getThumbnailAssetUrl(vA.outputImagePath)}
      afterUrl={getThumbnailAssetUrl(vB.outputImagePath)}
      beforeLabel={vA.buttonName || "Gốc"}
      afterLabel={vB.buttonName || "Kết quả"}
      onClose={() => setShowComparator(false)}
     />
    );
   })()}

   {/* -------------------- LEFT COLUMN: LIBRARY (BUTTONS & PROFILES) -------------------- */}
   <aside className="flex min-h-0 flex-col lg:col-start-1 lg:row-[1/3]">
    <Card className="flex flex-col h-full border-border/70 shadow-sm overflow-hidden bg-background/50 backdrop-blur-md">
     <Tabs value={effectiveLeftPanelTab} onValueChange={(v) => setLeftPanelTab(v as LeftPanelTab)} className="flex h-full flex-col">
      <div className="border-b border-border/50 pt-0 pb-2.5 px-3">
       <TabsList className={cn(STUDIO_TOP_TABS_CLASS, "w-full")}>
        <TabsTrigger value="buttons" className={cn(STUDIO_TAB_TRIGGER_CLASS, "flex-1 px-4")}>
         Buttons
        </TabsTrigger>
        <TabsTrigger value="profiles" className={cn(STUDIO_TAB_TRIGGER_CLASS, "flex-1 px-4")}>
         Profiles
        </TabsTrigger>
        {showProjectLibraryTab && (
         <TabsTrigger value="projects" className={cn(STUDIO_TAB_TRIGGER_CLASS, "flex-1 px-4")}>
          Projects
         </TabsTrigger>
        )}
       </TabsList>
      </div>
       <TabsContent value="buttons" className="flex-1 flex flex-col m-0 min-h-0">
        <ScrollArea className="h-full">
         <div className="space-y-4 p-4 pr-3">
          <div className="flex items-center gap-2">
           <div className="relative group flex-1">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 size-3.5 text-muted-foreground" />
            <Input placeholder="Tìm button..." className={cn(STUDIO_INPUT_CLASS, "pl-9")} value={buttonSearchQuery} onChange={e => setButtonSearchQuery(e.target.value)} />
           </div>

           <Button
            variant="secondary"
            size="sm"
            className={cn(STUDIO_BUTTON_CLASS, "rounded-lg font-medium ")}
            onClick={() => void handleImportButtonPreset()}
            disabled={importingButtonPreset}
           >
            {importingButtonPreset ? <Loader2 className="mr-2 size-3.5 animate-spin" /> : <Upload className="mr-2 size-3.5" />}
            Nhập preset
           </Button>
          </div>

          <div className={STUDIO_LIBRARY_GRID_CLASS}>
           {sortedButtons.map((b) => (
            <div key={b.id} className="group relative flex flex-col">
             <div className={STUDIO_LIBRARY_CARD_ACTIONS_CLASS}>
              <div className={STUDIO_LIBRARY_CARD_ICON_CLASS}>
               {b.icon}
              </div>
              <div className="flex items-center gap-0.5 rounded-lg border border-border/50 bg-background/90 p-0.5 shadow-sm opacity-0 group-hover:opacity-100 transition-opacity">
               <Button
                variant="ghost"
                size="icon-xs"
                className={cn("rounded-md text-muted-foreground hover:bg-muted/80 hover:text-primary", b.isPinned && "text-primary")}
                onClick={(e) => {
                 e.stopPropagation();
                 handleTogglePinButton(b.id);
                }}
                aria-label={b.isPinned ? `Bỏ ghim ${b.name}` : `Ghim ${b.name}`}
                title={b.isPinned ? `Bỏ ghim ${b.name}` : `Ghim ${b.name}`}
               >
                {b.isPinned ? <PinOff className="size-3" /> : <Pin className="size-3" />}
               </Button>
               <Button
                variant="ghost"
                size="icon-xs"
                className="rounded-md text-muted-foreground hover:bg-muted/80 hover:text-destructive"
                onClick={(e) => {
                 e.stopPropagation();
                 handleDeleteButton(b.id);
                }}
                aria-label={`Xoá ${b.name}`}
                title={`Xoá ${b.name}`}
               >
                <Trash2 className="size-3" />
               </Button>
               <Button
                variant="ghost"
                size="icon-xs"
                className="rounded-md text-muted-foreground hover:bg-muted/80 hover:text-primary"
                onClick={(e) => {
                 e.stopPropagation();
                 void handleExportButtonPreset(b.id);
                }}
                disabled={exportingButtonPresetId === b.id}
                aria-label={`Xuất preset ${b.name}`}
                title={`Xuất preset ${b.name}`}
               >
                {exportingButtonPresetId === b.id ? <Loader2 className="size-3 animate-spin" /> : <Download className="size-3" />}
               </Button>
              </div>
             </div>
             <button
              draggable="true"
              onDragStart={(e) => {
               e.dataTransfer.setData("buttonId", b.id);
               e.dataTransfer.effectAllowed = "copy";
              }}
              onClick={() => {
               if (mainPanelTab === "canvas") {
                addButtonToEffectControl(b);
               } else {
                handleEditButton(b);
               }
              }}
              className={cn(STUDIO_LIBRARY_CARD_CLASS, "cursor-grab active:cursor-grabbing")}
             >
              <div className="flex flex-col gap-1.5 pt-7">
                <div className="min-h-0 space-y-0.5">
                 <div className="text-[12px] font-bold leading-tight">
                  <span className="line-clamp-1 text-pretty">{b.name}</span>
                 </div>
                </div>
              </div>
             </button>
            </div>
           ))}
          </div>
         </div>
        </ScrollArea>       </TabsContent>

       <TabsContent value="profiles" className="flex-1 flex flex-col m-0 min-h-0">
        <ScrollArea className="h-full">
         <div className="space-y-4 p-4 pr-3">
          <div className="flex items-center gap-2">
           <div className="relative group flex-1">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 size-3.5 text-muted-foreground" />
            <Input placeholder="Tìm profile..." className={cn(STUDIO_INPUT_CLASS, "pl-9")} value={profileSearchQuery} onChange={e => setProfileSearchQuery(e.target.value)} />
           </div>
           <Button
            variant="secondary"
            size="sm"
            className={cn(STUDIO_BUTTON_CLASS, "rounded-lg font-medium ")}
            onClick={() => void handleImportProfilePreset()}
            disabled={importingProfilePreset}
           >
            {importingProfilePreset ? <Loader2 className="mr-2 size-3.5 animate-spin" /> : <Upload className="mr-2 size-3.5" />}
            Nhập preset
           </Button>
          </div>
          <div className={STUDIO_LIBRARY_GRID_CLASS}>
           {sortedProfiles.map((p) => (
             <div key={p.id} className="group relative">
             <div className={STUDIO_LIBRARY_CARD_ACTIONS_CLASS}>
              <div className={STUDIO_LIBRARY_CARD_ICON_CLASS}>
               <span>{p.icon || "📦"}</span>
              </div>
              <div className="flex items-center gap-0.5 rounded-lg border border-border/50 bg-background/90 p-0.5 shadow-sm opacity-0 group-hover:opacity-100 transition-opacity">
                <Button
                 variant="ghost"
                 size="icon-xs"
                 className={cn("rounded-md text-muted-foreground hover:bg-muted/80 hover:text-primary", p.isPinned && "text-primary")}
                 onClick={(e) => {
                  e.stopPropagation();
                  handleTogglePinProfile(p.id);
                 }}
                 aria-label={p.isPinned ? `Bỏ ghim ${p.name}` : `Ghim ${p.name}`}
                 title={p.isPinned ? `Bỏ ghim ${p.name}` : `Ghim ${p.name}`}
                >
                 {p.isPinned ? <PinOff className="size-3" /> : <Pin className="size-3" />}
                </Button>
                <Button
                 variant="ghost"
                 size="icon-xs"
                 className="rounded-md text-muted-foreground hover:bg-muted/80 hover:text-destructive"
                 onClick={(e) => {
                  e.stopPropagation();
                  handleDeleteProfile(p.id);
                 }}
                 aria-label={`Xoá profile ${p.name}`}
                 title={`Xoá profile ${p.name}`}
                >
                 <Trash2 className="size-3" />
                </Button>
                <Button
                 variant="ghost"
                 size="icon-xs"
                 className="rounded-md text-muted-foreground hover:bg-muted/80 hover:text-primary"
                 onClick={(e) => {
                  e.stopPropagation();
                  void handleExportProfilePreset(p.id);
                 }}
                 disabled={exportingProfilePresetId === p.id}
                 aria-label={`Xuất preset profile ${p.name}`}
                 title={`Xuất preset profile ${p.name}`}
                >
                 {exportingProfilePresetId === p.id ? <Loader2 className="size-3 animate-spin" /> : <Download className="size-3" />}
                </Button>
              </div>
             </div>
             <button
              draggable="true"
              onDragStart={(e) => {
               e.dataTransfer.setData("profileId", p.id);
               e.dataTransfer.effectAllowed = "copy";
              }}
              onClick={() => {
               if (mainPanelTab === "canvas") {
                applyProfileToEffectControl(p);
               } else {
                handleEditProfile(p);
               }
              }}
              className={STUDIO_LIBRARY_CARD_CLASS}
             >
              <div className="flex flex-col gap-2">
               <div className={STUDIO_LIBRARY_CARD_ICON_CLASS}>
                <span>{p.icon || "📦"}</span>
               </div>
               <div className="min-h-0 space-y-1 text-left">
                <div className="text-[13px] font-semibold leading-5">
                 <span className="line-clamp-2 text-pretty">{p.name}</span>
                </div>
               </div>
              </div>
             </button>
            </div>
           ))}
          </div>
         </div>
        </ScrollArea>
       </TabsContent>

        {showProjectLibraryTab && (
         <TabsContent value="projects" className="flex-1 flex flex-col m-0 min-h-0">
          <ScrollArea className="h-full">
           <div className="space-y-3 p-4 pr-3">
            <div className="flex items-center gap-2">
             <div className="relative flex-1 group">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 size-3.5 text-muted-foreground" />
              <Input placeholder="Tìm dự án..." className={cn(STUDIO_INPUT_CLASS, "pl-9")} value={projectSearchQuery} onChange={e => setProjectSearchQuery(e.target.value)} />
             </div>
             <Button
               variant="outline"
               size="icon"
               className="h-9 w-9 rounded-xl shrink-0 bg-card border-border/50 hover:border-primary/50 hover:bg-primary/5 shadow-sm"
               onClick={() => imageInputRef.current?.click()}
               title="Tạo dự án mới"
             >
              <Plus className="size-4" />
             </Button>
            </div>
            {sortedProjects.map(p => (
             <div key={p.id} className="relative group">
              <button
               onClick={() => void handleSelectProject(p.id)}
               className={cn(
                "w-full flex items-center gap-3 p-3 rounded-2xl border transition-all text-left active:scale-[0.98]",
                activeProject?.id === p.id
                 ? "border-primary bg-primary/5 ring-1 ring-primary/20"
                 : "border-border/50 bg-card hover:border-primary/30 hover:bg-muted/30"
               )}
              >
               <div className="size-10 rounded-lg bg-black/20 border border-border/20 overflow-hidden shrink-0">
                {p.previewImagePath ? (
                 <img src={getThumbnailAssetUrl(p.previewImagePath)} alt={p.name} className="size-full object-cover" />
                ) : p.base64Image ? (
                 <img src={p.base64Image} alt={p.name} className="size-full object-cover" />
                ) : (
                 <Layers className="size-full p-2 text-muted-foreground/50" />
                )}
               </div>
               <div className="flex-1 min-w-0">
                <div className="text-sm font-semibold truncate text-foreground/90">{p.name}</div>
                <div className="mt-0.5 flex items-center gap-2 text-xs text-muted-foreground">
                 <span>{p.versionCount} versions</span>
                 <span>•</span>
                 <span>{new Date(p.updatedAt).toLocaleDateString()}</span>
                </div>
               </div>
              </button>

              <div className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity flex gap-1">
               <Button
                variant="ghost"
                size="icon"
                className="h-7 w-7 rounded-lg bg-background/80 backdrop-blur-sm border border-border/50 hover:text-primary shadow-sm"
                onClick={(e) => {
                 e.stopPropagation();
                 void handleRenameProject(p.id, p.name);
                }}
               >
                <Pencil className="size-3" />
               </Button>
               <Button
                variant="ghost"
                size="icon"
                className="h-7 w-7 rounded-lg bg-background/80 backdrop-blur-sm border border-border/50 hover:text-destructive shadow-sm"
                onClick={(e) => {
                 e.stopPropagation();
                 void handleDeleteProject(p.id);
                }}
               >
                <Trash2 className="size-3" />
               </Button>
              </div>
             </div>
            ))}
           </div>
          </ScrollArea>
        </TabsContent>
       )}
     </Tabs>
    </Card>
   </aside>

   {/* -------------------- CENTER COLUMN -------------------- */}
   <main className="flex flex-col min-h-0 gap-4 lg:col-start-2 lg:row-start-2">
    <SessionStatusAlert
     authenticated={Boolean(sessionStatus?.authenticated)}
     notReadyTitle={"Phiên Gemini của Thumbnail chưa sẵn sàng"}
     message={sessionStatus?.message ?? "Mở cửa sổ đăng nhập Gemini của Thumbnail, đăng nhập đúng profile riêng của app rồi bấm làm mới phiên."}
    />
    {mainPanelTab === "config" ? (
     <Card className="flex-1 border-border/70 shadow-sm overflow-hidden flex flex-col bg-background/50 backdrop-blur-md">
       <div className="px-6 pt-0 pb-2.5 border-b border-border/50 bg-muted/20 flex items-center justify-between">
        <Tabs value={configPanelTab} onValueChange={(v) => setConfigPanelTab(v as ConfigPanelTab)} className="w-fit">
         <TabsList className={STUDIO_TOP_TABS_CLASS}>
          <TabsTrigger value="button" className={cn(STUDIO_TAB_TRIGGER_CLASS, "px-4")}>
           {editingButtonId ? "Sửa Button" : "Tạo Button"}
          </TabsTrigger>
          <TabsTrigger value="profile" className={cn(STUDIO_TAB_TRIGGER_CLASS, "px-4")}>
           {editingProfileId ? "Sửa Profile" : "Tạo Profile"}
          </TabsTrigger>
         </TabsList>
        </Tabs>

        <div className="flex items-center gap-2">
         {configPanelTab === "button" ? (
          <div className="flex items-center gap-2">
           {editingButtonId && (
            <Button variant="ghost" size="xs" onClick={() => { handleCancelEdit(); setMainPanelTab("canvas"); }} className="h-8 rounded-full px-3 text-xs hover:bg-destructive/10 hover:text-destructive">Hủy</Button>
           )}
           <Button
            onClick={() => void handleSaveButton()}
            disabled={submitting}
            className="h-8 rounded-full px-4 text-[10px] font-bold shadow-lg shadow-primary/20"
           >
            {submitting ? <Loader2 className="size-3 animate-spin mr-2" /> : <Save className="size-3 mr-2" />}
            {editingButtonId ? "Lưu thay đổi" : "Lưu Button"}
           </Button>
          </div>
         ) : (
          <div className="flex items-center gap-2">
           {editingProfileId && (
            <Button variant="ghost" size="xs" onClick={() => { handleCancelEdit(); setMainPanelTab("canvas"); }} className="h-8 rounded-full px-3 text-xs hover:bg-destructive/10 hover:text-destructive">Hủy</Button>
           )}
           <Button
            onClick={() => void handleSaveProfile()}
            disabled={activeEffects.length === 0 || submitting}
            className="h-8 rounded-full px-4 text-[10px] font-bold  shadow-lg shadow-primary/20"
           >
            {submitting ? <Loader2 className="size-3 animate-spin mr-2" /> : <Save className="size-3 mr-2" />}
            {editingProfileId ? "Lưu thay đổi" : "Lưu Profile"}
           </Button>
          </div>
         )}
        </div>
       </div>

       <ScrollArea className="flex-1">
        <div className="space-y-8 p-6">
        {configPanelTab === "button" ? (
         <div className="mx-auto max-w-4xl space-y-10 pb-6">
          <div className="grid grid-cols-2 gap-12">
           <div className="space-y-6">
            <FieldGroup className="gap-6">
             <div className="flex gap-4 items-end">
              <Field className="w-16 shrink-0">
               <TooltipFieldLabel tooltip="Biểu tượng đại diện cho button." className={STUDIO_LABEL_CLASS}>Icon</TooltipFieldLabel>
               <Dialog>
                <DialogTrigger asChild>
                 <button className="size-16 flex items-center justify-center rounded-2xl border-2 border-dashed border-border hover:border-primary/50 hover:bg-primary/5 transition-all text-3xl shadow-sm">
                  {buttonIcon}
                 </button>
                </DialogTrigger>
                <DialogContent className="p-0 border-none bg-transparent shadow-none w-fit">
                 <EmojiPicker selected={buttonIcon} onSelect={(e) => { setButtonIcon(e); }} />
                </DialogContent>
               </Dialog>
              </Field>
              <Field className="flex-1">
               <TooltipFieldLabel tooltip="Tên hiển thị của button trong thư viện và effect control." className={STUDIO_LABEL_CLASS}>Tên Button</TooltipFieldLabel>
               <Input value={buttonBuilderName} onChange={e => setButtonBuilderName(e.target.value)} placeholder="VD: Thay đổi bầu trời" className="h-16 rounded-2xl bg-muted/20 text-base font-bold px-5" />
              </Field>
             </div>
             <Field>
              <TooltipFieldLabel tooltip="Prompt mẫu gửi sang Gemini. Dùng cú pháp {key} để chèn giá trị từ các field ở dưới." className={STUDIO_LABEL_CLASS}>Prompt Gốc (Template)</TooltipFieldLabel>
              <Textarea value={buttonBuilderPrompt} onChange={e => setButtonBuilderPrompt(e.target.value)} placeholder="Prompt gửi Gemini, dùng {key} để chèn tham số..." className="min-h-[150px] rounded-xl bg-muted/20 font-mono text-xs leading-relaxed" />
             </Field>
            </FieldGroup>

            <div className="rounded-2xl border border-border/50 bg-muted/10 p-4">
             <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center gap-3">
               <TooltipFieldLabel tooltip="Chọn cụm công cụ mà canvas nên tự chuyển tới ngay khi user apply button này." className={cn(STUDIO_LABEL_CLASS, "text-foreground/80")}>Yêu cầu công cụ canvas</TooltipFieldLabel>
               <Badge variant="outline" className="border-primary/30 bg-primary/10 text-primary">
                {normalizeRequiredTools(buttonRequiredTools, false).length} cụm
               </Badge>
              </div>
              <div className="flex flex-wrap justify-end gap-2">
              {TOOL_REQUIREMENT_OPTIONS.map((toolOption) => {
               const ToolIcon = toolOption.icon;
               const isSelected = buttonRequiredTools.includes(toolOption.id);
               return (
                <Button
                 key={toolOption.id}
                 type="button"
                 variant={isSelected ? "default" : "outline"}
                 size="sm"
                 className="h-8 rounded-full px-3 text-xs font-medium"
                 onClick={() => {
                  setButtonRequiredTools((current) => {
                   if (current.includes(toolOption.id)) {
                    return current.filter((item) => item !== toolOption.id);
                   }
                   return [...current, toolOption.id];
                  });
                   setCanvasToolRequest({ toolGroup: toolOption.id as ThumbnailRequiredTool, nonce: Date.now() });
                 }}
                >
                 <ToolIcon className="mr-1.5 size-3.5" />
                 {toolOption.label}
                </Button>
               );
              })}
              </div>
             </div>
            </div>
           </div>

           <div className="space-y-6">
            <div className="flex items-center justify-between">
             <TooltipFieldLabel tooltip="Khai báo các field mà user sẽ nhập khi dùng button này." className={STUDIO_LABEL_CLASS}>Tham số (Fields)</TooltipFieldLabel>
             <Dialog open={isFieldDialogOpen} onOpenChange={setIsFieldDialogOpen}>
              <DialogTrigger asChild>
               <Button
                variant="outline"
                size="sm"
                className={cn(STUDIO_BUTTON_CLASS, "rounded-lg font-medium")}
                onClick={() => {
                  setNewFieldKey(""); setNewFieldLabel(""); setNewFieldType("text");
                  setNewFieldDefault(""); setNewFieldOptions("");
                  setNewFieldMin(null); setNewFieldMax(null); setNewFieldRequired(false);
                  setNewFieldVisibleIf(""); setNewFieldBindToCanvas(null);
                }}
               >
                <Plus className="size-3 mr-1.5" /> Thêm tham số
               </Button>
              </DialogTrigger>
              <DialogContent className="sm:max-w-lg overflow-hidden flex flex-col max-h-[90vh]">
                <DialogHeader><DialogTitle className="text-sm font-bold tracking-tight">Cấu hình Tham số mới</DialogTitle></DialogHeader>
                <ScrollArea className="flex-1 -mx-6 px-6">
                 <div className="space-y-6 py-6 pr-1">
                  <div className="grid grid-cols-2 gap-4">
                   <Field><TooltipFieldLabel tooltip="Key dùng trong prompt dạng {key}." className={STUDIO_LABEL_CLASS}>Mã tham số (Key)</TooltipFieldLabel><Input value={newFieldKey} onChange={e => setNewFieldKey(e.target.value)} placeholder="vd: sky_color" className={cn(STUDIO_INPUT_CLASS, "h-9")} /></Field>
                   <Field><TooltipFieldLabel tooltip="Tên hiển thị cho user khi nhập dữ liệu." className={STUDIO_LABEL_CLASS}>Tên hiển thị (Label)</TooltipFieldLabel><Input value={newFieldLabel} onChange={e => setNewFieldLabel(e.target.value)} placeholder="vd: Màu sắc bầu trời" className={cn(STUDIO_INPUT_CLASS, "h-9")} /></Field>
                  </div>

                  <Field>
                   <TooltipFieldLabel tooltip="Chọn kiểu input phù hợp với dữ liệu mà button cần nhận." className={STUDIO_LABEL_CLASS}>Loại input</TooltipFieldLabel>
                   <Select value={newFieldType} onValueChange={(v: any) => {
                    setNewFieldType(v);
                    if (v === 'toggle') setNewFieldDefault(false);
                    else if (v === 'slider' || v === 'number') setNewFieldDefault(0);
                    else if (v === 'color') setNewFieldDefault("#FFFFFF");
                    else if (v === 'multi-select') setNewFieldDefault([]);
                    else setNewFieldDefault("");
                   }}>
                    <SelectTrigger className={cn(STUDIO_INPUT_CLASS, "h-9")}><SelectValue /></SelectTrigger>
                    <SelectContent>
                     <SelectItem value="text">Text Input</SelectItem>
                     <SelectItem value="textarea">Text Area</SelectItem>
                     <SelectItem value="select">Dropdown (Chọn 1)</SelectItem>
                     <SelectItem value="multi-select">Multi Select (Chọn nhiều)</SelectItem>
                     <SelectItem value="slider">Slider (Thanh trượt)</SelectItem>
                     <SelectItem value="number">Number (Số lượng)</SelectItem>
                     <SelectItem value="color">Color Picker (Màu sắc)</SelectItem>
                     <SelectItem value="toggle">Toggle (Bật/Tắt)</SelectItem>
                    </SelectContent>
                   </Select>
                  </Field>

                  <Field>
                   <TooltipFieldLabel tooltip="Tự động đồng bộ giá trị với thuộc tính của Canvas." className={STUDIO_LABEL_CLASS}>Nối cấu hình Canvas</TooltipFieldLabel>
                   <Select value={newFieldBindToCanvas || "none"} onValueChange={(v: any) => setNewFieldBindToCanvas(v === "none" ? null : v)}>
                    <SelectTrigger className={cn(STUDIO_INPUT_CLASS, "h-9")}><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="none">Không đồng bộ (None)</SelectItem>
                      <SelectItem value="artboard_ratio">Tỉ lệ Artboard</SelectItem>
                      <SelectItem value="crop_ratio">Tỉ lệ Cắt (Crop)</SelectItem>
                      <SelectItem value="brush_color">Màu cọ vẽ</SelectItem>
                      <SelectItem value="shape_type">Loại hình học (Shape)</SelectItem>
                      <SelectItem value="shape_color">Màu hình học</SelectItem>
                    </SelectContent>
                   </Select>
                  </Field>

                  {newFieldType === 'select' || newFieldType === 'multi-select' ? (
                   <Field>
                    <TooltipFieldLabel tooltip="Nhập các lựa chọn, phân tách bằng dấu phẩy." className={STUDIO_LABEL_CLASS}>Tùy chọn</TooltipFieldLabel>
                    <Input value={newFieldOptions} onChange={e => setNewFieldOptions(e.target.value)} placeholder="vd: Red, Green, Blue" className={cn(STUDIO_INPUT_CLASS, "h-9")} />
                   </Field>
                  ) : null}

                  {newFieldType === 'slider' || newFieldType === 'number' ? (
                   <div className="grid grid-cols-2 gap-4">
                    <Field><TooltipFieldLabel tooltip="Giá trị nhỏ nhất được phép." className={STUDIO_LABEL_CLASS}>Min</TooltipFieldLabel><Input type="number" value={newFieldMin ?? ""} onChange={e => setNewFieldMin(e.target.value ? Number(e.target.value) : null)} className={cn(STUDIO_INPUT_CLASS, "h-9")} /></Field>
                    <Field><TooltipFieldLabel tooltip="Giá trị lớn nhất được phép." className={STUDIO_LABEL_CLASS}>Max</TooltipFieldLabel><Input type="number" value={newFieldMax ?? ""} onChange={e => setNewFieldMax(e.target.value ? Number(e.target.value) : null)} className={cn(STUDIO_INPUT_CLASS, "h-9")} /></Field>
                   </div>
                  ) : null}

                  <div className="grid grid-cols-2 gap-4 pt-2 border-t border-border/50">
                   <div className="flex items-center justify-between px-3 py-2 rounded-xl bg-muted/10 border border-border/50">
                    <TooltipFieldLabel tooltip="Đánh dấu nếu user bắt buộc phải nhập field này." className={cn(STUDIO_LABEL_CLASS, "text-foreground/80")}>Bắt buộc nhập</TooltipFieldLabel>
                    <Switch checked={newFieldRequired} onCheckedChange={setNewFieldRequired} />
                   </div>
                   <Field>
                    <TooltipFieldLabel tooltip="Nhập mã key (VD: my_key) để hiện khi field đó có giá trị, hoặc biểu thức so sánh (VD: my_key=value)." className={STUDIO_LABEL_CLASS}>Điều kiện hiển thị</TooltipFieldLabel>
                    <Input value={newFieldVisibleIf} onChange={e => setNewFieldVisibleIf(e.target.value)} placeholder="Hiện nếu key này có giá trị..." className={cn(STUDIO_INPUT_CLASS, "h-9")} />
                   </Field>
                  </div>
                 </div>
                </ScrollArea>
                <DialogFooter className="pt-4 border-t border-border/50">
                 <Button
                  className="w-full h-10 rounded-xl font-bold"
                  onClick={() => {
                   const options = newFieldOptions.split(',').map(s => s.trim()).filter(Boolean);
                   void options; // suppress unused variable — options đã được inline bên dưới
                   if (editingFieldIndex !== null) {
                     const updatedFields = [...builderFields];
                     updatedFields[editingFieldIndex] = {
                      key: newFieldKey,
                      label: newFieldLabel,
                      type: newFieldType,
                      value: newFieldDefault,
                      options: newFieldOptions.split(",").map(s => s.trim()).filter(Boolean).length ? newFieldOptions.split(",").map(s => s.trim()).filter(Boolean) : undefined,
                      min: newFieldMin,
                      max: newFieldMax,
                      required: newFieldRequired,
                      visibleIf: newFieldVisibleIf || undefined,
                      bindToCanvas: newFieldBindToCanvas || undefined,
                      tooltip: ""
                     };
                     setBuilderFields(updatedFields);
                     if (newFieldBindToCanvas === "artboard_ratio") {
                       setCanvasGuideRequest({ guide: { mode: "artboard", ratioLabel: newFieldDefault }, nonce: Date.now() });
                       setCanvasSyncNonce(n => n + 1);
                     } else if (newFieldBindToCanvas === "crop_ratio") {
                       setCanvasGuideRequest({ guide: { mode: "crop", ratioLabel: newFieldDefault }, nonce: Date.now() });
                       setCanvasSyncNonce(n => n + 1);
                     }
                   } else {
                    setBuilderFields([...builderFields, {
                     key: newFieldKey,
                     label: newFieldLabel,
                     type: newFieldType,
                     value: newFieldDefault,
                     options: newFieldOptions.split(",").map(s => s.trim()).filter(Boolean).length ? newFieldOptions.split(",").map(s => s.trim()).filter(Boolean) : undefined,
                     min: newFieldMin,
                     max: newFieldMax,
                     required: newFieldRequired,
                     visibleIf: newFieldVisibleIf || undefined,
                     bindToCanvas: newFieldBindToCanvas || undefined,
                     tooltip: ""
                    }]);
                    if (newFieldBindToCanvas === "artboard_ratio") {
                      setCanvasGuideRequest({ guide: { mode: "artboard", ratioLabel: newFieldDefault }, nonce: Date.now() });
                      setCanvasSyncNonce(n => n + 1);
                    } else if (newFieldBindToCanvas === "crop_ratio") {
                      setCanvasGuideRequest({ guide: { mode: "crop", ratioLabel: newFieldDefault }, nonce: Date.now() });
                      setCanvasSyncNonce(n => n + 1);
                    }
                   }                   setNewFieldKey(""); setNewFieldLabel(""); setNewFieldOptions("");
                   setNewFieldMin(null); setNewFieldMax(null); setNewFieldRequired(false);
                   setNewFieldVisibleIf(""); setNewFieldBindToCanvas(null);
                   setEditingFieldIndex(null); setIsFieldDialogOpen(false);
                 }}>{editingFieldIndex !== null ? "Lưu thay đổi tham số" : "Thêm tham số vào Button"}</Button>
                </DialogFooter>
              </DialogContent>
             </Dialog>
            </div>

            <ScrollArea className="h-[400px] rounded-2xl border border-border/50 bg-muted/5">
              <div className="p-4 space-y-2">
               {builderFields.map((f, i) => (
                <div key={i} className="group relative flex items-center justify-between p-3 rounded-2xl border border-border/30 bg-background/50 hover:bg-background transition-all shadow-sm">
                  <div className="flex flex-col gap-1">
                   <div className="flex items-center gap-2">
                    <span className="text-sm font-semibold text-foreground">{f.label}</span>
                    {f.required && <Badge variant="outline" className="h-5 px-2 text-[11px] border-destructive/30 text-destructive bg-destructive/5">Required</Badge>}
                   </div>
                   <div className="flex items-center gap-2 text-xs text-muted-foreground font-mono">
                    <span className="rounded bg-muted px-1.5 py-0.5 text-[11px]">{"{"}{f.key}{"}"}</span>
                    <span>•</span>
                    <span className="capitalize">{f.type}</span>
                    {f.min !== null && <span>• Min: {f.min}</span>}
                    {f.max !== null && <span>• Max: {f.max}</span>}
                    {f.bindToCanvas && <span className="text-primary/80 ml-1">• Nối với: {f.bindToCanvas}</span>}
                   </div>
                  </div>
                  <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                   <Button variant="ghost" size="icon" className="h-8 w-8 text-muted-foreground hover:text-primary" onClick={() => {
                    setNewFieldKey(f.key);
                    setNewFieldLabel(f.label);
                    setNewFieldType(f.type);
                    setNewFieldDefault(f.value);
                    setNewFieldOptions(f.options?.join(", ") || "");
                    setNewFieldMin(f.min ?? null);
                    setNewFieldMax(f.max ?? null);
                    setNewFieldRequired(f.required || false);
                    setNewFieldVisibleIf(typeof f.visibleIf === 'string' ? f.visibleIf : "");
                    setNewFieldBindToCanvas(f.bindToCanvas || null);
                    setEditingFieldIndex(i);
                    setIsFieldDialogOpen(true);
                   }}>
                    <Edit3 className="size-3" />
                   </Button>
                   <Button variant="ghost" size="icon" className="h-8 w-8 text-muted-foreground hover:text-destructive" onClick={() => setBuilderFields(builderFields.filter((_, idx) => idx !== i))}>
                    <Trash2 className="size-3" />
                   </Button>
                  </div>
                </div>
               ))}
               {builderFields.length === 0 && <div className="text-center py-20 text-muted-foreground/40 italic text-xs">Chưa có tham số nào được định nghĩa.</div>}
              </div>
            </ScrollArea>
           </div>
          </div>


         </div>
        ) : (
         <div className="mx-auto max-w-2xl space-y-8 pb-6">


          <FieldGroup className="gap-6">
            <div className="flex gap-4 items-end">
             <Field className="w-16 shrink-0">
              <TooltipFieldLabel tooltip="Biểu tượng đại diện cho profile." className={STUDIO_LABEL_CLASS}>Icon</TooltipFieldLabel>
              <Dialog>
               <DialogTrigger asChild>
                <button className="size-16 flex items-center justify-center rounded-2xl border-2 border-dashed border-border hover:border-primary/50 hover:bg-primary/5 transition-all text-3xl shadow-sm">
                 {profileIcon || "📦"}
                </button>
               </DialogTrigger>
               <DialogContent className="p-0 border-none bg-transparent shadow-none w-fit">
                <EmojiPicker selected={profileIcon} onSelect={(e) => { setProfileIcon(e); }} />
               </DialogContent>
              </Dialog>
             </Field>
             <Field className="flex-1">
              <TooltipFieldLabel tooltip="Tên hiển thị của profile." className={STUDIO_LABEL_CLASS}>Tên Profile</TooltipFieldLabel>
              <Input
               value={profileName}
               onChange={e => setProfileName(e.target.value)}
               placeholder="VD: Cinematic Summer Look" className="h-16 rounded-2xl bg-muted/20 text-base font-bold px-5"
              />
             </Field>
            </div>
             <Field className="flex-[2]">
              <TooltipFieldLabel tooltip="Mô tả ngắn giúp phân biệt profile với các preset khác." className={STUDIO_LABEL_CLASS}>Mô tả ngắn</TooltipFieldLabel>
              <Input value={profileDesc} onChange={e => setProfileDesc(e.target.value)} placeholder="Tóm tắt công dụng..." className="h-10 rounded-xl bg-muted/20 text-sm" />
             </Field>

            <div className="space-y-3">
             <TooltipFieldLabel tooltip="Danh sách effect hiện tại sẽ được đóng gói vào profile này." className={STUDIO_LABEL_CLASS}>Các effect sẽ được lưu</TooltipFieldLabel>
             <div
              className="p-2 rounded-2xl border border-border/50 bg-muted/5 min-h-[100px] flex flex-col gap-2 transition-all duration-200 group/drop"
              onDragOver={(e) => {
               e.preventDefault();
               e.currentTarget.classList.add("border-primary", "bg-primary/5", "ring-4", "ring-primary/10");
              }}
              onDragLeave={(e) => {
               e.currentTarget.classList.remove("border-primary", "bg-primary/5", "ring-4", "ring-primary/10");
              }}
              onDrop={(e) => {
               e.preventDefault();
               e.currentTarget.classList.remove("border-primary", "bg-primary/5", "ring-4", "ring-primary/10");
               const buttonId = e.dataTransfer.getData("buttonId");
               const button = buttons.find((item) => item.id === buttonId);
               if (button) {
                addButtonToEffectControl(button);
               }
              }}
             >
               {activeEffects.map(eff => {
                const b = buttons.find(btn => btn.id === eff.buttonId);
                return (
                 <div key={eff.id} className="group/item flex items-center gap-3 p-2 bg-background border border-border/50 rounded-xl hover:border-primary/30 transition-colors">
                  <div className="size-6 flex items-center justify-center rounded bg-primary/10 text-xs">{b?.icon}</div>
                  <span className="text-sm font-semibold flex-1 truncate">{b?.name}</span>
                  <Button
                   variant="ghost"
                   size="icon"
                   className="size-6 rounded-lg opacity-0 group-hover/item:opacity-100 hover:bg-destructive/10 hover:text-destructive transition-all"
                   onClick={() => setActiveEffects(current => current.filter(item => item.id !== eff.id))}
                  >
                   <Trash2 className="size-3" />
                  </Button>
                 </div>
                )
               })}
               {activeEffects.length === 0 && <div className="py-8 text-center text-xs text-muted-foreground/40">Kéo thả button vào đây hoặc thêm vào canvas để tạo profile.</div>}
             </div>
            </div>
          </FieldGroup>
         </div>
        )}

        </div>
       </ScrollArea>
     </Card>
    ) : (
     <>
      {/* -------------------- CANVAS AREA -------------------- */}
      <Card className="relative min-h-[20rem] flex-1 overflow-hidden border-border/70 bg-black/40 shadow-xl backdrop-blur-sm lg:min-h-0">
       <div className="absolute inset-0 flex items-center justify-center pointer-events-none opacity-20">
         <Layers className="size-32 text-primary" />
       </div>
       {activeProject ? (
        <div className="absolute inset-0 flex flex-col">
          <div className="flex-1 relative flex flex-col overflow-hidden">
           <MaskCanvas
            key={selectedVersion?.id ?? activeProject.id}
            imageUrl={selectedVersion?.outputImagePath ? getThumbnailAssetUrl(selectedVersion.outputImagePath) : (activeProject?.base64Image || "")}
            onMaskChange={setMaskBase64}
            onGuideChange={handleCanvasGuideChange}
            onBrushChange={handleCanvasBrushChange}
            onShapeChange={handleCanvasShapeChange}
            onImageChange={handleCanvasImageChange}
            keepViewState={false}
            requestedToolGroup={canvasToolRequest?.toolGroup ?? null}
            requestedToolNonce={canvasToolRequest?.nonce}
            requestedGuide={canvasGuideRequest?.guide || null}
            requestedGuideNonce={canvasGuideRequest?.nonce}
            requestedToolSettingsNonce={canvasSyncNonce}
            requestedBrushSize={canvasBrushSize}
            requestedBrushColor={canvasBrushColor}
            requestedShapeTool={canvasShapeTool}
            requestedShapeFill={canvasShapeFill}
            requestedShapeOpacity={canvasShapeOpacity}
            requestedShapeHardness={canvasShapeHardness}
            requestedShapeSize={canvasShapeSize}
            canvasBgType={thumbnailSettingsDraft?.canvas_bg_type}
            canvasBgColor={thumbnailSettingsDraft?.canvas_bg_color}
            canvasBgImage={thumbnailSettingsDraft?.canvas_bg_image}
            canvasBgFit={thumbnailSettingsDraft?.canvas_bg_fit}
            canvasBgOpacity={thumbnailSettingsDraft?.canvas_bg_opacity}
            canvasBgBrightness={thumbnailSettingsDraft?.canvas_bg_brightness}
           />
          </div>
        </div>
       ) : (
        <div className="h-full flex flex-col items-center justify-center text-center p-12">
          <div className="size-24 rounded-full bg-primary/10 flex items-center justify-center mb-6 animate-pulse">
           <Layers className="size-12 text-primary" />
          </div>
          <h3 className="text-xl font-black tracking-tighter mb-2">Editor Canvas</h3>
          <p className="text-muted-foreground text-sm max-w-xs mx-auto mb-8">
           Kéo thả ảnh vào đây hoặc dán từ clipboard để bắt đầu dự án thumbnail mới.
          </p>
          <div className="flex gap-4">
           <Button onClick={() => void handlePasteFromClipboard()} className="rounded-xl px-6 h-10 font-bold">
            <Plus className="size-4 mr-2" /> Dán từ Clipboard
           </Button>
           <Button variant="outline" onClick={() => imageInputRef.current?.click()} className="rounded-xl px-6 h-10 font-bold border-border/70">
            Chọn file ảnh
           </Button>
          </div>
        </div>
       )}
      </Card>

      {/* -------------------- CENTER COLUMN: HISTORY (CAROUSEL) -------------------- */}
      {activeProject && (
       <Card className="relative flex min-h-[9.5rem] flex-col border-border/70 bg-background/40 shadow-sm backdrop-blur-md lg:h-36">
        {versions.filter(v => v.outputImagePath).length >= 2 && (
         <Button
          variant="ghost"
          size="xs"
          className="absolute right-4 top-3 z-10 h-7 rounded-full px-2 text-xs hover:bg-primary/10 hover:text-primary"
          onClick={() => setGalleryPreviewVersionId(versions.filter(v => v.outputImagePath)[0]?.id ?? null)}
         >
          <SplitSquareVertical className="w-3 h-3" />
          Xem tất cả
         </Button>
        )}
        <div className="flex-1 w-full overflow-x-auto scrollbar-hide py-0.5">
          <div className="flex min-w-max flex-row items-center gap-4 px-6 py-4 h-full">
            {/* History Versions */}

          {versions.slice().reverse().map((v) => (
           <div
            key={v.id}
            onClick={() => void handleSelectVersion(v.id)}
            className={cn(
             "group relative flex h-20 w-44 shrink-0 cursor-pointer gap-3 rounded-2xl border p-2 text-left transition-all md:w-40",
             selectedVersion?.id === v.id
              ? "border-primary bg-primary/10 ring-1 ring-primary/30 shadow-md shadow-primary/5"
              : "border-border/50 hover:border-primary/20 hover:bg-muted/30"
            )}
           >
            {/* Thumbnail */}
            <div className="relative size-14 shrink-0 overflow-hidden rounded-xl border border-border/20 bg-black/20">
             {v.outputImagePath && <img src={getThumbnailAssetUrl(v.outputImagePath)} alt={v.id} className="size-full object-cover group-hover:scale-105 transition-transform duration-500" />}
             {v.outputImagePath && (
              <button
               onClick={(e) => { e.stopPropagation(); setGalleryPreviewVersionId(v.id); }}
               className="absolute inset-0 bg-black/50 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center"
              >
               <svg className="w-3.5 h-3.5 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" /><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" /></svg>
              </button>
             )}
            </div>
            <div className="flex min-w-0 flex-1 flex-col justify-center pr-7">
             <div className="flex flex-col gap-1.5">
               <div className="flex items-center gap-2">
                 <span className="text-xs font-black text-primary">{v.label}</span>
                {v.status === "branch" && (
                 <Badge
                  variant="outline"
                  className="h-4 border-amber-500/30 bg-amber-500/5 px-1.5 text-[9px] font-bold  text-amber-500"
                 >
                  B
                 </Badge>
                )}
               </div>
               <span className="text-[11px] font-medium tabular-nums text-muted-foreground/80">
                {v.createdAt.split(' ')[1]}
               </span>
             </div>
            </div>

            {/* Delete Action */}
            <div className="absolute top-1.5 right-1.5 flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
             <Button
              variant="ghost"
              size="icon"
              className="h-6 w-6 rounded-lg bg-background/80 backdrop-blur-sm border border-border/50 hover:text-destructive shadow-sm"
              onClick={(e) => {
               e.stopPropagation();
               void handleDeleteVersion(v.id);
              }}
             >
              <Trash2 className="size-2.5" />
             </Button>
            </div>
           </div>
          ))}
         </div>
      </div>
     </Card>
    )}

    {/* -------------------- GALLERY PREVIEW OVERLAY -------------------- */}
    {galleryPreviewVersionId !== null && activeProject && (() => {
     const versionImgs = versions.filter(v => v.outputImagePath);
     const currentGalleryIdx = versionImgs.findIndex(v => v.id === galleryPreviewVersionId);
     const currentGalleryVersion = versionImgs[currentGalleryIdx];
     // Resolve which slot this version belongs to for A/B badge
     const getSlot = (id: string) => {
      if (id === compareVersionAId) return "A";
      if (id === compareVersionBId) return "B";
      return null;
     };
     const canCompare = compareVersionAId && compareVersionBId && compareVersionAId !== compareVersionBId;
     const handlePickForCompare = (vId: string) => {
      if (compareVersionAId === vId) { setCompareVersionAId(null); return; }
      if (compareVersionBId === vId) { setCompareVersionBId(null); return; }
      if (!compareVersionAId) { setCompareVersionAId(vId); return; }
      if (!compareVersionBId) { setCompareVersionBId(vId); return; }
      // Both slots full — replace B with new pick
      setCompareVersionBId(vId);
     };
     return (
      <div className="fixed inset-0 z-50 bg-background/95 backdrop-blur-md flex flex-col" onClick={() => setGalleryPreviewVersionId(null)}>
       {/* Header */}
       <div className="flex items-center justify-between px-6 py-4 border-b border-border/50 shrink-0" onClick={e => e.stopPropagation()}>
        <div className="flex items-center gap-3">
         <SplitSquareVertical className="size-5 text-primary" />
         <span className="text-sm font-black text-foreground">Gallery · {activeProject.name}</span>
         <Badge variant="outline" className="border-border/60 text-xs text-muted-foreground">{versionImgs.length} ảnh</Badge>
        </div>
        <div className="flex items-center gap-2">
         {canCompare && (
          <Button
           size="sm"
           className="h-8 rounded-full bg-primary px-3 text-xs hover:bg-primary/90 text-primary-foreground"
           onClick={() => { setShowComparator(true); setGalleryPreviewVersionId(null); }}
          >
           <SplitSquareVertical className="size-3" />
           So sánh A vs B
          </Button>
         )}
         {(compareVersionAId || compareVersionBId) && (
          <Button variant="ghost" size="sm" className="h-8 rounded-full px-3 text-xs text-muted-foreground hover:text-foreground" onClick={() => { setCompareVersionAId(null); setCompareVersionBId(null); }}>
           Xóa chọn
          </Button>
         )}
         <Button variant="ghost" size="icon" className="text-muted-foreground hover:text-foreground hover:bg-muted/50 rounded-full" onClick={() => setGalleryPreviewVersionId(null)}>
          <X className="size-5" />
         </Button>
        </div>
       </div>

       {/* Main preview */}
       <div className="flex-1 flex items-center justify-center p-6 gap-4 min-h-0" onClick={e => e.stopPropagation()}>
        {/* Prev */}
        <Button
         variant="ghost"
         size="icon"
         className="h-10 w-10 rounded-full bg-muted/50 hover:bg-muted text-foreground shrink-0"
         disabled={currentGalleryIdx <= 0}
         onClick={() => currentGalleryIdx > 0 && setGalleryPreviewVersionId(versionImgs[currentGalleryIdx - 1].id)}
        >
         <ChevronDown className="size-5 rotate-90" />
        </Button>

        {/* Current image */}
        {currentGalleryVersion && (
         <div className="flex-1 max-w-4xl h-full flex flex-col gap-3 min-h-0">
          {/* A/B slot badge on main image */}
          <ZoomableGalleryImage
           src={getThumbnailAssetUrl(currentGalleryVersion.outputImagePath)}
           alt={currentGalleryVersion.buttonName}
           badge={getSlot(currentGalleryVersion.id)}
           badgeClass={getSlot(currentGalleryVersion.id) === "A" ? "bg-blue-500 text-white" : "bg-rose-500 text-white"}
          />
          <div className="flex items-center justify-between">
           <div className="text-muted-foreground text-xs font-bold">
            <span className="text-foreground">{currentGalleryVersion.buttonName}</span>
            {currentGalleryVersion.note && <span className="ml-2 text-emerald-500">{currentGalleryVersion.note}</span>}
           </div>
           <div className="flex items-center gap-2">
            {/* Pick A / Pick B button */}
            <Button
             variant="outline"
             size="sm"
             className={cn(
              "h-8 rounded-full px-3 text-xs font-medium",
              getSlot(currentGalleryVersion.id) === "A" ? "border-blue-500 text-blue-500 hover:bg-blue-500/10" :
              getSlot(currentGalleryVersion.id) === "B" ? "border-rose-500 text-rose-500 hover:bg-rose-500/10" :
              "border-border/50 text-muted-foreground hover:bg-muted/50 hover:text-foreground"
             )}
             onClick={() => handlePickForCompare(currentGalleryVersion.id)}
            >
             {getSlot(currentGalleryVersion.id)
              ? `Bỏ chọn ${getSlot(currentGalleryVersion.id)}`
              : !compareVersionAId ? "Chọn làm A"
              : !compareVersionBId ? "Chọn làm B"
              : "Thay thế B"}
            </Button>
            <Button
             variant="outline"
             size="sm"
             className="h-8 rounded-full border-border/50 px-3 text-xs text-foreground hover:bg-muted/50"
             onClick={() => { void handleSelectVersion(currentGalleryVersion.id); setGalleryPreviewVersionId(null); }}
            >
             <Play className="size-3 mr-1.5" /> Dùng phiên bản này
            </Button>
           </div>
          </div>
         </div>
        )}

        {/* Next */}
        <Button
         variant="ghost"
         size="icon"
         className="h-10 w-10 rounded-full bg-muted/50 hover:bg-muted text-foreground shrink-0"
         disabled={currentGalleryIdx >= versionImgs.length - 1}
         onClick={() => currentGalleryIdx < versionImgs.length - 1 && setGalleryPreviewVersionId(versionImgs[currentGalleryIdx + 1].id)}
        >
         <ChevronDown className="size-5 -rotate-90" />
        </Button>
       </div>

       {/* Thumbnail strip with A/B labels */}
       <div className="shrink-0 border-t border-border/50 p-4" onClick={e => e.stopPropagation()}>
        <p className="mb-2 text-xs font-semibold text-muted-foreground">Chọn A và B để so sánh · click thumbnail để chọn</p>
        <div className="flex gap-3 overflow-x-auto py-4 px-2 scrollbar-hide">
         {versionImgs.map((v) => {
          const slot = getSlot(v.id);
          return (
           <button
            key={v.id}
            onClick={() => handlePickForCompare(v.id)}
            className={cn(
             "shrink-0 h-16 w-20 rounded-lg overflow-hidden border-2 transition-all relative",
             slot === "A" ? "border-blue-500 ring-2 ring-blue-500/40 scale-105"
             : slot === "B" ? "border-rose-500 ring-2 ring-rose-500/40 scale-105"
             : v.id === galleryPreviewVersionId ? "border-primary"
             : "border-border/50 hover:border-primary/50 opacity-60 hover:opacity-100"
            )}
           >
            <img src={getThumbnailAssetUrl(v.outputImagePath)} alt={v.id} className="h-full w-full object-cover" />
            {slot && (
             <div className={cn(
              "absolute inset-0 flex items-center justify-center text-white text-lg font-black",
              slot === "A" ? "bg-blue-500/50" : "bg-rose-500/50"
             )}>
              {slot}
             </div>
            )}
           </button>
          );
         })}
        </div>
       </div>
      </div>
     );
    })()}
   </>
  )}
 </main>

   {/* -------------------- RIGHT COLUMN -------------------- */}
   <aside className="flex min-h-[22rem] flex-col lg:col-start-3 lg:row-start-2 lg:min-h-0">
    {mainPanelTab === "config" ? (
     <Card className="flex flex-col h-full border-border/70 shadow-sm overflow-hidden bg-background/50 backdrop-blur-md">
      <ScrollArea className="flex-1">
       <div className="p-4 space-y-4">
        {configPanelTab === "button" ? (
         <>
          <div className="rounded-2xl border border-border/50 bg-card/80 p-4">
           <div className="space-y-4">
            <EffectControlPreviewCard
             icon={buttonIcon || "✨"}
             name={buttonBuilderName || "Tên button mới"}
             fields={builderFields}
             requiredTools={buttonRequiredTools}
             requiresMask={false}
            />
            {buttonBuilderPrompt.trim() && (
             <div className="mt-4 border-t border-border/40 pt-4">
              <p className={STUDIO_LABEL_CLASS}>Prompt mẫu</p>
              <p className="mt-2 whitespace-pre-wrap break-words text-xs leading-relaxed text-muted-foreground">
               {buttonPreviewPrompt || buttonBuilderPrompt.trim()}
              </p>
             </div>
            )}
           </div>
          </div>
         </>
        ) : (
          <>
           <div className="rounded-2xl border border-border/50 bg-card/70 p-4">
            <div className="space-y-4">
             {profilePreviewEffects.length > 0 ? (
              <div className="mt-3 space-y-2">
               {profilePreviewEffects.map((effect) => (
                <EffectControlPreviewCard
                 key={effect.id}
                 icon={effect.icon}
                 name={effect.name}
                 fields={effect.fields}
                 requiredTools={effect.requiredTools}
                 requiresMask={effect.requiresMask}
                />
               ))}
              </div>
             ) : (
              <div className="rounded-xl border border-dashed border-border/50 px-3 py-5 text-center text-xs text-muted-foreground">
               Chưa có hiệu ứng nào được thêm vào profile này.
              </div>
             )}
            </div>
           </div>
          </>
        )}
       </div>
      </ScrollArea>
     </Card>
    ) : (
     <Card className="flex flex-col h-full border-border/70 shadow-sm overflow-hidden bg-background/50 backdrop-blur-md">
      <Tabs value={effectTab} onValueChange={(v) => setEffectTab(v as any)} className="flex-1 flex flex-col min-h-0">
       <div className="px-4 pt-0 pb-2.5 border-b border-border/50 bg-muted/20 flex items-center justify-between">
        <TabsList className={STUDIO_TOP_TABS_CLASS}>
         <TabsTrigger value="effects" className={STUDIO_TAB_TRIGGER_CLASS}>Hiệu ứng</TabsTrigger>
         <TabsTrigger value="gemini" className={STUDIO_TAB_TRIGGER_CLASS}>Gemini</TabsTrigger>
         <TabsTrigger value="app" className={STUDIO_TAB_TRIGGER_CLASS}>Canvas</TabsTrigger>
        </TabsList>

        <div className="flex items-center gap-2">
         {activeEffects.length > 0 && (
          <Dialog>
           <DialogTrigger asChild>
            <Button
             variant="ghost" size="xs" className="h-8 gap-2 rounded-full border border-border/40 px-3 text-xs hover:bg-primary/10 hover:text-primary"
             disabled={submitting}
            >
             <Save className="w-3 h-3" />
             Lưu Profile
            </Button>
           </DialogTrigger>
           <DialogContent className="sm:max-w-md">
            <DialogHeader>
             <DialogTitle>Lưu Profile Hiệu ứng</DialogTitle>
             <p className="text-sm text-muted-foreground">
              Đóng gói {activeEffects.length} hiệu ứng hiện tại thành một profile để sử dụng lại.
             </p>
            </DialogHeader>
            <div className="flex gap-4 items-end py-4">
             <Field className="w-16 shrink-0">
              <TooltipFieldLabel tooltip="Biểu tượng đại diện" className={STUDIO_LABEL_CLASS}>Icon</TooltipFieldLabel>
              <Dialog>
               <DialogTrigger asChild>
                <button className="size-16 flex items-center justify-center rounded-2xl border-2 border-dashed border-border hover:border-primary/50 hover:bg-primary/5 transition-all text-3xl shadow-sm">
                 {profileIcon || "📦"}
                </button>
               </DialogTrigger>
               <DialogContent className="p-0 border-none bg-transparent shadow-none w-fit">
                <EmojiPicker selected={profileIcon} onSelect={(e) => { setProfileIcon(e); }} />
               </DialogContent>
              </Dialog>
             </Field>
             <Field className="flex-1">
              <TooltipFieldLabel tooltip="Tên hiển thị của profile." className={STUDIO_LABEL_CLASS}>Tên Profile</TooltipFieldLabel>
              <Input
               value={profileName}
               onChange={e => setProfileName(e.target.value)}
               placeholder="VD: Cinematic Summer Look" className="h-16 rounded-2xl bg-muted/20 text-base font-bold px-5"
              />
             </Field>
            </div>
            <DialogFooter>
             <DialogClose asChild>
              <Button variant="outline">Hủy</Button>
             </DialogClose>
             <DialogClose asChild>
              <Button onClick={() => void handleSaveProfile()}>Lưu Profile</Button>
             </DialogClose>
            </DialogFooter>
           </DialogContent>
          </Dialog>
         )}
         {activeEffects.length > 0 && (
          <Button variant="ghost" size="icon" className="h-7 w-7 text-muted-foreground hover:text-destructive" onClick={() => setActiveEffects([])}>
           <X className="w-3.5 h-3.5" />
          </Button>
         )}
        </div>
       </div>

       <TabsContent value="effects" className="flex-1 flex flex-col min-h-0 m-0 border-0">
        <ScrollArea
         className="min-h-0 flex-1"
         onDragOver={(e) => {
          e.preventDefault();
          e.dataTransfer.dropEffect = "copy";
         }}
         onDrop={(e) => {
          const buttonId = e.dataTransfer.getData("buttonId");
          if (buttonId) {
           const b = buttons.find(btn => btn.id === buttonId);
           if (b) {
            addButtonToEffectControl(b);
           }
          }
         }}
        >
         <div className="space-y-4 p-4 pr-3">
           {activeEffects.map((eff) => {
            const b = buttons.find(btn => btn.id === eff.buttonId);
            if (!b) return null;

            return (
             <div
              key={eff.id}
              draggable
              onDragStart={(e) => {
               e.dataTransfer.setData("effectId", eff.id);
               setDraggedEffectId(eff.id);
              }}
              onDragOver={(e) => {
               if (draggedEffectId && draggedEffectId !== eff.id) {
                e.preventDefault();
               }
              }}
              onDrop={(e) => {
               const sourceId = e.dataTransfer.getData("effectId");
               if (sourceId && sourceId !== eff.id) {
                e.preventDefault();
                e.stopPropagation();
                setActiveEffects(prev => {
                 const sourceIndex = prev.findIndex(item => item.id === sourceId);
                 const targetIndex = prev.findIndex(item => item.id === eff.id);
                 if (sourceIndex < 0 || targetIndex < 0) return prev;
                 const next = [...prev];
                 const [removed] = next.splice(sourceIndex, 1);
                 next.splice(targetIndex, 0, removed);
                 return next;
                });
               }
               setDraggedEffectId(null);
              }}
              onDragEnd={() => setDraggedEffectId(null)}
              className={cn(
               "rounded-2xl border bg-card/50 overflow-hidden shadow-sm transition-all duration-200",
               draggedEffectId === eff.id ? "opacity-30 border-primary" : "opacity-100 border-border/50 hover:border-primary/30"
              )}
             >
              <div className="px-4 py-2 bg-muted/30 border-b border-border/30 flex items-center justify-between">
               <div className="flex items-center gap-2 flex-1 cursor-pointer select-none" onClick={() => toggleEffectCollapse(eff.id)}>
                <div className="size-6 flex items-center justify-center rounded bg-primary/10 text-xs">{b.icon}</div>
                <span className="text-xs font-semibold  text-primary/80">{b.name}</span>
                {collapsedEffects.has(eff.id) ? <ChevronDown className="size-3 text-muted-foreground" /> : <ChevronUp className="size-3 text-muted-foreground" />}
               </div>
               <Button variant="ghost" size="icon" className="h-5 w-5 text-muted-foreground hover:text-destructive" onClick={() => setActiveEffects(activeEffects.filter(e => e.id !== eff.id))}>
                <Trash2 className="size-3" />
               </Button>
              </div>
              {!collapsedEffects.has(eff.id) && (
               <div className="space-y-4 p-4 border-t border-border/10">
                {eff.fields.map(field => (
                 <ThumbnailFieldRenderer
                  key={field.key}
                  field={field}
                  allFields={eff.fields}
                  onChange={(val) => handleEffectFieldChange(eff.id, field.key, val)}
                 />
                ))}
               </div>
              )}
             </div>
            )
           })}

           {activeEffects.length === 0 && (
            <div className="flex flex-col items-center justify-center py-20 text-center space-y-4 opacity-40">
             <div className="size-12 rounded-full bg-muted flex items-center justify-center border border-dashed border-border"><Plus className="size-6 text-muted-foreground" /></div>
             <p className="max-w-[170px] text-xs font-medium text-muted-foreground">Kéo hoặc thêm button từ thư viện để bắt đầu hiệu chỉnh.</p>
            </div>
           )}
         </div>
        </ScrollArea>
       </TabsContent>

       <TabsContent value="gemini" className="flex-1 flex flex-col min-h-0 m-0 border-0">
        <ScrollArea className="flex-1">
         <div className="p-4 space-y-5">
          <div className="pt-1">
           {thumbnailGeminiSettingsPanel}
          </div>

          {runPromptPreview ? (
           <div className="space-y-2">
            <span className={cn(STUDIO_LABEL_CLASS, "px-1")}>Preview Prompt</span>
            <div className="rounded-2xl border border-border/50 bg-background/80 p-3">
             <p className="whitespace-pre-wrap break-words text-xs leading-relaxed text-muted-foreground">
              {runPromptPreview}
             </p>
            </div>
           </div>
          ) : (
           <div className="p-8 text-center border border-dashed border-border/50 rounded-2xl opacity-50">
            <p className="text-xs font-medium text-muted-foreground">Thêm effect để xem prompt preview.</p>
           </div>
          )}
         </div>
        </ScrollArea>
       </TabsContent>

       <TabsContent value="app" className="flex-1 flex flex-col min-h-0 m-0 border-0">
        <ScrollArea className="flex-1">
         <div className="p-4 space-y-6">
          <div>
           <div className={cn(STUDIO_LABEL_CLASS, "mb-3 px-1 text-[13px] text-foreground/80")}>Cấu hình Canvas</div>
           <FieldGroup className="gap-5">
           <Field>
            <TooltipFieldLabel tooltip="Thay đổi nền của vùng Canvas" className={STUDIO_LABEL_CLASS}>Dạng nền</TooltipFieldLabel>
            <Select value={thumbnailSettingsDraft?.canvas_bg_type || "solid"} onValueChange={(v) => void handleSaveThumbnailSettings({ canvas_bg_type: v })}>
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
           
           {thumbnailSettingsDraft?.canvas_bg_type === "custom" ? (
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
                     reader.onload = (ev) => void handleSaveThumbnailSettings({ canvas_bg_image: ev.target?.result as string });
                     reader.readAsDataURL(file);
                    }
                   };
                   input.click();
                 }}>
                  {thumbnailSettingsDraft?.canvas_bg_image ? (
                   <><RefreshCw className="size-3 mr-2" /> Thay đổi ảnh</>
                  ) : (
                   <><Upload className="size-3 mr-2" /> Tải ảnh lên</>
                  )}
                 </Button>
                 {thumbnailSettingsDraft?.canvas_bg_image && (
                  <Button variant="ghost" size="icon" className="size-9 rounded-xl border border-border/50 bg-background/50 hover:bg-destructive/10 hover:text-destructive shrink-0" onClick={() => void handleSaveThumbnailSettings({ canvas_bg_image: "" })}>
                   <Trash2 className="size-3" />
                  </Button>
                 )}
                </div>
               </Field>
               <Field>
                <TooltipFieldLabel tooltip="Cách ảnh nền vừa vặn" className={STUDIO_LABEL_CLASS}>Chế độ hiển thị</TooltipFieldLabel>
                <Select value={thumbnailSettingsDraft?.canvas_bg_fit || "cover"} onValueChange={(v) => void handleSaveThumbnailSettings({ canvas_bg_fit: v })}>
                 <SelectTrigger className={STUDIO_INPUT_CLASS}>
                  <SelectValue />
                 </SelectTrigger>
                 <SelectContent>
                  <SelectItem value="cover">Lấp đầy</SelectItem>
                  <SelectItem value="contain">Vừa vặn</SelectItem>
                  <SelectItem value="fill">Kéo giãn</SelectItem>
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
                value={thumbnailSettingsDraft?.canvas_bg_color || "#0f0f0f"}
                onChange={(e) => void handleSaveThumbnailSettings({ canvas_bg_color: e.target.value })}
                className="size-9 rounded-xl cursor-pointer"
               />
               <Input
                value={thumbnailSettingsDraft?.canvas_bg_color || "#0f0f0f"}
                onChange={(e) => void handleSaveThumbnailSettings({ canvas_bg_color: e.target.value })}
                className={STUDIO_INPUT_CLASS}
               />
              </div>
             </Field>
           )}

           <Field>
            <TooltipFieldLabel tooltip="Độ mờ của nền" className={STUDIO_LABEL_CLASS}>Độ mờ ({thumbnailSettingsDraft?.canvas_bg_opacity ?? 100}%)</TooltipFieldLabel>
            <Slider
             value={[thumbnailSettingsDraft?.canvas_bg_opacity ?? 100]}
             min={0} max={100} step={1}
             onValueChange={(v) => void handleSaveThumbnailSettings({ canvas_bg_opacity: v[0] })}
            />
           </Field>

           <Field>
            <TooltipFieldLabel tooltip="Độ sáng của nền" className={STUDIO_LABEL_CLASS}>Độ sáng ({thumbnailSettingsDraft?.canvas_bg_brightness ?? 100}%)</TooltipFieldLabel>
            <Slider
             value={[thumbnailSettingsDraft?.canvas_bg_brightness ?? 100]}
             min={0} max={200} step={1}
             onValueChange={(v) => void handleSaveThumbnailSettings({ canvas_bg_brightness: v[0] })}
            />
           </Field>

           </FieldGroup>
          </div>
         </div>
        </ScrollArea>
       </TabsContent>

      </Tabs>

      <div className="border-t border-border/50 bg-muted/10 p-4 space-y-3">
        <div className="flex items-center justify-end px-1">
         {submitting && <Badge variant="outline" className="h-5 text-[11px] animate-pulse">{runStatus || "Processing"}</Badge>}
        </div>

        <Button onClick={() => void handleRun()} disabled={submitting || activeEffects.length === 0} className="w-full h-11 rounded-2xl font-black shadow-xl shadow-primary/20">
         {submitting ? (
          <>
           <Loader2 className="size-4 animate-spin mr-2" />
           {runStatus || "Đang xử lý..."}
          </>
         ) : (
          <>
           <Play className="size-4 mr-2" />
           Run Studio
          </>
         )}
        </Button>
      </div>
     </Card>
    )}
   </aside>
  </div>
 );
}
