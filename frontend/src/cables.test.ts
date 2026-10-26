import assert from "node:assert/strict";
import { layoutCables, type Rect } from "./cables.ts";
import type { Link } from "./types.ts";

function link(partial: Partial<Link> & Pick<Link, "id" | "aDevice" | "aInterface" | "bDevice" | "bInterface" | "status">): Link {
  return {
    source: "user",
    reason: "",
    ...partial,
  };
}

const anchors = new Map<string, { x: number; y: number }>([
  ["ACC|GigabitEthernet0/1", { x: 682, y: 220 }],
  ["ACC|GigabitEthernet0/10", { x: 682, y: 300 }],
  ["ACC|GigabitEthernet0/11", { x: 682, y: 326 }],
  ["CORE|GigabitEthernet1/0/2", { x: 982, y: 180 }],
  ["H1|Ethernet0", { x: 282, y: 520 }],
  ["H2|Ethernet0", { x: 1082, y: 540 }],
]);

const cards = new Map<string, Rect>([
  ["ACC", { x: 400, y: 160, w: 300, h: 220 }],
  ["CORE", { x: 700, y: 40, w: 300, h: 200 }],
  ["H1", { x: 40, y: 480, w: 300, h: 90 }],
  ["H2", { x: 800, y: 500, w: 300, h: 90 }],
]);

const laid = layoutCables(
  [
    link({
      id: "uplink",
      aDevice: "ACC",
      aInterface: "GigabitEthernet0/1",
      bDevice: "CORE",
      bInterface: "GigabitEthernet1/0/2",
      status: "confirmed",
    }),
    link({
      id: "host1",
      aDevice: "ACC",
      aInterface: "GigabitEthernet0/10",
      bDevice: "H1",
      bInterface: "Ethernet0",
      status: "suggested",
    }),
    link({
      id: "host2",
      aDevice: "ACC",
      aInterface: "GigabitEthernet0/11",
      bDevice: "H2",
      bInterface: "Ethernet0",
      status: "confirmed",
    }),
  ],
  anchors,
  cards,
);

assert.equal(laid.length, 3);
assert.ok(laid.some((cable) => cable.label.endsWith("confirmed")));
assert.ok(laid.some((cable) => cable.label.endsWith("suggested")));
assert.equal(
  laid.some((cable) => cable.label.endsWith(" link")),
  false,
);

function overlaps(left: (typeof laid)[number], right: (typeof laid)[number]) {
  const a = { x: left.labelX - left.labelW / 2, y: left.labelY - left.labelH / 2, w: left.labelW, h: left.labelH };
  const b = { x: right.labelX - right.labelW / 2, y: right.labelY - right.labelH / 2, w: right.labelW, h: right.labelH };
  return !(a.x + a.w <= b.x || a.x >= b.x + b.w || a.y + a.h <= b.y || a.y >= b.y + b.h);
}

for (let i = 0; i < laid.length; i += 1) {
  for (let j = i + 1; j < laid.length; j += 1) {
    assert.equal(overlaps(laid[i], laid[j]), false, `${laid[i].label} overlaps ${laid[j].label}`);
  }
  for (const card of cards.values()) {
    const box = {
      x: laid[i].labelX - laid[i].labelW / 2,
      y: laid[i].labelY - laid[i].labelH / 2,
      w: laid[i].labelW,
      h: laid[i].labelH,
    };
    const hits = !(
      box.x + box.w <= card.x ||
      box.x >= card.x + card.w ||
      box.y + box.h <= card.y ||
      box.y >= card.y + card.h
    );
    assert.equal(hits, false, `${laid[i].label} overlaps a card`);
  }
}

console.log("cables ok");
