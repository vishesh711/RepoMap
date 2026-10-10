/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: { port: 5173 },
  build: {
    rollupOptions: {
      output: {
        // Libraries change rarely; keep them in their own long-cached files.
        manualChunks: {
          react: ["react", "react-dom", "react-dom/client", "react-router-dom"],
          supabase: ["@supabase/supabase-js"],
        },
      },
    },
  },
  test: { environment: "jsdom", globals: false },
});
