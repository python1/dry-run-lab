import path from "node:path";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { host: "127.0.0.1", port: 8743, strictPort: true },
  build: {
    outDir: path.resolve(__dirname, "../src/dryrun_lab/static"),
    emptyOutDir: true,
  },
});
