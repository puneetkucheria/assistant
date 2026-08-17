import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In dev: serve UI on :5173 and proxy /api to the FastAPI backend on :8000.
// In production: `npm run build` emits to ../backend/static/ so the FastAPI
// process can serve the SPA at a single origin on the LAN.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://localhost:8000", changeOrigin: true },
    },
  },
  build: {
    outDir: "../backend/static",
    emptyOutDir: true,
  },
});
