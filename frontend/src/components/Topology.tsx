import { useEffect, useMemo, useRef, useState } from "react";
import type { Device, Lab, Link } from "../types";
import { Button } from "./ui/button";

const CARD_W = 300;
const HEADER_H = 48;
const PORT_H = 26;

type View = { x: number; y: number; w: number; h: number };

function short(name: string) {
  return name
    .replace("TenGigabitEthernet", "Te")
    .replace("GigabitEthernet", "Gi")
    .replace("FastEthernet", "Fa");
}

function interfaceKey(name: string) {
  return name
    .split(/(\d+)/)
    .filter(Boolean)
    .map((part) => (/^\d+$/.test(part) ? Number(part) : part.toLowerCase()));
}

function compareInterfaces(left: string, right: string) {
  const a = interfaceKey(left);
  const b = interfaceKey(right);
  const length = Math.max(a.length, b.length);
  for (let index = 0; index < length; index += 1) {
    const x = a[index];
    const y = b[index];
    if (x === undefined) return -1;
    if (y === undefined) return 1;
    if (x === y) continue;
    if (typeof x === "number" && typeof y === "number") return x - y;
    return String(x) < String(y) ? -1 : 1;
  }
  return 0;
}

function physical(device: Device) {
  return device.interfaces
    .filter((iface) => iface.physical)
    .slice()
    .sort((left, right) => compareInterfaces(left.name, right.name));
}

function cardHeight(device: Device) {
  const ports = Math.max(physical(device).length, 1);
  const extra = device.unsimulated.length > 0 ? 22 : 0;
  return HEADER_H + ports * PORT_H + 12 + extra;
}

export function Topology({
  lab,
  selected,
  pending,
  fitNonce,
  onSelect,
  onMove,
  onPort,
}: {
  lab: Lab;
  selected: string | null;
  pending: { device: string; iface: string } | null;
  fitNonce: number;
  onSelect: (name: string) => void;
  onMove: (name: string, x: number, y: number) => void;
  onPort: (device: string, iface: string) => void;
}) {
  const [pos, setPos] = useState<Record<string, { x: number; y: number }>>({});
  const [drag, setDrag] = useState<{ name: string; dx: number; dy: number } | null>(null);
  const [view, setView] = useState<View>({ x: 0, y: 0, w: 1400, h: 900 });
  const svgRef = useRef<SVGSVGElement>(null);
  const posRef = useRef(pos);
  posRef.current = pos;
  const viewRef = useRef(view);
  viewRef.current = view;
  const onMoveRef = useRef(onMove);
  onMoveRef.current = onMove;
  const userAdjusted = useRef(false);

  useEffect(() => {
    if (!drag) return;
    const svg = svgRef.current;
    const move = (event: PointerEvent) => {
      if (!svg) return;
      const point = svg.createSVGPoint();
      point.x = event.clientX;
      point.y = event.clientY;
      const ctm = svg.getScreenCTM();
      if (!ctm) return;
      const local = point.matrixTransform(ctm.inverse());
      setPos((current) => ({
        ...current,
        [drag.name]: { x: local.x - drag.dx, y: local.y - drag.dy },
      }));
    };
    const up = () => {
      const at = posRef.current[drag.name];
      setDrag(null);
      if (at) onMoveRef.current(drag.name, at.x, at.y);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    return () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
  }, [drag]);

  useEffect(() => {
    setPos(Object.fromEntries(lab.devices.map((device) => [device.name, { x: device.x, y: device.y }])));
  }, [lab]);

  function fit() {
    const svg = svgRef.current;
    if (!svg || lab.devices.length === 0) return;
    const rect = svg.getBoundingClientRect();
    if (rect.width < 40 || rect.height < 40) return;
    let minX = Infinity;
    let minY = Infinity;
    let maxX = -Infinity;
    let maxY = -Infinity;
    for (const device of lab.devices) {
      const at = posRef.current[device.name] ?? { x: device.x, y: device.y };
      minX = Math.min(minX, at.x);
      minY = Math.min(minY, at.y);
      maxX = Math.max(maxX, at.x + CARD_W);
      maxY = Math.max(maxY, at.y + cardHeight(device));
    }
    const pad = 220;
    const contentW = Math.max(1, maxX - minX + pad * 2);
    const contentH = Math.max(1, maxY - minY + pad * 2);
    const aspect = rect.width / rect.height;
    let w = contentW;
    let h = contentH;
    if (w / h > aspect) h = w / aspect;
    else w = h * aspect;
    const cx = (minX + maxX) / 2;
    const cy = (minY + maxY) / 2;
    setView({ x: cx - w / 2, y: cy - h / 2, w, h });
  }

  function zoomAt(factor: number, wx: number, wy: number) {
    userAdjusted.current = true;
    setView((current) => {
      const nextW = Math.min(16000, Math.max(220, current.w * factor));
      const nextH = current.h * (nextW / current.w);
      return {
        x: wx - (wx - current.x) * (nextW / current.w),
        y: wy - (wy - current.y) * (nextH / current.h),
        w: nextW,
        h: nextH,
      };
    });
  }

  function zoomCenter(factor: number) {
    const current = viewRef.current;
    zoomAt(factor, current.x + current.w / 2, current.y + current.h / 2);
  }

  const signature = `${lab.name}:${lab.devices.map((device) => device.name).join(",")}:${fitNonce}`;

  useEffect(() => {
    if (!lab.devices.length) return;
    userAdjusted.current = false;
    const id = requestAnimationFrame(() => fit());
    return () => cancelAnimationFrame(id);
    // fit reads the latest svg size and device positions.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [signature]);

  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;
    const observer = new ResizeObserver(() => {
      if (!userAdjusted.current) fit();
    });
    observer.observe(svg);
    const onWheel = (event: WheelEvent) => {
      event.preventDefault();
      const point = svg.createSVGPoint();
      point.x = event.clientX;
      point.y = event.clientY;
      const ctm = svg.getScreenCTM();
      if (!ctm) return;
      const local = point.matrixTransform(ctm.inverse());
      zoomAt(event.deltaY > 0 ? 1.12 : 0.88, local.x, local.y);
    };
    svg.addEventListener("wheel", onWheel, { passive: false });
    return () => {
      observer.disconnect();
      svg.removeEventListener("wheel", onWheel);
    };
    // The listener calls the latest zoomAt via setView.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lab.devices.length]);

  const anchors = useMemo(() => {
    const map = new Map<string, { x: number; y: number }>();
    for (const device of lab.devices) {
      const at = pos[device.name] ?? { x: device.x, y: device.y };
      physical(device).forEach((iface, index) => {
        map.set(`${device.name}|${iface.name}`, {
          x: at.x + CARD_W - 18,
          y: at.y + HEADER_H + index * PORT_H + PORT_H / 2,
        });
      });
    }
    return map;
  }, [lab.devices, pos]);

  const cards = useMemo(() => {
    const map = new Map<string, Rect>();
    for (const device of lab.devices) {
      const at = pos[device.name] ?? { x: device.x, y: device.y };
      map.set(device.name, { x: at.x, y: at.y, w: CARD_W, h: cardHeight(device) });
    }
    return map;
  }, [lab.devices, pos]);

  const cables = useMemo(() => layoutCables(lab.links, anchors, cards), [lab.links, anchors, cards]);

  if (lab.devices.length === 0) {
    return (
      <div className="flex h-full items-center justify-center px-8 text-center">
        <div>
          <p className="font-serif text-2xl text-paper">Empty bench</p>
          <p className="mx-auto mt-2 max-w-sm text-sm text-muted">
            Add a router or a switch, paste a config, or load the office lab. Cables you have not
            confirmed stay dashed.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="relative h-full w-full">
      <div className="absolute right-3 top-3 z-10 flex gap-1">
        <Button type="button" size="sm" variant="secondary" aria-label="Zoom in" onClick={() => zoomCenter(0.8)}>
          +
        </Button>
        <Button type="button" size="sm" variant="secondary" aria-label="Zoom out" onClick={() => zoomCenter(1.25)}>
          −
        </Button>
        <Button
          type="button"
          size="sm"
          variant="secondary"
          onClick={() => {
            userAdjusted.current = false;
            fit();
          }}
        >
          Fit
        </Button>
      </div>
      <svg
        ref={svgRef}
        className="h-full w-full touch-none"
        viewBox={`${view.x} ${view.y} ${view.w} ${view.h}`}
        role="img"
        aria-label="Lab canvas"
      >
        <defs>
          <pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse">
            <path d="M 40 0 L 0 0 0 40" fill="none" stroke="#2a3124" strokeWidth="1" />
          </pattern>
        </defs>
        <rect
          x={view.x}
          y={view.y}
          width={view.w}
          height={view.h}
          fill="#171b13"
          onPointerDown={(event) => {
            if (event.button !== 0) return;
            const svg = svgRef.current;
            if (!svg) return;
            const start = { x: event.clientX, y: event.clientY, view: viewRef.current };
            userAdjusted.current = true;
            const move = (ev: PointerEvent) => {
              const scale = svg.getBoundingClientRect().width / start.view.w;
              setView({
                x: start.view.x - (ev.clientX - start.x) / scale,
                y: start.view.y - (ev.clientY - start.y) / (svg.getBoundingClientRect().height / start.view.h),
                w: start.view.w,
                h: start.view.h,
              });
            };
            const up = () => {
              window.removeEventListener("pointermove", move);
              window.removeEventListener("pointerup", up);
            };
            window.addEventListener("pointermove", move);
            window.addEventListener("pointerup", up);
          }}
          style={{ cursor: "grab" }}
        />
        <rect x={view.x} y={view.y} width={view.w} height={view.h} fill="url(#grid)" pointerEvents="none" />
        {cables.map((cable) => (
          <path
            key={cable.id}
            d={cable.d}
            fill="none"
            stroke={cable.color}
            strokeWidth={cable.width}
            strokeDasharray={cable.dash}
            pointerEvents="none"
          />
        ))}
        {lab.devices.map((device) => {
          const at = pos[device.name] ?? { x: device.x, y: device.y };
          const ports = physical(device);
          const height = cardHeight(device);
          const active = selected === device.name;
          return (
            <g key={device.name} transform={`translate(${at.x} ${at.y})`}>
              <rect
                width={CARD_W}
                height={height}
                rx="12"
                fill="#22281c"
                stroke={active ? "#e2a84a" : "#3a4130"}
                strokeWidth={active ? 3 : 1.5}
              />
              <rect
                width={CARD_W}
                height={HEADER_H}
                rx="12"
                fill={device.role === "router" ? "#3a3018" : "#1c2a30"}
                onPointerDown={(event) => {
                  event.stopPropagation();
                  const svg = svgRef.current;
                  if (!svg) return;
                  const point = svg.createSVGPoint();
                  point.x = event.clientX;
                  point.y = event.clientY;
                  const ctm = svg.getScreenCTM();
                  if (!ctm) return;
                  const local = point.matrixTransform(ctm.inverse());
                  setDrag({ name: device.name, dx: local.x - at.x, dy: local.y - at.y });
                  onSelect(device.name);
                }}
                style={{ cursor: "grab" }}
              />
              <text x="16" y="32" fill="#f4ecda" fontFamily="ui-sans-serif, system-ui, sans-serif" fontSize="24" fontWeight="700">
                {device.name}
              </text>
              <text x={CARD_W - 16} y="30" textAnchor="end" fill="#d5d8c8" fontSize="14" fontFamily="ui-sans-serif, system-ui, sans-serif">
                {device.role === "router" ? "router" : "switch"}
              </text>
              {ports.map((iface, index) => {
                const armed = pending?.device === device.name && pending.iface === iface.name;
                return (
                  <g
                    key={iface.name}
                    transform={`translate(0 ${HEADER_H + index * PORT_H})`}
                    onClick={(event) => {
                      event.stopPropagation();
                      onSelect(device.name);
                      onPort(device.name, iface.name);
                    }}
                    style={{ cursor: "crosshair" }}
                  >
                    <text x="16" y="18" fill="#f4ecda" fontSize="15" fontFamily="ui-monospace, monospace">
                      {short(iface.name)}
                    </text>
                    <circle cx={CARD_W - 18} cy="13" r={armed ? 8 : 6} fill={armed ? "#e2a84a" : "#8fbf78"} />
                  </g>
                );
              })}
              {warningCaption(device) && (
                <text x="16" y={height - 8} fill="#e15b45" fontSize="13">
                  {warningCaption(device)}
                </text>
              )}
            </g>
          );
        })}
        {cables.map((cable) => (
          <g key={`${cable.id}-label`} pointerEvents="none">
            <rect
              x={cable.labelX - cable.labelW / 2}
              y={cable.labelY - cable.labelH / 2}
              width={cable.labelW}
              height={cable.labelH}
              rx={4}
              fill="#171b13"
              stroke={cable.color}
              strokeWidth={1}
            />
            <text
              x={cable.labelX}
              y={cable.labelY}
              textAnchor="middle"
              dominantBaseline="middle"
              fill={cable.color}
              fontSize="14"
              fontFamily="ui-sans-serif, system-ui, sans-serif"
            >
              {cable.label}
            </text>
          </g>
        ))}
      </svg>
    </div>
  );
}

type Pt = { x: number; y: number };
type Rect = { x: number; y: number; w: number; h: number };

type CableLayout = {
  id: string;
  d: string;
  color: string;
  width: number;
  dash?: string;
  label: string;
  labelX: number;
  labelY: number;
  labelW: number;
  labelH: number;
};

function warningCaption(device: Device) {
  const ignored = device.unsimulated.filter((row) => row.kind === "ignored").length;
  const missed = device.unsimulated.length - ignored;
  const parts: string[] = [];
  if (missed) parts.push(`${missed} line${missed === 1 ? "" : "s"} not simulated`);
  if (ignored) parts.push(`${ignored} ignored when ip routing is enabled`);
  return parts.join(" · ");
}

function insideAny(point: Pt, rects: Rect[]) {
  return rects.some(
    (rect) => point.x >= rect.x && point.x <= rect.x + rect.w && point.y >= rect.y && point.y <= rect.y + rect.h,
  );
}

function linePoint(a: Pt, b: Pt, t: number): Pt {
  return { x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t };
}

function quadPoint(a: Pt, control: Pt, b: Pt, t: number): Pt {
  const u = 1 - t;
  return {
    x: u * u * a.x + 2 * u * t * control.x + t * t * b.x,
    y: u * u * a.y + 2 * u * t * control.y + t * t * b.y,
  };
}

function visibleMid(sample: (t: number) => Pt, rects: Rect[]): Pt {
  const outside: Pt[] = [];
  for (let step = 0; step <= 48; step += 1) {
    const point = sample(step / 48);
    if (!insideAny(point, rects)) outside.push(point);
  }
  if (outside.length === 0) return sample(0.5);
  return outside[Math.floor((outside.length - 1) / 2)];
}

function outwardNormal(a: Pt, b: Pt, rects: Rect[]): Pt {
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const len = Math.hypot(dx, dy) || 1;
  let nx = -dy / len;
  let ny = dx / len;
  if (rects.length === 0) return { x: nx, y: ny };
  const mid = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
  const cx = rects.reduce((sum, rect) => sum + rect.x + rect.w / 2, 0) / rects.length;
  const cy = rects.reduce((sum, rect) => sum + rect.y + rect.h / 2, 0) / rects.length;
  if ((cx - mid.x) * nx + (cy - mid.y) * ny > 0) {
    nx = -nx;
    ny = -ny;
  }
  return { x: nx, y: ny };
}

function labelSize(text: string) {
  return { w: Math.max(64, text.length * 7.6 + 16), h: 22 };
}

function boxesOverlap(box: Rect, rect: Rect) {
  const pad = 6;
  return !(
    box.x + box.w < rect.x - pad ||
    box.x > rect.x + rect.w + pad ||
    box.y + box.h < rect.y - pad ||
    box.y > rect.y + rect.h + pad
  );
}

function placeLabel(anchor: Pt, normal: Pt, text: string, rects: Rect[]) {
  const size = labelSize(text);
  for (let step = 0; step < 18; step += 1) {
    const x = anchor.x + normal.x * 18 * step;
    const y = anchor.y + normal.y * 18 * step;
    const box = { x: x - size.w / 2, y: y - size.h / 2, w: size.w, h: size.h };
    if (!rects.some((rect) => boxesOverlap(box, rect))) return { x, y, ...size };
  }
  return { x: anchor.x + normal.x * 18 * 18, y: anchor.y + normal.y * 18 * 18, ...size };
}

function layoutCables(links: Link[], anchors: Map<string, Pt>, cards: Map<string, Rect>): CableLayout[] {
  const groups = new Map<string, Link[]>();
  for (const link of links) {
    const key = [link.aDevice, link.bDevice].sort().join("\0");
    const list = groups.get(key) ?? [];
    list.push(link);
    groups.set(key, list);
  }
  const cardRects = [...cards.values()];
  const occupied: Rect[] = [...cardRects];
  const laid: CableLayout[] = [];
  for (const list of groups.values()) {
    list.sort((left, right) =>
      `${left.aInterface} ${left.bInterface}`.localeCompare(`${right.aInterface} ${right.bInterface}`),
    );
    list.forEach((link, index) => {
      const a = anchors.get(`${link.aDevice}|${link.aInterface}`);
      const b = anchors.get(`${link.bDevice}|${link.bInterface}`);
      if (!a || !b) return;
      const ends = [cards.get(link.aDevice), cards.get(link.bDevice)].filter((rect): rect is Rect => Boolean(rect));
      const normal = outwardNormal(a, b, ends);
      const curved = list.length > 1;
      const bulge = curved ? 72 + index * 64 : 0;
      const mid = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
      const control = { x: mid.x + normal.x * bulge, y: mid.y + normal.y * bulge };
      const sample = (t: number) => (curved ? quadPoint(a, control, b, t) : linePoint(a, b, t));
      const seen = visibleMid(sample, cardRects);
      const stagger = (index - (list.length - 1) / 2) * 30;
      const suggested = link.status === "suggested";
      const label = `${short(link.aInterface)}–${short(link.bInterface)} ${suggested ? "suggested" : "link"}`;
      const placed = placeLabel({ x: seen.x, y: seen.y + stagger }, normal, label, occupied);
      occupied.push({
        x: placed.x - placed.w / 2,
        y: placed.y - placed.h / 2,
        w: placed.w,
        h: placed.h,
      });
      laid.push({
        id: link.id,
        d: curved
          ? `M ${a.x} ${a.y} Q ${control.x} ${control.y} ${b.x} ${b.y}`
          : `M ${a.x} ${a.y} L ${b.x} ${b.y}`,
        color: suggested ? "#e2a84a" : "#8fbf78",
        width: suggested ? 2 : 3.5,
        dash: suggested ? "8 6" : undefined,
        label,
        labelX: placed.x,
        labelY: placed.y,
        labelW: placed.w,
        labelH: placed.h,
      });
    });
  }
  return laid;
}
