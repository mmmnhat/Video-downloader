import { useEffect, useState, useTransition } from "react";
import {
  Download, History, Loader2,
  Palette, Play, Plus, Search
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
  selectThumbnailProject,
  selectThumbnailVersion,
  type ThumbnailBootstrapPayload,
  type ThumbnailButtonField,
  type ThumbnailProjectDetail,
} from "@/lib/api";

import { cn } from "@/lib/utils";
import {
  TAB_CARD_GAP_CLASS,
  TAB_STICKY_TOP_CLASS,
  TAB_VIEWPORT_CARD_HEIGHT_CLASS,
} from "@/lib/layout";

function fieldValueMap(fields: ThumbnailButtonField[]) {
  return Object.fromEntries(fields.map((field) => [field.key, field.value]));
}

function getErrorMessage(error: unknown) {
  return error instanceof Error ? error.message : "Yêu cầu thất bại.";
}

type LeftPanelTab = "tools" | "projects" | "export";
type MainPanelTab = "editor" | "builder" | "profile";

export default function ThumbnailStudio() {
  const [bootLoading, setBootLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [bootstrap, setBootstrap] = useState<ThumbnailBootstrapPayload | null>(null);
  const [activeProject, setActiveProject] = useState<ThumbnailProjectDetail | null>(null);

  const [selectedMode] = useState<"preset" | "custom" | "mask">("preset");
  const [selectedButtonId, setSelectedButtonId] = useState("");
  const [regenerateMode] = useState<"same-chat" | "new-chat">("new-chat");
  
  const [leftPanelTab, setLeftPanelTab] = useState<LeftPanelTab>("tools");
  const [mainPanelTab, setMainPanelTab] = useState<MainPanelTab>("editor");

  // Button Builder State
  const [buttonBuilderName, setButtonBuilderName] = useState("");
  const [buttonBuilderIcon] = useState("✨");
  const [buttonBuilderCategory, setButtonBuilderCategory] = useState("General");
  const [buttonBuilderPrompt, setButtonBuilderPrompt] = useState("");
  const [builderRequiresMask, setBuilderRequiresMask] = useState(false);
  const [builderCreateNewChat, setBuilderCreateNewChat] = useState(true);
  const [builderAllowRegenerate, setBuilderAllowRegenerate] = useState(true);
  const [builderFields, setBuilderFields] = useState<ThumbnailButtonField[]>([]);

  // Export State
  const [exportSize, setExportSize] = useState("1280x720");
  const [exportFormat, setExportFormat] = useState("PNG");
  const [exportName] = useState("");
  const [exportFolder, setExportFolder] = useState("");

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
  const versions = activeProject?.versions ?? [];
  const selectedVersion = activeProject?.currentVersion ?? versions[versions.length - 1] ?? null;
  const selectedButton = buttons.find((button) => button.id === selectedButtonId) ?? buttons[0] ?? null;

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

  function handleFieldChange(key: string, nextValue: string | number) {
    if (!selectedButton) return;
    const nextFields = selectedButton.fields.map((field) => (field.key === key ? { ...field, value: field.type === "slider" ? Number(nextValue) : String(nextValue) } : field));
    setBootstrap((current) =>
      current ? { ...current, buttons: current.buttons.map((b) => (b.id === selectedButton.id ? { ...b, fields: nextFields } : b)) } : current
    );
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

  function handleAddBuilderField(type: "text" | "select" | "slider") {
    const key = `field_${builderFields.length + 1}`;
    const newField: ThumbnailButtonField = {
      key,
      label: `Trường ${builderFields.length + 1}`,
      type,
      value: type === "slider" ? 5 : "",
      tooltip: "Mô tả tham số này...",
      options: type === "select" ? ["Tùy chọn 1", "Tùy chọn 2"] : [],
      min: type === "slider" ? 1 : null,
      max: type === "slider" ? 10 : null,
    };
    setBuilderFields([...builderFields, newField]);
  }

  function handleRemoveBuilderField(key: string) {
    setBuilderFields(builderFields.filter((f) => f.key !== key));
  }

  async function handleCreateButton() {
    if (!buttonBuilderName || !buttonBuilderPrompt) return toast.error("Vui lòng nhập tên và mẫu prompt.");
    setSubmitting(true);
    try {
      const button = await createThumbnailButton({
        name: buttonBuilderName,
        icon: buttonBuilderIcon,
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
      });
      syncProject(project);
      toast.success(isRegenerate ? "Đã tạo nhánh chỉnh sửa mới." : "Gemini đã trả về phiên bản mới.");
    } catch (error) {
      toast.error(getErrorMessage(error));
    } finally {
      setSubmitting(false);
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

  if (bootLoading) {
    return (
      <Card className="border-border/70 shadow-sm">
        <CardContent className="flex items-center justify-center gap-3 py-16 text-sm text-muted-foreground">
          <Loader2 className="size-4 animate-spin" />
          Khởi tạo Studio Tạo ảnh...
        </CardContent>
      </Card>
    );
  }

  return (
    <div className={cn("grid lg:grid-cols-[22rem_minmax(0,1fr)]", TAB_CARD_GAP_CLASS)}>
      {/* -------------------- LEFT PANEL (STICKY CONFIG) -------------------- */}
      <aside className="relative flex flex-col min-w-0">
        <Card className={cn("relative flex flex-col border-border/70 shadow-[0_24px_90px_rgba(15,23,42,0.08)] lg:sticky", TAB_STICKY_TOP_CLASS, TAB_VIEWPORT_CARD_HEIGHT_CLASS, "lg:overflow-hidden")}>
          <div className="flex items-center justify-between px-4 pt-0 pb-2 shrink-0">
            <Tabs value={leftPanelTab} onValueChange={(value) => setLeftPanelTab(value as LeftPanelTab)} className="flex items-center">
              <TabsList className="h-8 bg-muted/20 p-0.5 border border-border/40">
                <TabsTrigger value="tools" className="h-7 px-3 text-[11px] font-medium uppercase tracking-wider">Công cụ</TabsTrigger>
                <TabsTrigger value="projects" className="h-7 px-3 text-[11px] font-medium uppercase tracking-wider">Dự án</TabsTrigger>
                <TabsTrigger value="export" className="h-7 px-3 text-[11px] font-medium uppercase tracking-wider">Xuất ảnh</TabsTrigger>
              </TabsList>
            </Tabs>
          </div>

          <CardContent className="flex flex-col min-h-0 flex-1 gap-5 pt-2 overflow-y-auto">
            <Tabs value={leftPanelTab} className="flex-col flex-1 flex">
              <TabsContent value="tools" className="flex-1 mt-0 flex flex-col">
                <div className="relative mb-4">
                  <Input placeholder="Tìm kiếm hành động..." className="h-8 pl-8 text-xs bg-muted/20 border-border/70 rounded-full" />
                  <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 size-3.5 text-muted-foreground" />
                </div>
                
                <ScrollArea className="flex-1 -mx-4 px-4">
                  <div className="space-y-6">
                    {["Face", "Background", "General", "Custom"].map(cat => {
                      const catButtons = buttons.filter(b => b.category === cat);
                      if (!catButtons.length) return null;
                      return (
                        <div key={cat} className="space-y-2">
                          <div className="flex items-center gap-2">
                            <Badge variant="outline">{cat}</Badge>
                          </div>
                          <div className="grid grid-cols-2 gap-2">
                            {catButtons.map(button => (
                              <button
                                key={button.id}
                                onClick={() => setSelectedButtonId(button.id)}
                                className={cn(
                                  "flex flex-col items-start rounded-lg border p-2.5 transition-all text-left",
                                  selectedButtonId === button.id
                                    ? "border-primary bg-primary/10 shadow-sm"
                                    : "border-border/70 bg-card hover:bg-muted/50"
                                )}
                              >
                                <div className="mb-1.5 text-base">{button.icon}</div>
                                <div className="text-xs font-semibold leading-tight line-clamp-1">{button.name}</div>
                                <div className="mt-1 flex gap-1 flex-wrap">
                                  {button.requiresMask && <span className="rounded bg-blue-500/10 px-1 py-0.5 text-[9px] text-blue-500 uppercase font-bold tracking-wider">mask</span>}
                                  {button.fields.length > 0 && <span className="rounded bg-purple-500/10 px-1 py-0.5 text-[9px] text-purple-500 uppercase font-bold tracking-wider">tham số</span>}
                                </div>
                              </button>
                            ))}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </ScrollArea>

                {selectedButton && selectedButton.fields.length > 0 && (
                  <div className="mt-4 pt-4 border-t border-border/70 space-y-3">
                    <div className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground">Cấu hình tham số</div>
                    <FieldGroup className="gap-3">
                      {selectedButton.fields.map(field => (
                        <Field key={field.key}>
                          <TooltipFieldLabel tooltip={field.tooltip || ""}>{field.label}</TooltipFieldLabel>
                          {field.type === 'slider' ? (
                            <div className="flex items-center gap-3">
                              <input 
                                type="range" 
                                min={field.min ?? 0} 
                                max={field.max ?? 10} 
                                value={Number(field.value)}
                                onChange={e => handleFieldChange(field.key, e.target.value)}
                                className="flex-1 h-1.5 bg-muted rounded-full appearance-none accent-primary"
                              />
                              <span className="text-xs font-mono w-6 text-right">{field.value}</span>
                            </div>
                          ) : field.type === 'select' ? (
                            <Select value={String(field.value)} onValueChange={v => handleFieldChange(field.key, v)}>
                              <SelectTrigger className="h-8 bg-muted/20 border-border/70 text-xs"><SelectValue /></SelectTrigger>
                              <SelectContent>
                                {field.options?.map(o => <SelectItem key={o} value={o}>{o}</SelectItem>)}
                              </SelectContent>
                            </Select>
                          ) : (
                            <Input value={String(field.value)} onChange={e => handleFieldChange(field.key, e.target.value)} className="h-8 bg-muted/20 border-border/70 text-xs" />
                          )}
                        </Field>
                      ))}
                    </FieldGroup>
                  </div>
                )}
              </TabsContent>

              <TabsContent value="projects" className="flex-1 mt-0">
                <div className="space-y-4">
                  <div className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground mb-2">Thư viện dự án</div>
                  {bootstrap?.projects.length ? (
                    <div className="space-y-2">
                      {bootstrap.projects.map(p => (
                        <button 
                          key={p.id} 
                          onClick={() => void handleSelectProject(p.id)} 
                          className={cn(
                            "w-full flex items-center justify-between p-3 rounded-lg border transition-all text-left",
                            activeProject?.id === p.id ? "border-primary bg-primary/5" : "border-border/70 bg-card hover:bg-muted/50"
                          )}
                        >
                          <div>
                            <div className="text-sm font-semibold">{p.name}</div>
                            <div className="text-[10px] text-muted-foreground mt-0.5">{p.versionCount} phiên bản</div>
                          </div>
                          {activeProject?.id === p.id && <div className="size-2 rounded-full bg-primary" />}
                        </button>
                      ))}
                    </div>
                  ) : (
                    <div className="text-sm text-muted-foreground text-center py-8">Chưa có dự án nào</div>
                  )}
                </div>
              </TabsContent>

              <TabsContent value="export" className="flex-1 mt-0">
                <FieldGroup className="gap-4">
                  <Field>
                    <TooltipFieldLabel tooltip="Định dạng tệp ảnh đầu ra.">Định dạng</TooltipFieldLabel>
                    <Select value={exportFormat} onValueChange={setExportFormat}>
                      <SelectTrigger className="h-8 bg-muted/20 border-border/70 text-xs"><SelectValue /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="PNG">PNG (Không nén)</SelectItem>
                        <SelectItem value="JPG">JPG (Tối ưu hóa)</SelectItem>
                      </SelectContent>
                    </Select>
                  </Field>
                  <Field>
                    <TooltipFieldLabel tooltip="Kích thước ảnh khi xuất bản.">Độ phân giải</TooltipFieldLabel>
                    <Select value={exportSize} onValueChange={setExportSize}>
                      <SelectTrigger className="h-8 bg-muted/20 border-border/70 text-xs"><SelectValue /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="1920x1080">1920x1080 (Full HD)</SelectItem>
                        <SelectItem value="1280x720">1280x720 (HD)</SelectItem>
                        <SelectItem value="1024x576">1024x576 (Web)</SelectItem>
                      </SelectContent>
                    </Select>
                  </Field>
                  <Field>
                    <TooltipFieldLabel tooltip="Thư mục để lưu tệp ảnh xuất.">Thư mục lưu</TooltipFieldLabel>
                    <div className="flex items-center gap-1 p-1 pl-3 rounded-full border border-border/70 bg-muted/20">
                      <span className="text-xs flex-1 truncate text-muted-foreground">{exportFolder || "Chưa chọn..."}</span>
                      <Button variant="ghost" size="sm" className="h-7 px-3 text-xs hover:bg-background/50 rounded-full shrink-0" onClick={() => void handleChooseExportFolder()}>Chọn</Button>
                    </div>
                  </Field>
                  <Button onClick={() => void handleExport()} disabled={exporting || !selectedVersion} className="w-full mt-2" size="sm">
                    {exporting ? <Loader2 className="size-4 animate-spin mr-2" /> : <Download className="size-4 mr-2" />}
                    Xuất ảnh
                  </Button>
                </FieldGroup>
              </TabsContent>
            </Tabs>
          </CardContent>
        </Card>
      </aside>

      {/* -------------------- MAIN PANEL -------------------- */}
      <Card className={cn("flex flex-col border-border/70 shadow-[0_24px_90px_rgba(15,23,42,0.08)]", TAB_VIEWPORT_CARD_HEIGHT_CLASS, "lg:overflow-hidden")}>
        <div className="flex items-center justify-between px-4 pt-0 pb-2 flex-none">
          <Tabs value={mainPanelTab} onValueChange={(value) => setMainPanelTab(value as MainPanelTab)}>
            <TabsList className="h-8 bg-muted/20 p-0.5 border border-border/40">
              <TabsTrigger value="editor" className="h-7 px-3 text-[11px] font-medium uppercase tracking-wider">Chỉnh sửa</TabsTrigger>
              <TabsTrigger value="builder" className="h-7 px-3 text-[11px] font-medium uppercase tracking-wider">Tạo công cụ</TabsTrigger>
              <TabsTrigger value="profile" className="h-7 px-3 text-[11px] font-medium uppercase tracking-wider">Lịch sử</TabsTrigger>
            </TabsList>
          </Tabs>
          
          <div className="flex items-center gap-2">
            <Button variant="default" size="sm" className="h-7 text-xs rounded-full px-4" onClick={() => void handleRun(false)} disabled={submitting || !activeProject || !selectedButton}>
              {submitting ? <Loader2 className="size-3.5 animate-spin mr-1.5" /> : <Play className="size-3.5 mr-1.5" />}
              Chạy công cụ
            </Button>
          </div>
        </div>

        <CardContent className="flex-1 flex flex-col min-h-0 p-0 overflow-hidden bg-muted/5">
          <Tabs value={mainPanelTab} className="flex-1 flex flex-col min-h-0">
            <TabsContent value="editor" className="flex-1 flex flex-col m-0 min-h-0">
              {/* CANVAS AREA */}
              <div className="relative flex-1 flex items-center justify-center p-4 overflow-hidden">
                <div className="absolute inset-0 opacity-[0.03]" style={{ backgroundImage: "linear-gradient(var(--border) 1px, transparent 1px), linear-gradient(90deg, var(--border) 1px, transparent 1px)", backgroundSize: "20px 20px" }} />
                
                {activeProject ? (
                  <div className="relative flex aspect-video w-full max-w-4xl items-center justify-center overflow-hidden rounded-xl border border-border/50 bg-card shadow-2xl">
                    {selectedVersion?.outputImagePath ? (
                      <img src={getThumbnailAssetUrl(selectedVersion.outputImagePath)} alt="Preview" className="h-full w-full object-contain" />
                    ) : (
                      <div className="flex flex-col items-center justify-center gap-4 text-muted-foreground">
                        <Loader2 className="size-8 animate-spin" />
                        <div className="text-sm">Đang tải hình ảnh...</div>
                      </div>
                    )}
                    
                    {submitting && (
                      <div className="absolute inset-0 z-50 flex flex-col items-center justify-center bg-background/80 backdrop-blur-sm">
                        <div className="mb-4 flex flex-col items-center">
                          <Loader2 className="size-8 animate-spin text-primary mb-4" />
                          <div className="text-sm font-semibold">Gemini đang xử lý hình ảnh...</div>
                        </div>
                      </div>
                    )}
                  </div>
                ) : (
                  <div className="flex flex-col items-center justify-center max-w-sm text-center">
                    <div className="flex size-20 items-center justify-center rounded-2xl bg-primary/10 text-primary mb-6 shadow-sm">
                      <Palette className="size-10" />
                    </div>
                    <h3 className="text-xl font-bold mb-2">Bắt đầu dự án mới</h3>
                    <p className="text-sm text-muted-foreground mb-8">Sao chép một hình ảnh bất kỳ và nhấn <kbd className="font-mono bg-muted px-1.5 py-0.5 rounded text-foreground border">Ctrl+V</kbd> để tạo dự án ngay lập tức.</p>
                  </div>
                )}
              </div>

              {/* VERSION STRIP */}
              {activeProject && (
                <div className="h-20 border-t border-border/70 bg-card px-4 flex items-center gap-3 overflow-x-auto">
                  <div className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground shrink-0 w-16">Lịch sử</div>
                  {versions.map(v => (
                    <button
                      key={v.id}
                      onClick={() => void handleSelectVersion(v.id)}
                      className={cn(
                        "relative flex h-14 w-20 shrink-0 cursor-pointer items-center justify-center rounded-md border-2 bg-muted/30 transition-all overflow-hidden",
                        selectedVersion?.id === v.id ? "border-primary shadow-md" : "border-transparent hover:border-border"
                      )}
                    >
                      {v.outputImagePath ? (
                        <img src={getThumbnailAssetUrl(v.outputImagePath)} alt={v.id} className="h-full w-full object-cover" />
                      ) : (
                        <div className="text-[10px] font-mono text-muted-foreground uppercase">{v.id === "original" ? "Gốc" : v.id}</div>
                      )}
                      {v.status === "branch" && <div className="absolute top-1 right-1 size-1.5 rounded-full bg-amber-500" />}
                    </button>
                  ))}
                  <button 
                    onClick={() => void handleRun(true)} 
                    disabled={submitting}
                    className="flex h-14 w-14 shrink-0 items-center justify-center rounded-md border-2 border-dashed border-border text-muted-foreground hover:text-foreground hover:border-primary/50 transition-colors"
                  >
                    <Plus className="size-5" />
                  </button>
                </div>
              )}
            </TabsContent>

            <TabsContent value="builder" className="flex-1 flex flex-col m-0 p-6 overflow-y-auto">
              <div className="max-w-2xl mx-auto w-full space-y-8">
                <div>
                  <h3 className="text-lg font-bold">Tạo Công Cụ Tùy Chỉnh</h3>
                  <p className="text-sm text-muted-foreground mt-1">Thiết kế các mẫu prompt Gemini đặc biệt cho quy trình làm việc của riêng bạn.</p>
                </div>

                <FieldGroup className="gap-6">
                  <div className="grid grid-cols-2 gap-4">
                    <Field>
                      <TooltipFieldLabel tooltip="Tên hiển thị của công cụ.">Tên công cụ</TooltipFieldLabel>
                      <Input value={buttonBuilderName} onChange={e => setButtonBuilderName(e.target.value)} placeholder="Ví dụ: Tăng độ nét" className="h-9 bg-muted/20 border-border/70" />
                    </Field>
                    <Field>
                      <TooltipFieldLabel tooltip="Phân loại công cụ vào nhóm.">Danh mục</TooltipFieldLabel>
                      <Input value={buttonBuilderCategory} onChange={e => setButtonBuilderCategory(e.target.value)} placeholder="Face, Background..." className="h-9 bg-muted/20 border-border/70" />
                    </Field>
                  </div>

                  <Field>
                    <TooltipFieldLabel tooltip="Lệnh gửi đến Gemini. Sử dụng {field_name} để chèn tham số động.">Mẫu Prompt</TooltipFieldLabel>
                    <Textarea 
                      value={buttonBuilderPrompt} 
                      onChange={e => setButtonBuilderPrompt(e.target.value)}
                      placeholder="Mô tả cách Gemini thay đổi hình ảnh..."
                      className="min-h-[120px] resize-y bg-muted/20 border-border/70 font-mono text-sm"
                    />
                  </Field>

                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                    <div className="flex items-center justify-between p-3 rounded-lg border border-border/70 bg-card">
                      <span className="text-xs font-medium">Cần vẽ mask</span>
                      <Switch checked={builderRequiresMask} onCheckedChange={setBuilderRequiresMask} className="scale-75 origin-right" />
                    </div>
                    <div className="flex items-center justify-between p-3 rounded-lg border border-border/70 bg-card">
                      <span className="text-xs font-medium">Tạo chat mới</span>
                      <Switch checked={builderCreateNewChat} onCheckedChange={setBuilderCreateNewChat} className="scale-75 origin-right" />
                    </div>
                    <div className="flex items-center justify-between p-3 rounded-lg border border-border/70 bg-card">
                      <span className="text-xs font-medium">Cho phép nhánh</span>
                      <Switch checked={builderAllowRegenerate} onCheckedChange={setBuilderAllowRegenerate} className="scale-75 origin-right" />
                    </div>
                  </div>

                  <div className="pt-4 border-t border-border/70">
                    <div className="flex items-center justify-between mb-4">
                      <div className="text-sm font-bold">Tham số động (Fields)</div>
                      <div className="flex gap-2">
                        <Button variant="outline" size="sm" className="h-7 text-xs rounded-full" onClick={() => handleAddBuilderField("text")}>+ Chữ</Button>
                        <Button variant="outline" size="sm" className="h-7 text-xs rounded-full" onClick={() => handleAddBuilderField("slider")}>+ Thanh trượt</Button>
                      </div>
                    </div>

                    <div className="space-y-3">
                      {builderFields.map((f, i) => (
                        <div key={f.key} className="flex gap-3 items-start p-3 rounded-lg border border-border/70 bg-card">
                          <div className="flex-1 space-y-3">
                            <div className="flex items-center justify-between">
                              <Badge variant="secondary" className="text-[10px] uppercase font-mono">{f.type}</Badge>
                              <span className="text-xs font-mono text-muted-foreground">{`{${f.key}}`}</span>
                            </div>
                            <Input 
                              value={f.label} 
                              onChange={e => setBuilderFields(builderFields.map((field, idx) => idx === i ? {...field, label: e.target.value} : field))}
                              className="h-8 text-sm border-transparent bg-muted/30 focus-visible:bg-background"
                              placeholder="Nhãn hiển thị..."
                            />
                          </div>
                          <Button variant="ghost" size="icon" className="h-8 w-8 text-destructive hover:bg-destructive/10" onClick={() => handleRemoveBuilderField(f.key)}>
                            ×
                          </Button>
                        </div>
                      ))}
                      {builderFields.length === 0 && <div className="text-sm text-muted-foreground text-center py-4 border border-dashed border-border rounded-lg">Chưa có tham số nào. Thêm tham số để tuỳ biến prompt.</div>}
                    </div>
                  </div>

                  <div className="pt-4 flex justify-end gap-3">
                    <Button variant="default" onClick={() => void handleCreateButton()} disabled={submitting}>Lưu công cụ</Button>
                  </div>
                </FieldGroup>
              </div>
            </TabsContent>

            <TabsContent value="profile" className="flex-1 flex flex-col m-0 p-6 items-center justify-center text-muted-foreground">
               <History className="size-12 mb-4 opacity-20" />
               <p>Tính năng lưu trữ Profile (Workflow) đang được phát triển.</p>
            </TabsContent>
          </Tabs>
        </CardContent>
      </Card>
    </div>
  );
}
