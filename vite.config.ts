import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      // Development only: production builds are served by FastAPI on the same origin.
      "/api": "http://127.0.0.1:8000",
    },
  },
});
