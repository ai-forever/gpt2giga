import { Buffer } from "node:buffer";
import { spawnSync } from "node:child_process";
import { readFile, rm, stat, writeFile, mkdir } from "node:fs/promises";
import { extname, join, relative } from "node:path";
import process from "node:process";

import {
  canonicalBrandPath,
  canonicalJson,
  frontendInputFiles,
  lockfilePath,
  namedFilesDigest,
  normalizePath,
  outputRoot,
  projectRoot,
  sha256,
  treeDigest,
  walkFiles,
} from "./asset-contract.mjs";

const viteManifestPath = join(outputRoot, ".vite", "manifest.json");
const formatVersion = "gpt2giga-cockpit-v2-assets-v1";
const provenanceFormatVersion = "gpt2giga-cockpit-assets-provenance-v1";
const sbomFormatVersion = "gpt2giga-cockpit-sbom-v1";
const licenseFormatVersion = "gpt2giga-cockpit-licenses-v1";

const mediaTypes = new Map([
  [".css", "text/css; charset=utf-8"],
  [".html", "text/html; charset=utf-8"],
  [".js", "text/javascript; charset=utf-8"],
  [".json", "application/json; charset=utf-8"],
  [".svg", "image/svg+xml"],
  [".webmanifest", "application/manifest+json"],
  [".woff2", "font/woff2"],
]);

function git(args, fallback = null) {
  const result = spawnSync("git", ["-C", projectRoot, ...args], {
    encoding: "utf8",
    stdio: "pipe",
  });
  if (result.status !== 0) {
    if (fallback !== null) return fallback;
    process.stderr.write(result.stderr);
    process.exit(result.status ?? 1);
  }
  return result.stdout.trim();
}

function packageName(path, record) {
  if (typeof record.name === "string" && record.name !== "") return record.name;
  const prefix = "node_modules/";
  if (!path.startsWith(prefix)) return null;
  const parts = path.slice(prefix.length).split("/");
  return parts[0].startsWith("@") ? parts.slice(0, 2).join("/") : parts[0];
}

function packageUrl(name, version) {
  const encoded = name
    .split("/")
    .map((part) => encodeURIComponent(part))
    .join("/");
  return `pkg:npm/${encoded}@${encodeURIComponent(version)}`;
}

function integrityHash(integrity) {
  const match = integrity.match(/^(sha256|sha384|sha512)-([A-Za-z0-9+/=]+)$/u);
  if (match === null) return null;
  return {
    alg: match[1].toUpperCase().replace("SHA", "SHA-"),
    content: Buffer.from(match[2], "base64").toString("hex"),
  };
}

function supplyChainEvidence(lockfile) {
  const componentsByPurl = new Map();
  for (const [path, record] of Object.entries(lockfile.packages ?? {})) {
    if (path === "" || typeof record !== "object" || record === null) continue;
    const name = packageName(path, record);
    if (name === null || typeof record.version !== "string") continue;
    const purl = packageUrl(name, record.version);
    const component = {
      "bom-ref": purl,
      name,
      purl,
      type: "library",
      version: record.version,
    };
    if (typeof record.license === "string" && record.license !== "") {
      component.licenses = [{ expression: record.license }];
    }
    if (typeof record.integrity === "string" && record.integrity !== "") {
      const hash = integrityHash(record.integrity);
      if (hash !== null) component.hashes = [hash];
    }
    componentsByPurl.set(purl, component);
  }
  const components = [...componentsByPurl.values()];
  components.sort((left, right) =>
    `${left.name}@${left.version}`.localeCompare(`${right.name}@${right.version}`)
  );
  const packages = components.map((component) => ({
    license: component.licenses?.[0]?.expression ?? "UNKNOWN",
    name: component.name,
    version: component.version,
  }));
  return {
    licenses: {
      format_version: licenseFormatVersion,
      package_count: packages.length,
      packages,
    },
    sbom: {
      bomFormat: "CycloneDX",
      components,
      metadata: {
        component: {
          "bom-ref": "pkg:npm/%40gpt2giga/harness-cockpit-v2@0.0.1",
          name: "@gpt2giga/harness-cockpit-v2",
          purl: "pkg:npm/%40gpt2giga/harness-cockpit-v2@0.0.1",
          type: "application",
          version: "0.0.1",
        },
        properties: [
          { name: "gpt2giga:format-version", value: sbomFormatVersion },
        ],
      },
      specVersion: "1.6",
      version: 1,
    },
  };
}

const viteManifest = JSON.parse(await readFile(viteManifestPath, "utf8"));
const entry = viteManifest["index.html"];
if (entry?.isEntry !== true || typeof entry.file !== "string") {
  throw new Error("Vite manifest has no deterministic index entry");
}

const initial = new Set(["index.html", entry.file, ...(entry.css ?? [])]);
const runtimeFiles = await walkFiles(outputRoot, {
  exclude: (name) => (
    name === ".vite"
    || name.startsWith(".vite/")
    || name === "_build"
    || name.startsWith("_build/")
    || name === "manifest.json"
  ),
});
const assets = {};
for (const absolute of runtimeFiles) {
  const name = normalizePath(relative(outputRoot, absolute));
  if (name.endsWith(".br") || name.endsWith(".gz")) {
    await rm(absolute);
    continue;
  }
  const content = await readFile(absolute);
  assets[name] = {
    bytes: content.byteLength,
    media_type: mediaTypes.get(extname(name)) ?? "application/octet-stream",
    sha256: sha256(content),
  };
}

const retainedRuntimeFiles = runtimeFiles.filter(
  (path) => !path.endsWith(".br") && !path.endsWith(".gz"),
);
const outputSha256 = await treeDigest(outputRoot, retainedRuntimeFiles);
const lockfile = JSON.parse(await readFile(lockfilePath, "utf8"));
const evidence = supplyChainEvidence(lockfile);
const buildDirectory = join(outputRoot, "_build");
await mkdir(buildDirectory, { recursive: true });
const sbomContent = canonicalJson(evidence.sbom);
const licensesContent = canonicalJson(evidence.licenses);
const sbomPath = join(buildDirectory, "sbom.cdx.json");
const licensesPath = join(buildDirectory, "licenses.json");
await writeFile(sbomPath, sbomContent);
await writeFile(licensesPath, licensesContent);

const inputs = await frontendInputFiles();
const sourceRevision = (
  process.env.GIGALOOM_SOURCE_REVISION
  ?? process.env.GITHUB_SHA
  ?? git(["rev-parse", "HEAD"])
).toLowerCase();
const sourceStatus = git(
  ["status", "--porcelain", "--untracked-files=all", "--", "frontend", "branding"],
  "",
);
const provenance = {
  brand_sha256: sha256(await readFile(canonicalBrandPath)),
  format_version: provenanceFormatVersion,
  frontend_input_files: inputs.length,
  frontend_input_sha256: await namedFilesDigest(inputs),
  licenses_sha256: sha256(licensesContent),
  lockfile_sha256: sha256(await readFile(lockfilePath)),
  node_version: process.version,
  npm_version: process.env.GIGALOOM_NPM_VERSION ?? "unknown",
  output_sha256: outputSha256,
  sbom_sha256: sha256(sbomContent),
  source_dirty: sourceStatus !== "",
  source_revision: sourceRevision,
};
const provenanceContent = canonicalJson(provenance);
const provenancePath = join(buildDirectory, "provenance.json");
await writeFile(provenancePath, provenanceContent);

async function record(path, relativeName) {
  const content = await readFile(path);
  return {
    bytes: content.byteLength,
    path: relativeName,
    sha256: sha256(content),
  };
}

const manifest = {
  assets,
  build: {
    licenses: await record(licensesPath, "_build/licenses.json"),
    output_sha256: outputSha256,
    provenance: await record(provenancePath, "_build/provenance.json"),
    sbom: await record(sbomPath, "_build/sbom.cdx.json"),
  },
  entry: "index.html",
  format_version: formatVersion,
  initial: [...initial].sort(),
};
await writeFile(join(outputRoot, "manifest.json"), canonicalJson(manifest));
await rm(join(outputRoot, ".vite"), { recursive: true, force: true });

const manifestStat = await stat(join(outputRoot, "manifest.json"));
if (!manifestStat.isFile()) {
  throw new Error("Cockpit V2 manifest was not written");
}
