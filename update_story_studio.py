import re

with open("web/src/components/StoryStudio.tsx", "r") as f:
    code = f.read()

# 1. Add StoryMainTab type update
code = code.replace(
    'type StoryMainTab = "videos" | "collection" | "history";',
    'type StoryMainTab = "videos" | "collection" | "history" | "projects";'
)

# 2. Add projects state and handlers
state_injection = """ const [projects, setProjects] = useState<StoryProjectSummary[]>([]);
 const [activeProjectId, setActiveProjectId] = useLocalStorage<string | null>("story.activeProjectId", null);
 const [projectSearchQuery, setProjectSearchQuery] = useState("");
 
 const sortedProjects = useMemo(() => {
  if (!projectSearchQuery) return projects;
  return projects.filter(p => p.name.toLowerCase().includes(projectSearchQuery.toLowerCase()));
 }, [projects, projectSearchQuery]);

 const handleSelectProject = useCallback(async (projectId: string) => {
  try {
   const bootstrap = await selectStoryProject(projectId);
   setProjects(bootstrap.projects || []);
   setActiveProjectId(bootstrap.activeProjectId || null);
   setVideoSummaries(bootstrap.videoSummaries);
   setSelectedVideoId(bootstrap.activeVideoId || bootstrap.videoSummaries[0]?.id || null);
  } catch (error) {
   toast.error(getErrorMessage(error));
  }
 }, [setActiveProjectId, setSelectedVideoId]);

 const handleRenameProject = useCallback(async (projectId: string, currentName: string) => {
  const newName = window.prompt("Nhập tên mới cho dự án:", currentName);
  if (!newName || newName === currentName) return;
  try {
   const bootstrap = await renameStoryProject(projectId, newName);
   setProjects(bootstrap.projects || []);
  } catch (error) {
   toast.error(getErrorMessage(error));
  }
 }, []);

 const handleDeleteProject = useCallback(async (projectId: string) => {
  if (!window.confirm("Bạn có chắc chắn muốn xóa dự án này?")) return;
  try {
   const bootstrap = await deleteStoryProject(projectId);
   setProjects(bootstrap.projects || []);
   setActiveProjectId(bootstrap.activeProjectId || null);
   setVideoSummaries(bootstrap.videoSummaries);
   setSelectedVideoId(bootstrap.activeVideoId || bootstrap.videoSummaries[0]?.id || null);
  } catch (error) {
   toast.error(getErrorMessage(error));
  }
 }, [setActiveProjectId, setSelectedVideoId]);
 
 const [selectedExportKeys, setSelectedExportKeys]"""

code = code.replace(" const [selectedExportKeys, setSelectedExportKeys]", state_injection)

# 3. Update init()
init_old = """    setSessionStatus(bootstrap.sessionStatus);
    setVideoSummaries(bootstrap.videoSummaries);"""
init_new = """    setSessionStatus(bootstrap.sessionStatus);
    setProjects(bootstrap.projects || []);
    setActiveProjectId(bootstrap.activeProjectId || null);
    setVideoSummaries(bootstrap.videoSummaries);"""
code = code.replace(init_old, init_new)

# 4. Add "Dự án" tab header
header_old = """      <TabsList className="bg-muted/50 p-1 border border-border/50">
       <TabsTrigger value="videos" className="h-7 px-3 text-[11px] font-medium ">Video ({videoSummaries.length})</TabsTrigger>
       <TabsTrigger value="collection" className="h-7 px-3 text-[11px] font-medium ">Bộ sưu tập</TabsTrigger>
       <TabsTrigger value="history" className="h-7 px-3 text-[11px] font-medium ">Lịch sử</TabsTrigger>
      </TabsList>"""
header_new = """      <TabsList className="bg-muted/50 p-1 border border-border/50">
       <TabsTrigger value="projects" className="h-7 px-3 text-[11px] font-medium ">Dự án</TabsTrigger>
       <TabsTrigger value="videos" className="h-7 px-3 text-[11px] font-medium ">Video ({videoSummaries.length})</TabsTrigger>
       <TabsTrigger value="collection" className="h-7 px-3 text-[11px] font-medium ">Bộ sưu tập</TabsTrigger>
       <TabsTrigger value="history" className="h-7 px-3 text-[11px] font-medium ">Lịch sử</TabsTrigger>
      </TabsList>"""
code = code.replace(header_old, header_new)

# 5. Add "Dự án" tab content
# Need to insert right after `<TabsContent value="videos"` block. Wait, I can insert it BEFORE `<TabsContent value="videos"`.
tab_content_old = """     <CardContent className="flex-1 flex flex-col min-h-0 gap-4 p-4 pt-2 overflow-hidden">
     <Tabs value={mainPanelTab} className="flex-1 flex flex-col min-h-0">
      <TabsContent value="videos" className="flex-1 flex flex-col gap-4">"""

tab_content_new = """     <CardContent className="flex-1 flex flex-col min-h-0 gap-4 p-4 pt-2 overflow-hidden">
     <Tabs value={mainPanelTab} className="flex-1 flex flex-col min-h-0">
      <TabsContent value="projects" className="flex-1 flex flex-col gap-4">
        <ScrollArea className="h-full">
         <div className="space-y-3 pr-3">
          <div className="flex items-center gap-2">
           <div className="relative flex-1 group">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 size-3.5 text-muted-foreground" />
            <Input placeholder="Tìm dự án..." className="h-9 pl-9 rounded-xl border-border/50 bg-muted/20" value={projectSearchQuery} onChange={e => setProjectSearchQuery(e.target.value)} />
           </div>
           <Button
             variant="outline"
             size="icon"
             className="h-9 w-9 rounded-xl shrink-0 bg-card border-border/50 hover:border-primary/50 hover:bg-primary/5 shadow-sm"
             onClick={handleChooseSourceFolder}
             title="Tạo dự án mới từ thư mục"
           >
            <Plus className="size-4" />
           </Button>
          </div>
          {sortedProjects.map(p => (
           <div key={p.id} className="relative group">
            <button
             onClick={() => void handleSelectProject(p.id)}
             className={`w-full flex items-center gap-3 p-3 rounded-2xl border transition-all text-left active:scale-[0.98] ${
              activeProjectId === p.id
               ? "border-primary bg-primary/5 ring-1 ring-primary/20"
               : "border-border/50 bg-card hover:border-primary/30 hover:bg-muted/30"
             }`}
            >
             <div className="size-10 rounded-lg bg-black/20 border border-border/20 flex items-center justify-center shrink-0">
               <FolderTree className="size-5 text-muted-foreground" />
             </div>
             <div className="flex-1 min-w-0">
              <div className="text-sm font-semibold truncate text-foreground/90">{p.name}</div>
              <div className="mt-0.5 flex items-center gap-2 text-xs text-muted-foreground">
               <span className="truncate max-w-[200px]">{p.folderPath}</span>
               <span>•</span>
               <span>{p.videoCount} videos</span>
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

      <TabsContent value="videos" className="flex-1 flex flex-col gap-4">"""
code = code.replace(tab_content_old, tab_content_new)

# 6. Imports
imports_old = """import { listStoryGems } from "@/lib/api";"""
imports_new = """import { listStoryGems, selectStoryProject, renameStoryProject, deleteStoryProject } from "@/lib/api";
import { StoryProjectSummary } from "@/lib/api";"""
code = code.replace(imports_old, imports_new)

# 7. Add FolderTree and Pencil
code = code.replace("Plus,", "Plus, FolderTree, Pencil,")

with open("web/src/components/StoryStudio.tsx", "w") as f:
    f.write(code)

