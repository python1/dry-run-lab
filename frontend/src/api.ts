import type { Lab } from "./types";

async function request(path: string, init?: RequestInit): Promise<Lab> {
  const response = await fetch(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = body.detail || detail;
    } catch {
      /* keep status text */
    }
    throw new Error(detail);
  }
  return response.json();
}

export const api = {
  lab: () => request("/api/lab"),
  health: async () => {
    const response = await fetch("/api/health");
    if (!response.ok) throw new Error("health failed");
    return response.json() as Promise<{
      engineUp: boolean;
      disclaimer: string;
      credit: string;
      version: string;
    }>;
  },
  loadExample: () => request("/api/lab/load-example", { method: "POST" }),
  addDevice: (body: {
    name: string;
    role: string;
    x?: number;
    y?: number;
    config?: string;
    ip?: string;
    mask?: string;
    gateway?: string;
  }) => request("/api/devices", { method: "POST", body: JSON.stringify(body) }),
  updateDevice: (
    name: string,
    body: { config?: string; neighborText?: string; x?: number; y?: number },
  ) => request(`/api/devices/${encodeURIComponent(name)}`, { method: "PUT", body: JSON.stringify(body) }),
  deleteDevice: (name: string) =>
    request(`/api/devices/${encodeURIComponent(name)}`, { method: "DELETE" }),
  link: (body: { aDevice: string; aInterface: string; bDevice: string; bInterface: string }) =>
    request("/api/links", { method: "POST", body: JSON.stringify(body) }),
  confirm: (id: string) => request(`/api/links/${id}/confirm`, { method: "POST" }),
  dismiss: (id: string) => request(`/api/links/${id}/dismiss`, { method: "POST" }),
  show: async (device: string, command: string) => {
    const response = await fetch("/api/show", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ device, command }),
    });
    const raw = await response.text();
    let body: { detail?: string; text?: string; prompt?: string; lab?: Lab } = {};
    if (raw) {
      try {
        body = JSON.parse(raw) as typeof body;
      } catch {
        throw new Error(raw.trim().slice(0, 300) || response.statusText || "show failed");
      }
    }
    if (!response.ok) throw new Error(body.detail || raw.trim().slice(0, 300) || "show failed");
    return {
      text: body.text as string,
      prompt: (body.prompt as string) || `${device}#`,
      lab: body.lab as Lab | undefined,
    };
  },
};
