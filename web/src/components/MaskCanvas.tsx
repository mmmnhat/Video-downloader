import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Circle,
  Crop,
  Eraser,
  FlipHorizontal,
  FlipVertical,
  Frame,
  GripVertical,
  Maximize,
  MousePointer2,
  MoveDiagonal2,
  Paintbrush,
  Redo2,
  RotateCcw,
  RotateCw,
  Settings2,
  Square,
  Trash2 as TrashIcon,
  Undo2,
  ZoomIn,
  ZoomOut,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Slider } from "@/components/ui/slider";
import { useLocalStorage } from "@/hooks/use-local-storage";
import { cn } from "@/lib/utils";

interface MaskCanvasProps {
  imageUrl: string;
  onMaskChange?: (base64: string | null) => void;
  onGuideChange?: (guide: CanvasGuide | null) => void;
  className?: string;
  isSubmitting?: boolean;
  keepViewState?: boolean;
}

type Point = { x: number; y: number };
type Rect = { x: number; y: number; width: number; height: number };
type CanvasTool = "brush" | "eraser" | "pan" | "scale" | "crop" | "artboard" | "rect" | "ellipse";
type FrameTool = "crop" | "artboard";
type ShapeTool = "rect" | "ellipse";
type ToolGroup = "frame" | "shape";
type DockMode = "orb" | "rail" | "expanded";

type DraftModifiers = {
  centerBoth: boolean;
  centerSingleAxis: boolean;
  lockAspect: boolean;
};

type CanvasShape = {
  id: string;
  type: ShapeTool;
  rect: Rect;
  fill: string;
  opacity: number;
  hardness: number;
};

type HistorySnapshot = {
  maskData: ImageData | null;
  guide: CanvasGuide | null;
  shapes: CanvasShape[];
};

type OverlayInteraction =
  | {
      kind: "draft-guide";
      mode: FrameTool;
      start: Point;
      current: Point;
      modifiers: DraftModifiers;
    }
  | {
      kind: "move-guide";
      startPointer: Point;
      startRect: Rect;
      moved: boolean;
    }
  | {
      kind: "draft-shape";
      type: ShapeTool;
      start: Point;
      current: Point;
      modifiers: DraftModifiers;
    }
  | {
      kind: "move-shape";
      shapeId: string;
      startPointer: Point;
      startRect: Rect;
      moved: boolean;
    };

export type CanvasGuide = {
  mode: "crop" | "artboard";
  ratioLabel: string | null;
  rect: Rect;
};

type RatioPreset = {
  label: string;
  width: number;
  height: number;
};

const ARTBOARD_RATIOS: RatioPreset[] = [
  { label: "16:9", width: 16, height: 9 },
  { label: "4:5", width: 4, height: 5 },
  { label: "1:1", width: 1, height: 1 },
  { label: "3:4", width: 3, height: 4 },
  { label: "2:3", width: 2, height: 3 },
  { label: "9:16", width: 9, height: 16 },
  { label: "21:9", width: 21, height: 9 },
];

const MIN_SCALE = 0.1;
const MAX_SCALE = 5;

function clamp(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), max);
}

function cloneRect(rect: Rect): Rect {
  return { ...rect };
}

function cloneGuide(guide: CanvasGuide | null): CanvasGuide | null {
  if (!guide) return null;
  return {
    ...guide,
    rect: cloneRect(guide.rect),
  };
}

function cloneShapes(shapes: CanvasShape[]): CanvasShape[] {
  return shapes.map((shape) => ({
    ...shape,
    rect: cloneRect(shape.rect),
  }));
}

function cloneImageData(data: ImageData | null): ImageData | null {
  if (!data) return null;
  return new ImageData(new Uint8ClampedArray(data.data), data.width, data.height);
}

function pointInRect(point: Point, rect: Rect) {
  return (
    point.x >= rect.x &&
    point.x <= rect.x + rect.width &&
    point.y >= rect.y &&
    point.y <= rect.y + rect.height
  );
}

function getDraftModifiers(event: { shiftKey: boolean; altKey: boolean }, lockAspect: boolean): DraftModifiers {
  return {
    centerBoth: event.shiftKey,
    centerSingleAxis: !event.shiftKey && event.altKey,
    lockAspect,
  };
}

function getRectFromDrag(
  start: Point,
  current: Point,
  modifiers: DraftModifiers,
  ratio?: number | null,
) {
  const deltaX = current.x - start.x;
  const deltaY = current.y - start.y;
  const signX = deltaX >= 0 ? 1 : -1;
  const signY = deltaY >= 0 ? 1 : -1;
  let widthBase = Math.abs(deltaX);
  let heightBase = Math.abs(deltaY);

  if (modifiers.lockAspect) {
    const size = Math.max(widthBase, heightBase);
    widthBase = size;
    heightBase = size;
  } else if (ratio && ratio > 0) {
    if (widthBase === 0 && heightBase === 0) {
      widthBase = 0;
      heightBase = 0;
    } else if (widthBase / Math.max(heightBase, 1) > ratio) {
      heightBase = widthBase / ratio;
    } else {
      widthBase = heightBase * ratio;
    }
  }

  if (modifiers.centerBoth) {
    return {
      x: start.x - widthBase,
      y: start.y - heightBase,
      width: widthBase * 2,
      height: heightBase * 2,
    };
  }

  if (modifiers.centerSingleAxis) {
    if (widthBase >= heightBase) {
      return {
        x: start.x - widthBase,
        y: signY >= 0 ? start.y : start.y - heightBase,
        width: widthBase * 2,
        height: heightBase,
      };
    }
    return {
      x: signX >= 0 ? start.x : start.x - widthBase,
      y: start.y - heightBase,
      width: widthBase,
      height: heightBase * 2,
    };
  }

  return {
    x: signX >= 0 ? start.x : start.x - widthBase,
    y: signY >= 0 ? start.y : start.y - heightBase,
    width: widthBase,
    height: heightBase,
  };
}

function clampRectToImage(rect: Rect, width: number, height: number) {
  const nextWidth = Math.min(rect.width, width);
  const nextHeight = Math.min(rect.height, height);
  return {
    x: clamp(rect.x, 0, width - nextWidth),
    y: clamp(rect.y, 0, height - nextHeight),
    width: nextWidth,
    height: nextHeight,
  };
}

function isShapeVisibleInCanvas(shape: CanvasShape, width: number, height: number) {
  return (
    shape.rect.width > 0 &&
    shape.rect.height > 0 &&
    shape.rect.x < width &&
    shape.rect.y < height &&
    shape.rect.x + shape.rect.width > 0 &&
    shape.rect.y + shape.rect.height > 0
  );
}

function hasMaskPixels(data: ImageData | null) {
  if (!data) return false;
  for (let index = 3; index < data.data.length; index += 4) {
    if (data.data[index] !== 0) {
      return true;
    }
  }
  return false;
}

function drawShapeToContext(ctx: CanvasRenderingContext2D, shape: CanvasShape) {
  ctx.save();
  ctx.globalAlpha = shape.opacity / 100;
  ctx.globalCompositeOperation = "source-over";
  ctx.fillStyle = shape.fill;
  ctx.shadowBlur = Math.max(0, (100 - shape.hardness) / 2);
  ctx.shadowColor = shape.fill;

  if (shape.type === "rect") {
    ctx.fillRect(shape.rect.x, shape.rect.y, shape.rect.width, shape.rect.height);
    ctx.restore();
    return;
  }

  ctx.beginPath();
  ctx.ellipse(
    shape.rect.x + shape.rect.width / 2,
    shape.rect.y + shape.rect.height / 2,
    shape.rect.width / 2,
    shape.rect.height / 2,
    0,
    0,
    Math.PI * 2,
  );
  ctx.fill();
  ctx.closePath();
  ctx.restore();
}

export default function MaskCanvas({
  imageUrl,
  onMaskChange,
  onGuideChange,
  className,
  isSubmitting,
  keepViewState,
}: MaskCanvasProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const imageRef = useRef<HTMLImageElement>(null);
  const stageRef = useRef<HTMLDivElement>(null);

  const [tool, setTool] = useState<CanvasTool>("brush");
  const [frameTool, setFrameTool] = useState<FrameTool>("crop");
  const [shapeTool, setShapeTool] = useState<ShapeTool>("rect");
  const [brushSize, setBrushSize] = useState(45);
  const [brushOpacity, setBrushOpacity] = useState(80);
  const [brushHardness, setBrushHardness] = useState(60);
  const [maskColor, setMaskColor] = useState("#ff0000");
  const [selectedRatioLabel, setSelectedRatioLabel] = useState("16:9");
  const [imageSize, setImageSize] = useState({ width: 0, height: 0 });

  const [scale, setScale] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [viewRotation, setViewRotation] = useState(0);
  const [flipX, setFlipX] = useState(false);
  const [flipY, setFlipY] = useState(false);
  const [hasZoomed, setHasZoomed] = useState(false);

  const [isPanning, setIsPanning] = useState(false);
  const [isScaling, setIsScaling] = useState(false);
  const [isDrawing, setIsDrawing] = useState(false);
  const [overlayInteraction, setOverlayInteraction] = useState<OverlayInteraction | null>(null);
  const [guide, setGuide] = useState<CanvasGuide | null>(null);
  const [shapes, setShapes] = useState<CanvasShape[]>([]);
  const [selectedShapeId, setSelectedShapeId] = useState<string | null>(null);

  const [history, setHistory] = useState<HistorySnapshot[]>([]);
  const [historyIndex, setHistoryIndex] = useState(-1);
  const historyRef = useRef<HistorySnapshot[]>([]);
  const historyIndexRef = useRef(-1);

  const [dockMode, setDockMode] = useLocalStorage<DockMode>(
    "thumbnail.maskCanvas.dockMode",
    "expanded",
  );
  const [dockPos, setDockPos] = useState({ x: 20, y: 80 });
  const [isDraggingDock, setIsDraggingDock] = useState(false);
  const [dragOffset, setDragOffset] = useState({ x: 0, y: 0 });
  const [cyclingGroup, setCyclingGroup] = useState<ToolGroup | null>(null);
  const groupCycleTimerRef = useRef<number | null>(null);
  const dockClickTimerRef = useRef<number | null>(null);

  const panStartRef = useRef<Point>({ x: 0, y: 0 });
  const scaleStartRef = useRef({ y: 0, scale: 1 });
  const lastPosRef = useRef<Point | null>(null);
  const guideRef = useRef<CanvasGuide | null>(null);
  const shapesRef = useRef<CanvasShape[]>([]);

  const selectedRatio = useMemo(
    () => ARTBOARD_RATIOS.find((item) => item.label === selectedRatioLabel) ?? ARTBOARD_RATIOS[0],
    [selectedRatioLabel],
  );

  const activeFrameTool = tool === "crop" || tool === "artboard" ? tool : frameTool;
  const activeShapeTool = tool === "rect" || tool === "ellipse" ? tool : shapeTool;
  const activeRatio = selectedRatio.width / selectedRatio.height;

  useEffect(() => {
    guideRef.current = guide;
  }, [guide]);

  useEffect(() => {
    shapesRef.current = shapes;
  }, [shapes]);

  const updateHistoryState = useCallback((nextHistory: HistorySnapshot[], nextIndex: number) => {
    historyRef.current = nextHistory;
    historyIndexRef.current = nextIndex;
    setHistory(nextHistory);
    setHistoryIndex(nextIndex);
  }, []);

  const activateFrameTool = useCallback((nextTool: FrameTool) => {
    setFrameTool(nextTool);
    setTool(nextTool);
  }, []);

  const activateShapeTool = useCallback((nextTool: ShapeTool) => {
    setShapeTool(nextTool);
    setTool(nextTool);
  }, []);

  const fitToScreen = useCallback((force = false) => {
    if (!containerRef.current || !canvasRef.current || !imageRef.current) return;

    const container = containerRef.current;
    const canvas = canvasRef.current;
    if (container.clientWidth === 0 || container.clientHeight === 0) {
      requestAnimationFrame(() => fitToScreen(force));
      return;
    }

    const padding = 60;
    const scaleX = (container.clientWidth - padding) / canvas.width;
    const scaleY = (container.clientHeight - padding) / canvas.height;
    const nextScale = Math.min(scaleX, scaleY, 1);

    setScale(nextScale > 0 ? nextScale : 1);
    setPan({ x: 0, y: 0 });
    if (force) {
      setHasZoomed(false);
    }
  }, []);

  const readMaskData = useCallback(() => {
    if (!canvasRef.current) return null;
    const ctx = canvasRef.current.getContext("2d");
    if (!ctx) return null;
    return ctx.getImageData(0, 0, canvasRef.current.width, canvasRef.current.height);
  }, []);

  const restoreMaskData = useCallback((maskData: ImageData | null) => {
    if (!canvasRef.current) return;
    const ctx = canvasRef.current.getContext("2d");
    if (!ctx) return;
    ctx.clearRect(0, 0, canvasRef.current.width, canvasRef.current.height);
    if (maskData) {
      ctx.putImageData(maskData, 0, 0);
    }
  }, []);

  const buildMaskBase64 = useCallback((maskData: ImageData | null, shapeList: CanvasShape[]) => {
    if (!canvasRef.current || !onMaskChange) return null;
    const width = canvasRef.current.width;
    const height = canvasRef.current.height;
    const visibleShapes = shapeList.filter((shape) => isShapeVisibleInCanvas(shape, width, height));
    if (!hasMaskPixels(maskData) && visibleShapes.length === 0) {
      return null;
    }

    const outputCanvas = document.createElement("canvas");
    outputCanvas.width = width;
    outputCanvas.height = height;
    const outputCtx = outputCanvas.getContext("2d");
    if (!outputCtx) return null;

    if (maskData) {
      outputCtx.putImageData(maskData, 0, 0);
    }
    visibleShapes.forEach((shape) => drawShapeToContext(outputCtx, shape));
    return outputCanvas.toDataURL("image/png");
  }, [onMaskChange]);

  const notifyMaskChangeFrom = useCallback((maskData: ImageData | null, shapeList: CanvasShape[]) => {
    if (!onMaskChange) return;
    onMaskChange(buildMaskBase64(maskData, shapeList));
  }, [buildMaskBase64, onMaskChange]);

  const notifyMaskChange = useCallback(() => {
    notifyMaskChangeFrom(readMaskData(), shapesRef.current);
  }, [notifyMaskChangeFrom, readMaskData]);

  const createSnapshot = useCallback((
    maskData = readMaskData(),
    nextGuide: CanvasGuide | null = guideRef.current,
    nextShapes: CanvasShape[] = shapesRef.current,
  ): HistorySnapshot => ({
    maskData: cloneImageData(maskData),
    guide: cloneGuide(nextGuide),
    shapes: cloneShapes(nextShapes),
  }), [readMaskData]);

  const pushHistory = useCallback((
    maskData = readMaskData(),
    nextGuide: CanvasGuide | null = guideRef.current,
    nextShapes: CanvasShape[] = shapesRef.current,
  ) => {
    const snapshot = createSnapshot(maskData, nextGuide, nextShapes);
    const nextHistory = historyRef.current.slice(0, historyIndexRef.current + 1);
    nextHistory.push(snapshot);
    if (nextHistory.length > 30) {
      nextHistory.shift();
    }
    updateHistoryState(nextHistory, nextHistory.length - 1);
  }, [createSnapshot, readMaskData, updateHistoryState]);

  const replaceHistory = useCallback((
    maskData = readMaskData(),
    nextGuide: CanvasGuide | null = guideRef.current,
    nextShapes: CanvasShape[] = shapesRef.current,
  ) => {
    const snapshot = createSnapshot(maskData, nextGuide, nextShapes);
    updateHistoryState([snapshot], 0);
  }, [createSnapshot, readMaskData, updateHistoryState]);

  const restoreSnapshot = useCallback((snapshot: HistorySnapshot) => {
    restoreMaskData(snapshot.maskData);
    setGuide(cloneGuide(snapshot.guide));
    setShapes(cloneShapes(snapshot.shapes));
    setSelectedShapeId(null);
    setOverlayInteraction(null);
    notifyMaskChangeFrom(snapshot.maskData, snapshot.shapes);
  }, [notifyMaskChangeFrom, restoreMaskData]);

  useEffect(() => {
    if (!imageUrl || !canvasRef.current || !imageRef.current) return;

    const img = imageRef.current;
    const handleLoad = () => {
      if (!canvasRef.current) return;
      canvasRef.current.width = img.naturalWidth;
      canvasRef.current.height = img.naturalHeight;
      setImageSize({ width: img.naturalWidth, height: img.naturalHeight });
      restoreMaskData(null);
      const initialGuide = null;
      const initialShapes: CanvasShape[] = [];
      setGuide(initialGuide);
      setShapes(initialShapes);
      setSelectedShapeId(null);
      setOverlayInteraction(null);
      replaceHistory(null, initialGuide, initialShapes);
      notifyMaskChangeFrom(null, initialShapes);

      if (!keepViewState) {
        setViewRotation(0);
        setFlipX(false);
        setFlipY(false);
        fitToScreen(true);
      }
    };

    if (img.complete) {
      handleLoad();
    } else {
      img.onload = handleLoad;
    }
  }, [fitToScreen, imageUrl, keepViewState, notifyMaskChangeFrom, replaceHistory, restoreMaskData]);

  useEffect(() => {
    if (!containerRef.current || hasZoomed) return;
    const observer = new ResizeObserver(() => {
      if (!hasZoomed) fitToScreen();
    });
    observer.observe(containerRef.current);
    return () => observer.disconnect();
  }, [fitToScreen, hasZoomed]);

  useEffect(() => {
    onGuideChange?.(guide);
  }, [guide, onGuideChange]);

  const handleUndo = () => {
    if (historyIndexRef.current <= 0) return;
    const nextIndex = historyIndexRef.current - 1;
    const snapshot = historyRef.current[nextIndex];
    updateHistoryState(historyRef.current, nextIndex);
    restoreSnapshot(snapshot);
  };

  const handleRedo = () => {
    if (historyIndexRef.current >= historyRef.current.length - 1) return;
    const nextIndex = historyIndexRef.current + 1;
    const snapshot = historyRef.current[nextIndex];
    updateHistoryState(historyRef.current, nextIndex);
    restoreSnapshot(snapshot);
  };

  const handleClear = () => {
    restoreMaskData(null);
    const nextShapes: CanvasShape[] = [];
    setShapes(nextShapes);
    setSelectedShapeId(null);
    pushHistory(null, guideRef.current, nextShapes);
    notifyMaskChangeFrom(null, nextShapes);
  };

  const handleClearGuide = () => {
    if (!guideRef.current) return;
    setGuide(null);
    pushHistory(readMaskData(), null, shapesRef.current);
  };

  const resetView = () => {
    setViewRotation(0);
    setFlipX(false);
    setFlipY(false);
    fitToScreen(true);
  };

  const getWorkspacePoint = useCallback((e: React.PointerEvent<HTMLDivElement>): Point | null => {
    if (!canvasRef.current) return null;

    const canvasRect = canvasRef.current.getBoundingClientRect();
    const hasViewTransform = flipX || flipY || (((viewRotation % 360) + 360) % 360) !== 0;

    if (!hasViewTransform) {
      const relativeX = (e.clientX - canvasRect.left) / Math.max(canvasRect.width, 1);
      const relativeY = (e.clientY - canvasRect.top) / Math.max(canvasRect.height, 1);
      return {
        x: relativeX * canvasRef.current.width,
        y: relativeY * canvasRef.current.height,
      };
    }

    const centerX = canvasRect.left + canvasRect.width / 2;
    const centerY = canvasRect.top + canvasRect.height / 2;
    const dx = e.clientX - centerX;
    const dy = e.clientY - centerY;

    const normalizedRotation = ((viewRotation % 360) + 360) % 360;
    const usesSwappedAxes = normalizedRotation === 90 || normalizedRotation === 270;
    const baseSpan = usesSwappedAxes ? canvasRef.current.height : canvasRef.current.width;
    const scaleFromDom = baseSpan > 0 ? canvasRect.width / baseSpan : scale;
    const safeScale = scaleFromDom || scale || 1;

    const scaledX = dx / safeScale;
    const scaledY = dy / safeScale;

    const angle = (viewRotation * Math.PI) / 180;
    const rotatedX = scaledX * Math.cos(angle) + scaledY * Math.sin(angle);
    const rotatedY = -scaledX * Math.sin(angle) + scaledY * Math.cos(angle);
    const localX = rotatedX * (flipX ? -1 : 1);
    const localY = rotatedY * (flipY ? -1 : 1);

    return {
      x: localX + canvasRef.current.width / 2,
      y: localY + canvasRef.current.height / 2,
    };
  }, [flipX, flipY, scale, viewRotation]);

  const getImagePoint = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    const point = getWorkspacePoint(e);
    if (!point || !canvasRef.current) return null;
    if (
      point.x < 0 ||
      point.y < 0 ||
      point.x > canvasRef.current.width ||
      point.y > canvasRef.current.height
    ) {
      return null;
    }
    return point;
  }, [getWorkspacePoint]);

  const drawBrushDot = (ctx: CanvasRenderingContext2D, point: Point, currentTool: "brush" | "eraser") => {
    ctx.save();
    ctx.beginPath();
    ctx.arc(point.x, point.y, brushSize / 2, 0, Math.PI * 2);
    ctx.fillStyle = maskColor;
    ctx.globalAlpha = brushOpacity / 100;
    ctx.globalCompositeOperation = currentTool === "eraser" ? "destination-out" : "source-over";
    ctx.shadowBlur = Math.max(0, (100 - brushHardness) / 2);
    ctx.shadowColor = currentTool === "eraser" ? "transparent" : maskColor;
    ctx.fill();
    ctx.closePath();
    ctx.restore();
  };

  const findTopmostShapeAtPoint = useCallback((point: Point) => {
    for (let index = shapesRef.current.length - 1; index >= 0; index -= 1) {
      const shape = shapesRef.current[index];
      if (pointInRect(point, shape.rect)) {
        return shape;
      }
    }
    return null;
  }, []);

  const updateGuideDuringDrag = useCallback((point: Point, currentGuide: CanvasGuide, action: Extract<OverlayInteraction, { kind: "move-guide" }>) => {
    if (!canvasRef.current) return;
    const deltaX = point.x - action.startPointer.x;
    const deltaY = point.y - action.startPointer.y;
    const movedRect = {
      ...action.startRect,
      x: action.startRect.x + deltaX,
      y: action.startRect.y + deltaY,
    };
    const nextRect = currentGuide.mode === "crop"
      ? clampRectToImage(movedRect, canvasRef.current.width, canvasRef.current.height)
      : movedRect;
    const nextGuide = { ...currentGuide, rect: nextRect };
    guideRef.current = nextGuide;
    setGuide(nextGuide);
  }, []);

  const updateShapeDuringDrag = useCallback((point: Point, action: Extract<OverlayInteraction, { kind: "move-shape" }>) => {
    const deltaX = point.x - action.startPointer.x;
    const deltaY = point.y - action.startPointer.y;
    setShapes((current) => {
      const nextShapes = current.map((shape) =>
        shape.id === action.shapeId
          ? {
              ...shape,
              rect: {
                ...action.startRect,
                x: action.startRect.x + deltaX,
                y: action.startRect.y + deltaY,
              },
            }
          : shape,
      );
      shapesRef.current = nextShapes;
      return nextShapes;
    });
  }, []);

  const buildDraftGuide = useCallback((action: Extract<OverlayInteraction, { kind: "draft-guide" }>) => {
    if (!canvasRef.current) return null;
    const rawRect = getRectFromDrag(
      action.start,
      action.current,
      action.modifiers,
      action.mode === "artboard" ? activeRatio : null,
    );
    const nextRect = action.mode === "crop"
      ? clampRectToImage(rawRect, canvasRef.current.width, canvasRef.current.height)
      : rawRect;

    return {
      mode: action.mode,
      ratioLabel: action.mode === "artboard" ? selectedRatio.label : null,
      rect: nextRect,
    } satisfies CanvasGuide;
  }, [activeRatio, selectedRatio.label]);

  const buildDraftShape = useCallback((action: Extract<OverlayInteraction, { kind: "draft-shape" }>) => {
    return {
      id: "draft",
      type: action.type,
      rect: getRectFromDrag(action.start, action.current, action.modifiers, null),
      fill: maskColor,
      opacity: brushOpacity,
      hardness: brushHardness,
    } satisfies CanvasShape;
  }, [brushHardness, brushOpacity, maskColor]);

  const handlePointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    if (tool === "pan" || e.button === 1 || e.button === 2) {
      setIsPanning(true);
      panStartRef.current = { x: e.clientX - pan.x, y: e.clientY - pan.y };
      setHasZoomed(true);
      return;
    }

    if (tool === "scale") {
      setIsScaling(true);
      scaleStartRef.current = { y: e.clientY, scale };
      setHasZoomed(true);
      return;
    }

    const workspacePoint = getWorkspacePoint(e);
    if (!workspacePoint) return;

    if (tool === "crop" || tool === "artboard") {
      const currentGuide = guideRef.current;
      if (currentGuide && currentGuide.mode === tool && pointInRect(workspacePoint, currentGuide.rect)) {
        setOverlayInteraction({
          kind: "move-guide",
          startPointer: workspacePoint,
          startRect: cloneRect(currentGuide.rect),
          moved: false,
        });
        return;
      }

      const modifiers = getDraftModifiers(e, false);
      setOverlayInteraction({
        kind: "draft-guide",
        mode: tool,
        start: workspacePoint,
        current: workspacePoint,
        modifiers,
      });
      return;
    }

    if (tool === "rect" || tool === "ellipse") {
      const hitShape = findTopmostShapeAtPoint(workspacePoint);
      if (hitShape) {
        setSelectedShapeId(hitShape.id);
        setOverlayInteraction({
          kind: "move-shape",
          shapeId: hitShape.id,
          startPointer: workspacePoint,
          startRect: cloneRect(hitShape.rect),
          moved: false,
        });
        return;
      }

      setSelectedShapeId(null);
      setOverlayInteraction({
        kind: "draft-shape",
        type: tool,
        start: workspacePoint,
        current: workspacePoint,
        modifiers: getDraftModifiers(e, e.shiftKey),
      });
      return;
    }

    const point = getImagePoint(e);
    if (!point || !canvasRef.current) return;

    setIsDrawing(true);
    lastPosRef.current = point;
    const ctx = canvasRef.current.getContext("2d");
    if (ctx) {
      drawBrushDot(ctx, point, tool);
    }
  };

  const handlePointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    if (isPanning) {
      setPan({
        x: e.clientX - panStartRef.current.x,
        y: e.clientY - panStartRef.current.y,
      });
      return;
    }

    if (isScaling) {
      const delta = (scaleStartRef.current.y - e.clientY) * 0.004;
      setScale(clamp(scaleStartRef.current.scale + delta, MIN_SCALE, MAX_SCALE));
      return;
    }

    if (overlayInteraction) {
      const workspacePoint = getWorkspacePoint(e);
      if (!workspacePoint) return;

      if (overlayInteraction.kind === "draft-guide") {
        setOverlayInteraction({
          ...overlayInteraction,
          current: workspacePoint,
          modifiers: getDraftModifiers(e, false),
        });
        return;
      }

      if (overlayInteraction.kind === "draft-shape") {
        setOverlayInteraction({
          ...overlayInteraction,
          current: workspacePoint,
          modifiers: getDraftModifiers(e, e.shiftKey),
        });
        return;
      }

      if (overlayInteraction.kind === "move-guide" && guideRef.current) {
        updateGuideDuringDrag(workspacePoint, guideRef.current, overlayInteraction);
        setOverlayInteraction({ ...overlayInteraction, moved: true });
        return;
      }

      if (overlayInteraction.kind === "move-shape") {
        updateShapeDuringDrag(workspacePoint, overlayInteraction);
        setOverlayInteraction({ ...overlayInteraction, moved: true });
        return;
      }
    }

    const point = getImagePoint(e);
    if (!point || !isDrawing || !lastPosRef.current || !canvasRef.current) return;
    const ctx = canvasRef.current.getContext("2d");
    if (!ctx) return;

    ctx.save();
    ctx.beginPath();
    ctx.moveTo(lastPosRef.current.x, lastPosRef.current.y);
    ctx.lineTo(point.x, point.y);
    ctx.strokeStyle = maskColor;
    ctx.lineWidth = brushSize;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.globalAlpha = brushOpacity / 100;
    ctx.globalCompositeOperation = tool === "eraser" ? "destination-out" : "source-over";
    ctx.shadowBlur = Math.max(0, (100 - brushHardness) / 2);
    ctx.shadowColor = tool === "eraser" ? "transparent" : maskColor;
    ctx.stroke();
    ctx.closePath();
    ctx.restore();
    lastPosRef.current = point;
  };

  const handlePointerUp = () => {
    if (isPanning) {
      setIsPanning(false);
      return;
    }

    if (isScaling) {
      setIsScaling(false);
      return;
    }

    if (overlayInteraction) {
      if (overlayInteraction.kind === "draft-guide") {
        const nextGuide = buildDraftGuide(overlayInteraction);
        setOverlayInteraction(null);
        if (!nextGuide || nextGuide.rect.width < 2 || nextGuide.rect.height < 2) {
          return;
        }
        setGuide(nextGuide);
        pushHistory(readMaskData(), nextGuide, shapesRef.current);
        return;
      }

      if (overlayInteraction.kind === "move-guide") {
        setOverlayInteraction(null);
        if (overlayInteraction.moved && guideRef.current) {
          pushHistory(readMaskData(), guideRef.current, shapesRef.current);
        }
        return;
      }

      if (overlayInteraction.kind === "draft-shape") {
        const nextShape = buildDraftShape(overlayInteraction);
        setOverlayInteraction(null);
        if (nextShape.rect.width < 2 || nextShape.rect.height < 2) {
          return;
        }
        const nextShapes = [...shapesRef.current, nextShape];
        setShapes(nextShapes);
        setSelectedShapeId(nextShape.id);
        pushHistory(readMaskData(), guideRef.current, nextShapes);
        notifyMaskChangeFrom(readMaskData(), nextShapes);
        return;
      }

      if (overlayInteraction.kind === "move-shape") {
        setOverlayInteraction(null);
        if (overlayInteraction.moved) {
          pushHistory(readMaskData(), guideRef.current, shapesRef.current);
          notifyMaskChange();
        }
        return;
      }
    }

    if (isDrawing && canvasRef.current) {
      setIsDrawing(false);
      lastPosRef.current = null;
      const maskData = readMaskData();
      pushHistory(maskData, guideRef.current, shapesRef.current);
      notifyMaskChangeFrom(maskData, shapesRef.current);
    }
  };

  const handleWheel = (e: React.WheelEvent) => {
    if (e.ctrlKey || e.metaKey) {
      e.preventDefault();
      const delta = -e.deltaY * 0.001;
      setScale((currentScale) => clamp(currentScale + delta, MIN_SCALE, MAX_SCALE));
      setHasZoomed(true);
    }
  };

  const handleDockDragStart = (e: React.PointerEvent) => {
    if (!containerRef.current) return;
    setIsDraggingDock(true);
    const containerRect = containerRef.current.getBoundingClientRect();
    setDragOffset({
      x: (containerRect.right - e.clientX) - dockPos.x,
      y: (e.clientY - containerRect.top) - dockPos.y,
    });
    e.stopPropagation();
  };

  const handleGlobalPointerMove = useCallback((e: PointerEvent) => {
    if (!isDraggingDock || !containerRef.current) return;
    const containerRect = containerRef.current.getBoundingClientRect();
    const newRight = (containerRect.right - e.clientX) - dragOffset.x;
    const newTop = (e.clientY - containerRect.top) - dragOffset.y;
    const dockWidth = dockMode === "orb" ? 64 : dockMode === "rail" ? 92 : 356;
    const dockHeight = dockMode === "orb" ? 64 : dockMode === "rail" ? 430 : 620;

    setDockPos({
      x: Math.max(10, Math.min(containerRect.width - dockWidth - 10, newRight)),
      y: Math.max(10, Math.min(containerRect.height - dockHeight - 10, newTop)),
    });
  }, [dockMode, dragOffset.x, dragOffset.y, isDraggingDock]);

  const handleGlobalPointerUp = useCallback(() => {
    setIsDraggingDock(false);
  }, []);

  useEffect(() => {
    if (!isDraggingDock) return undefined;
    window.addEventListener("pointermove", handleGlobalPointerMove);
    window.addEventListener("pointerup", handleGlobalPointerUp);
    return () => {
      window.removeEventListener("pointermove", handleGlobalPointerMove);
      window.removeEventListener("pointerup", handleGlobalPointerUp);
    };
  }, [handleGlobalPointerMove, handleGlobalPointerUp, isDraggingDock]);

  const startGroupCycle = (group: ToolGroup) => {
    if (groupCycleTimerRef.current) {
      window.clearTimeout(groupCycleTimerRef.current);
    }
    groupCycleTimerRef.current = window.setTimeout(() => {
      setCyclingGroup(group);
    }, 220);
  };

  const stopGroupCycle = () => {
    if (groupCycleTimerRef.current) {
      window.clearTimeout(groupCycleTimerRef.current);
      groupCycleTimerRef.current = null;
    }
    setCyclingGroup(null);
  };

  useEffect(() => {
    return () => {
      if (dockClickTimerRef.current) {
        window.clearTimeout(dockClickTimerRef.current);
      }
    };
  }, []);

  const handleDockSingleClick = useCallback(() => {
    if (dockClickTimerRef.current) {
      window.clearTimeout(dockClickTimerRef.current);
    }
    dockClickTimerRef.current = window.setTimeout(() => {
      setDockMode((current) => {
        if (current === "orb") return "rail";
        if (current === "rail") return "orb";
        return "rail";
      });
      dockClickTimerRef.current = null;
    }, 180);
  }, [setDockMode]);

  const handleDockDoubleClick = useCallback(() => {
    if (dockClickTimerRef.current) {
      window.clearTimeout(dockClickTimerRef.current);
      dockClickTimerRef.current = null;
    }
    setDockMode("expanded");
  }, [setDockMode]);

  const handleGroupWheel = (group: ToolGroup, e: React.WheelEvent) => {
    if (cyclingGroup !== group) return;
    e.preventDefault();
    e.stopPropagation();

    if (group === "frame") {
      activateFrameTool(activeFrameTool === "crop" ? "artboard" : "crop");
      return;
    }

    activateShapeTool(activeShapeTool === "rect" ? "ellipse" : "rect");
  };

  const previewGuide = overlayInteraction?.kind === "draft-guide"
    ? buildDraftGuide(overlayInteraction)
    : guide;
  const previewShape = overlayInteraction?.kind === "draft-shape"
    ? buildDraftShape(overlayInteraction)
    : null;

  const renderGuideOverlay = (currentGuide: CanvasGuide | null) => {
    if (!currentGuide) return null;

    return (
      <div
        className={cn(
          "pointer-events-none absolute border-2 shadow-[0_0_0_9999px_rgba(0,0,0,0.32)]",
          currentGuide.mode === "artboard" ? "border-sky-400" : "border-amber-400",
        )}
        style={{
          left: currentGuide.rect.x,
          top: currentGuide.rect.y,
          width: currentGuide.rect.width,
          height: currentGuide.rect.height,
        }}
      >
        <div
          className={cn(
            "absolute left-2 top-2 rounded-full px-2 py-1 text-[9px] font-black uppercase tracking-[0.2em] text-white shadow-lg",
            currentGuide.mode === "artboard" ? "bg-sky-500/90" : "bg-amber-500/90",
          )}
        >
          {currentGuide.mode === "artboard" ? `Artboard ${currentGuide.ratioLabel}` : "Crop"}
        </div>
      </div>
    );
  };

  const renderShapeOverlay = (shape: CanvasShape, isSelected: boolean, isDraft = false) => (
    <div
      key={shape.id}
      className={cn(
        "pointer-events-none absolute border-2",
        shape.type === "ellipse" ? "rounded-full" : "rounded-none",
        isDraft ? "border-dashed" : "border-solid",
        isSelected && "ring-2 ring-white/70 ring-offset-2 ring-offset-black/30",
      )}
      style={{
        left: shape.rect.x,
        top: shape.rect.y,
        width: shape.rect.width,
        height: shape.rect.height,
        borderColor: shape.fill,
        backgroundColor: `${shape.fill}33`,
      }}
    />
  );

  const renderToolSettings = () => {
    const isPaintTool = tool === "brush" || tool === "eraser" || tool === "rect" || tool === "ellipse";
    const isFrameMode = tool === "crop" || tool === "artboard";

    return (
      <div className="space-y-4">
        <div className="rounded-2xl border border-border/40 bg-muted/20 p-3">
          <div className="mb-3 flex items-center justify-between">
            <div>
              <p className="text-[10px] font-black uppercase tracking-[0.22em] text-foreground/70">Tool Active</p>
              <p className="text-sm font-semibold text-foreground">
                {{
                  brush: "Brush",
                  eraser: "Eraser",
                  pan: "Pan",
                  scale: "Transform",
                  crop: "Crop",
                  artboard: "Artboard",
                  rect: "Shape Rect",
                  ellipse: "Shape Circle",
                }[tool]}
              </p>
            </div>
            {isFrameMode && (
              <span className="rounded-full bg-primary/10 px-2 py-1 text-[10px] font-bold text-primary">
                {tool === "artboard" ? selectedRatio.label : "free"}
              </span>
            )}
          </div>

          <p className="text-[11px] leading-relaxed text-muted-foreground">
            {tool === "pan" && "Kéo để di chuyển canvas. Giữ chuột giữa hoặc chuột phải cũng pan được."}
            {tool === "scale" && "Kéo lên xuống để zoom. Flip và rotate cũng được gom trong tool Transform này."}
            {tool === "crop" && "Click kéo để tạo crop từ vị trí chuột. Kéo lên vùng crop hiện có để di chuyển."}
            {tool === "artboard" && "Artboard có thể vượt khỏi ảnh. Kéo vào artboard hiện có để di chuyển."}
            {tool === "rect" && "Click kéo để tạo shape mask. Kéo vào shape hiện có để di chuyển."}
            {tool === "ellipse" && "Click kéo để tạo shape tròn. Kéo vào shape hiện có để di chuyển."}
            {tool === "brush" && "Vẽ mask tự do lên vùng cần chỉnh sửa."}
            {tool === "eraser" && "Xóa mask ở vùng đã tô."}
          </p>

          {(tool === "crop" || tool === "artboard" || tool === "rect" || tool === "ellipse") && (
            <div className="mt-3 rounded-xl border border-border/30 bg-background/50 p-2 text-[10px] leading-relaxed text-muted-foreground">
              <div>`Shift`: bung đều 4 hướng từ điểm bấm.</div>
              <div>`Alt`: bung đều 2 hướng theo trục kéo mạnh hơn.</div>
            </div>
          )}
        </div>

        {tool === "artboard" && (
          <div className="space-y-2.5 rounded-2xl border border-border/40 bg-muted/10 p-3">
            <div className="flex items-center justify-between text-[10px] font-bold uppercase text-muted-foreground/80">
              <span>Tỉ lệ artboard</span>
              <span className="rounded bg-primary/10 px-1.5 py-0.5 font-mono text-primary">{selectedRatio.label}</span>
            </div>
            <div className="grid grid-cols-3 gap-2">
              {ARTBOARD_RATIOS.map((ratio) => (
                <Button
                  key={ratio.label}
                  variant={selectedRatio.label === ratio.label ? "default" : "outline"}
                  size="sm"
                  className="h-8 rounded-xl text-[10px] font-bold"
                  onClick={() => {
                    setSelectedRatioLabel(ratio.label);
                    if (guideRef.current?.mode === "artboard") {
                      const currentGuide = guideRef.current;
                      const centerX = currentGuide.rect.x + currentGuide.rect.width / 2;
                      const centerY = currentGuide.rect.y + currentGuide.rect.height / 2;
                      let nextWidth = currentGuide.rect.width;
                      let nextHeight = currentGuide.rect.height;
                      const nextRatio = ratio.width / ratio.height;
                      if (nextWidth / Math.max(nextHeight, 1) > nextRatio) {
                        nextHeight = nextWidth / nextRatio;
                      } else {
                        nextWidth = nextHeight * nextRatio;
                      }
                      const nextGuide = {
                        ...currentGuide,
                        ratioLabel: ratio.label,
                        rect: {
                          x: centerX - nextWidth / 2,
                          y: centerY - nextHeight / 2,
                          width: nextWidth,
                          height: nextHeight,
                        },
                      } satisfies CanvasGuide;
                      setGuide(nextGuide);
                      pushHistory(readMaskData(), nextGuide, shapesRef.current);
                    }
                  }}
                >
                  {ratio.label}
                </Button>
              ))}
            </div>
          </div>
        )}

        {tool === "scale" && (
          <div className="space-y-3 rounded-2xl border border-border/40 bg-muted/10 p-3">
            <div className="flex items-center justify-between text-[10px] font-bold uppercase text-muted-foreground/80">
              <span>Transform</span>
              <span className="rounded bg-primary/10 px-1.5 py-0.5 font-mono text-primary">
                {viewRotation}°
              </span>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <Button variant="outline" size="sm" className="h-9 rounded-xl text-[10px] font-black uppercase" onClick={() => setFlipX((current) => !current)}>
                <FlipHorizontal className="mr-1.5 h-3.5 w-3.5" />
                Flip X
              </Button>
              <Button variant="outline" size="sm" className="h-9 rounded-xl text-[10px] font-black uppercase" onClick={() => setFlipY((current) => !current)}>
                <FlipVertical className="mr-1.5 h-3.5 w-3.5" />
                Flip Y
              </Button>
              <Button variant="outline" size="sm" className="h-9 rounded-xl text-[10px] font-black uppercase" onClick={() => setViewRotation((current) => (current - 90 + 360) % 360)}>
                <RotateCcw className="mr-1.5 h-3.5 w-3.5" />
                -90
              </Button>
              <Button variant="outline" size="sm" className="h-9 rounded-xl text-[10px] font-black uppercase" onClick={() => setViewRotation((current) => (current + 90) % 360)}>
                <RotateCw className="mr-1.5 h-3.5 w-3.5" />
                +90
              </Button>
            </div>
          </div>
        )}

        {isPaintTool && (
          <div className="space-y-4 rounded-2xl border border-border/40 bg-muted/10 p-3">
            <div className="space-y-2.5">
              <div className="flex items-center justify-between text-[10px] font-bold uppercase text-muted-foreground/80">
                <span>Kích thước</span>
                <span className="rounded bg-primary/10 px-1.5 py-0.5 font-mono text-primary">{brushSize}px</span>
              </div>
              <Slider value={[brushSize]} min={5} max={200} step={1} onValueChange={([value]) => setBrushSize(value)} />
            </div>

            <div className="space-y-2.5">
              <div className="flex items-center justify-between text-[10px] font-bold uppercase text-muted-foreground/80">
                <span>Độ cứng</span>
                <span className="rounded bg-primary/10 px-1.5 py-0.5 font-mono text-primary">{brushHardness}%</span>
              </div>
              <Slider value={[brushHardness]} min={0} max={100} step={1} onValueChange={([value]) => setBrushHardness(value)} />
            </div>

            <div className="space-y-2.5">
              <div className="flex items-center justify-between text-[10px] font-bold uppercase text-muted-foreground/80">
                <span>Độ mờ</span>
                <span className="rounded bg-primary/10 px-1.5 py-0.5 font-mono text-primary">{brushOpacity}%</span>
              </div>
              <Slider value={[brushOpacity]} min={10} max={100} step={1} onValueChange={([value]) => setBrushOpacity(value)} />
            </div>

            <div className="flex items-center justify-between">
              <span className="text-[10px] font-black uppercase tracking-[0.18em] text-muted-foreground">Màu mask</span>
              <div className="relative h-7 w-7 overflow-hidden rounded-full border border-border shadow-inner">
                <div className="h-full w-full" style={{ backgroundColor: maskColor }} />
                <input
                  type="color"
                  value={maskColor}
                  onChange={(e) => setMaskColor(e.target.value)}
                  className="absolute inset-0 h-full w-full cursor-pointer opacity-0"
                />
              </div>
            </div>
          </div>
        )}

        <div className="grid grid-cols-2 gap-2">
          <Button
            variant="outline"
            size="sm"
            className="h-9 rounded-xl text-[10px] font-black uppercase"
            onClick={handleClearGuide}
            disabled={!guide}
          >
            Xóa guide
          </Button>
          <Button variant="outline" size="sm" className="h-9 rounded-xl text-[10px] font-black uppercase" onClick={resetView}>
            Reset view
          </Button>
        </div>

        <Button
          variant="ghost"
          size="sm"
          className="h-9 w-full rounded-xl text-[10px] font-black uppercase tracking-[0.22em] text-destructive/80 hover:bg-destructive/10 hover:text-destructive"
          onClick={handleClear}
          disabled={isSubmitting}
        >
          <TrashIcon className="mr-2 size-3" />
          Xóa tất cả mask
        </Button>
      </div>
    );
  };

  const renderActiveToolIcon = () => {
    switch (tool) {
      case "brush":
        return <Paintbrush className="h-5 w-5" />;
      case "eraser":
        return <Eraser className="h-5 w-5" />;
      case "crop":
        return <Crop className="h-5 w-5" />;
      case "artboard":
        return <Frame className="h-5 w-5" />;
      case "rect":
        return <Square className="h-5 w-5" />;
      case "ellipse":
        return <Circle className="h-5 w-5" />;
      case "scale":
        return <MoveDiagonal2 className="h-5 w-5" />;
      case "pan":
      default:
        return <MousePointer2 className="h-5 w-5" />;
    }
  };

  const isOrbDock = dockMode === "orb";
  const isRailDock = dockMode === "rail";
  const isExpandedDock = dockMode === "expanded";

  return (
    <div className={cn("relative flex h-full w-full flex-col bg-muted/10", className)}>
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
        <Button variant="ghost" size="icon" className="h-8 w-8 rounded-full" onClick={() => { setScale((current) => clamp(current - 0.2, MIN_SCALE, MAX_SCALE)); setHasZoomed(true); }}>
          <ZoomOut className="h-4 w-4" />
        </Button>
        <span className="min-w-[3rem] text-center text-xs font-medium tabular-nums">{Math.round(scale * 100)}%</span>
        <Button variant="ghost" size="icon" className="h-8 w-8 rounded-full" onClick={() => { setScale((current) => clamp(current + 0.2, MIN_SCALE, MAX_SCALE)); setHasZoomed(true); }}>
          <ZoomIn className="h-4 w-4" />
        </Button>
        <Button variant="ghost" size="icon" className="h-8 w-8 rounded-full" onClick={() => fitToScreen(true)}>
          <Maximize className="h-4 w-4" />
        </Button>
      </div>

      <div
        className={cn("absolute z-20 transition-all duration-300 ease-in-out", isDraggingDock ? "transition-none" : "")}
        style={{
          top: dockPos.y,
          right: dockPos.x,
          width: isOrbDock ? "64px" : isRailDock ? "92px" : "352px",
        }}
      >
        <div className={cn("border border-border/50 bg-background/92 shadow-2xl backdrop-blur-xl", isOrbDock ? "rounded-full p-1.5" : "rounded-[28px] p-3.5")}>
          {isOrbDock ? (
            <button
              type="button"
              onPointerDown={handleDockDragStart}
              onClick={handleDockSingleClick}
              onDoubleClick={(event) => {
                event.stopPropagation();
                handleDockDoubleClick();
              }}
              className="group relative flex h-12 w-12 cursor-move items-center justify-center rounded-full bg-primary text-primary-foreground shadow-lg active:cursor-grabbing"
              title="1 click: dock dài · 2 click: xổ ra"
            >
              {renderActiveToolIcon()}
            </button>
          ) : (
        <>
          <div onPointerDown={handleDockDragStart} className="mb-3 flex cursor-move items-center justify-between rounded-2xl bg-muted/30 px-3 py-2 active:cursor-grabbing">
            <div className="flex items-center gap-2">
              <button
                type="button"
                className="rounded-xl bg-primary/10 p-1.5 text-primary"
                onClick={(event) => {
                  event.stopPropagation();
                  handleDockSingleClick();
                }}
                onDoubleClick={(event) => {
                  event.stopPropagation();
                  handleDockDoubleClick();
                }}
                title="1 click: chuyển tròn/dài · 2 click: xổ ra"
              >
                <Settings2 className="h-4 w-4" />
              </button>
              {!isRailDock && (
                <div>
                  <p className="text-[10px] font-black uppercase tracking-[0.22em] text-foreground/70">Canvas Dock</p>
                  <p className="text-[10px] text-muted-foreground">Brush, crop, artboard, transform</p>
                </div>
              )}
            </div>
            <GripVertical className="h-4 w-4 text-muted-foreground/50" />
          </div>

          <div className={cn("flex gap-3", isRailDock && "justify-center")}>
            <div className="flex flex-col items-center gap-2 rounded-[22px] border border-border/40 bg-muted/15 p-2.5">
              <Button
                variant={tool === "brush" ? "default" : "ghost"}
                size="icon"
                className="h-11 w-11 rounded-2xl"
                onClick={() => setTool("brush")}
                onDoubleClick={() => setDockMode("expanded")}
              >
                <Paintbrush className="h-4 w-4" />
              </Button>
              <Button
                variant={tool === "eraser" ? "default" : "ghost"}
                size="icon"
                className="h-11 w-11 rounded-2xl"
                onClick={() => setTool("eraser")}
                onDoubleClick={() => setDockMode("expanded")}
              >
                <Eraser className="h-4 w-4" />
              </Button>
              <Button
                variant={tool === "crop" || tool === "artboard" ? "default" : "ghost"}
                size="icon"
                className={cn("relative h-11 w-11 rounded-2xl", cyclingGroup === "frame" && "ring-2 ring-primary/40")}
                onClick={() => activateFrameTool(activeFrameTool)}
                onPointerDown={() => startGroupCycle("frame")}
                onPointerUp={stopGroupCycle}
                onPointerLeave={stopGroupCycle}
                onWheel={(e) => handleGroupWheel("frame", e)}
                onDoubleClick={() => setDockMode("expanded")}
              >
                {activeFrameTool === "crop" ? <Crop className="h-4 w-4" /> : <Frame className="h-4 w-4" />}
              </Button>
              <Button
                variant={tool === "rect" || tool === "ellipse" ? "default" : "ghost"}
                size="icon"
                className={cn("relative h-11 w-11 rounded-2xl", cyclingGroup === "shape" && "ring-2 ring-primary/40")}
                onClick={() => activateShapeTool(activeShapeTool)}
                onPointerDown={() => startGroupCycle("shape")}
                onPointerUp={stopGroupCycle}
                onPointerLeave={stopGroupCycle}
                onWheel={(e) => handleGroupWheel("shape", e)}
                onDoubleClick={() => setDockMode("expanded")}
              >
                {activeShapeTool === "rect" ? <Square className="h-4 w-4" /> : <Circle className="h-4 w-4" />}
              </Button>
              <Button
                variant={tool === "scale" ? "default" : "ghost"}
                size="icon"
                className="h-11 w-11 rounded-2xl"
                onClick={() => setTool("scale")}
                onDoubleClick={() => setDockMode("expanded")}
              >
                <MoveDiagonal2 className="h-4 w-4" />
              </Button>
              <Button
                variant={tool === "pan" ? "default" : "ghost"}
                size="icon"
                className="h-11 w-11 rounded-2xl"
                onClick={() => setTool("pan")}
                onDoubleClick={() => setDockMode("expanded")}
              >
                <MousePointer2 className="h-4 w-4" />
              </Button>
            </div>

            {isExpandedDock && <div className="min-w-0 flex-1">{renderToolSettings()}</div>}
          </div>
        </>
          )}
        </div>
      </div>

      <div
        ref={containerRef}
        className="relative flex flex-1 items-center justify-center overflow-hidden"
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
          <div
            ref={stageRef}
            className="relative shrink-0"
            style={{
              width: imageSize.width || undefined,
              height: imageSize.height || undefined,
              transform: `rotate(${viewRotation}deg) scale(${flipX ? -1 : 1}, ${flipY ? -1 : 1})`,
              transformOrigin: "center center",
            }}
          >
            <img
              ref={imageRef}
              src={imageUrl}
              className="pointer-events-none block max-w-none"
              style={{
                width: imageSize.width || undefined,
                height: imageSize.height || undefined,
              }}
              alt="Canvas background"
              onError={() => console.error("Failed to load image:", imageUrl)}
            />
            <canvas
              ref={canvasRef}
              className={cn(
                "absolute left-0 top-0 block",
                tool === "pan" ? "cursor-grab active:cursor-grabbing" : "cursor-crosshair",
              )}
              style={{
                width: imageSize.width || undefined,
                height: imageSize.height || undefined,
              }}
            />
            {renderGuideOverlay(previewGuide)}
            {shapes.map((shape) => renderShapeOverlay(shape, shape.id === selectedShapeId))}
            {previewShape ? renderShapeOverlay(previewShape, false, true) : null}
          </div>
        </div>
      </div>
    </div>
  );
}
