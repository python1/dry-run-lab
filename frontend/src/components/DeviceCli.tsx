import { FitAddon } from "@xterm/addon-fit";
import { Terminal } from "@xterm/xterm";
import { useEffect, useRef, type PointerEvent as ReactPointerEvent } from "react";
import "@xterm/xterm/css/xterm.css";
import { api } from "../api";
import type { Lab } from "../types";

export function DeviceCli({ device, onLab }: { device: string | null; onLab?: (lab: Lab) => void }) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const hostRef = useRef<HTMLDivElement>(null);
  const barRef = useRef<HTMLDivElement>(null);
  const thumbRef = useRef<HTMLDivElement>(null);
  const syncRef = useRef<() => void>(() => {});

  useEffect(() => {
    const host = hostRef.current;
    const scroll = scrollRef.current;
    if (!host || !scroll) return;

    const term = new Terminal({
      fontFamily: "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
      fontSize: 13,
      cursorBlink: true,
      convertEol: true,
      scrollback: 2000,
      cols: 120,
      rows: 20,
      theme: {
        background: "#10140c",
        foreground: "#f4ecda",
        cursor: "#e2a84a",
        selectionBackground: "#3a4130",
      },
    });
    const fit = new FitAddon();
    term.loadAddon(fit);
    term.open(host);

    let minCols = 80;
    const contentWidth = () => {
      const canvas = host.querySelector(".xterm-text-layer");
      if (canvas instanceof HTMLCanvasElement && canvas.style.width) {
        const parsed = Number.parseFloat(canvas.style.width);
        if (parsed > 0) return parsed;
      }
      return scroll.clientWidth;
    };
    const syncThumb = () => {
      const bar = barRef.current;
      const thumb = thumbRef.current;
      if (!bar || !thumb) return;
      const max = scroll.scrollWidth - scroll.clientWidth;
      const barWidth = bar.clientWidth;
      if (max <= 1 || barWidth <= 0) {
        thumb.style.width = `${Math.max(barWidth, 0)}px`;
        thumb.style.transform = "translateX(0px)";
        return;
      }
      const thumbW = Math.max(48, (scroll.clientWidth / scroll.scrollWidth) * barWidth);
      const left = (scroll.scrollLeft / max) * (barWidth - thumbW);
      thumb.style.width = `${thumbW}px`;
      thumb.style.transform = `translateX(${left}px)`;
    };
    syncRef.current = syncThumb;
    const layout = () => {
      host.style.width = `${Math.max(scroll.clientWidth, 1)}px`;
      const proposed = fit.proposeDimensions();
      const cols = Math.max(proposed?.cols ?? 80, minCols);
      const rows = Math.max(proposed?.rows ?? 12, 8);
      if (term.cols !== cols || term.rows !== rows) term.resize(cols, rows);
      host.style.width = `${Math.max(contentWidth(), scroll.clientWidth)}px`;
      syncThumb();
    };

    const writeBlock = (text: string) => {
      const lines = text.replace(/\s+$/, "").split("\n");
      const longest = lines.reduce((max, line) => Math.max(max, line.length), 0);
      if (longest + 4 > minCols) {
        minCols = longest + 4;
        layout();
      }
      for (const line of lines) term.writeln(line);
    };

    layout();
    const observer = new ResizeObserver(() => layout());
    observer.observe(scroll);
    scroll.addEventListener("scroll", syncThumb);

    let buffer = "";
    const promptRef = { current: `${device ?? "lab"}# ` };
    const prompt = () => {
      term.write(`\r\n${promptRef.current}`);
    };
    term.writeln("Device CLI");
    term.writeln("show vlan brief    show interfaces trunk    show access-lists");
    term.writeln("show ip ospf neighbor    ping    traceroute    configure terminal    revert");
    term.writeln("A show command this lab does not compute says it is not simulated.");
    term.writeln("Lines stay intact. Scroll sideways for the rest.");
    if (!device) term.writeln("Select a device first.");
    prompt();

    const submit = async (command: string) => {
      const trimmed = command.trim();
      if (!trimmed) {
        prompt();
        return;
      }
      if (!device) {
        term.writeln("Select a device first.");
        prompt();
        return;
      }
      try {
        const result = await api.show(device, trimmed);
        if (result.lab && onLab) onLab(result.lab);
        promptRef.current = result.prompt.endsWith(" ") ? result.prompt : `${result.prompt} `;
        const lines = result.text.split("\n");
        const body = lines[0]?.includes(trimmed) ? lines.slice(1) : lines;
        writeBlock(body.join("\n"));
      } catch (error) {
        term.writeln(`\x1b[31m${error instanceof Error ? error.message : "request failed"}\x1b[0m`);
      }
      prompt();
    };

    const disposable = term.onData((data) => {
      if (data === "\r") {
        const command = buffer;
        buffer = "";
        term.write("\r\n");
        void submit(command);
        return;
      }
      if (data === "\u007f") {
        if (!buffer) return;
        buffer = buffer.slice(0, -1);
        term.write("\b \b");
        return;
      }
      if (data === "\u0003") {
        buffer = "";
        term.write("^C");
        prompt();
        return;
      }
      const printable = data.replace(/[\r\n]/g, "");
      if (printable) {
        buffer += printable;
        term.write(printable);
      }
      if (data.includes("\n") || data.includes("\r")) {
        const command = buffer;
        buffer = "";
        term.write("\r\n");
        void submit(command);
      }
    });

    return () => {
      disposable.dispose();
      observer.disconnect();
      scroll.removeEventListener("scroll", syncThumb);
      term.dispose();
    };
  }, [device, onLab]);

  const onBarPointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    const scroll = scrollRef.current;
    const bar = barRef.current;
    const thumb = thumbRef.current;
    if (!scroll || !bar || !thumb) return;
    event.preventDefault();
    const barRect = bar.getBoundingClientRect();
    const thumbRect = thumb.getBoundingClientRect();
    const max = Math.max(0, scroll.scrollWidth - scroll.clientWidth);
    const onThumb = event.clientX >= thumbRect.left && event.clientX <= thumbRect.right;
    if (!onThumb && barRect.width > 0) {
      scroll.scrollLeft = ((event.clientX - barRect.left) / barRect.width) * max;
      syncRef.current();
    }
    const startX = event.clientX;
    const startLeft = scroll.scrollLeft;
    const span = Math.max(1, barRect.width - thumbRect.width);
    const move = (ev: PointerEvent) => {
      if (max <= 0) return;
      scroll.scrollLeft = startLeft + ((ev.clientX - startX) / span) * max;
      syncRef.current();
    };
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };

  return (
    <div className="flex h-full min-h-0 w-full flex-col">
      <div ref={scrollRef} className="device-cli-scroll min-h-0 w-full flex-1">
        <div ref={hostRef} className="h-full" />
      </div>
      <div
        ref={barRef}
        className="terminal-hscroll"
        role="scrollbar"
        aria-orientation="horizontal"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label="Terminal horizontal scroll"
        onPointerDown={onBarPointerDown}
      >
        <div ref={thumbRef} className="terminal-hscroll-thumb" />
      </div>
    </div>
  );
}
