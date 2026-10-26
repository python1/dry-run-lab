import { createHash } from "node:crypto";
import path from "node:path";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig, type Plugin } from "vite";

// The name is the hash of the bytes that ship. A later edit of a file Vite
// already named left the broken script and the fixed script both called
// index-NBzIT_bQ.js, so a browser kept the broken copy.
function shipContentHash(): Plugin {
  return {
    name: "ship-content-hash",
    enforce: "post",
    renderChunk(code) {
      const next = code
        .split("\n")
        .map((line) => (line.trim() === "" ? "" : line))
        .join("\n");
      return next === code ? null : { code: next, map: null };
    },
    generateBundle(_options, bundle) {
      const renames: Array<[string, string]> = [];
      for (const item of Object.values(bundle)) {
        if (item.type !== "chunk" || !item.fileName.endsWith(".js")) continue;
        const hash = createHash("sha256").update(item.code).digest("hex").slice(0, 8);
        const parts = item.fileName.split("/");
        const base = parts.pop() ?? "index.js";
        const stem = base.replace(/-[A-Za-z0-9_-]+\.js$/, "").replace(/\.js$/, "");
        const next = [...parts, `${stem}-${hash}.js`].join("/");
        if (next === item.fileName) continue;
        renames.push([item.fileName, next]);
        item.fileName = next;
      }
      for (const item of Object.values(bundle)) {
        if (item.type !== "asset" || typeof item.source !== "string") continue;
        let source = item.source;
        for (const [from, to] of renames) source = source.split(from).join(to);
        item.source = source;
      }
    },
  };
}

export default defineConfig({
  plugins: [react(), tailwindcss(), shipContentHash()],
  server: { host: "127.0.0.1", port: 8743, strictPort: true },
  build: {
    outDir: path.resolve(__dirname, "../src/dryrun_lab/static"),
    emptyOutDir: true,
  },
});
