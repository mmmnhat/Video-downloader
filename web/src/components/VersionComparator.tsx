import React, { useState, useRef, useEffect } from "react";
import { X, Maximize2, MoveHorizontal } from "lucide-react";
import { Button } from "@/components/ui/button";

interface VersionComparatorProps {
  beforeUrl: string;
  afterUrl: string;
  beforeLabel?: string;
  afterLabel?: string;
  onClose: () => void;
}

export default function VersionComparator({
  beforeUrl,
  afterUrl,
  beforeLabel = "Gốc",
  afterLabel = "Đã sửa",
  onClose
}: VersionComparatorProps) {
  const [sliderPos, setSliderPos] = useState(50);
  const containerRef = useRef<HTMLDivElement>(null);

  const handleMove = (e: React.MouseEvent | React.TouchEvent) => {
    if (!containerRef.current) return;
    
    const rect = containerRef.current.getBoundingClientRect();
    const x = "touches" in e ? e.touches[0].clientX : (e as React.MouseEvent).clientX;
    const position = ((x - rect.left) / rect.width) * 100;
    
    setSliderPos(Math.min(Math.max(position, 0), 100));
  };

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-background/95 backdrop-blur-xl animate-in fade-in duration-300">
      <div className="relative h-[90vh] w-[95vw] flex flex-col gap-4">
        {/* Header */}
        <div className="flex items-center justify-between px-4">
          <div className="flex items-center gap-3">
            <div className="size-8 rounded-lg bg-primary/10 text-primary flex items-center justify-center">
              <Maximize2 className="size-5" />
            </div>
            <div>
              <h2 className="text-lg font-bold tracking-tight">So sánh Version</h2>
              <p className="text-xs text-muted-foreground italic">Kéo thanh trượt để xem sự thay đổi</p>
            </div>
          </div>
          <Button variant="ghost" size="icon" className="rounded-full h-10 w-10" onClick={onClose}>
            <X className="size-6" />
          </Button>
        </div>

        {/* Slider Container */}
        <div 
          ref={containerRef}
          className="relative flex-1 cursor-ew-resize overflow-hidden rounded-2xl border border-border/50 bg-muted select-none"
          onMouseMove={handleMove}
          onTouchMove={handleMove}
        >
          {/* After Image (Full width) */}
          <img 
            src={afterUrl} 
            alt="After" 
            className="absolute inset-0 h-full w-full object-contain pointer-events-none"
          />

          {/* Before Image (Clipped) */}
          <div 
            className="absolute inset-0 h-full overflow-hidden border-r-2 border-primary/50 shadow-[4px_0_20px_rgba(0,0,0,0.3)] pointer-events-none"
            style={{ width: `${sliderPos}%` }}
          >
            <img 
              src={beforeUrl} 
              alt="Before" 
              className="h-full w-[95vw] object-contain max-w-none pointer-events-none"
              style={{ width: containerRef.current?.clientWidth }}
            />
            {/* Label Before */}
            <div className="absolute top-6 left-6 px-3 py-1.5 rounded-full bg-black/60 text-white text-[10px] font-bold uppercase tracking-widest backdrop-blur-md">
              {beforeLabel}
            </div>
          </div>

          {/* Label After */}
          <div className="absolute top-6 right-6 px-3 py-1.5 rounded-full bg-primary/60 text-white text-[10px] font-bold uppercase tracking-widest backdrop-blur-md">
            {afterLabel}
          </div>

          {/* Slider Handle */}
          <div 
            className="absolute inset-y-0 z-10 w-1 bg-primary pointer-events-none"
            style={{ left: `${sliderPos}%` }}
          >
            <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 size-10 rounded-full bg-primary text-white shadow-xl flex items-center justify-center ring-4 ring-primary/20">
              <MoveHorizontal className="size-6" />
            </div>
          </div>
        </div>

        {/* Footer info */}
        <div className="flex justify-center gap-12 text-[10px] font-bold uppercase tracking-widest text-muted-foreground/60">
           <div className="flex items-center gap-2"><div className="size-2 rounded-full bg-muted" /> Ảnh Gốc</div>
           <div className="flex items-center gap-2"><div className="size-2 rounded-full bg-primary" /> Kết quả Gemini</div>
        </div>
      </div>
    </div>
  );
}
