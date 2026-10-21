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

function physical(device: Device) {
  return device.interfaces.filter((iface) => iface.physical);
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
    const pad = 56;
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
        {lab.links.map((link) => (
          <Cable key={link.id} link={link} anchors={anchors} />
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
              {device.unsimulated.length > 0 && (
                <text x="16" y={height - 8} fill="#e15b45" fontSize="13">
                  {device.unsimulated.length} line{device.unsimulated.length === 1 ? "" : "s"} not simulated
                </text>
              )}
            </g>
          );
        })}
      </svg>
    </div>
  );
}

function Cable({
  link,
  anchors,
}: {
  link: Link;
  anchors: Map<string, { x: number; y: number }>;
}) {
  const a = anchors.get(`${link.aDevice}|${link.aInterface}`);
  const b = anchors.get(`${link.bDevice}|${link.bInterface}`);
  if (!a || !b) return null;
  const suggested = link.status === "suggested";
  const midX = (a.x + b.x) / 2;
  const midY = (a.y + b.y) / 2;
  return (
    <g>
      <line
        x1={a.x}
        y1={a.y}
        x2={b.x}
        y2={b.y}
        stroke={suggested ? "#e2a84a" : "#8fbf78"}
        strokeWidth={suggested ? 2 : 3.5}
        strokeDasharray={suggested ? "8 6" : undefined}
      />
      <text x={midX} y={midY - 8} textAnchor="middle" fill={suggested ? "#e2a84a" : "#8fbf78"} fontSize="14">
        {suggested ? "suggested" : "link"}
      </text>
    </g>
  );
}
