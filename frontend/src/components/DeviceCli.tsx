import { FitAddon } from "@xterm/addon-fit";
import { Terminal } from "@xterm/xterm";
import { useEffect, useRef } from "react";
import "@xterm/xterm/css/xterm.css";
import { api } from "../api";

export function DeviceCli({ device }: { device: string | null }) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const hostRef = useRef<HTMLDivElement>(null);

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
    const layout = () => {
      host.style.width = `${Math.max(scroll.clientWidth, 1)}px`;
      const proposed = fit.proposeDimensions();
      const cols = Math.max(proposed?.cols ?? 80, minCols);
      const rows = Math.max(proposed?.rows ?? 12, 8);
      if (term.cols !== cols || term.rows !== rows) term.resize(cols, rows);
      const screen = host.querySelector(".xterm-screen");
      const width = screen instanceof HTMLElement ? screen.offsetWidth : scroll.clientWidth;
      host.style.width = `${Math.max(width, scroll.clientWidth)}px`;
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

    let buffer = "";
    const prompt = () => {
      term.write(`\r\n${device ?? "lab"}# `);
    };
    term.writeln("Device CLI");
    term.writeln("show running-config    show ip interface brief    show ip route");
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
        const text = await api.show(device, trimmed);
        const lines = text.split("\n");
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
      term.dispose();
    };
  }, [device]);

  return (
    <div ref={scrollRef} className="device-cli-scroll h-full w-full">
      <div ref={hostRef} className="h-full" />
    </div>
  );
}
