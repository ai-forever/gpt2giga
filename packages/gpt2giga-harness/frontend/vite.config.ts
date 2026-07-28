import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";
import type { Plugin } from "vite";
import { defineConfig } from "vitest/config";

const outputDirectory = process.env.GIGALOOM_COCKPIT_OUTPUT ?? fileURLToPath(
  new URL("../src/gpt2giga_harness/ui/cockpit_v2/assets", import.meta.url),
);

function katexWoff2Only(): Plugin {
  return {
    enforce: "pre",
    name: "katex-woff2-only",
    transform(code, id) {
      if (!id.endsWith("/katex/dist/katex.min.css")) return null;
      return code.replace(
        /src:url\(([^)]+\.woff2)\) format\("woff2"\),url\([^)]+\.woff\) format\("woff"\),url\([^)]+\.ttf\) format\("truetype"\)/g,
        'src:url($1) format("woff2")',
      );
    },
  };
}

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
  plugins: [katexWoff2Only(), react()],
  test: {
    environment: "node",
  },
});
