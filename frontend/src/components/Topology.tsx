import { useEffect, useMemo, useRef, useState } from "react";
import type { Device, Lab, Link } from "../types";

const CARD_W = 176;

function short(name: string) {
  return name
    .replace("TenGigabitEthernet", "Te")
    .replace("GigabitEthernet", "Gi")
    .replace("FastEthernet", "Fa");
}

function physical(device: Device) {
  return device.interfaces.filter((iface) => iface.physical);
}

export function Topology({
  lab,
  selected,
  pending,
  onSelect,
  onMove,
  onPort,
}: {
  lab: Lab;
  selected: string | null;
  pending: { device: string; iface: string } | null;
  onSelect: (name: string) => void;
  onMove: (name: string, x: number, y: number) => void;
  onPort: (device: string, iface: string) => void;
}) {
  const [pos, setPos] = useState<Record<string, { x: number; y: number }>>({});
  const [drag, setDrag] = useState<{ name: string; dx: number; dy: number } | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const posRef = useRef(pos);
  posRef.current = pos;
  const onMoveRef = useRef(onMove);
  onMoveRef.current = onMove;

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

  const anchors = useMemo(() => {
    const map = new Map<string, { x: number; y: number }>();
    for (const device of lab.devices) {
      const at = pos[device.name] ?? { x: device.x, y: device.y };
      physical(device).forEach((iface, index) => {
        map.set(`${device.name}|${iface.name}`, {
          x: at.x + CARD_W - 12,
          y: at.y + 40 + index * 18 + 9,
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
    <svg
      ref={svgRef}
      className="h-full w-full"
      viewBox="0 0 1040 680"
      role="img"
      aria-label="Lab canvas"
    >
      <defs>
        <pattern id="grid" width="28" height="28" patternUnits="userSpaceOnUse">
          <path d="M 28 0 L 0 0 0 28" fill="none" stroke="#2a3124" strokeWidth="1" />
        </pattern>
      </defs>
      <rect width="1040" height="680" fill="#171b13" />
      <rect width="1040" height="680" fill="url(#grid)" />
      {lab.links.map((link) => (
        <Cable key={link.id} link={link} anchors={anchors} />
      ))}
      {lab.devices.map((device) => {
        const at = pos[device.name] ?? { x: device.x, y: device.y };
        const ports = physical(device);
        const extra = device.unsimulated.length > 0 ? 14 : 0;
        const height = 40 + Math.max(ports.length, 1) * 18 + 8 + extra;
        const active = selected === device.name;
        return (
          <g key={device.name} transform={`translate(${at.x} ${at.y})`}>
            <rect
              width={CARD_W}
              height={height}
              rx="8"
              fill="#22281c"
              stroke={active ? "#e2a84a" : "#3a4130"}
              strokeWidth={active ? 2 : 1}
            />
            <rect
              width={CARD_W}
              height="32"
              rx="8"
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
            <text x="12" y="21" fill="#f4ecda" fontFamily="Georgia, serif" fontSize="15">
              {device.name}
            </text>
            <text x={CARD_W - 12} y="20" textAnchor="end" fill="#a8ae99" fontSize="10">
              {device.role === "router" ? "router" : "switch"}
            </text>
            {ports.map((iface, index) => {
              const armed = pending?.device === device.name && pending.iface === iface.name;
              return (
                <g
                  key={iface.name}
                  transform={`translate(0 ${40 + index * 18})`}
                  onClick={(event) => {
                    event.stopPropagation();
                    onSelect(device.name);
                    onPort(device.name, iface.name);
                  }}
                  style={{ cursor: "crosshair" }}
                >
                  <text x="12" y="13" fill="#d9d3c3" fontSize="11" fontFamily="ui-monospace, monospace">
                    {short(iface.name)}
                  </text>
                  <circle cx={CARD_W - 12} cy="9" r={armed ? 6 : 4} fill={armed ? "#e2a84a" : "#8fbf78"} />
                </g>
              );
            })}
            {device.unsimulated.length > 0 && (
              <text x="12" y={height - 4} fill="#e15b45" fontSize="10">
                {device.unsimulated.length} line{device.unsimulated.length === 1 ? "" : "s"} not simulated
              </text>
            )}
          </g>
        );
      })}
    </svg>
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
        strokeWidth={suggested ? 1.5 : 2.5}
        strokeDasharray={suggested ? "6 4" : undefined}
      />
      <text x={midX} y={midY - 6} textAnchor="middle" fill={suggested ? "#e2a84a" : "#8fbf78"} fontSize="10">
        {suggested ? "suggested" : "link"}
      </text>
    </g>
  );
}
