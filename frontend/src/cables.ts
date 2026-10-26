import type { Link } from "./types";

export type Pt = { x: number; y: number };
export type Rect = { x: number; y: number; w: number; h: number };

export type CableLayout = {
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

function short(name: string) {
  return name
    .replace("TenGigabitEthernet", "Te")
    .replace("GigabitEthernet", "Gi")
    .replace("FastEthernet", "Fa")
    .replace("Ethernet", "Et");
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

export function boxesOverlap(box: Rect, rect: Rect) {
  const pad = 6;
  return !(
    box.x + box.w < rect.x - pad ||
    box.x > rect.x + rect.w + pad ||
    box.y + box.h < rect.y - pad ||
    box.y > rect.y + rect.h + pad
  );
}

function placeLabel(anchor: Pt, normal: Pt, text: string, occupied: Rect[]) {
  const size = labelSize(text);
  const tangent = { x: -normal.y, y: normal.x };
  const gap = size.h + 12;
  for (let ring = 0; ring < 16; ring += 1) {
    for (const side of [0, 1, -1, 2, -2, 3, -3]) {
      const along = 8 + ring * gap;
      const across = side * gap;
      const x = anchor.x + normal.x * along + tangent.x * across;
      const y = anchor.y + normal.y * along + tangent.y * across;
      const box = { x: x - size.w / 2, y: y - size.h / 2, w: size.w, h: size.h };
      if (!occupied.some((rect) => boxesOverlap(box, rect))) return { x, y, w: size.w, h: size.h };
    }
  }
  const far = 8 + 16 * gap;
  return {
    x: anchor.x + normal.x * far,
    y: anchor.y + normal.y * far,
    w: size.w,
    h: size.h,
  };
}

export function layoutCables(links: Link[], anchors: Map<string, Pt>, cards: Map<string, Rect>): CableLayout[] {
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
      const suggested = link.status === "suggested";
      const down = Boolean(link.down);
      const kind = suggested ? "suggested" : "confirmed";
      const label = `${short(link.aInterface)}–${short(link.bInterface)} ${down ? `${kind} down` : kind}`;
      const placed = placeLabel(seen, normal, label, occupied);
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
        color: down ? "#e15b45" : suggested ? "#e2a84a" : "#8fbf78",
        width: down ? 3 : suggested ? 2 : 3.5,
        dash: down ? "7 6" : suggested ? "8 6" : undefined,
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
