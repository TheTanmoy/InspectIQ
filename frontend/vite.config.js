import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// /api calls are proxied to FastAPI, so no CORS issues and no hard-coded URLs.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": "http://localhost:8000" },
  },
});
