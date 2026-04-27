import React, { useEffect, useRef, useState, useCallback } from "react";
import { Eraser, MousePointer2, Paintbrush, Redo2, Undo2, ZoomIn, ZoomOut, Maximize } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Slider } from "@/components/ui/slider";
import { cn } from "@/lib/utils";

interface MaskCanvasProps {
  imageUrl: string;
  onMaskChange?: (base64: string | null) => void;
  className?: string;
  isSubmitting?: boolean;
}

type Point = { x: number; y: number };

export default function MaskCanvas({ imageUrl, onMaskChange, className, isSubmitting }: MaskCanvasProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const imageRef = useRef<HTMLImageElement>(null);

  // Tools state
  const [tool, setTool] = useState<"brush" | "eraser" | "pan">("brush");
  const [brushSize, setBrushSize] = useState(45);
  const [brushOpacity, setBrushOpacity] = useState(80);
  const [brushHardness, setBrushHardness] = useState(60); 
  const [maskColor, setMaskColor] = useState("#FF0000");

  // Viewport state
  const [scale, setScale] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [isPanning, setIsPanning] = useState(false);
  const panStartRef = useRef<Point>({ x: 0, y: 0 });

  // Drawing state
  const [isDrawing, setIsDrawing] = useState(false);
  const lastPosRef = useRef<Point | null>(null);

  // History state
  const [history, setHistory] = useState<ImageData[]>([]);
  const [historyIndex, setHistoryIndex] = useState(-1);

  const fitToScreen = useCallback(() => {
    if (!containerRef.current || !canvasRef.current || !imageRef.current) return;
    
    const container = containerRef.current;
    const canvas = canvasRef.current;
    
    // Ensure container has size
    if (container.clientWidth === 0 || container.clientHeight === 0) {
        // Retry in next frame
        requestAnimationFrame(fitToScreen);
        return;
    }

    const padding = 60;
    const scaleX = (container.clientWidth - padding) / canvas.width;
    const scaleY = (container.clientHeight - padding) / canvas.height;
    
    const newScale = Math.min(scaleX, scaleY, 1);
    setScale(newScale > 0 ? newScale : 1);
    setPan({ x: 0, y: 0 });
  }, []);

  // Initialize canvas when image loads
  useEffect(() => {
    if (!imageUrl || !canvasRef.current || !imageRef.current) return;
    
    const img = imageRef.current;
    const handleLoad = () => {
      if (canvasRef.current && img) {
        canvasRef.current.width = img.naturalWidth;
        canvasRef.current.height = img.naturalHeight;
        const ctx = canvasRef.current.getContext("2d");
        if (ctx) {
          ctx.clearRect(0, 0, canvasRef.current.width, canvasRef.current.height);
          saveHistoryState(ctx, canvasRef.current.width, canvasRef.current.height);
        }
        fitToScreen();
      }
    };

    if (img.complete) {
        handleLoad();
    } else {
        img.onload = handleLoad;
    }
  }, [imageUrl, fitToScreen]);

  // Re-fit on container resize
  useEffect(() => {
    if (!containerRef.current) return;
    const observer = new ResizeObserver(() => {
      fitToScreen();
    });
    observer.observe(containerRef.current);
    return () => observer.disconnect();
  }, [fitToScreen]);

  const saveHistoryState = (ctx: CanvasRenderingContext2D, width: number, height: number) => {
    const imageData = ctx.getImageData(0, 0, width, height);
    setHistory((prev) => {
      const newHistory = prev.slice(0, historyIndex + 1);
      newHistory.push(imageData);
      if (newHistory.length > 20) newHistory.shift(); 
      setHistoryIndex(newHistory.length - 1);
      return newHistory;
    });
  };

  const handleUndo = () => {
    if (historyIndex > 0 && canvasRef.current) {
      const newIndex = historyIndex - 1;
      const ctx = canvasRef.current.getContext("2d");
      if (ctx) {
        ctx.putImageData(history[newIndex], 0, 0);
        setHistoryIndex(newIndex);
        notifyMaskChange();
      }
    }
  };

  const handleRedo = () => {
    if (historyIndex < history.length - 1 && canvasRef.current) {
      const newIndex = historyIndex + 1;
      const ctx = canvasRef.current.getContext("2d");
      if (ctx) {
        ctx.putImageData(history[newIndex], 0, 0);
        setHistoryIndex(newIndex);
        notifyMaskChange();
      }
    }
  };

  const handleClear = () => {
    if (!canvasRef.current) return;
    const ctx = canvasRef.current.getContext("2d");
    if (ctx) {
      ctx.clearRect(0, 0, canvasRef.current.width, canvasRef.current.height);
      saveHistoryState(ctx, canvasRef.current.width, canvasRef.current.height);
      notifyMaskChange();
    }
  };

  const notifyMaskChange = () => {
    if (!canvasRef.current || !onMaskChange) return;
    const ctx = canvasRef.current.getContext("2d");
    if (!ctx) return;
    const data = ctx.getImageData(0, 0, canvasRef.current.width, canvasRef.current.height).data;
    let isEmpty = true;
    for (let i = 3; i < data.length; i += 4) {
      if (data[i] !== 0) {
        isEmpty = false;
        break;
      }
    }
    if (isEmpty) {
      onMaskChange(null);
    } else {
      onMaskChange(canvasRef.current.toDataURL("image/png"));
    }
  };

  const getCanvasPoint = (e: React.PointerEvent<HTMLDivElement>): Point | null => {
    if (!canvasRef.current || !containerRef.current) return null;
    const rect = canvasRef.current.getBoundingClientRect();
    return {
      x: (e.clientX - rect.left) * (canvasRef.current.width / rect.width),
      y: (e.clientY - rect.top) * (canvasRef.current.height / rect.height)
    };
  };

  const handlePointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    if (tool === "pan" || e.button === 1 || e.button === 2) {
      setIsPanning(true);
      panStartRef.current = { x: e.clientX - pan.x, y: e.clientY - pan.y };
      return;
    }

    const point = getCanvasPoint(e);
    if (!point || !canvasRef.current) return;

    setIsDrawing(true);
    lastPosRef.current = point;
    
    const ctx = canvasRef.current.getContext("2d");
    if (ctx) {
      ctx.beginPath();
      ctx.arc(point.x, point.y, brushSize / 2, 0, Math.PI * 2);
      ctx.fillStyle = maskColor;
      ctx.globalAlpha = brushOpacity / 100;
      ctx.globalCompositeOperation = tool === "eraser" ? "destination-out" : "source-over";
      
      const blur = Math.max(0, (100 - brushHardness) / 2);
      ctx.shadowBlur = blur;
      ctx.shadowColor = tool === "eraser" ? "transparent" : maskColor;
      
      ctx.fill();
      ctx.closePath();
    }
  };

  const handlePointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    if (isPanning) {
      setPan({
        x: e.clientX - panStartRef.current.x,
        y: e.clientY - panStartRef.current.y
      });
      return;
    }

    if (!isDrawing || !lastPosRef.current || !canvasRef.current) return;
    const point = getCanvasPoint(e);
    if (!point) return;

    const ctx = canvasRef.current.getContext("2d");
    if (ctx) {
      ctx.beginPath();
      ctx.moveTo(lastPosRef.current.x, lastPosRef.current.y);
      ctx.lineTo(point.x, point.y);
      ctx.strokeStyle = maskColor;
      ctx.lineWidth = brushSize;
      ctx.lineCap = "round";
      ctx.lineJoin = "round";
      ctx.globalAlpha = brushOpacity / 100;
      ctx.globalCompositeOperation = tool === "eraser" ? "destination-out" : "source-over";
      
      const blur = Math.max(0, (100 - brushHardness) / 2);
      ctx.shadowBlur = blur;
      ctx.shadowColor = tool === "eraser" ? "transparent" : maskColor;
      
      ctx.stroke();
      ctx.closePath();
      
      lastPosRef.current = point;
    }
  };

  const handlePointerUp = () => {
    if (isPanning) {
      setIsPanning(false);
      return;
    }
    if (isDrawing && canvasRef.current) {
      setIsDrawing(false);
      lastPosRef.current = null;
      const ctx = canvasRef.current.getContext("2d");
      if (ctx) {
        saveHistoryState(ctx, canvasRef.current.width, canvasRef.current.height);
        notifyMaskChange();
      }
    }
  };

  const handleWheel = (e: React.WheelEvent) => {
    if (e.ctrlKey || e.metaKey) {
      e.preventDefault();
      const zoomSensitivity = 0.001;
      const delta = -e.deltaY * zoomSensitivity;
      setScale((s) => Math.min(Math.max(0.1, s + delta), 5));
    }
  };

  return (
    <div className={cn("relative flex h-full w-full flex-col bg-muted/10", className)}>
      {/* Top Toolbar */}
      <div className="absolute top-4 left-1/2 z-10 flex -translate-x-1/2 items-center gap-1 rounded-full border border-border/50 bg-background/95 p-1.5 shadow-sm backdrop-blur">
        <Button variant="ghost" size="icon" className="h-8 w-8 rounded-full" onClick={handleUndo} disabled={historyIndex <= 0 || isSubmitting}>
          <Undo2 className="h-4 w-4" />
        </Button>
        <Button variant="ghost" size="icon" className="h-8 w-8 rounded-full" onClick={handleRedo} disabled={historyIndex >= history.length - 1 || isSubmitting}>
          <Redo2 className="h-4 w-4" />
        </Button>
        <div className="mx-2 h-4 w-px bg-border" />
        <Button variant={tool === "pan" ? "secondary" : "ghost"} size="icon" className="h-8 w-8 rounded-full" onClick={() => setTool("pan")}>
          <MousePointer2 className="h-4 w-4" />
        </Button>
        <Button variant="ghost" size="icon" className="h-8 w-8 rounded-full" onClick={() => setScale(s => Math.max(0.1, s - 0.2))}>
          <ZoomOut className="h-4 w-4" />
        </Button>
        <span className="w-12 text-center text-xs font-medium tabular-nums">{Math.round(scale * 100)}%</span>
        <Button variant="ghost" size="icon" className="h-8 w-8 rounded-full" onClick={() => setScale(s => Math.min(5, s + 0.2))}>
          <ZoomIn className="h-4 w-4" />
        </Button>
        <Button variant="ghost" size="icon" className="h-8 w-8 rounded-full" onClick={fitToScreen}>
          <Maximize className="h-4 w-4" />
        </Button>
      </div>

      {/* Right Panel - Tools */}
      <div className="absolute top-4 right-4 z-10 flex w-64 flex-col gap-4 rounded-xl border border-border/50 bg-background/95 p-4 shadow-sm backdrop-blur">
        <div className="text-xs font-bold uppercase tracking-wider text-muted-foreground">Công cụ vẽ (Mask)</div>
        
        <div className="flex gap-2">
          <Button variant={tool === "brush" ? "default" : "secondary"} className="flex-1" size="sm" onClick={() => setTool("brush")}>
            <Paintbrush className="mr-2 h-4 w-4" /> Vẽ
          </Button>
          <Button variant={tool === "eraser" ? "default" : "secondary"} className="flex-1" size="sm" onClick={() => setTool("eraser")}>
            <Eraser className="mr-2 h-4 w-4" /> Tẩy
          </Button>
        </div>

        <div className="space-y-4 pt-2">
          <div className="space-y-2">
            <div className="flex items-center justify-between text-xs">
              <span>Kích thước</span>
              <span className="font-mono text-muted-foreground">{brushSize}px</span>
            </div>
            <Slider value={[brushSize]} min={5} max={200} step={1} onValueChange={(v: number[]) => setBrushSize(v[0])} />
          </div>

          <div className="space-y-2">
            <div className="flex items-center justify-between text-xs">
              <span>Độ cứng</span>
              <span className="font-mono text-muted-foreground">{brushHardness}%</span>
            </div>
            <Slider value={[brushHardness]} min={0} max={100} step={1} onValueChange={(v: number[]) => setBrushHardness(v[0])} />
          </div>

          <div className="space-y-2">
            <div className="flex items-center justify-between text-xs">
              <span>Độ mờ</span>
              <span className="font-mono text-muted-foreground">{brushOpacity}%</span>
            </div>
            <Slider value={[brushOpacity]} min={10} max={100} step={1} onValueChange={(v: number[]) => setBrushOpacity(v[0])} />
          </div>

          <div className="flex items-center justify-between border-t border-border/50 pt-4">
            <span className="text-xs font-medium">Màu Mask</span>
            <div className="flex items-center gap-2">
              <div className="relative group cursor-pointer">
                <div 
                  className="h-6 w-6 rounded-full shadow-inner border border-white/20" 
                  style={{ backgroundColor: maskColor }} 
                />
                <input 
                  type="color" 
                  value={maskColor}
                  onChange={(e) => setMaskColor(e.target.value)}
                  className="absolute inset-0 opacity-0 cursor-pointer w-full h-full"
                />
              </div>
              <span className="text-[10px] font-mono uppercase text-muted-foreground">{maskColor}</span>
            </div>
          </div>
        </div>

        <Button variant="outline" size="sm" className="mt-2 w-full text-destructive hover:bg-destructive/10" onClick={handleClear} disabled={isSubmitting}>
          Xóa tất cả mask
        </Button>
      </div>

      {/* Canvas Area */}
      <div 
        ref={containerRef}
        className="relative flex-1 overflow-hidden flex items-center justify-center"
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onPointerLeave={handlePointerUp}
        onWheel={handleWheel}
        style={{ touchAction: "none" }}
      >
        <div 
          className="relative transition-transform duration-75 ease-out"
          style={{ 
            transform: `translate(${pan.x}px, ${pan.y}px) scale(${scale})`,
          }}
        >
          <img 
            ref={imageRef} 
            src={imageUrl}
            className="pointer-events-none block" 
            alt="Canvas background" 
            onError={() => console.error("Failed to load image:", imageUrl)}
          />
          <canvas 
            ref={canvasRef} 
            className={cn(
              "absolute left-0 top-0 block", 
              tool === "pan" ? "cursor-grab active:cursor-grabbing" : "cursor-crosshair"
            )} 
          />
        </div>
      </div>
    </div>
  );
}
