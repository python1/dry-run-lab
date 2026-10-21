export type Role = "router" | "switch";

export interface Iface {
  name: string;
  description: string;
  address: string | null;
  network: string | null;
  physical: boolean;
  shutdown: boolean;
}

export interface WarningRow {
  device: string | null;
  file: string;
  line: number | null;
  text: string;
  detail: string;
  kind: string;
}

export interface Device {
  name: string;
  role: Role;
  config: string;
  neighborText: string;
  x: number;
  y: number;
  interfaces: Iface[];
  unsimulated: WarningRow[];
}

export interface Link {
  id: string;
  aDevice: string;
  aInterface: string;
  bDevice: string;
  bInterface: string;
  status: "suggested" | "confirmed";
  source: string;
  reason: string;
}

export interface Lab {
  name: string;
  devices: Device[];
  links: Link[];
  notes: string[];
  warnings: WarningRow[];
  engineError: string | null;
  engineUp: boolean;
  unsimulatedCount: number;
  disclaimer: string;
  credit: string;
}
