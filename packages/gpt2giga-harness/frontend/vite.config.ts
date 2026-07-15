import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

const outputDirectory = fileURLToPath(
  new URL("../src/gpt2giga_harness/ui/cockpit_v2/assets", import.meta.url),
);

export default defineConfig({
  base: "/cockpit-v2/assets/",
  build: {
    assetsDir: "assets",
    assetsInlineLimit: 0,
    emptyOutDir: true,
    manifest: true,
    outDir: outputDirectory,
    rollupOptions: {
      output: {
        assetFileNames: "assets/[name]-[hash][extname]",
        chunkFileNames: "assets/[name]-[hash].js",
        entryFileNames: "assets/[name]-[hash].js",
      },
    },
    sourcemap: false,
    target: "es2022",
  },
  plugins: [react()],
  test: {
    environment: "node",
  },
});
