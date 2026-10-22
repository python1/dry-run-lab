import { useEffect, useRef, useState } from "react";
import { Cable, Plus, Router, Trash2 } from "lucide-react";
import { api } from "./api";
import { DeviceCli } from "./components/DeviceCli";
import { Topology } from "./components/Topology";
import { Badge } from "./components/ui/badge";
import { Button } from "./components/ui/button";
import { Dialog, DialogContent } from "./components/ui/dialog";
import { Input } from "./components/ui/input";
import { Textarea } from "./components/ui/textarea";
import type { Lab, Role } from "./types";

const DISCLAIMER =
  "Computed results are a simulation from these configs. They are not proof that a live network will behave the same way. Not affiliated with or endorsed by Cisco.";
const CREDIT = "Created by Paul Charydczak";
const SPLIT_KEY = "dryrun-terminal-height";

function readSplit() {
  try {
    const raw = sessionStorage.getItem(SPLIT_KEY);
    const value = raw ? Number(raw) : 300;
    return Number.isFinite(value) && value >= 120 ? value : 300;
  } catch {
    return 300;
  }
}

type Tab = "canvas" | "devices" | "config" | "cli";

export default function App() {
  const [lab, setLab] = useState<Lab | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [pending, setPending] = useState<{ device: string; iface: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("canvas");
  const [draftConfig, setDraftConfig] = useState("");
  const [draftNeighbors, setDraftNeighbors] = useState("");
  const [addOpen, setAddOpen] = useState(false);
  const [addRole, setAddRole] = useState<Role>("router");
  const [addName, setAddName] = useState("");
  const [addIp, setAddIp] = useState("");
  const [addMask, setAddMask] = useState("");
  const [addGateway, setAddGateway] = useState("");
  const [notice, setNotice] = useState<string | null>(null);
  const [fitNonce, setFitNonce] = useState(0);
  const [terminalHeight, setTerminalHeight] = useState(readSplit);
  const [stamp, setStamp] = useState("");
  const gridRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    try {
      sessionStorage.setItem(SPLIT_KEY, String(Math.round(terminalHeight)));
    } catch {
      /* session storage can be blocked */
    }
  }, [terminalHeight]);

  async function run(action: () => Promise<Lab>) {
    setBusy(true);
    setError(null);
    try {
      const next = await action();
      if (next.notice) setNotice(next.notice);
      setLab(next);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Request failed");
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    void run(() => api.lab());
    void api
      .health()
      .then((body) => setStamp(body.version || "unknown"))
      .catch(() => setStamp("unknown"));
  }, []);

  const device = lab?.devices.find((item) => item.name === selected) ?? null;

  useEffect(() => {
    if (!lab) return;
    if (!selected && lab.devices[0]) setSelected(lab.devices[0].name);
    if (selected && !lab.devices.some((item) => item.name === selected)) {
      setSelected(lab.devices[0]?.name ?? null);
    }
  }, [lab, selected]);

  useEffect(() => {
    setDraftConfig(device?.config ?? "");
    setDraftNeighbors(device?.neighborText ?? "");
  }, [device?.name, device?.config, device?.neighborText]);

  function onPort(name: string, iface: string) {
    if (!pending) {
      setPending({ device: name, iface });
      return;
    }
    if (pending.device === name && pending.iface === iface) {
      setPending(null);
      return;
    }
    if (pending.device === name) {
      setPending({ device: name, iface });
      return;
    }
    const body = {
      aDevice: pending.device,
      aInterface: pending.iface,
      bDevice: name,
      bInterface: iface,
    };
    setPending(null);
    void run(() => api.link(body));
  }

  const suggestions = lab?.links.filter((link) => link.status === "suggested") ?? [];
  const unsimulated = device?.unsimulated ?? [];
  const limits = unsimulated.filter((row) => row.kind === "limit");
  const unreachable = unsimulated.filter((row) => row.kind === "unreachable");
  const missed = unsimulated.filter(
    (row) => row.kind !== "ignored" && row.kind !== "limit" && row.kind !== "unreachable",
  );
  const ignored = unsimulated.filter((row) => row.kind === "ignored");

  return (
    <div className="flex h-dvh w-screen flex-col overflow-hidden">
      <header className="flex items-center justify-between gap-4 border-b border-line px-4 py-3">
        <div className="flex items-center gap-3">
          <Mark />
          <div>
            <h1 className="font-serif text-xl leading-none tracking-tight">Dry Run Lab</h1>
            <p className="mt-1 text-xs text-muted">
              {lab?.name ?? "lab"} · loopback only
              {lab ? ` · engine ${lab.engineUp ? "up" : "down"}` : ""}
            </p>
          </div>
        </div>
        <div className="hidden text-right text-xs text-muted sm:block">
          <div>{CREDIT}</div>
          <div>{busy ? "Computing…" : "Configs stay on this machine"}</div>
        </div>
      </header>
      <div className="border-b border-amber/40 bg-amber/10 px-4 py-2 text-sm text-amber">{DISCLAIMER}</div>
      {(error || lab?.engineError) && (
        <div className="border-b border-coral/50 bg-coral/15 px-4 py-2 text-sm text-coral">
          {error || lab?.engineError}
        </div>
      )}
      {notice && (
        <div className="border-b border-steel/40 bg-steel/10 px-4 py-2">
          <div className="mb-1 flex items-center justify-between gap-3">
            <h2 className="text-xs uppercase tracking-wider text-steel">Topology change</h2>
            <button type="button" className="text-xs text-muted" onClick={() => setNotice(null)}>
              Dismiss
            </button>
          </div>
          <pre className="max-h-48 overflow-auto whitespace-pre-wrap font-mono text-xs text-paper">{notice}</pre>
        </div>
      )}
      <nav className="flex gap-1 border-b border-line px-2 py-1 lg:hidden">
        {(["canvas", "devices", "config", "cli"] as Tab[]).map((item) => (
          <button
            key={item}
            className={`rounded px-3 py-1 text-sm capitalize ${tab === item ? "bg-panel-2 text-paper" : "text-muted"}`}
            onClick={() => setTab(item)}
          >
            {item === "cli" ? "device CLI" : item}
          </button>
        ))}
      </nav>
      <div
        ref={gridRef}
        className="lab-grid min-h-0 flex-1"
        style={{ ["--terminal-h" as string]: `${terminalHeight}px` }}
      >
        <aside className={`${tab === "devices" ? "flex" : "hidden"} min-h-0 flex-col border-line lg:col-start-1 lg:row-start-1 lg:flex lg:border-r`}>
          <div className="flex items-center justify-between px-3 py-2">
            <h2 className="text-xs uppercase tracking-wider text-muted">Devices</h2>
            <Button
              size="sm"
              variant="secondary"
              onClick={() =>
                void run(async () => {
                  const next = await api.loadExample();
                  setFitNonce((value) => value + 1);
                  return next;
                })
              }
              disabled={busy}
            >
              Load office lab
            </Button>
          </div>
          <div className="flex flex-wrap gap-2 px-3 pb-2">
            <Button
              size="sm"
              variant="secondary"
              onClick={() => {
                setAddRole("router");
                setAddName("");
                setAddIp("");
                setAddMask("");
                setAddGateway("");
                setAddOpen(true);
              }}
            >
              <Plus className="h-3.5 w-3.5" /> Router
            </Button>
            <Button
              size="sm"
              variant="secondary"
              onClick={() => {
                setAddRole("switch");
                setAddName("");
                setAddIp("");
                setAddMask("");
                setAddGateway("");
                setAddOpen(true);
              }}
            >
              <Plus className="h-3.5 w-3.5" /> Switch
            </Button>
            <Button
              size="sm"
              variant="secondary"
              onClick={() => {
                setAddRole("host");
                setAddName("");
                setAddIp("");
                setAddMask("");
                setAddGateway("");
                setAddOpen(true);
              }}
            >
              <Plus className="h-3.5 w-3.5" /> Host
            </Button>
          </div>
          <div className="min-h-0 flex-1 overflow-auto px-2">
            {lab?.devices.map((item) => (
              <button
                key={item.name}
                onClick={() => {
                  setSelected(item.name);
                  setTab("config");
                }}
                className={`mb-1 flex w-full items-center justify-between rounded px-2 py-2 text-left ${
                  selected === item.name ? "bg-panel-2" : "hover:bg-panel"
                }`}
              >
                <span className="flex items-center gap-2">
                  <Router className={`h-4 w-4 ${item.role === "router" ? "text-amber" : item.role === "host" ? "text-moss" : "text-steel"}`} />
                  <span>{item.name}</span>
                  <Badge tone={item.role === "router" ? "amber" : item.role === "host" ? "moss" : "steel"}>{item.role}</Badge>
                </span>
                {item.unsimulated.some(
                  (row) => row.kind !== "ignored" && row.kind !== "limit" && row.kind !== "unreachable",
                ) && (
                  <Badge tone="coral">
                    {
                      item.unsimulated.filter(
                        (row) => row.kind !== "ignored" && row.kind !== "limit" && row.kind !== "unreachable",
                      ).length
                    }
                  </Badge>
                )}
                {item.unsimulated.some((row) => row.kind === "unreachable") && (
                  <Badge tone="amber">never matches</Badge>
                )}
                {item.unsimulated.some((row) => row.kind === "ignored") && (
                  <Badge tone="amber">ignored</Badge>
                )}
              </button>
            ))}
            {!lab?.devices.length && <p className="px-2 text-sm text-muted">No devices yet.</p>}
          </div>
          <div className="border-t border-line px-3 py-2">
            <h2 className="mb-2 flex items-center gap-2 text-xs uppercase tracking-wider text-muted">
              <Cable className="h-3.5 w-3.5" /> Suggested links
            </h2>
            {pending && (
              <p className="mb-2 text-xs text-amber">
                Drawing from {pending.device} {short(pending.iface)}. Click the other interface.
              </p>
            )}
            <div className="max-h-40 overflow-auto">
              {suggestions.map((link) => (
                <div key={link.id} className="mb-2 rounded border border-amber/40 bg-amber/5 p-2 text-xs">
                  <div className="text-paper">
                    {link.aDevice} {short(link.aInterface)} — {link.bDevice} {short(link.bInterface)}
                  </div>
                  <div className="mt-1 text-muted">{link.reason}</div>
                  <div className="mt-2 flex gap-2">
                    <Button size="sm" onClick={() => void run(() => api.confirm(link.id))} disabled={busy}>
                      Confirm
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => void run(() => api.dismiss(link.id))} disabled={busy}>
                      Dismiss
                    </Button>
                  </div>
                </div>
              ))}
              {!suggestions.length && <p className="text-xs text-muted">No open suggestions.</p>}
              {lab?.notes.map((note) => (
                <p key={note} className="mt-2 text-xs text-muted">
                  {note}
                </p>
              ))}
            </div>
          </div>
        </aside>
        <section className={`${tab === "canvas" ? "block" : "hidden"} h-full min-h-0 overflow-hidden lg:col-start-2 lg:row-start-1 lg:block`}>
          {lab ? (
            <Topology
              lab={lab}
              selected={selected}
              pending={pending}
              fitNonce={fitNonce}
              onSelect={(name) => {
                setSelected(name);
              }}
              onMove={(name, x, y) => void run(() => api.updateDevice(name, { x, y }))}
              onPort={onPort}
            />
          ) : (
            <div className="flex h-full items-center justify-center text-muted">Loading the lab…</div>
          )}
        </section>
        <aside className={`${tab === "config" ? "flex" : "hidden"} min-h-0 flex-col border-line lg:col-start-3 lg:row-start-1 lg:flex lg:border-l`}>
          <div className="flex items-center justify-between px-3 py-2">
            <h2 className="text-xs uppercase tracking-wider text-muted">Config {device ? `· ${device.name}` : ""}</h2>
            {device && (
              <Button
                size="sm"
                variant="ghost"
                onClick={() => {
                  const name = device.name;
                  if (selected === name) setSelected(null);
                  void run(() => api.deleteDevice(name));
                }}
              >
                <Trash2 className="h-3.5 w-3.5" />
              </Button>
            )}
          </div>
          {device ? (
            <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-auto px-3 pb-3">
              {device.versionNote ? (
                <p className="text-xs text-amber">{device.versionNote}</p>
              ) : null}
              <Textarea
                value={draftConfig}
                onChange={(event) => setDraftConfig(event.target.value)}
                className="min-h-48 flex-1"
                spellCheck={false}
                aria-label="Device config"
              />
              <label className="text-xs text-muted" htmlFor="neighbors">
                Neighbor text (CDP or LLDP paste)
              </label>
              <Textarea
                id="neighbors"
                value={draftNeighbors}
                onChange={(event) => setDraftNeighbors(event.target.value)}
                className="h-24"
                spellCheck={false}
              />
              <Button
                disabled={busy}
                onClick={() =>
                  void run(() =>
                    api.updateDevice(device.name, { config: draftConfig, neighborText: draftNeighbors }),
                  )
                }
              >
                Save and recompute
              </Button>
              {limits.length > 0 && (
                <div className="rounded-md border border-steel/50 bg-steel/10 p-3">
                  <h3 className="text-sm font-semibold text-steel">Not modeled</h3>
                  <ul className="mt-2 space-y-2">
                    {limits.map((row, index) => (
                      <li key={`${row.text}-${index}`} className="text-xs">
                        <div className="font-mono text-steel">{row.text}</div>
                        <div className="text-paper/80">{row.detail}</div>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {unreachable.length > 0 && (
                <div className="rounded-md border border-amber/60 bg-amber/10 p-3">
                  <h3 className="text-sm font-semibold text-amber">Will never match</h3>
                  <ul className="mt-2 space-y-2">
                    {unreachable.map((row, index) => (
                      <li key={`${row.text}-${index}`} className="text-xs">
                        <div className="font-mono text-amber">{row.text}</div>
                        <div className="text-paper/80">{row.detail}</div>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {missed.length === 0 && ignored.length === 0 && limits.length === 0 && unreachable.length === 0 ? (
                <div className="rounded-md border border-line p-3">
                  <h3 className="text-sm font-semibold text-paper">Lines the engine did not model</h3>
                  <p className="mt-2 text-xs text-muted">No unparsed lines reported for this device.</p>
                </div>
              ) : null}
              {missed.length > 0 && (
                <div className="rounded-md border border-coral/60 bg-coral/10 p-3">
                  <h3 className="text-sm font-semibold text-coral">These lines were NOT simulated</h3>
                  <ul className="mt-2 space-y-2">
                    {missed.map((row, index) => (
                      <li key={`${row.line}-${index}`} className="text-xs">
                        <div className="font-mono text-coral">
                          {row.line ? `line ${row.line}: ` : ""}
                          {row.text}
                        </div>
                        <div className="text-paper/80">{row.detail}</div>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {ignored.length > 0 && (
                <div className="rounded-md border border-amber/50 bg-amber/10 p-3">
                  <h3 className="text-sm font-semibold text-amber">Ignored when ip routing is enabled</h3>
                  <ul className="mt-2 space-y-2">
                    {ignored.map((row, index) => (
                      <li key={`${row.line}-${index}`} className="text-xs">
                        <div className="font-mono text-amber">
                          {row.line ? `line ${row.line}: ` : ""}
                          {row.text}
                        </div>
                        <div className="text-paper/80">{row.detail}</div>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          ) : (
            <p className="px-3 text-sm text-muted">Select a device to paste its config.</p>
          )}
        </aside>
        <div
          role="separator"
          aria-orientation="horizontal"
          aria-label="Resize canvas and terminal"
          aria-valuenow={Math.round(terminalHeight)}
          className="split-handle hidden cursor-row-resize items-center justify-center lg:col-span-3 lg:col-start-1 lg:row-start-2 lg:flex"
          onPointerDown={(event) => {
            event.preventDefault();
            const grid = gridRef.current;
            if (!grid) return;
            const move = (ev: PointerEvent) => {
              const rect = grid.getBoundingClientRect();
              const next = rect.bottom - ev.clientY - 14;
              const clamped = Math.min(Math.max(next, 140), Math.max(180, rect.height - 180));
              setTerminalHeight(clamped);
            };
            const up = () => {
              window.removeEventListener("pointermove", move);
              window.removeEventListener("pointerup", up);
            };
            window.addEventListener("pointermove", move);
            window.addEventListener("pointerup", up);
          }}
        >
          <span className="h-1.5 w-24 rounded-full bg-muted/80" />
        </div>
        <section className={`${tab === "cli" ? "flex" : "hidden"} min-h-0 flex-col border-t border-line bg-[#10140c] lg:col-span-3 lg:col-start-1 lg:row-start-3 lg:flex`}>
          <div className="flex items-center justify-between px-3 py-1.5">
            <h2 className="text-xs uppercase tracking-wider text-muted">Device CLI · computed</h2>
            <label className="flex items-center gap-2 text-xs text-muted">
              Device
              <select
                className="rounded border border-line bg-ink px-2 py-1 text-paper"
                value={selected ?? ""}
                onChange={(event) => setSelected(event.target.value || null)}
              >
                <option value="">none</option>
                {lab?.devices.map((item) => (
                  <option key={item.name} value={item.name}>
                    {item.name}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <div className="min-h-0 flex-1 px-2 pb-3">
            <DeviceCli device={selected} onLab={setLab} />
          </div>
        </section>
      </div>
      <footer className="flex items-center justify-between border-t border-line px-4 py-1.5 text-xs text-muted">
        <span>
          {CREDIT}
          {stamp ? <span className="ml-3">{stamp}</span> : null}
        </span>
        <span>Not a live network</span>
      </footer>
      <Dialog open={addOpen} onOpenChange={setAddOpen}>
        <DialogContent title={addRole === "router" ? "Add a router" : addRole === "host" ? "Add a host" : "Add a switch"}>
          <form
            className="space-y-3"
            onSubmit={(event) => {
              event.preventDefault();
              const name = addName.trim();
              if (!nameOk(name)) return;
              if (addRole === "host" && !hostFieldsOk(addIp, addMask, addGateway)) return;
              setAddOpen(false);
              void run(() =>
                api.addDevice(
                  addRole === "host"
                    ? {
                        name,
                        role: addRole,
                        ip: addIp.trim(),
                        mask: addMask.trim(),
                        gateway: addGateway.trim(),
                      }
                    : { name, role: addRole, x: 80 + Math.random() * 200, y: 80 },
                ),
              );
            }}
          >
            <label className="block text-sm text-muted" htmlFor="device-name">
              Name
            </label>
            <Input id="device-name" value={addName} onChange={(event) => setAddName(event.target.value)} autoFocus />
            {addRole === "host" && (
              <>
                <label className="block text-sm text-muted" htmlFor="host-ip">
                  IP address
                </label>
                <Input
                  id="host-ip"
                  value={addIp}
                  onChange={(event) => setAddIp(event.target.value)}
                  autoComplete="off"
                />
                <label className="block text-sm text-muted" htmlFor="host-mask">
                  Mask
                </label>
                <Input
                  id="host-mask"
                  value={addMask}
                  onChange={(event) => setAddMask(event.target.value)}
                  autoComplete="off"
                />
                <label className="block text-sm text-muted" htmlFor="host-gateway">
                  Gateway
                </label>
                <Input
                  id="host-gateway"
                  value={addGateway}
                  onChange={(event) => setAddGateway(event.target.value)}
                  autoComplete="off"
                />
                <p className="text-xs text-muted">IP address, mask, and gateway are required.</p>
              </>
            )}
            <Button
              type="submit"
              disabled={
                !nameOk(addName.trim()) || (addRole === "host" && !hostFieldsOk(addIp, addMask, addGateway))
              }
            >
              Add {addRole}
            </Button>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function nameOk(name: string) {
  return /^[A-Za-z][A-Za-z0-9_-]{0,31}$/.test(name);
}

function ipv4Ok(value: string) {
  const parts = value.trim().split(".");
  if (parts.length !== 4) return false;
  return parts.every((part) => /^\d{1,3}$/.test(part) && Number(part) <= 255);
}

function maskOk(value: string) {
  const text = value.trim();
  if (/^\d{1,2}$/.test(text)) {
    const prefix = Number(text);
    return prefix >= 0 && prefix <= 32;
  }
  if (text.startsWith("/")) return maskOk(text.slice(1));
  if (!ipv4Ok(text)) return false;
  const bits = text.split(".").reduce((acc, octet) => (acc << 8) + Number(octet), 0) >>> 0;
  let seenZero = false;
  for (let index = 31; index >= 0; index -= 1) {
    const one = (bits & (1 << index)) !== 0;
    if (!one) seenZero = true;
    else if (seenZero) return false;
  }
  return true;
}

function hostFieldsOk(ip: string, mask: string, gateway: string) {
  return ipv4Ok(ip) && maskOk(mask) && ipv4Ok(gateway);
}

function short(name: string) {
  return name.replace("GigabitEthernet", "Gi").replace("TenGigabitEthernet", "Te").replace("FastEthernet", "Fa");
}

function Mark() {
  return (
    <svg width="28" height="28" viewBox="0 0 32 32" aria-hidden="true">
      <rect width="32" height="32" rx="6" fill="#262c20" />
      <circle cx="8" cy="16" r="3" fill="#e2a84a" />
      <circle cx="24" cy="9" r="3" fill="#8eb6c9" />
      <circle cx="24" cy="23" r="3" fill="#8fbf78" />
      <path d="M11 15.2 L21 10.2 M11 16.8 L21 21.8" stroke="#f4ecda" strokeWidth="1.4" />
    </svg>
  );
}
