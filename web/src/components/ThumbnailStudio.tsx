import { useEffect, useState, useTransition, useMemo } from "react";
import {
  Download, History, Loader2,
  Palette, Play, Plus, Search,
  CheckCircle2, Circle, Clock, MessageSquare,
  Layers, Maximize2, Trash2, Settings2,
  Type, List, Sliders, ToggleLeft, Hash,
  MessageCircle, MessagesSquare, Check, Sparkles,
  Zap
} from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Field, FieldGroup } from "@/components/ui/field";
import { TooltipFieldLabel } from "@/components/ui/tooltip-field-label";

import {
  chooseFolder,
  createThumbnailButton,
  createThumbnailProject,
  exportThumbnailImage,
  getThumbnailAssetUrl,
  getThumbnailBootstrap,
  openFolder,
  runThumbnailGeneration,
  runThumbnailProfile,
  selectThumbnailProject,
  selectThumbnailVersion,
  type ThumbnailBootstrapPayload,
  type ThumbnailButtonField,
  type ThumbnailProjectDetail,
} from "@/lib/api";
import MaskCanvas from "./MaskCanvas";
import VersionComparator from "./VersionComparator";

import { cn } from "@/lib/utils";

function fieldValueMap(fields: ThumbnailButtonField[]) {
  return Object.fromEntries(fields.map((field) => [field.key, field.value])) as Record<string, string | number | boolean | string[]>;
}

function getErrorMessage(error: unknown) {
  return error instanceof Error ? error.message : "Yêu cầu thất bại.";
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

type LeftPanelTab = "tools" | "profiles" | "projects" | "export";
type MainPanelTab = "editor" | "builder";

export default function ThumbnailStudio() {
  const [bootLoading, setBootLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [bootstrap, setBootstrap] = useState<ThumbnailBootstrapPayload | null>(null);
  const [activeProject, setActiveProject] = useState<ThumbnailProjectDetail | null>(null);
  const [maskBase64, setMaskBase64] = useState<string | null>(null);
  const [showComparator, setShowComparator] = useState(false);

  const [selectedMode] = useState<"preset" | "custom" | "mask">("preset");
  const [selectedButtonId, setSelectedButtonId] = useState("");
  const [regenerateMode, setRegenerateMode] = useState<"same-chat" | "new-chat">("new-chat");
  
  const [leftPanelTab, setLeftPanelTab] = useState<LeftPanelTab>("tools");
  const [mainPanelTab, setMainPanelTab] = useState<MainPanelTab>("editor");

  // Button Builder State
  const [buttonBuilderName, setButtonBuilderName] = useState("");
  const [buttonBuilderCategory, setButtonBuilderCategory] = useState("Custom");
  const [buttonBuilderPrompt, setButtonBuilderPrompt] = useState("");
  const [builderRequiresMask, setBuilderRequiresMask] = useState(false);
  const [builderCreateNewChat, setBuilderCreateNewChat] = useState(true);
  const [builderAllowRegenerate, setBuilderAllowRegenerate] = useState(true);
  const [builderFields, setBuilderFields] = useState<ThumbnailButtonField[]>([]);
  
  // Builder: New Field State
  const [newFieldKey, setNewFieldKey] = useState("");
  const [newFieldLabel, setNewFieldLabel] = useState("");
  const [newFieldType, setNewFieldType] = useState<ThumbnailButtonField["type"]>("text");
  const [newFieldOptions, setNewFieldOptions] = useState("");
  const [newFieldMin, setNewFieldMin] = useState(0);
  const [newFieldMax, setNewFieldMax] = useState(10);
  const [newFieldVisibleIf, setNewFieldVisibleIf] = useState("");

  // Export State
  const [exportSize, setExportSize] = useState("original");
  const [exportFormat, setExportFormat] = useState("PNG");
  const [exportFolder, setExportFolder] = useState("");
  const [exportName, setExportName] = useState("thumbnail_final");

  const [, startTransition] = useTransition();

  useEffect(() => {
    void (async () => {
      setBootLoading(true);
      try {
        const payload = await getThumbnailBootstrap();
        startTransition(() => {
          setBootstrap(payload);
          setActiveProject(payload.activeProject);
          const firstButton = payload.buttons[0];
          if (firstButton) {
            setSelectedButtonId(firstButton.id);
          }
        });
      } catch (error) {
        toast.error(getErrorMessage(error));
      } finally {
        setBootLoading(false);
      }
    })();
  }, []);

  const buttons = bootstrap?.buttons ?? [];
  const profiles = useMemo(() => {
    return (bootstrap?.profiles ?? []).map(p => ({
      ...p,
      // Ensure compatibility between button_ids (Python) and buttonIds (TS)
      buttonIds: (p as any).button_ids || (p as any).buttonIds || []
    }));
  }, [bootstrap]);

  const versions = activeProject?.versions ?? [];
  const selectedVersion = activeProject?.currentVersion ?? versions[versions.length - 1] ?? null;
  const selectedButton = useMemo(() => 
    buttons.find((button) => button.id === selectedButtonId) ?? buttons[0] ?? null,
    [buttons, selectedButtonId]
  );

  const previewPrompt = useMemo(() => {
    if (!selectedButton) return "";
    let p = selectedButton.promptTemplate;
    selectedButton.fields.forEach(f => {
      let val = f.value ?? "";
      if (Array.isArray(val)) val = val.join(", ");
      p = p.replace(new RegExp(`\\{${f.key}\\}`, "g"), String(val));
    });
    return p;
  }, [selectedButton]);

  const beforeVersion = useMemo(() => {
    if (!activeProject || !selectedVersion) return null;
    if (selectedVersion.parentVersionId) {
      return activeProject.versions.find(v => v.id === selectedVersion.parentVersionId) || activeProject.versions[0];
    }
    return activeProject.versions[0];
  }, [activeProject, selectedVersion]);

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

  function handleFieldChange(key: string, nextValue: any) {
    if (!selectedButton) return;
    const nextFields = selectedButton.fields.map((field) => 
      field.key === key ? { ...field, value: nextValue } : field
    );
    setBootstrap((current) =>
      current ? { ...current, buttons: current.buttons.map((b) => (b.id === selectedButton.id ? { ...b, fields: nextFields } : b)) } : current
    );
  }

  function handleMultiSelectToggle(fieldKey: string, option: string) {
    if (!selectedButton) return;
    const field = selectedButton.fields.find(f => f.key === fieldKey);
    if (!field) return;
    
    const currentValues = Array.isArray(field.value) ? field.value : [];
    const nextValues = currentValues.includes(option)
      ? currentValues.filter(v => v !== option)
      : [...currentValues, option];
    
    handleFieldChange(fieldKey, nextValues);
  }

  useEffect(() => {
    function handlePaste(event: ClipboardEvent) {
      if (activeProject) return;
      const items = event.clipboardData?.items;
      if (!items) return;

      for (const item of items) {
        if (item.type.startsWith("image/")) {
          const file = item.getAsFile();
          if (!file) continue;

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
              syncProject(project);
              toast.success("Đã tạo dự án từ clipboard.");
            } catch (error) {
              toast.error(getErrorMessage(error));
            } finally {
              setSubmitting(false);
            }
          };
          reader.readAsDataURL(file);
          break;
        }
      }
    }

    document.addEventListener("paste", handlePaste);
    return () => document.removeEventListener("paste", handlePaste);
  }, [activeProject]);

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
        syncProject(project);
        toast.success("Đã tạo dự án thành công.");
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

  const handlePickImage = async () => {
    try {
      const input = document.createElement("input");
      input.type = "file";
      input.accept = "image/*";
      input.onchange = async (e) => {
        const file = (e.target as HTMLInputElement).files?.[0];
        if (file) await processImageFile(file);
      };
      input.click();
    } catch (error) {
      toast.error(getErrorMessage(error));
    }
  };

  function handleAddField() {
    if (!newFieldKey || !newFieldLabel) return toast.error("Vui lòng nhập Key và Label cho field.");
    const options = newFieldOptions.split(",").map(s => s.trim()).filter(s => !!s);
    
    const field: ThumbnailButtonField = {
      key: newFieldKey,
      label: newFieldLabel,
      type: newFieldType,
      value: (newFieldType === 'toggle' ? false : newFieldType === 'number' || newFieldType === 'slider' ? 0 : newFieldType === 'multi-select' ? [] : ""),
      tooltip: "",
      options: options.length ? options : undefined,
      min: newFieldType === 'slider' || newFieldType === 'number' ? newFieldMin : undefined,
      max: newFieldType === 'slider' || newFieldType === 'number' ? newFieldMax : undefined,
      visibleIf: newFieldVisibleIf || undefined,
    };

    setBuilderFields([...builderFields, field]);
    setNewFieldKey("");
    setNewFieldLabel("");
    setNewFieldOptions("");
    setNewFieldVisibleIf("");
  }

  async function handleCreateButton() {
    if (!buttonBuilderName || !buttonBuilderPrompt) return toast.error("Vui lòng nhập tên và mẫu prompt.");
    setSubmitting(true);
    try {
      const button = await createThumbnailButton({
        name: buttonBuilderName,
        icon: "✨",
        category: buttonBuilderCategory,
        promptTemplate: buttonBuilderPrompt,
        requiresMask: builderRequiresMask,
        createNewChat: builderCreateNewChat,
        allowRegenerate: builderAllowRegenerate,
        fields: builderFields,
      });
      startTransition(() => {
        setBootstrap((current) =>
          current ? { ...current, buttons: [...current.buttons.filter((item) => item.id !== button.id), button] } : current,
        );
        setSelectedButtonId(button.id);
        setMainPanelTab("editor");
        setLeftPanelTab("tools");
        setBuilderFields([]);
        setButtonBuilderName("");
        setButtonBuilderPrompt("");
      });
      toast.success("Đã lưu hành động mới.");
    } catch (error) {
      toast.error(getErrorMessage(error));
    } finally {
      setSubmitting(false);
    }
  }

  async function handleSelectProject(projectId: string) {
    try {
      const project = await selectThumbnailProject(projectId);
      syncProject(project);
    } catch (error) {
      toast.error(getErrorMessage(error));
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

  async function handleRun(isRegenerate: boolean) {
    if (!activeProject || !selectedButton) return toast.error("Hãy tạo dự án và chọn hành động trước.");
    setSubmitting(true);
    try {
      const project = await runThumbnailGeneration({
        projectId: activeProject.id,
        buttonId: selectedButton.id,
        fieldValues: fieldValueMap(selectedButton.fields),
        selectedMode,
        regenerateMode,
        maskMode: selectedMode === "mask" ? "red" : selectedButton.requiresMask ? "selected" : "none",
        isRegenerate,
        maskBase64: maskBase64 || undefined,
      });
      syncProject(project);
      toast.success(isRegenerate ? "Đã tạo nhánh chỉnh sửa mới." : "Gemini đã trả về phiên bản mới.");
    } catch (error) {
      toast.error(getErrorMessage(error));
    } finally {
      setSubmitting(false);
    }
  }

  async function handleRunProfile(profileId: string) {
    if (!activeProject) return toast.error("Hãy tạo dự án trước.");
    setSubmitting(true);
    try {
      const project = await runThumbnailProfile({
        projectId: activeProject.id,
        profileId: profileId,
        maskBase64: maskBase64 || undefined,
      });
      syncProject(project);
      toast.success("Đã chạy Profile thành công.");
    } catch (error) {
      toast.error(getErrorMessage(error));
    } finally {
      setSubmitting(false);
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
        format: exportFormat,
        size: exportSize,
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
    <div className={cn("grid lg:grid-cols-[20rem_minmax(0,1fr)_18rem] h-[calc(100vh-7rem)]", "gap-4")}>
      
      {/* BEFORE/AFTER COMPARATOR OVERLAY */}
      {showComparator && beforeVersion && selectedVersion && (
        <VersionComparator
          beforeUrl={getThumbnailAssetUrl(beforeVersion.outputImagePath)}
          afterUrl={getThumbnailAssetUrl(selectedVersion.outputImagePath)}
          beforeLabel={beforeVersion.buttonName || "Gốc"}
          afterLabel={selectedVersion.buttonName || "Kết quả"}
          onClose={() => setShowComparator(false)}
        />
      )}

      {/* -------------------- LEFT COLUMN: BUTTON LIBRARY -------------------- */}
      <aside className="flex flex-col min-h-0">
        <Card className="flex flex-col h-full border-border/70 shadow-sm overflow-hidden">
          <div className="px-4 py-3 border-b border-border/50 flex items-center justify-between">
            <h2 className="text-sm font-bold uppercase tracking-tight">Thư viện Button</h2>
            <Button variant="ghost" size="icon" className="h-6 w-6" onClick={() => setMainPanelTab("builder")}>
              <Plus className="h-4 w-4" />
            </Button>
          </div>
          
          <div className="p-3 border-b border-border/50">
            <div className="relative">
              <Input placeholder="Tìm kiếm button..." className="h-8 pl-8 text-xs bg-muted/20 border-border/70 rounded-full" />
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 size-3.5 text-muted-foreground" />
            </div>
          </div>

          <ScrollArea className="flex-1">
            <Tabs value={leftPanelTab} onValueChange={(v) => setLeftPanelTab(v as LeftPanelTab)} className="w-full">
              <div className="px-3 py-2">
                <TabsList className="w-full h-8 bg-muted/30">
                  <TabsTrigger value="tools" className="flex-1 text-[10px] uppercase font-bold">Công cụ</TabsTrigger>
                  <TabsTrigger value="profiles" className="flex-1 text-[10px] uppercase font-bold">Profiles</TabsTrigger>
                  <TabsTrigger value="projects" className="flex-1 text-[10px] uppercase font-bold">Dự án</TabsTrigger>
                  <TabsTrigger value="export" className="flex-1 text-[10px] uppercase font-bold">Xuất</TabsTrigger>
                </TabsList>
              </div>

              <TabsContent value="tools" className="m-0 p-3 space-y-6">
                {["Cleanup", "Color", "Face / Expression", "Camera / Composition", "Extend / Resize", "General", "Custom"].map(cat => {
                  const catButtons = buttons.filter(b => b.category === cat);
                  if (!catButtons.length) return null;
                  return (
                    <div key={cat} className="space-y-2">
                      <div className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground/70">{cat}</div>
                      <div className="grid grid-cols-1 gap-1.5">
                        {catButtons.map(button => (
                          <button
                            key={button.id}
                            onClick={() => { setSelectedButtonId(button.id); setMainPanelTab("editor"); }}
                            className={cn(
                              "flex items-center gap-3 rounded-lg border p-2 transition-all text-left",
                              selectedButtonId === button.id
                                ? "border-primary/50 bg-primary/5 ring-1 ring-primary/20"
                                : "border-transparent hover:bg-muted/50"
                            )}
                          >
                            <div className="flex-none flex size-8 items-center justify-center rounded-md bg-background border border-border/50 text-base shadow-sm">
                              {button.icon}
                            </div>
                            <div className="min-w-0 flex-1">
                              <div className="text-[11px] font-semibold leading-tight truncate">{button.name}</div>
                              {button.summary && <div className="text-[9px] text-muted-foreground truncate">{button.summary}</div>}
                            </div>
                          </button>
                        ))}
                      </div>
                    </div>
                  );
                })}
              </TabsContent>

              <TabsContent value="profiles" className="m-0 p-3 space-y-3">
                 {profiles.map(profile => (
                   <div key={profile.id} className="group relative flex flex-col p-3 rounded-xl border border-border/70 bg-card hover:bg-muted/50 transition-all">
                     <div className="flex items-center gap-3">
                       <div className="size-10 rounded-lg bg-primary/10 text-primary flex items-center justify-center text-lg shadow-inner">
                         {profile.icon}
                       </div>
                       <div className="flex-1 min-w-0">
                         <div className="text-[11px] font-bold truncate">{profile.name}</div>
                         <div className="text-[9px] text-muted-foreground line-clamp-1">{profile.description}</div>
                       </div>
                       <Button 
                        size="icon" 
                        variant="secondary" 
                        className="h-8 w-8 rounded-full shadow-sm"
                        disabled={submitting || !activeProject}
                        onClick={() => void handleRunProfile(profile.id)}
                       >
                         {submitting ? <Loader2 className="size-3 animate-spin" /> : <Zap className="size-3 text-primary fill-primary/20" />}
                       </Button>
                     </div>
                      <div className="mt-3 flex flex-wrap gap-1">
                        {profile.buttonIds?.map((b_id: string) => {
                          const b = buttons.find(btn => btn.id === b_id);
                          return b ? (
                            <Badge key={b_id} variant="outline" className="text-[8px] h-4 py-0 bg-muted/30 border-border/50">
                              {b.name}
                            </Badge>
                          ) : null;
                        })}
                     </div>
                   </div>
                 ))}
              </TabsContent>

              <TabsContent value="projects" className="m-0 p-3">
                <div className="space-y-2">
                  {bootstrap?.projects.map(p => (
                    <button 
                      key={p.id} 
                      onClick={() => void handleSelectProject(p.id)} 
                      className={cn(
                        "w-full flex flex-col p-3 rounded-lg border transition-all text-left",
                        activeProject?.id === p.id ? "border-primary bg-primary/5" : "border-border/70 bg-card hover:bg-muted/50"
                      )}
                    >
                      <div className="text-xs font-semibold">{p.name}</div>
                      <div className="text-[10px] text-muted-foreground mt-1 flex items-center gap-2">
                        <Clock className="size-3" /> {new Date(p.updatedAt).toLocaleDateString()}
                        <Layers className="size-3 ml-1" /> {p.versionCount} vers
                      </div>
                    </button>
                  ))}
                </div>
              </TabsContent>

              <TabsContent value="export" className="m-0 p-3 space-y-4">
                <FieldGroup className="gap-4">
                  <Field>
                    <TooltipFieldLabel tooltip="Định dạng tệp ảnh đầu ra.">Định dạng</TooltipFieldLabel>
                    <Select value={exportFormat} onValueChange={setExportFormat}>
                      <SelectTrigger className="h-8 bg-muted/20 border-border/70 text-xs"><SelectValue /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="PNG">PNG</SelectItem>
                        <SelectItem value="JPG">JPG</SelectItem>
                      </SelectContent>
                    </Select>
                  </Field>
                  <Field>
                    <TooltipFieldLabel tooltip="Kích thước ảnh khi xuất bản.">Độ phân giải</TooltipFieldLabel>
                    <Select value={exportSize} onValueChange={setExportSize}>
                      <SelectTrigger className="h-8 bg-muted/20 border-border/70 text-xs"><SelectValue /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="original">Gốc (Không cắt xén)</SelectItem>
                        <SelectItem value="1280x720">HD (1280x720 - 16:9)</SelectItem>
                        <SelectItem value="1920x1080">Full HD (1920x1080 - 16:9)</SelectItem>
                      </SelectContent>
                    </Select>
                  </Field>
                  <Field>
                    <TooltipFieldLabel tooltip="Tên tệp tin khi xuất.">Tên tệp</TooltipFieldLabel>
                    <Input value={exportName} onChange={e => setExportName(e.target.value)} placeholder="thumbnail_final" className="h-8 bg-muted/20 border-border/70 text-xs" />
                  </Field>
                  <Field>
                    <TooltipFieldLabel tooltip="Thư mục để lưu tệp ảnh xuất.">Thư mục lưu</TooltipFieldLabel>
                    <div className="flex items-center gap-1 p-1 pl-3 rounded-full border border-border/70 bg-muted/20">
                      <span className="text-[10px] flex-1 truncate text-muted-foreground">{exportFolder || "Chưa chọn..."}</span>
                      <Button variant="ghost" size="sm" className="h-6 px-2 text-[10px] hover:bg-background/50 rounded-full shrink-0" onClick={() => void handleChooseExportFolder()}>Chọn</Button>
                    </div>
                  </Field>
                  <Button onClick={() => void handleExport()} disabled={exporting || !selectedVersion} className="w-full" size="sm">
                    {exporting ? <Loader2 className="size-4 animate-spin mr-2" /> : <Download className="size-4 mr-2" />}
                    Xuất ảnh
                  </Button>
                </FieldGroup>
              </TabsContent>
            </Tabs>
          </ScrollArea>
        </Card>
      </aside>

      {/* -------------------- CENTER COLUMN: CANVAS & SETTINGS -------------------- */}
      <main className="flex flex-col min-h-0 gap-4">
        
        {/* TOP: CANVAS AREA */}
        <Card className="flex-1 border-border/70 shadow-sm overflow-hidden relative bg-muted/5">
          {mainPanelTab === "editor" ? (
            <div className="h-full flex flex-col">
              {activeProject ? (
                selectedVersion?.outputImagePath ? (
                  <MaskCanvas
                    imageUrl={getThumbnailAssetUrl(selectedVersion.outputImagePath)}
                    onMaskChange={setMaskBase64}
                    isSubmitting={submitting}
                    className="flex-1"
                  />
                ) : (
                  <div className="flex-1 flex items-center justify-center"><Loader2 className="animate-spin" /></div>
                )
              ) : (
                <div className="flex-1 flex flex-col items-center justify-center p-12">
                  <div 
                    className="w-full max-w-xl aspect-video rounded-3xl border-2 border-dashed border-border/50 bg-background/50 flex flex-col items-center justify-center p-8 transition-all hover:border-primary/30 hover:bg-primary/5 group"
                    onDragOver={(e) => e.preventDefault()}
                    onDrop={async (e) => {
                      e.preventDefault();
                      const file = e.dataTransfer.files[0];
                      if (file && file.type.startsWith("image/")) await processImageFile(file);
                    }}
                  >
                    <div className="size-20 rounded-2xl bg-primary/10 text-primary flex items-center justify-center mb-6 shadow-inner group-hover:scale-110 transition-transform">
                      <Palette className="size-10" />
                    </div>
                    <h3 className="text-xl font-bold tracking-tight mb-2">Sẵn sàng sáng tạo</h3>
                    <p className="text-sm text-muted-foreground max-w-sm mb-8 leading-relaxed">
                      Dán ảnh từ Clipboard hoặc kéo thả tệp vào đây để bắt đầu chỉnh sửa với AI.
                    </p>
                    
                    <div className="flex items-center gap-4">
                      <Button 
                        size="lg" 
                        className="rounded-full px-8 h-12 font-bold shadow-lg shadow-primary/20"
                        onClick={() => void handlePasteFromClipboard()}
                        disabled={submitting}
                      >
                        <MessageSquare className="size-5 mr-2" />
                        Dán ảnh (Clipboard)
                      </Button>
                      <Button 
                        variant="outline" 
                        size="lg" 
                        className="rounded-full px-8 h-12 font-bold bg-background/50"
                        onClick={() => void handlePickImage()}
                        disabled={submitting}
                      >
                        <Plus className="size-5 mr-2" />
                        Chọn tệp ảnh
                      </Button>
                    </div>

                    <div className="mt-8 flex items-center gap-2 px-4 py-2 rounded-full bg-muted/50 border border-border/50">
                       <span className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground">Mẹo:</span>
                       <span className="text-[10px] text-muted-foreground">Nhấn <kbd className="px-1.5 py-0.5 rounded bg-background border border-border/50 font-mono mx-1">Ctrl+V</kbd> bất cứ lúc nào</span>
                    </div>
                  </div>
                </div>
              )}
            </div>
          ) : (
            /* -------------------- BUTTON BUILDER VIEW (UPGRADED) -------------------- */
            <div className="h-full flex flex-col bg-background">
               <div className="flex items-center justify-between px-6 py-4 border-b border-border/50">
                 <div>
                   <h3 className="text-sm font-bold uppercase tracking-tight">Thiết kế Button Thần Thánh</h3>
                   <p className="text-[10px] text-muted-foreground">Tạo quy trình chỉnh sửa riêng với các tham số linh hoạt.</p>
                 </div>
                 <div className="flex gap-2">
                   <Button variant="ghost" size="sm" onClick={() => setMainPanelTab("editor")}>Hủy</Button>
                   <Button size="sm" onClick={() => void handleCreateButton()} disabled={submitting}>Lưu Button</Button>
                 </div>
               </div>

               <div className="flex-1 grid grid-cols-[1fr_300px] min-h-0">
                 {/* Left: Basic Info & Prompt */}
                 <ScrollArea className="border-right border-border/50">
                   <div className="p-6 space-y-6">
                     <div className="grid grid-cols-2 gap-4">
                       <Field>
                         <TooltipFieldLabel tooltip="Tên hiển thị của nút.">Tên Button</TooltipFieldLabel>
                         <Input value={buttonBuilderName} onChange={e => setButtonBuilderName(e.target.value)} placeholder="Ví dụ: Làm mặt sốc hơn" className="bg-muted/20" />
                       </Field>
                       <Field>
                         <TooltipFieldLabel tooltip="Nhóm để phân loại nút.">Danh mục</TooltipFieldLabel>
                         <Select value={buttonBuilderCategory} onValueChange={setButtonBuilderCategory}>
                           <SelectTrigger className="bg-muted/20"><SelectValue /></SelectTrigger>
                           <SelectContent>
                             {["Cleanup", "Color", "Face", "Camera", "Extend", "Custom"].map(c => <SelectItem key={c} value={c}>{c}</SelectItem>)}
                           </SelectContent>
                         </Select>
                       </Field>
                     </div>

                     <Field>
                       <TooltipFieldLabel tooltip="Mẫu prompt gửi tới Gemini. Dùng {key} để chèn giá trị từ các field bên phải.">Prompt Template</TooltipFieldLabel>
                       <Textarea 
                         value={buttonBuilderPrompt} 
                         onChange={e => setButtonBuilderPrompt(e.target.value)}
                         placeholder="Ví dụ: Make the character expression more {expression}, intensity {intensity}/10."
                         className="min-h-[200px] font-mono text-xs bg-muted/20 selection:bg-primary/20"
                       />
                     </Field>

                     <div className="grid grid-cols-3 gap-4 p-4 rounded-xl border border-border/50 bg-muted/5">
                        <div className="flex items-center gap-2"><Switch checked={builderRequiresMask} onCheckedChange={setBuilderRequiresMask}/><span className="text-[11px] font-medium">Cần vẽ Mask</span></div>
                        <div className="flex items-center gap-2"><Switch checked={builderCreateNewChat} onCheckedChange={setBuilderCreateNewChat}/><span className="text-[11px] font-medium">Tạo Chat mới</span></div>
                        <div className="flex items-center gap-2"><Switch checked={builderAllowRegenerate} onCheckedChange={setBuilderAllowRegenerate}/><span className="text-[11px] font-medium">Cho phép Gen lại</span></div>
                     </div>
                   </div>
                 </ScrollArea>

                 {/* Right: Field Management */}
                 <div className="flex flex-col min-h-0 bg-muted/5 border-l border-border/50">
                   <div className="p-4 border-b border-border/50 bg-muted/20">
                     <h4 className="text-[10px] font-bold uppercase tracking-wider mb-4 flex items-center gap-2"><Settings2 className="size-3" /> Tham số động</h4>
                     <FieldGroup className="gap-3">
                       <Input value={newFieldLabel} onChange={e => setNewFieldLabel(e.target.value)} placeholder="Nhãn (ví dụ: Biểu cảm)" className="h-8 text-xs" />
                       <Input value={newFieldKey} onChange={e => setNewFieldKey(e.target.value)} placeholder="Mã (ví dụ: expression)" className="h-8 text-xs font-mono" />
                       
                       <Select value={newFieldType} onValueChange={(v: any) => setNewFieldType(v)}>
                         <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
                         <SelectContent>
                           <SelectItem value="text"><div className="flex items-center gap-2"><Type className="size-3" /> Văn bản</div></SelectItem>
                           <SelectItem value="textarea"><div className="flex items-center gap-2"><Type className="size-3" /> Đoạn văn</div></SelectItem>
                           <SelectItem value="select"><div className="flex items-center gap-2"><List className="size-3" /> Lựa chọn đơn</div></SelectItem>
                           <SelectItem value="multi-select"><div className="flex items-center gap-2"><List className="size-3" /> Chọn nhiều (Style)</div></SelectItem>
                           <SelectItem value="slider"><div className="flex items-center gap-2"><Sliders className="size-3" /> Thanh trượt</div></SelectItem>
                           <SelectItem value="number"><div className="flex items-center gap-2"><Hash className="size-3" /> Con số</div></SelectItem>
                           <SelectItem value="toggle"><div className="flex items-center gap-2"><ToggleLeft className="size-3" /> Công tắc</div></SelectItem>
                           <SelectItem value="color"><div className="flex items-center gap-2"><Palette className="size-3" /> Màu sắc</div></SelectItem>
                         </SelectContent>
                       </Select>

                       {(newFieldType === 'select' || newFieldType === 'multi-select') && (
                         <Input value={newFieldOptions} onChange={e => setNewFieldOptions(e.target.value)} placeholder="Option 1, Option 2..." className="h-8 text-xs" />
                       )}

                       {(newFieldType === 'slider' || newFieldType === 'number') && (
                         <div className="flex gap-2">
                           <Input type="number" value={newFieldMin} onChange={e => setNewFieldMin(Number(e.target.value))} placeholder="Min" className="h-8 text-xs" />
                           <Input type="number" value={newFieldMax} onChange={e => setNewFieldMax(Number(e.target.value))} placeholder="Max" className="h-8 text-xs" />
                         </div>
                       )}

                       <Input value={newFieldVisibleIf} onChange={e => setNewFieldVisibleIf(e.target.value)} placeholder="Hiện nếu key này bật..." className="h-8 text-[10px] font-mono" />

                       <Button size="sm" variant="secondary" className="w-full h-8 text-[11px]" onClick={handleAddField}><Plus className="size-3 mr-1" /> Thêm Field</Button>
                     </FieldGroup>
                   </div>

                   <ScrollArea className="flex-1">
                     <div className="p-4 space-y-2">
                       {builderFields.map((f, idx) => (
                         <div key={idx} className="flex items-center justify-between p-2 rounded-lg border border-border/50 bg-background shadow-sm">
                           <div className="min-w-0 flex-1">
                             <div className="text-[11px] font-bold">{f.label}</div>
                             <div className="text-[9px] text-muted-foreground font-mono truncate">{"{"}{f.key}{"}"} • {f.type} {f.visibleIf && `(If ${f.visibleIf})`}</div>
                           </div>
                           <Button variant="ghost" size="icon" className="h-6 w-6 text-destructive" onClick={() => setBuilderFields(builderFields.filter((_, i) => i !== idx))}>
                             <Trash2 className="size-3" />
                           </Button>
                         </div>
                       ))}
                       {builderFields.length === 0 && (
                         <div className="text-center py-8 text-muted-foreground opacity-50">
                           <Settings2 className="size-8 mx-auto mb-2" />
                           <p className="text-[10px]">Chưa có tham số nào.</p>
                         </div>
                       )}
                     </div>
                   </ScrollArea>
                 </div>
               </div>
            </div>
          )}
        </Card>

        {/* BOTTOM: SETTINGS & PROGRESS */}
        {activeProject && mainPanelTab === "editor" && (
          <Card className="h-72 border-border/70 shadow-sm grid grid-cols-[1fr_1.2fr_1fr] divide-x divide-border/50 overflow-hidden">
            
            {/* THIẾT LẬP BUTTON */}
            <div className="flex flex-col min-h-0">
              <div className="px-4 py-2 bg-muted/20 border-b border-border/50 text-[10px] font-bold uppercase tracking-wider flex items-center gap-2">
                <Sparkles className="size-3 text-primary" /> Thiết lập Button
              </div>
              <ScrollArea className="flex-1 p-4">
                {selectedButton ? (
                  <div className="space-y-4">
                    <div className="flex items-center gap-2">
                      <div className="size-6 flex items-center justify-center rounded bg-primary/10 text-xs shadow-sm">{selectedButton.icon}</div>
                      <span className="text-xs font-bold truncate">{selectedButton.name}</span>
                    </div>
                    <FieldGroup className="gap-3">
                      {selectedButton.fields.map(field => {
                        if (!isFieldVisible(field, selectedButton.fields)) return null;
                        
                        return (
                          <Field key={field.key}>
                            <label className="text-[10px] font-medium text-muted-foreground uppercase">{field.label}</label>
                            {field.type === 'slider' ? (
                              <div className="flex items-center gap-3">
                                <input 
                                  type="range" min={field.min ?? 0} max={field.max ?? 10} 
                                  value={Number(field.value)}
                                  onChange={e => handleFieldChange(field.key, e.target.value)}
                                  className="flex-1 h-1 bg-muted rounded-full appearance-none accent-primary"
                                />
                                <span className="text-[10px] font-mono w-4 text-right">{field.value}</span>
                              </div>
                            ) : field.type === 'select' ? (
                              <Select value={String(field.value)} onValueChange={v => handleFieldChange(field.key, v)}>
                                <SelectTrigger className="h-7 bg-muted/20 text-[11px]"><SelectValue /></SelectTrigger>
                                <SelectContent>
                                  {field.options?.map(o => <SelectItem key={o} value={o}>{o}</SelectItem>)}
                                </SelectContent>
                              </Select>
                            ) : field.type === 'multi-select' ? (
                              <div className="flex flex-wrap gap-1.5 p-2 rounded-lg border border-border/50 bg-muted/10">
                                {field.options?.map(o => {
                                  const isSelected = Array.isArray(field.value) && field.value.includes(o);
                                  return (
                                    <button
                                      key={o}
                                      onClick={() => handleMultiSelectToggle(field.key, o)}
                                      className={cn(
                                        "px-2 py-1 rounded text-[9px] font-bold uppercase transition-all border",
                                        isSelected 
                                          ? "bg-primary border-primary text-primary-foreground shadow-sm" 
                                          : "bg-background border-border/50 text-muted-foreground hover:bg-muted"
                                      )}
                                    >
                                      {isSelected && <Check className="size-2.5 inline mr-1" />}
                                      {o}
                                    </button>
                                  );
                                })}
                              </div>
                            ) : field.type === 'toggle' ? (
                               <div className="flex items-center gap-2 py-1">
                                 <Switch checked={Boolean(field.value)} onCheckedChange={v => handleFieldChange(field.key, v)} />
                               </div>
                            ) : field.type === 'color' ? (
                               <div className="flex items-center gap-2">
                                 <Input type="color" value={String(field.value || "#FF0000")} onChange={e => handleFieldChange(field.key, e.target.value)} className="h-7 w-12 p-0.5 bg-muted/20 border-none" />
                                 <span className="text-[10px] font-mono text-muted-foreground">{String(field.value || "#FF0000").toUpperCase()}</span>
                               </div>
                            ) : field.type === 'textarea' ? (
                              <Textarea value={String(field.value)} onChange={e => handleFieldChange(field.key, e.target.value)} className="min-h-[60px] bg-muted/20 text-[11px]" />
                            ) : (
                              <Input value={String(field.value)} onChange={e => handleFieldChange(field.key, e.target.value)} className="h-7 bg-muted/20 text-[11px]" />
                            )}
                          </Field>
                        );
                      })}
                      {selectedButton.fields.length === 0 && <div className="text-[10px] text-muted-foreground italic py-2 text-center border border-dashed border-border rounded">Không có tham số.</div>}
                    </FieldGroup>
                  </div>
                ) : <div className="text-xs text-muted-foreground p-4 text-center">Chọn một button để cấu hình.</div>}
              </ScrollArea>
            </div>

            {/* PREVIEW PROMPT */}
            <div className="flex flex-col min-h-0 bg-muted/5">
              <div className="px-4 py-2 bg-muted/20 border-b border-border/50 text-[10px] font-bold uppercase tracking-wider flex items-center justify-between">
                <div className="flex items-center gap-2"><MessageSquare className="size-3 text-primary" /> Preview Prompt</div>
                {submitting && <Badge variant="outline" className="h-4 text-[8px] animate-pulse bg-primary/5 text-primary border-primary/20">Gemini Processing</Badge>}
              </div>
              <div className="flex-1 p-4 flex flex-col gap-3">
                <div className="flex-1 p-3 rounded-lg border border-border/50 bg-background font-mono text-[11px] leading-relaxed overflow-y-auto whitespace-pre-wrap text-muted-foreground selection:bg-primary/20">
                  {previewPrompt}
                </div>
                
                {/* REGENERATE MODE TOGGLE */}
                <div className="flex items-center justify-between px-1">
                   <div className="flex items-center gap-1.5">
                     <span className="text-[9px] font-bold uppercase text-muted-foreground">Chế độ:</span>
                     <button 
                        onClick={() => setRegenerateMode(regenerateMode === "new-chat" ? "same-chat" : "new-chat")}
                        className={cn(
                          "flex items-center gap-1.5 px-2 py-1 rounded-md border text-[9px] font-bold transition-all",
                          regenerateMode === "new-chat" 
                            ? "bg-amber-500/10 border-amber-500/30 text-amber-600" 
                            : "bg-blue-500/10 border-blue-500/30 text-blue-600"
                        )}
                     >
                       {regenerateMode === "new-chat" ? <MessagesSquare className="size-3" /> : <MessageCircle className="size-3" />}
                       {regenerateMode === "new-chat" ? "CHAT MỚI (Sạch)" : "TIẾP TỤC (Nhớ context)"}
                     </button>
                   </div>
                   <div className="flex gap-2">
                      <Button variant="ghost" size="sm" className="h-7 w-7 p-0 border border-border/50" onClick={() => void handleRun(true)} disabled={submitting} title="Tạo nhánh mới">
                        <Plus className="size-3" />
                      </Button>
                      <Button variant="default" size="sm" className="h-7 px-4 text-[10px] font-bold shadow-lg shadow-primary/20" onClick={() => void handleRun(false)} disabled={submitting}>
                        {submitting ? <Loader2 className="size-3 animate-spin mr-1.5" /> : <Play className="size-3 mr-1.5" />}
                        RUN
                      </Button>
                   </div>
                </div>
              </div>
            </div>

            {/* TIẾN TRÌNH HIỆN TẠI */}
            <div className="flex flex-col min-h-0">
              <div className="px-4 py-2 bg-muted/20 border-b border-border/50 text-[10px] font-bold uppercase tracking-wider flex items-center gap-2">
                <Clock className="size-3 text-primary" /> Tiến trình hiện tại
              </div>
              <div className="flex-1 p-6 space-y-6">
                 {[
                   { id: 1, label: "Upload ảnh & Mask", status: submitting ? "current" : "done" },
                   { id: 2, label: "Gửi prompt & Logic", status: submitting ? "waiting" : "done" },
                   { id: 3, label: "Gemini đang xử lý", status: submitting ? "waiting" : "done" },
                   { id: 4, label: "Nhận kết quả", status: submitting ? "waiting" : "done" }
                 ].map((step, idx) => (
                   <div key={step.id} className="relative flex items-center gap-4">
                     {idx < 3 && <div className={cn("absolute left-2 top-6 w-px h-6 transition-colors duration-500", !submitting ? "bg-primary" : "bg-muted")} />}
                     <div className={cn(
                       "size-4 rounded-full flex items-center justify-center shrink-0 z-10 transition-all duration-500",
                       !submitting ? "bg-primary text-primary-foreground shadow-md shadow-primary/30" : "border-2 border-muted bg-background"
                     )}>
                       {!submitting ? <CheckCircle2 className="size-3" /> : <Circle className="size-3 text-muted" />}
                     </div>
                     <span className={cn("text-[11px] font-medium transition-colors", !submitting ? "text-foreground" : "text-muted-foreground")}>
                       {step.label}
                     </span>
                   </div>
                 ))}
              </div>
            </div>
          </Card>
        )}
      </main>

      {/* -------------------- RIGHT COLUMN: HISTORY -------------------- */}
      <aside className="flex flex-col min-h-0">
        <Card className="flex flex-col h-full border-border/70 shadow-sm overflow-hidden">
          <div className="px-4 py-3 border-b border-border/50 flex items-center justify-between">
            <h2 className="text-sm font-bold uppercase tracking-tight">Lịch sử Version</h2>
            <History className="h-4 w-4 text-muted-foreground" />
          </div>
          
          <ScrollArea className="flex-1">
            <div className="p-3 space-y-3">
              {versions.slice().reverse().map((v, idx) => (
                <button
                  key={v.id}
                  onClick={() => void handleSelectVersion(v.id)}
                  className={cn(
                    "w-full group relative flex gap-3 p-2 rounded-xl border transition-all text-left",
                    selectedVersion?.id === v.id 
                      ? "border-primary bg-primary/5 shadow-sm" 
                      : "border-border/50 hover:border-border hover:bg-muted/30"
                  )}
                >
                  {/* Thumbnail */}
                  <div className="size-16 rounded-lg bg-muted border border-border/30 overflow-hidden shrink-0 shadow-inner">
                    {v.outputImagePath && <img src={getThumbnailAssetUrl(v.outputImagePath)} alt={v.id} className="size-full object-cover group-hover:scale-105 transition-transform duration-300" />}
                  </div>
                  
                  {/* Details */}
                  <div className="min-w-0 flex-1 pt-0.5">
                    <div className="flex items-center justify-between">
                       <span className="text-[10px] font-bold text-primary uppercase">v{versions.length - 1 - idx}</span>
                       <span className="text-[9px] text-muted-foreground font-medium">{v.createdAt.split(' ')[1]}</span>
                    </div>
                    <div className="text-[11px] font-bold truncate mt-0.5 text-foreground/90">{v.buttonName}</div>
                    <div className="text-[9px] text-muted-foreground line-clamp-2 mt-1 italic leading-tight">"{v.prompt}"</div>
                  </div>

                  {/* Indicators */}
                  {v.status === "branch" && <div className="absolute top-1 right-1 size-1.5 rounded-full bg-amber-500 ring-2 ring-background" />}
                  {selectedVersion?.id === v.id && <div className="absolute -left-1 top-1/2 -translate-y-1/2 w-1 h-8 bg-primary rounded-r-full" />}
                </button>
              ))}
              
              {versions.length === 0 && (
                <div className="text-center py-12 px-4 flex flex-col items-center">
                  <History className="size-10 text-muted/10 mb-2" />
                  <p className="text-[11px] text-muted-foreground">Chưa có lịch sử chỉnh sửa.</p>
                </div>
              )}
            </div>
          </ScrollArea>
          
          <div className="p-3 border-t border-border/50 bg-muted/10">
             <Button 
                variant="outline" 
                size="sm" 
                className="w-full h-8 text-[10px] uppercase font-bold tracking-wider hover:bg-background"
                onClick={() => setShowComparator(true)}
                disabled={!beforeVersion || !selectedVersion}
             >
               <Maximize2 className="size-3 mr-2" /> So sánh Version
             </Button>
          </div>
        </Card>
      </aside>

    </div>
  );
}
