import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev server proxies the API + SSE to the FastAPI backend on :8000, so the
// frontend always develops against the real thing (no mock emitter).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
        // critical for the SSE stream: don't buffer
        configure: (proxy) => {
          proxy.on("proxyReq", (proxyReq) => proxyReq.setHeader("Accept-Encoding", "identity"));
        },
      },
      // A2A discovery lives at the root well-known path (outside /api).
      "/.well-known": { target: "http://127.0.0.1:8000", changeOrigin: true },
    },
  },
  build: { outDir: "dist", chunkSizeWarningLimit: 1500 },
});
