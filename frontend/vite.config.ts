import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Proxy API + SSE to the FastAPI backend during development.
const backend = process.env.VITE_BACKEND_URL ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // SSE streams through these (http-proxy streams responses); changeOrigin
      // keeps the Host header consistent for the backend.
      "/v1": { target: backend, changeOrigin: true },
      "/healthz": { target: backend, changeOrigin: true },
      "/readyz": { target: backend, changeOrigin: true },
    },
  },
  build: {
    sourcemap: true,
    rollupOptions: {
      output: {
        // Split the React runtime into its own long-cacheable vendor chunk.
        manualChunks: { react: ["react", "react-dom"] },
      },
    },
  },
});
