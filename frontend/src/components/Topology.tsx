import { useEffect, useMemo, useRef, useState } from "react";
import { layoutCables, type Rect } from "../cables";
import type { Device, Lab } from "../types";
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
  busy,
  onSelect,
  onMove,
  onPort,
  onRemove,
}: {
  lab: Lab;
  selected: string | null;
  pending: { device: string; iface: string } | null;
  fitNonce: number;
  busy: boolean;
  onSelect: (name: string) => void;
  onMove: (name: string, x: number, y: number) => void;
  onPort: (device: string, iface: string) => void;
  onRemove: (id: string) => void;
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
          <p className="mx-auto mt-2 max-w-md text-sm text-muted">
            Add a router or a switch, paste a config, or load a lab folder. Cables you have not
            confirmed stay dashed.
          </p>
          <p className="mx-auto mt-2 max-w-md text-sm text-muted">
            CDP does not suggest a host cable. One is suggested when the host address is in an access
            VLAN subnet and the switch port description matches the host. Otherwise draw that cable.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="relative h-full w-full">
      <div className="absolute right-3 top-3 z-10 flex gap-1">
        <div className="mr-2 hidden rounded border border-line bg-ink/90 px-2 py-1 text-[11px] text-muted sm:block">
          Solid green: confirmed. Dashed orange: suggested.
        </div>
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
          <g key={cable.id}>
            <path
              d={cable.d}
              fill="none"
              stroke="transparent"
              strokeWidth={14}
              style={{ cursor: busy ? "wait" : "pointer" }}
              onPointerDown={(event) => event.stopPropagation()}
              onClick={(event) => {
                event.stopPropagation();
                if (!busy) onRemove(cable.id);
              }}
            >
              <title>Remove this cable</title>
            </path>
            <path
              d={cable.d}
              fill="none"
              stroke={cable.color}
              strokeWidth={cable.width}
              strokeDasharray={cable.dash}
              pointerEvents="none"
            />
          </g>
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
                fill={device.role === "router" ? "#3a3018" : device.role === "host" ? "#243024" : "#1c2a30"}
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
                {device.role}
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
                    style={{ cursor: busy ? "wait" : "crosshair" }}
                  >
                    <text x="16" y="18" fill="#f4ecda" fontSize="15" fontFamily="ui-monospace, monospace">
                      {short(iface.name)}
                    </text>
                    <title>{`Click ${short(iface.name)}, then the other port, to cable`}</title>
                    <circle cx={CARD_W - 18} cy="13" r="12" fill="transparent" />
                    <circle
                      cx={CARD_W - 18}
                      cy="13"
                      r={armed ? 10 : 9}
                      fill={armed ? "#e2a84a" : iface.shutdown ? "#e15b45" : "#8fbf78"}
                    />
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

function warningCaption(device: Device) {
  const ignored = device.unsimulated.filter((row) => row.kind === "ignored").length;
  const unreachable = device.unsimulated.filter((row) => row.kind === "unreachable").length;
  const missed = device.unsimulated.filter(
    (row) => row.kind !== "ignored" && row.kind !== "unreachable",
  ).length;
  const parts: string[] = [];
  if (missed) parts.push(`${missed} line${missed === 1 ? "" : "s"} not simulated`);
  if (unreachable) parts.push(`${unreachable} will never match`);
  if (ignored) parts.push(`${ignored} ignored when ip routing is enabled`);
  return parts.join(" · ");
}
