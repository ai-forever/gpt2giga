import { createHash } from "node:crypto";
import { readFile, stat } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const frontendRoot = dirname(dirname(fileURLToPath(import.meta.url)));
const outputRoot = join(frontendRoot, "..", "src", "gpt2giga_harness", "ui", "cockpit_v2", "assets");
const manifest = JSON.parse(await readFile(join(outputRoot, "manifest.json"), "utf8"));

if (manifest.format_version !== "gpt2giga-cockpit-v2-assets-v1" || manifest.entry !== "index.html") {
  throw new Error("Unexpected Cockpit V2 asset manifest contract");
}
if (!Array.isArray(manifest.initial) || manifest.initial.length < 2) {
  throw new Error("Initial asset graph is missing");
}

let initialCompressedBytes = 0;
let initialJavaScriptBytes = 0;
for (const [name, record] of Object.entries(manifest.assets)) {
  const content = await readFile(join(outputRoot, name));
  const digest = createHash("sha256").update(content).digest("hex");
  if (digest !== record.sha256 || content.byteLength !== record.bytes) {
    throw new Error(`Asset integrity mismatch: ${name}`);
  }
  for (const [variant, expectedDigest] of [
    [record.gzip, record.gzip_sha256],
    [record.brotli, record.brotli_sha256],
  ]) {
    if (typeof variant === "string" && !(await stat(join(outputRoot, variant))).isFile()) {
      throw new Error(`Compressed asset is missing: ${variant}`);
    }
    if (typeof variant === "string") {
      const variantContent = await readFile(join(outputRoot, variant));
      const variantDigest = createHash("sha256").update(variantContent).digest("hex");
      if (variantDigest !== expectedDigest) {
        throw new Error(`Compressed asset integrity mismatch: ${variant}`);
      }
    }
  }
  if (manifest.initial.includes(name)) {
    initialCompressedBytes += record.brotli_bytes ?? record.bytes;
    if (name.endsWith(".js")) {
      initialJavaScriptBytes += record.brotli_bytes ?? record.bytes;
    }
  }
}

if (initialCompressedBytes > 200 * 1024) {
  throw new Error(`Initial compressed assets exceed 200 KiB: ${initialCompressedBytes}`);
}
if (initialJavaScriptBytes > 100 * 1024) {
  throw new Error(`Initial JavaScript exceeds 100 KiB: ${initialJavaScriptBytes}`);
}

const names = Object.keys(manifest.assets);
for (const requiredPrefix of [
  "assets/workbench-",
  "assets/runs-",
  "assets/automation-",
  "assets/evaluation-",
  "assets/integrations-",
  "assets/markdown-",
  "assets/diff-",
  "assets/terminal-",
  "assets/editor-",
  "assets/raw-evidence-",
  "assets/settings-",
]) {
  if (!names.some((name) => name.startsWith(requiredPrefix) && name.endsWith(".js"))) {
    throw new Error(`Expected lazy chunk is missing: ${requiredPrefix}`);
  }
}

const index = await readFile(join(outputRoot, "index.html"), "utf8");
if (/https?:\/\//u.test(index) || /<script(?![^>]*\bsrc=)/u.test(index)) {
  throw new Error("Cockpit V2 index must load only CSP-safe local script assets");
}

const initialStyles = (
  await Promise.all(
    manifest.initial
      .filter((name) => name.endsWith(".css"))
      .map((name) => readFile(join(outputRoot, name), "utf8")),
  )
).join("\n");
if (/\.message-entry\s+strong\b/u.test(initialStyles)) {
  throw new Error("Message chrome must not override semantic Markdown strong styles");
}
if (!/\.message-role\b/u.test(initialStyles) || !/\.message-markdown\s+strong\b/u.test(initialStyles)) {
  throw new Error("Packaged chat typography contract is missing");
}
