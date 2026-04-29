import { useEffect, useState, useTransition, useMemo, useRef, useCallback } from "react";
import {
  Download, Loader2,
  Play, Plus, Search,
  Layers, Trash2, Pin, PinOff,
  Sliders, Zap, Save, X, ChevronDown, ChevronUp, Edit3, SplitSquareVertical, Pencil
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
import { ScrollArea, ScrollBar } from "@/components/ui/scroll-area";
import { Slider } from "@/components/ui/slider";
import { Field, FieldGroup } from "@/components/ui/field";
import { TooltipFieldLabel } from "@/components/ui/tooltip-field-label";
import {
  Dialog,
  DialogTrigger,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
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
  togglePinThumbnailButton,
  togglePinThumbnailProfile,
  getThumbnailAssetUrl,
  getThumbnailBootstrap,
  getThumbnailProject,
  openFolder,
  runThumbnailGenerationBatch,
  selectThumbnailVersion,
  deleteThumbnailVersion,
  renameThumbnailProject,
  type ThumbnailBootstrapPayload,
  type ThumbnailButtonField,
  type ThumbnailProfile,
  type ThumbnailProfileEffect,
  type ThumbnailProjectDetail,
  type ThumbnailVersion,
} from "../lib/api";
import MaskCanvas, { type CanvasGuide } from "./MaskCanvas";

import { useLocalStorage } from "@/hooks/use-local-storage";
import { cn } from "@/lib/utils";

function fieldValueMap(fields: ThumbnailButtonField[]) {
  return Object.fromEntries(fields.map((field) => [field.key, field.value])) as Record<string, string | number | boolean | string[]>;
}

function getErrorMessage(error: unknown) {
  return error instanceof Error ? error.message : "Yêu cầu thất bại.";
}

function getHistoryCopy(version: ThumbnailVersion) {
  const note = (version.note || "").trim();
  if (note && !/gemini/i.test(note)) {
    return note;
  }
  if (version.prompt?.trim()) {
    return `"${version.prompt.trim()}"`;
  }
  return "Không có mô tả.";
}

/**
 * Logic to check if a field should be visible based on visibleIf metadata
 */
function isFieldVisible(field: ThumbnailButtonField, allFields: ThumbnailButtonField[]): boolean {
  if (!field.visibleIf) return true;
  
  if (typeof field.visibleIf === "string") {
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
      <TooltipFieldLabel tooltip={field.tooltip} className="text-[10px] font-black uppercase text-muted-foreground tracking-widest">
        {field.label} {field.required && <span className="text-destructive">*</span>}
      </TooltipFieldLabel>
      {field.type === "slider" && <span className="text-[10px] font-mono font-bold text-primary">{field.value}</span>}
    </div>
  );

  switch (field.type) {
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
          <div className="flex flex-col gap-0.5">
            <span className="text-[10px] font-black uppercase text-foreground/80 tracking-tight">{field.label}</span>
            <span className="text-[9px] text-muted-foreground">{field.tooltip || "Bật hoặc tắt tùy chọn này"}</span>
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
              className="h-10 flex-1 bg-muted/10 border-border/50 text-sm font-mono uppercase"
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

const EMOJI_LIST = [
  { category: "Phổ biến", items: ["✨", "🖼️", "🎨", "🎭", "🌈", "⚡", "🔥", "❄️", "🌑", "☀️", "📸", "🎥", "🎬", "💎", "🌟", "🔥", "💥", "💫", "🤖", "🧠"] },
  { category: "Cảm xúc", items: ["😀", "😎", "🤩", "😮", "🤔", "😱", "😡", "😴", "😇", "🥳", "😭", "😍", "🤯", "👽", "👾", "👻", "🤡", "💩", "👹", "👺"] },
  { category: "Vật thể", items: ["👕", "👗", "🎒", "🚗", "🚲", "🏠", "🏢", "💻", "📱", "⌚", "🍔", "🍕", "🍦", "🍎", "🥕", "🍺", "☕", "⚽", "🏀", "🎮"] },
  { category: "Thiên nhiên", items: ["🐶", "🐱", "🦁", "🐲", "🌳", "🌵", "🌸", "🌊", "🌋", "🌪️", "☁️", "🌙", "⭐", "🌍", "🪐", "🍁", "🍄", "🐝", "🦋", "🦄"] },
];

function EmojiPicker({ selected, onSelect, className }: { selected: string, onSelect: (e: string) => void, className?: string }) {
  const [search, setSearch] = useState("");
  const filtered = EMOJI_LIST.map(cat => ({
    ...cat,
    items: cat.items.filter(i => i.includes(search))
  })).filter(cat => cat.items.length > 0);

  return (
    <div className={cn("p-4 space-y-4 bg-popover border border-border rounded-2xl shadow-2xl min-w-[300px]", className)}>
      <Input 
        placeholder="Tìm emoji..." 
        value={search} 
        onChange={e => setSearch(e.target.value)}
        className="h-9 bg-muted/20 border-border/50 rounded-xl"
      />
      <ScrollArea className="h-[250px]">
        <div className="space-y-4 pr-3">
          {filtered.map(cat => (
            <div key={cat.category} className="space-y-2">
              <h4 className="text-[9px] font-black uppercase text-muted-foreground tracking-widest">{cat.category}</h4>
              <div className="grid grid-cols-6 gap-1">
                {cat.items.map(emoji => (
                  <button
                    key={emoji}
                    onClick={() => onSelect(emoji)}
                    className={cn(
                      "size-9 flex items-center justify-center rounded-xl hover:bg-primary/20 transition-all text-lg",
                      selected === emoji && "bg-primary text-primary-foreground shadow-lg scale-110"
                    )}
                  >
                    {emoji}
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
    <div className="fixed inset-0 z-50 bg-black/92 backdrop-blur-md flex flex-col items-center justify-center p-6 gap-5">
      {/* Header */}
      <div className="flex items-center justify-between w-full max-w-5xl">
        <div className="flex items-center gap-3">
          <SplitSquareVertical className="size-5 text-primary" />
          <span className="text-sm font-black uppercase tracking-widest text-white">So sánh phiên bản</span>
          <div className="px-2 py-0.5 rounded-full bg-white/10 text-[9px] font-bold text-white/60 uppercase">Kéo thanh để so sánh</div>
        </div>
        <button
          onClick={onClose}
          className="size-9 flex items-center justify-center rounded-xl bg-white/10 hover:bg-white/20 text-white transition-all hover:scale-105"
        >
          <X className="size-5" />
        </button>
      </div>

      {/* Comparator canvas */}
      <div
        ref={containerRef}
        className="relative w-full max-w-5xl rounded-2xl overflow-hidden border border-white/10 shadow-2xl select-none"
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
        <span className="text-[10px] text-white/40 font-bold w-20 text-right truncate">{beforeLabel}</span>
        <input
          type="range" min={2} max={98} value={Math.round(sliderPos)}
          onChange={(e) => setSliderPos(Number(e.target.value))}
          className="flex-1 h-1 accent-white cursor-pointer"
        />
        <span className="text-[10px] text-white/40 font-bold w-20 truncate">{afterLabel}</span>
      </div>
    </div>
  );
}

export default function ThumbnailStudio() {
  const [bootLoading, setBootLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const submittingRef = useRef(false);
  const [exporting, setExporting] = useState(false);
  const [bootstrap, setBootstrap] = useState<ThumbnailBootstrapPayload | null>(null);
  const [activeProject, setActiveProject] = useState<ThumbnailProjectDetail | null>(null);
  const [maskBase64, setMaskBase64] = useState<string | null>(null);
  const [showComparator, setShowComparator] = useState(false);
  const [showExportDialog, setShowExportDialog] = useState(false);
  // Gallery preview: null = closed, string = versionId currently being previewed
  const [galleryPreviewVersionId, setGalleryPreviewVersionId] = useState<string | null>(null);
  const [canvasGuide, setCanvasGuide] = useState<CanvasGuide | null>(null);
  // Free-pick comparison: A and B are version IDs chosen by the user
  const [compareVersionAId, setCompareVersionAId] = useState<string | null>(null);
  const [compareVersionBId, setCompareVersionBId] = useState<string | null>(null);

  const [selectedMode] = useState<"preset" | "custom" | "mask">("preset");
  const [leftPanelTab, setLeftPanelTab] =
    useLocalStorage<LeftPanelTab>("thumbnail.leftPanelTab", "buttons");
  const [mainPanelTab, setMainPanelTab] =
    useLocalStorage<MainPanelTab>("thumbnail.mainPanelTab", "canvas");
  const [configPanelTab, setConfigPanelTab] =
    useLocalStorage<ConfigPanelTab>("thumbnail.configPanelTab", "button");
  const regenerateMode = "new-chat" as const;
  
  // Effect Control State
  const [activeEffects, setActiveEffects] = useState<EffectControlEffect[]>([]);

  // Button Builder State
  const [buttonBuilderName, setButtonBuilderName] = useState("");
  const [buttonBuilderCategory, setButtonBuilderCategory] = useState("Custom");
  const [buttonBuilderPrompt, setButtonBuilderPrompt] = useState("");
  const [builderRequiresMask, setBuilderRequiresMask] = useState(false);
  const builderCreateNewChat = true;
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
  const [newFieldDefault, setNewFieldDefault] = useState<any>("");
  const [newFieldOptions, setNewFieldOptions] = useState("");
  const [newFieldMin, setNewFieldMin] = useState<number | null>(null);
  const [newFieldMax, setNewFieldMax] = useState<number | null>(null);
  const [newFieldRequired, setNewFieldRequired] = useState(false);
  const [newFieldVisibleIf, setNewFieldVisibleIf] = useState("");

  // Export State
  const [exportFolder, setExportFolder] = useState("");
  const [exportName, setExportName] = useState("thumbnail_final");

  const [, startTransition] = useTransition();

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
    void (async () => {
      setBootLoading(true);
      try {
        const payload = await getThumbnailBootstrap();
        startTransition(() => {
          setBootstrap(payload);
          setActiveProject(payload.activeProject);
        });
      } catch (error) {
        toast.error(getErrorMessage(error));
      } finally {
        setBootLoading(false);
      }
    })();
  }, []);

  const buttons = useMemo(() => bootstrap?.buttons ?? [], [bootstrap?.buttons]);
  const profiles = useMemo(() => bootstrap?.profiles ?? [], [bootstrap?.profiles]);

  const versions = useMemo(() => activeProject?.versions ?? [], [activeProject?.versions]);
  const selectedVersion = activeProject?.currentVersion ?? versions[versions.length - 1] ?? null;

  const beforeVersion = useMemo(() => {
    if (!activeProject || !selectedVersion) return null;
    if (selectedVersion.parentVersionId) {
      return activeProject.versions.find(v => v.id === selectedVersion.parentVersionId) || activeProject.versions[0];
    }
    return activeProject.versions[0];
  }, [activeProject, selectedVersion]);
  const sortedButtons = useMemo(
    () => buttons.slice().sort((a, b) => Number(Boolean(b.isPinned)) - Number(Boolean(a.isPinned))),
    [buttons],
  );
  const sortedProfiles = useMemo(
    () => profiles.slice().sort((a, b) => Number(Boolean(b.isPinned)) - Number(Boolean(a.isPinned))),
    [profiles],
  );
  const sortedProjects = useMemo(
    () =>
      (bootstrap?.projects ?? [])
        .slice()
        .sort((a, b) => new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime()),
    [bootstrap?.projects],
  );
  const reversedVersions = useMemo(() => versions.slice().reverse(), [versions]);
  const versionImages = useMemo(() => versions.filter((v) => v.outputImagePath), [versions]);
  const selectedImageUrl = selectedVersion?.outputImagePath
    ? getThumbnailAssetUrl(selectedVersion.outputImagePath)
    : (activeProject?.base64Image || "");

  const applyCanvasGuideToFields = useCallback((buttonId: string, fields: ThumbnailButtonField[]) => {
    if (buttonId !== "extend-wide" || canvasGuide?.mode !== "artboard" || !canvasGuide.ratioLabel) {
      return fields;
    }

    const artboardHint = `Respect the ${canvasGuide.ratioLabel} artboard guide and keep the subject balanced inside the new frame.`;
    let changed = false;
    const nextFields = fields.map((field) => {
      if (field.key === "target_ratio" && field.value !== canvasGuide.ratioLabel) {
        changed = true;
        return { ...field, value: canvasGuide.ratioLabel };
      }
      if (field.key === "artboard_hint" && field.value !== artboardHint) {
        changed = true;
        return { ...field, value: artboardHint };
      }
      if (field.key === "custom_ratio" && field.value) {
        changed = true;
        return { ...field, value: "" };
      }
      return field;
    });
    return changed ? nextFields : fields;
  }, [canvasGuide]);

  useEffect(() => {
    if (canvasGuide?.mode !== "artboard") return;
    setActiveEffects((current) => {
      let changed = false;
      const next = current.map((effect) => {
        const nextFields = applyCanvasGuideToFields(effect.buttonId, effect.fields);
        if (nextFields !== effect.fields) {
          changed = true;
          return { ...effect, fields: nextFields };
        }
        return effect;
      });
      return changed ? next : current;
    });
  }, [applyCanvasGuideToFields, canvasGuide]);

  const buildEffectFromButton = useCallback((
    button: ThumbnailBootstrapPayload["buttons"][number],
    savedValues?: Record<string, any>,
  ) => {
    const nextFields = button.fields.map((field) => ({
      ...field,
      value: savedValues?.[field.key] ?? field.value,
    }));
    return {
      id: Math.random().toString(36).substr(2, 9),
      buttonId: button.id,
      fields: applyCanvasGuideToFields(button.id, nextFields),
    };
  }, [applyCanvasGuideToFields]);

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
      fields: applyCanvasGuideToFields(effect.buttonId, [...mergedFields, ...extraFields]),
    };
  }, [applyCanvasGuideToFields, buttons]);

  const applyProfileToEffectControl = useCallback((profile: ThumbnailProfile, options?: { silent?: boolean }) => {
    const nextEffects = profile.effects
      .map(buildEffectFromProfileEffect)
      .filter((effect): effect is EffectControlEffect => effect !== null);
    setActiveEffects(nextEffects);
    if (!options?.silent) {
      if (nextEffects.length === profile.effects.length) {
        toast.success(`Đã áp dụng Profile: ${profile.name}`);
      } else {
        toast.warning(`Đã áp dụng Profile: ${profile.name}. Một số effect không còn button tương ứng nên bị bỏ qua.`);
      }
    }
  }, [buildEffectFromProfileEffect]);

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
    setBuilderRequiresMask(button.requiresMask);
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
    setBuilderRequiresMask(false);
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
  }

  function handleEffectFieldChange(effectId: string, key: string, nextValue: any) {
    setActiveEffects((current) =>
      current.map((eff) =>
        eff.id === effectId
          ? {
              ...eff,
              fields: eff.fields.map((f) => (f.key === key ? { ...f, value: nextValue } : f)),
            }
          : eff
      )
    );
  }

  async function handleRun() {
    const isRegenerate = false;
    if (!activeProject || activeEffects.length === 0) return toast.error("Hãy chọn ảnh và thêm ít nhất một hiệu ứng (button).");
    if (!beginSubmit()) return;

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

      syncProject(currentProject);
      toast.success("Đã hoàn thành tạo ảnh với các hiệu ứng đã chọn.");
    } catch (error) {
      toast.error(getErrorMessage(error));
    } finally {
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
      handleCancelEdit();
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
        requiresMask: builderRequiresMask,
        createNewChat: builderCreateNewChat,
        allowRegenerate: true,
        fields: builderFields,
      });
      startTransition(() => {
        setBootstrap((current) =>
          current ? { ...current, buttons: [...current.buttons.filter((item) => item.id !== button.id), button] } : current,
        );
        toast.success(editingButtonId ? "Đã cập nhật hành động." : "Đã lưu hành động mới.");
        handleCancelEdit();
        setMainPanelTab("canvas");
      });
    } catch (error) {
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

  async function handleChooseExportFolder() {
    try {
      const result = await chooseFolder();
      setExportFolder(result.path);
    } catch (error) {
      toast.error(getErrorMessage(error));
    }
  }

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
          Khởi tạo ThumbAI Studio...
        </CardContent>
      </Card>
    );
  }

  return (
    <div className={cn("flex flex-col h-[calc(100vh-7rem)] gap-4")}>
      
      {/* HEADER WITH EXPORT */}
      <div className="flex items-center justify-between bg-card border border-border/70 p-3 px-5 rounded-2xl shadow-sm">
        <div className="flex items-center gap-6">
          <div className="flex items-center gap-2">
            <Zap className="size-5 text-primary fill-primary/20" />
            <h1 className="text-sm font-black uppercase tracking-widest text-foreground/80">Thumbnail Studio</h1>
          </div>
          <Tabs value={mainPanelTab} onValueChange={(v) => setMainPanelTab(v as MainPanelTab)} className="h-9">
            <TabsList className="bg-muted/50 p-1 h-full">
              <TabsTrigger value="canvas" className="text-[10px] uppercase font-bold h-full px-4 rounded-lg data-[state=active]:bg-background">Editor Canvas</TabsTrigger>
              <TabsTrigger value="config" className="text-[10px] uppercase font-bold h-full px-4 rounded-lg data-[state=active]:bg-background">Thiết lập & Cấu hình</TabsTrigger>
            </TabsList>
          </Tabs>
        </div>
        
        <div className="flex items-center gap-3">
          {activeProject && (
            <div className="px-3 py-1.5 rounded-xl bg-muted/30 border border-border/50 flex items-center gap-3">
               <div className="flex flex-col items-end">
                 <span className="text-[9px] font-bold text-muted-foreground uppercase leading-none mb-0.5">Dự án</span>
                 <span className="text-[11px] font-bold text-foreground leading-none">{activeProject.name}</span>
               </div>
               <div className="w-px h-6 bg-border/50" />
               {beforeVersion && (
                 <Button
                   variant="ghost" size="icon"
                   className={cn("h-8 w-8", showComparator ? "text-primary bg-primary/10" : "text-muted-foreground hover:text-primary")}
                   title="So sánh phiên bản"
                   onClick={() => setShowComparator(v => !v)}
                 >
                   <SplitSquareVertical className="size-4" />
                 </Button>
               )}
               <Button variant="ghost" size="icon" className="h-8 w-8 text-primary" onClick={() => setShowExportDialog(true)}>
                 <Download className="size-4" />
               </Button>
            </div>
          )}
        </div>
      </div>

      <div className={cn("grid lg:grid-cols-[20rem_minmax(0,1fr)_22rem] flex-1 min-h-0", "gap-4")}>
      
      {/* EXPORT DIALOG */}
      <Dialog open={showExportDialog} onOpenChange={setShowExportDialog}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="text-sm font-bold uppercase tracking-tight">Xuất ảnh Thumbnail</DialogTitle>
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
                <Button variant="secondary" size="sm" className="h-7 px-3 text-[10px] uppercase font-bold rounded-lg" onClick={() => void handleChooseExportFolder()}>Chọn thư mục</Button>
              </div>
            </Field>
          </div>
          <DialogFooter>
            <Button variant="ghost" size="sm" onClick={() => setShowExportDialog(false)}>Hủy</Button>
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
      <aside className="flex flex-col min-h-0">
        <Card className="flex flex-col h-full border-border/70 shadow-sm overflow-hidden bg-background/50 backdrop-blur-md">
          <ScrollArea className="flex-1">
            <Tabs value={leftPanelTab} onValueChange={(v) => setLeftPanelTab(v as LeftPanelTab)} className="w-full">
              <div className="px-4 py-3 border-b border-border/50">
                <TabsList className="w-full h-8 bg-muted/30 p-1">
                  <TabsTrigger value="buttons" className="flex-1 text-[10px] uppercase font-bold rounded-md">Buttons</TabsTrigger>
                  <TabsTrigger value="profiles" className="flex-1 text-[10px] uppercase font-bold rounded-md">Profiles</TabsTrigger>
                  <TabsTrigger value="projects" className="flex-1 text-[10px] uppercase font-bold rounded-md">Projects</TabsTrigger>
                </TabsList>
              </div>

              <TabsContent value="buttons" className="m-0 p-4 space-y-4">
                <div className="relative group">
                  <Search className="absolute left-3 top-1/2 -translate-y-1/2 size-3.5 text-muted-foreground" />
                  <Input placeholder="Tìm button..." className="h-9 pl-9 bg-muted/20 border-border/50 rounded-xl" />
                </div>
                
                <div className="grid grid-cols-2 gap-2">
                  {sortedButtons.map(b => (
                    <div key={b.id} className="relative group">
                      <button 
                        draggable="true"
                        onDragStart={(e) => {
                          e.dataTransfer.setData("buttonId", b.id);
                          e.dataTransfer.effectAllowed = "copy";
                        }}
                        onClick={() => {
                          if (mainPanelTab === "canvas") {
                            const newEffect = buildEffectFromButton(b);
                            setActiveEffects((current) => [...current, newEffect]);
                            toast.success(`Đã thêm ${b.name}`);
                          } else {
                            handleEditButton(b);
                          }
                        }}
                        className="w-full flex flex-col items-center justify-center p-4 rounded-2xl border border-border/50 bg-card hover:border-primary/50 hover:bg-primary/5 transition-all text-center gap-3 active:scale-95 cursor-grab active:cursor-grabbing"
                      >
                        <div className="size-10 flex items-center justify-center rounded-xl bg-primary/10 text-primary group-hover:scale-110 transition-transform">{b.icon}</div>
                        <div className="text-[11px] font-bold uppercase tracking-tight">{b.name}</div>
                        {b.isPinned && <Pin className="absolute top-2 left-2 size-3 text-primary fill-primary" />}
                      </button>
                      
                      <div className="absolute top-1 right-1 flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                        <Button 
                          variant="ghost" 
                          size="icon" 
                          className="h-6 w-6 rounded-lg bg-background/80 backdrop-blur-sm border border-border/50 hover:text-primary"
                          onClick={(e) => {
                            e.stopPropagation();
                            handleTogglePinButton(b.id);
                          }}
                        >
                          {b.isPinned ? <PinOff className="size-3" /> : <Pin className="size-3" />}
                        </Button>
                        <Button 
                          variant="ghost" 
                          size="icon" 
                          className="h-6 w-6 rounded-lg bg-background/80 backdrop-blur-sm border border-border/50 hover:text-destructive"
                          onClick={(e) => {
                            e.stopPropagation();
                            handleDeleteButton(b.id);
                          }}
                        >
                          <Trash2 className="size-3" />
                        </Button>
                      </div>
                    </div>
                  ))}
                </div>
              </TabsContent>

              <TabsContent value="profiles" className="m-0 p-4 space-y-3">
                 {sortedProfiles.map(p => (
                   <div key={p.id} className="relative group/prof">
                    <button 
                      onClick={() => {
                        if (mainPanelTab === "canvas") {
                          applyProfileToEffectControl(p);
                        } else {
                          handleEditProfile(p);
                        }
                      }}
                      className="w-full flex items-center justify-between p-3 rounded-xl border border-border/50 bg-card hover:bg-muted/50 transition-all group"
                    >
                      <div className="flex items-center gap-3">
                          <div className="size-8 flex items-center justify-center rounded-lg bg-primary/10 text-primary"><span>{p.icon || "📦"}</span></div>
                          <div className="text-left">
                            <div className="text-xs font-bold flex items-center gap-1">
                              {p.name}
                              {p.isPinned && <Pin className="size-2.5 text-primary fill-primary" />}
                            </div>
                            <div className="text-[10px] text-muted-foreground truncate max-w-[120px]">{p.description || "Combo nhiều hành động"}</div>
                          </div>
                        </div>
                      </button>
                      <div className="flex gap-1 opacity-0 group-hover/prof:opacity-100 transition-opacity absolute right-3 top-1/2 -translate-y-1/2">
                        <Button 
                          variant="ghost" 
                          size="icon" 
                          className="h-7 w-7 rounded-lg hover:text-primary"
                          onClick={(e) => {
                            e.stopPropagation();
                            handleTogglePinProfile(p.id);
                          }}
                        >
                          {p.isPinned ? <PinOff className="size-3" /> : <Pin className="size-3" />}
                        </Button>
                        <Button 
                          variant="ghost" 
                          size="icon" 
                          className="h-7 w-7 rounded-lg hover:text-destructive"
                          onClick={(e) => {
                            e.stopPropagation();
                            handleDeleteProfile(p.id);
                          }}
                        >
                          <Trash2 className="size-3" />
                        </Button>
                      </div>
                   </div>
                 ))}
              </TabsContent>

              <TabsContent value="projects" className="m-0 p-4 space-y-3">
                <div className="relative group mb-2">
                  <Search className="absolute left-3 top-1/2 -translate-y-1/2 size-3.5 text-muted-foreground" />
                  <Input placeholder="Tìm dự án..." className="h-9 pl-9 bg-muted/20 border-border/50 rounded-xl" />
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
                        {p.base64Image ? (
                          <img src={p.base64Image} alt={p.name} className="size-full object-cover" />
                        ) : (
                          <Layers className="size-full p-2 text-muted-foreground/50" />
                        )}
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="text-[11px] font-bold truncate text-foreground/90">{p.name}</div>
                        <div className="text-[9px] text-muted-foreground flex items-center gap-2 mt-0.5">
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
              </TabsContent>
            </Tabs>
          </ScrollArea>
        </Card>
      </aside>

      {/* -------------------- CENTER COLUMN -------------------- */}
      <main className="flex flex-col min-h-0 gap-4">
        {mainPanelTab === "config" ? (
          <Card className="flex-1 border-border/70 shadow-sm overflow-hidden flex flex-col bg-background/50 backdrop-blur-md">
             <div className="px-6 py-4 border-b border-border/50 bg-muted/20">
               <Tabs value={configPanelTab} onValueChange={(v) => setConfigPanelTab(v as ConfigPanelTab)} className="w-fit">
                 <TabsList className="bg-muted p-1">
                   <TabsTrigger value="button" className="text-[10px] uppercase font-bold rounded px-4">
                     {editingButtonId ? "Sửa Button" : "Tạo Button"}
                   </TabsTrigger>
                   <TabsTrigger value="profile" className="text-[10px] uppercase font-bold rounded px-4">
                     {editingProfileId ? "Sửa Profile" : "Tạo Profile"}
                   </TabsTrigger>
                 </TabsList>
               </Tabs>
             </div>
             
             <ScrollArea className="flex-1 p-8">
               {configPanelTab === "button" ? (
                 <div className="max-w-4xl mx-auto space-y-12">
                   <div className="flex items-center justify-between">
                     <div>
                       <h2 className="text-xl font-black uppercase tracking-tighter">
                         {editingButtonId ? "Cập nhật Button" : "Button Builder"}
                       </h2>
                       <p className="text-xs text-muted-foreground">Xây dựng các module xử lý ảnh thông minh.</p>
                     </div>
                     <div className="flex items-center gap-2">
                       {editingButtonId && (
                         <Button variant="ghost" onClick={handleCancelEdit} className="h-9 px-4 rounded-xl font-bold">Hủy</Button>
                       )}
                       <Button onClick={() => void handleSaveButton()} className="h-9 px-6 rounded-xl font-bold">
                         {editingButtonId ? "Lưu thay đổi" : "Lưu Button"}
                       </Button>
                     </div>
                   </div>
                   
                   <div className="grid grid-cols-2 gap-12">
                     <div className="space-y-6">
                        <FieldGroup className="gap-6">
                          <Field>
                            <label className="text-[10px] font-black uppercase text-muted-foreground tracking-widest">Tên Module</label>
                            <Input value={buttonBuilderName} onChange={e => setButtonBuilderName(e.target.value)} placeholder="VD: Thay đổi bầu trời" className="h-10 bg-muted/20 text-sm font-bold" />
                          </Field>
                          <Field>
                            <label className="text-[10px] font-black uppercase text-muted-foreground tracking-widest">Icon</label>
                            <div className="flex gap-4 items-center">
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
                               <div className="flex-1 space-y-1">
                                 <span className="text-xs font-bold text-foreground">Chọn biểu tượng</span>
                                 <p className="text-[10px] text-muted-foreground leading-tight">Biểu tượng này sẽ hiển thị trên nút bấm trong thư viện.</p>
                               </div>
                            </div>
                          </Field>
                          <Field>
                            <label className="text-[10px] font-black uppercase text-muted-foreground tracking-widest">Prompt Gốc (Template)</label>
                            <Textarea value={buttonBuilderPrompt} onChange={e => setButtonBuilderPrompt(e.target.value)} placeholder="Prompt gửi Gemini, dùng {key} để chèn tham số..." className="min-h-[150px] bg-muted/20 font-mono text-xs leading-relaxed" />
                          </Field>
                        </FieldGroup>
                        
                        <div className="p-4 rounded-2xl border border-border/50 bg-muted/10 space-y-4">
                           <div className="flex items-center justify-between gap-3 rounded-xl border border-emerald-500/20 bg-emerald-500/5 px-3 py-2">
                             <div className="flex flex-col gap-0.5">
                               <span className="text-[10px] font-black uppercase text-emerald-700 tracking-wide">Chế độ Gemini</span>
                               <span className="text-[9px] text-muted-foreground">Hệ thống luôn mở chat mới cho mỗi lần chạy.</span>
                             </div>
                             <Badge variant="outline" className="border-emerald-500/30 bg-emerald-500/10 text-emerald-700">Chat mới</Badge>
                           </div>
                           <div className="flex items-center justify-between">
                             <div className="flex flex-col">
                               <span className="text-[10px] font-black uppercase text-foreground/80">Yêu cầu vẽ Mask</span>
                               <span className="text-[9px] text-muted-foreground">User phải bôi vùng ảnh trước khi chạy</span>
                             </div>
                             <Switch checked={builderRequiresMask} onCheckedChange={setBuilderRequiresMask} />
                           </div>
                        </div>
                     </div>

                     <div className="space-y-6">
                        <div className="flex items-center justify-between">
                          <h3 className="text-[10px] font-black uppercase text-muted-foreground tracking-widest">Tham số (Fields)</h3>
                          <Dialog>
                            <DialogTrigger asChild>
                              <Button variant="outline" size="sm" className="h-7 text-[10px] font-bold">
                                <Plus className="size-3 mr-1.5" /> Thêm tham số
                              </Button>
                            </DialogTrigger>
                            <DialogContent className="sm:max-w-lg overflow-hidden flex flex-col max-h-[90vh]">
                               <DialogHeader><DialogTitle className="text-sm font-bold uppercase tracking-tight">Cấu hình Tham số mới</DialogTitle></DialogHeader>
                               <ScrollArea className="flex-1 -mx-6 px-6">
                                 <div className="space-y-6 py-6 pr-1">
                                    <div className="grid grid-cols-2 gap-4">
                                      <Field><label className="text-[10px] font-black uppercase text-muted-foreground tracking-widest">Mã tham số (Key)</label><Input value={newFieldKey} onChange={e => setNewFieldKey(e.target.value)} placeholder="vd: sky_color" className="h-9 bg-muted/20" /></Field>
                                      <Field><label className="text-[10px] font-black uppercase text-muted-foreground tracking-widest">Tên hiển thị (Label)</label><Input value={newFieldLabel} onChange={e => setNewFieldLabel(e.target.value)} placeholder="vd: Màu sắc bầu trời" className="h-9 bg-muted/20" /></Field>
                                    </div>

                                    <Field>
                                      <label className="text-[10px] font-black uppercase text-muted-foreground tracking-widest">Loại input</label>
                                      <Select value={newFieldType} onValueChange={(v: any) => {
                                        setNewFieldType(v);
                                        if (v === 'toggle') setNewFieldDefault(false);
                                        else if (v === 'slider' || v === 'number') setNewFieldDefault(0);
                                        else if (v === 'color') setNewFieldDefault("#FFFFFF");
                                        else setNewFieldDefault("");
                                      }}>
                                        <SelectTrigger className="h-9 bg-muted/20"><SelectValue /></SelectTrigger>
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

                                    {newFieldType === 'select' || newFieldType === 'multi-select' ? (
                                      <Field>
                                        <label className="text-[10px] font-black uppercase text-muted-foreground tracking-widest">Tùy chọn (cách nhau bởi dấu phẩy)</label>
                                        <Input value={newFieldOptions} onChange={e => setNewFieldOptions(e.target.value)} placeholder="vd: Red, Green, Blue" className="h-9 bg-muted/20" />
                                      </Field>
                                    ) : null}

                                    {newFieldType === 'slider' || newFieldType === 'number' ? (
                                      <div className="grid grid-cols-2 gap-4">
                                        <Field><label className="text-[10px] font-black uppercase text-muted-foreground tracking-widest">Min</label><Input type="number" value={newFieldMin ?? ""} onChange={e => setNewFieldMin(e.target.value ? Number(e.target.value) : null)} className="h-9 bg-muted/20" /></Field>
                                        <Field><label className="text-[10px] font-black uppercase text-muted-foreground tracking-widest">Max</label><Input type="number" value={newFieldMax ?? ""} onChange={e => setNewFieldMax(e.target.value ? Number(e.target.value) : null)} className="h-9 bg-muted/20" /></Field>
                                      </div>
                                    ) : null}

                                    <div className="grid grid-cols-2 gap-4 pt-2 border-t border-border/50">
                                      <div className="flex items-center justify-between px-3 py-2 rounded-xl bg-muted/10 border border-border/50">
                                        <span className="text-[10px] font-black uppercase text-foreground/80">Bắt buộc nhập</span>
                                        <Switch checked={newFieldRequired} onCheckedChange={setNewFieldRequired} />
                                      </div>
                                      <Field>
                                        <Input value={newFieldVisibleIf} onChange={e => setNewFieldVisibleIf(e.target.value)} placeholder="Hiện nếu key này có giá trị..." className="h-9 bg-muted/20 text-[10px]" />
                                      </Field>
                                    </div>
                                 </div>
                               </ScrollArea>
                               <DialogFooter className="pt-4 border-t border-border/50">
                                 <Button 
                                   className="w-full h-10 rounded-xl font-bold"
                                   onClick={() => {
                                     const options = newFieldOptions.split(',').map(s => s.trim()).filter(Boolean);
                                     setBuilderFields([...builderFields, { 
                                       key: newFieldKey, 
                                       label: newFieldLabel, 
                                       type: newFieldType, 
                                       value: newFieldDefault,
                                       options: options.length ? options : undefined,
                                       min: newFieldMin,
                                       max: newFieldMax,
                                       required: newFieldRequired,
                                       visibleIf: newFieldVisibleIf || undefined,
                                       tooltip: "" 
                                     }]);
                                     setNewFieldKey(""); setNewFieldLabel(""); setNewFieldOptions("");
                                     setNewFieldMin(null); setNewFieldMax(null); setNewFieldRequired(false);
                                     setNewFieldVisibleIf("");
                                  }}>Thêm tham số vào Button</Button>
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
                                       <span className="text-[11px] font-bold text-foreground">{f.label}</span>
                                       {f.required && <Badge variant="outline" className="h-4 px-1 text-[8px] border-destructive/30 text-destructive bg-destructive/5">Required</Badge>}
                                     </div>
                                     <div className="flex items-center gap-2 text-[9px] text-muted-foreground font-mono">
                                       <span className="bg-muted px-1.5 py-0.5 rounded text-[8px]">{"{"}{f.key}{"}"}</span>
                                       <span>•</span>
                                       <span className="capitalize">{f.type}</span>
                                       {f.min !== null && <span>• Min: {f.min}</span>}
                                       {f.max !== null && <span>• Max: {f.max}</span>}
                                     </div>
                                   </div>
                                   <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                                     <Button variant="ghost" size="icon" className="h-8 w-8 text-muted-foreground hover:text-primary" onClick={() => {
                                        // TODO: Implement field editing
                                        setNewFieldKey(f.key);
                                        setNewFieldLabel(f.label);
                                        setNewFieldType(f.type);
                                        setNewFieldDefault(f.value);
                                        setNewFieldOptions(f.options?.join(", ") || "");
                                        setNewFieldMin(f.min ?? null);
                                        setNewFieldMax(f.max ?? null);
                                        setNewFieldRequired(f.required || false);
                                        setNewFieldVisibleIf(typeof f.visibleIf === 'string' ? f.visibleIf : "");
                                        setBuilderFields(builderFields.filter((_, idx) => idx !== i));
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
                 <div className="max-w-md mx-auto space-y-8 py-12">
                   <div className="text-center relative">
                     <h2 className="text-xl font-black uppercase tracking-tighter">
                       {editingProfileId ? "Cập nhật Profile" : "Profile Creator"}
                     </h2>
                     <p className="text-xs text-muted-foreground">Lưu trạng thái hiện tại của Effect Control thành profile.</p>
                     {editingProfileId && (
                       <Button variant="ghost" size="sm" onClick={handleCancelEdit} className="absolute top-0 right-0 h-8 px-3 rounded-lg font-bold">Hủy</Button>
                     )}
                   </div>
                   
                   <FieldGroup className="gap-6">
                       <Field>
                         <label className="text-[10px] font-black uppercase text-muted-foreground">Tên Profile</label>
                         <Input 
                            value={profileName} 
                            onChange={e => setProfileName(e.target.value)}
                            placeholder="VD: Cinematic Summer Look" className="h-10 bg-muted/20 font-bold" 
                          />
                       </Field>
                        <div className="flex gap-4">
                          <Field className="flex-1">
                            <label className="text-[10px] font-black uppercase text-muted-foreground">Icon</label>
                            <div className="flex gap-4 items-center">
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
                               <div className="flex-1 space-y-1">
                                 <span className="text-xs font-bold text-foreground">Chọn biểu tượng</span>
                                 <p className="text-[10px] text-muted-foreground leading-tight">Biểu tượng cho Profile này.</p>
                               </div>
                            </div>
                          </Field>
                         <Field className="flex-[2]">
                           <label className="text-[10px] font-black uppercase text-muted-foreground">Mô tả ngắn</label>
                           <Input value={profileDesc} onChange={e => setProfileDesc(e.target.value)} placeholder="Tóm tắt công dụng..." className="h-10 bg-muted/20" />
                         </Field>
                       </div>
                       
                        <div className="space-y-3">
                          <label className="text-[10px] font-black uppercase text-muted-foreground">Trạng thái Effect Control</label>
                          <div className="p-2 rounded-2xl border border-border/50 bg-muted/5 min-h-[100px] flex flex-col gap-2">
                             {activeEffects.map(eff => {
                               const b = buttons.find(btn => btn.id === eff.buttonId);
                               return (
                                 <div key={eff.id} className="flex items-center gap-3 p-2 bg-background border border-border/50 rounded-xl">
                                    <div className="size-6 flex items-center justify-center rounded bg-primary/10 text-[10px]">{b?.icon}</div>
                                    <span className="text-[11px] font-bold flex-1">{b?.name}</span>
                                 </div>
                               )
                             })}
                             {activeEffects.length === 0 && <div className="text-center py-8 text-muted-foreground/30 text-[10px]">Kéo/Thêm button vào Effect Control trước.</div>}
                          </div>
                        </div>
                       
                       <Button 
                        onClick={() => void handleSaveProfile()}
                        className="w-full h-11 rounded-2xl font-black uppercase tracking-widest shadow-xl shadow-primary/20" 
                        disabled={activeEffects.length === 0 || submitting}
                       >
                         {submitting ? <Loader2 className="size-4 animate-spin mr-2" /> : <Save className="size-4 mr-2" />}
                         {editingProfileId ? "Lưu thay đổi" : "Lưu Profile Preset"}
                       </Button>
                   </FieldGroup>
                 </div>
               )}
             </ScrollArea>
          </Card>
        ) : (
          <>
            {/* -------------------- CANVAS AREA -------------------- */}
            <Card className="flex-1 border-border/70 shadow-xl bg-black/40 overflow-hidden relative group backdrop-blur-sm">
              <div className="absolute inset-0 flex items-center justify-center pointer-events-none opacity-20">
                 <Layers className="size-32 text-primary" />
              </div>
              {activeProject ? (
                <div className="h-full flex flex-col">
                    <div className="flex-1 relative">
                      <MaskCanvas 
                        imageUrl={selectedImageUrl}
                        onMaskChange={setMaskBase64}
                        onGuideChange={setCanvasGuide}
                        keepViewState={false}
                      />
                    </div>
                </div>
              ) : (
                <div className="h-full flex flex-col items-center justify-center text-center p-12">
                   <div className="size-24 rounded-full bg-primary/10 flex items-center justify-center mb-6 animate-pulse">
                     <Layers className="size-12 text-primary" />
                   </div>
                   <h3 className="text-xl font-black uppercase tracking-tighter mb-2">Editor Canvas</h3>
                   <p className="text-muted-foreground text-sm max-w-xs mx-auto mb-8">
                     Kéo thả ảnh vào đây hoặc dán từ clipboard để bắt đầu dự án thumbnail mới.
                   </p>
                   <div className="flex gap-4">
                     <Button onClick={() => void handlePasteFromClipboard()} className="rounded-xl px-6 h-10 font-bold">
                        <Plus className="size-4 mr-2" /> Dán từ Clipboard
                     </Button>
                     <input type="file" id="imageInput" accept="image/*" className="hidden" onChange={e => { if (e.target.files?.[0]) void processImageFile(e.target.files[0]); }} />
                     <Button variant="outline" onClick={() => document.getElementById('imageInput')?.click()} className="rounded-xl px-6 h-10 font-bold border-border/70">
                        Chọn file ảnh
                     </Button>
                   </div>
                </div>
              )}
            </Card>

            {/* -------------------- CENTER COLUMN: HISTORY (CAROUSEL) -------------------- */}
            {activeProject && (
              <Card className="h-40 border-border/70 shadow-sm overflow-hidden flex flex-col bg-background/40 backdrop-blur-md">
                {/* Carousel header */}
                <div className="flex items-center justify-between px-3 pt-2 pb-1 border-b border-border/30">
                  <span className="text-[9px] font-black uppercase tracking-widest text-muted-foreground">Lịch sử · {versions.length} phiên bản</span>
                  {versions.filter(v => v.outputImagePath).length >= 2 && (
                    <Button
                      variant="ghost"
                      size="xs"
                      className="h-5 text-[8px] gap-1 hover:bg-primary/10 hover:text-primary"
                      onClick={() => setGalleryPreviewVersionId(versions.filter(v => v.outputImagePath)[0]?.id ?? null)}
                    >
                      <SplitSquareVertical className="w-3 h-3" />
                      Xem tất cả
                    </Button>
                  )}
                </div>
                <ScrollArea className="flex-1 w-full">
                  <div className="flex flex-row p-2 gap-2 min-w-max">
                    {reversedVersions.map((v, idx) => (
                      <div
                        key={v.id}
                        onClick={() => void handleSelectVersion(v.id)}
                        className={cn(
                          "w-52 group relative flex gap-2.5 p-2 rounded-xl border transition-all text-left shrink-0 cursor-pointer",
                          selectedVersion?.id === v.id 
                            ? "border-primary bg-primary/10 ring-1 ring-primary/30 shadow-md shadow-primary/5" 
                            : "border-border/50 hover:border-primary/20 hover:bg-muted/30"
                        )}
                      >
                        {/* Thumbnail */}
                        <div className="size-14 rounded-lg bg-black/20 border border-border/20 overflow-hidden shrink-0 relative">
                          {v.outputImagePath && <img src={getThumbnailAssetUrl(v.outputImagePath)} alt={v.id} className="size-full object-cover group-hover:scale-105 transition-transform duration-500" />}
                          {/* Eye preview button */}
                          {v.outputImagePath && (
                            <button
                              onClick={(e) => { e.stopPropagation(); setGalleryPreviewVersionId(v.id); }}
                              className="absolute inset-0 bg-black/50 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center"
                            >
                              <svg className="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" /><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" /></svg>
                            </button>
                          )}
                        </div>
                        
                        {/* Details */}
                        <div className="min-w-0 flex-1 pt-0.5">
                          <div className="flex items-center justify-between mb-0.5">
                             <span className="text-[9px] font-black text-primary/70 uppercase">v{versions.length - 1 - idx}</span>
                             <span className="text-[8px] text-muted-foreground font-medium bg-muted/50 px-1.5 rounded-full">{v.createdAt.split(' ')[1]}</span>
                          </div>
                          <div className="text-[10px] font-bold truncate text-foreground/90">{v.buttonName}</div>
                          <div className="text-[9px] text-muted-foreground line-clamp-2 mt-1 italic leading-tight">
                            {getHistoryCopy(v)}
                          </div>
                        </div>
    
                        {/* Delete Action */}
                        <div className="absolute top-1.5 right-1.5 flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                          {v.status === "branch" && <div className="size-1.5 rounded-full bg-amber-500 ring-2 ring-background shadow-sm" />}
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
                  <ScrollBar orientation="horizontal" />
            </ScrollArea>
          </Card>
        )}

        {/* -------------------- GALLERY PREVIEW OVERLAY -------------------- */}
        {galleryPreviewVersionId !== null && activeProject && (() => {
          const currentGalleryIdx = versionImages.findIndex(v => v.id === galleryPreviewVersionId);
          const currentGalleryVersion = versionImages[currentGalleryIdx];
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
            <div className="fixed inset-0 z-50 bg-black/95 backdrop-blur-md flex flex-col" onClick={() => setGalleryPreviewVersionId(null)}>
              {/* Header */}
              <div className="flex items-center justify-between px-6 py-4 border-b border-white/10 shrink-0" onClick={e => e.stopPropagation()}>
                <div className="flex items-center gap-3">
                  <SplitSquareVertical className="size-5 text-primary" />
                  <span className="text-sm font-black uppercase tracking-widest text-white">Gallery · {activeProject.name}</span>
                  <Badge variant="outline" className="text-[9px] border-white/20 text-white/50">{versionImages.length} ảnh</Badge>
                </div>
                <div className="flex items-center gap-2">
                  {canCompare && (
                    <Button
                      size="sm"
                      className="h-7 text-[10px] gap-1.5 bg-primary hover:bg-primary/90"
                      onClick={() => { setShowComparator(true); setGalleryPreviewVersionId(null); }}
                    >
                      <SplitSquareVertical className="size-3" />
                      So sánh A vs B
                    </Button>
                  )}
                  {(compareVersionAId || compareVersionBId) && (
                    <Button variant="ghost" size="sm" className="h-7 text-[10px] text-white/40 hover:text-white" onClick={() => { setCompareVersionAId(null); setCompareVersionBId(null); }}>
                      Xóa chọn
                    </Button>
                  )}
                  <Button variant="ghost" size="icon" className="text-white/60 hover:text-white hover:bg-white/10 rounded-full" onClick={() => setGalleryPreviewVersionId(null)}>
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
                  className="h-10 w-10 rounded-full bg-white/10 hover:bg-white/20 text-white shrink-0"
                  disabled={currentGalleryIdx <= 0}
                  onClick={() => currentGalleryIdx > 0 && setGalleryPreviewVersionId(versionImages[currentGalleryIdx - 1].id)}
                >
                  <ChevronDown className="size-5 rotate-90" />
                </Button>

                {/* Current image */}
                {currentGalleryVersion && (
                  <div className="flex-1 max-w-4xl h-full flex flex-col gap-3 min-h-0">
                    {/* A/B slot badge on main image */}
                    <div className="relative flex-1 rounded-2xl overflow-hidden border border-white/10 shadow-2xl min-h-0 flex items-center justify-center bg-black/40">
                      <img
                        src={getThumbnailAssetUrl(currentGalleryVersion.outputImagePath)}
                        alt={currentGalleryVersion.buttonName}
                        className="max-h-full max-w-full object-contain"
                      />
                      {getSlot(currentGalleryVersion.id) && (
                        <div className={cn(
                          "absolute top-3 left-3 px-3 py-1 rounded-full text-xs font-black uppercase shadow-lg",
                          getSlot(currentGalleryVersion.id) === "A"
                            ? "bg-blue-500 text-white"
                            : "bg-rose-500 text-white"
                        )}>
                          {getSlot(currentGalleryVersion.id)}
                        </div>
                      )}
                    </div>
                    <div className="flex items-center justify-between">
                      <div className="text-white/60 text-xs font-bold">
                        <span className="text-white">{currentGalleryVersion.buttonName}</span>
                        {currentGalleryVersion.note && <span className="ml-2 text-emerald-400">{currentGalleryVersion.note}</span>}
                      </div>
                      <div className="flex items-center gap-2">
                        {/* Pick A / Pick B button */}
                        <Button
                          variant="outline"
                          size="sm"
                          className={cn(
                            "h-7 text-[10px] font-bold",
                            getSlot(currentGalleryVersion.id) === "A" ? "border-blue-500 text-blue-400 hover:bg-blue-500/10" :
                            getSlot(currentGalleryVersion.id) === "B" ? "border-rose-500 text-rose-400 hover:bg-rose-500/10" :
                            "border-white/20 text-white/70 hover:bg-white/10"
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
                          className="h-7 text-[10px] border-white/20 text-white hover:bg-white/10"
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
                  className="h-10 w-10 rounded-full bg-white/10 hover:bg-white/20 text-white shrink-0"
                  disabled={currentGalleryIdx >= versionImages.length - 1}
                  onClick={() => currentGalleryIdx < versionImages.length - 1 && setGalleryPreviewVersionId(versionImages[currentGalleryIdx + 1].id)}
                >
                  <ChevronDown className="size-5 -rotate-90" />
                </Button>
              </div>

              {/* Thumbnail strip with A/B labels */}
              <div className="shrink-0 border-t border-white/10 p-4" onClick={e => e.stopPropagation()}>
                <p className="text-[9px] text-white/30 font-bold uppercase mb-2">Chọn A và B để so sánh · click thumbnail để chọn</p>
                <div className="flex gap-2 overflow-x-auto pb-1">
                  {versionImages.map((v) => {
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
                          : "border-white/10 hover:border-white/30 opacity-60 hover:opacity-100"
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

      {/* -------------------- RIGHT COLUMN: EFFECT CONTROL -------------------- */}
      <aside className="flex flex-col min-h-0">
        <Card className="flex flex-col h-full border-border/70 shadow-sm overflow-hidden bg-background/50 backdrop-blur-md">
          <div className="px-5 py-4 border-b border-border/50 bg-muted/20 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Sliders className="size-4 text-primary" />
              <h2 className="text-[10px] font-black uppercase tracking-widest">Effect Control</h2>
            </div>
            <div className="flex items-center gap-2">
              {activeEffects.length > 0 && (
                <Button 
                  variant="ghost" size="xs" className="h-7 text-[10px] gap-1 hover:bg-primary/10 hover:text-primary"
                  onClick={handleSaveProfile}
                  disabled={submitting}
                >
                  <Save className="w-3 h-3" />
                  Lưu Profile
                </Button>
              )}
              {activeEffects.length > 0 && (
                <Button variant="ghost" size="icon" className="h-7 w-7 text-muted-foreground hover:text-destructive" onClick={() => setActiveEffects([])}>
                  <X className="w-3.5 h-3.5" />
                </Button>
              )}
            </div>
          </div>
          
          <ScrollArea 
            className="flex-1"
            onDragOver={(e) => {
              e.preventDefault();
              e.dataTransfer.dropEffect = "copy";
            }}
            onDrop={(e) => {
              const buttonId = e.dataTransfer.getData("buttonId");
              if (buttonId) {
                const b = buttons.find(btn => btn.id === buttonId);
                if (b) {
                  const newEffect = buildEffectFromButton(b);
                  setActiveEffects(prev => [...prev, newEffect]);
                  toast.success(`Đã thêm ${b.name}`);
                }
              }
            }}
          >
             <div className="p-4 space-y-4">
                {activeEffects.map((eff) => {
                  const b = buttons.find(btn => btn.id === eff.buttonId);
                  if (!b) return null;
                  
                  return (
                    <div key={eff.id} className="rounded-2xl border border-border/50 bg-card/50 overflow-hidden shadow-sm">
                      <div className="px-4 py-2 bg-muted/30 border-b border-border/30 flex items-center justify-between">
                        <div className="flex items-center gap-2 flex-1 cursor-pointer select-none" onClick={() => toggleEffectCollapse(eff.id)}>
                          <div className="size-5 flex items-center justify-center rounded bg-primary/10 text-[10px]">{b.icon}</div>
                          <span className="text-[10px] font-black text-primary/80 uppercase">{b.name}</span>
                          {collapsedEffects.has(eff.id) ? <ChevronDown className="size-3 text-muted-foreground" /> : <ChevronUp className="size-3 text-muted-foreground" />}
                        </div>
                        <Button variant="ghost" size="icon" className="h-5 w-5 text-muted-foreground hover:text-destructive" onClick={() => setActiveEffects(activeEffects.filter(e => e.id !== eff.id))}>
                          <Trash2 className="size-3" />
                        </Button>
                      </div>
                      {!collapsedEffects.has(eff.id) && (
                        <div className="p-4 space-y-4">
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
                     <p className="text-[10px] font-medium text-muted-foreground max-w-[150px]">Kéo hoặc thêm button từ thư viện để bắt đầu hiệu chỉnh.</p>
                  </div>
                )}
             </div>
          </ScrollArea>
          
          {activeEffects.length > 0 && (
            <div className="p-4 border-t border-border/50 bg-muted/10 space-y-3">
               <div className="flex items-center justify-between px-1">
                  <div className="flex items-center gap-2">
                    <span className="text-[9px] font-black uppercase text-muted-foreground">Chế độ:</span>
                    <Badge variant="outline" className="h-5 border-emerald-500/30 bg-emerald-500/10 text-[9px] font-bold text-emerald-700">Chat mới</Badge>
                  </div>
                  {submitting && <Badge variant="outline" className="h-4 text-[8px] animate-pulse">Processing</Badge>}
               </div>
               <Button onClick={() => void handleRun()} disabled={submitting} className="w-full h-11 rounded-2xl font-black uppercase tracking-widest shadow-xl shadow-primary/20">
                 {submitting ? <Loader2 className="size-4 animate-spin mr-2" /> : <Play className="size-4 mr-2" />}
                 Run Studio
               </Button>
            </div>
          )}
        </Card>
      </aside>
    </div>
  </div>
);
}
