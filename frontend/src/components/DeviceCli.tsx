import { FitAddon } from "@xterm/addon-fit";
import { Terminal } from "@xterm/xterm";
import { useEffect, useRef } from "react";
import "@xterm/xterm/css/xterm.css";
import { api } from "../api";

export function DeviceCli({ device }: { device: string | null }) {
  const host = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const node = host.current;
    if (!node) return;
    const term = new Terminal({
      fontFamily: "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
      fontSize: 13,
      cursorBlink: true,
      convertEol: true,
      scrollback: 2000,
      theme: {
        background: "#10140c",
        foreground: "#f4ecda",
        cursor: "#e2a84a",
        selectionBackground: "#3a4130",
      },
    });
    const fit = new FitAddon();
    term.loadAddon(fit);
    term.open(node);
    fit.fit();
    const observer = new ResizeObserver(() => fit.fit());
    observer.observe(node);

    let buffer = "";
    const prompt = () => {
      term.write(`\r\n${device ?? "lab"}# `);
    };
    term.writeln("Device CLI  ·  COMPUTED / SIMULATED");
    term.writeln("show running-config    show ip interface brief    show ip route");
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
        for (const line of body) term.writeln(line);
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

  return <div ref={host} className="h-full w-full" />;
}
