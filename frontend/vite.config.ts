import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5180,
    // The API is reached through the Compose web proxy (port 8088), never directly.
    proxy: { "/api": process.env.OWNCLOUD_API ?? "http://localhost:8088" },
  },
});
