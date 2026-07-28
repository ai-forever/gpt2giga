import { createHash } from "node:crypto";
import { lstat, readFile, readdir } from "node:fs/promises";
import { dirname, join, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import process from "node:process";

export const frontendRoot = dirname(dirname(fileURLToPath(import.meta.url)));
export const projectRoot = resolve(frontendRoot, "..");
export const repositoryRoot = resolve(projectRoot, "..", "..");
export const canonicalBrandPath = join(projectRoot, "branding", "gigaloom-mark.svg");
export const lockfilePath = join(frontendRoot, "package-lock.json");
export const outputRoot = resolve(
  process.env.GIGALOOM_COCKPIT_OUTPUT
    ?? join(projectRoot, "src", "gpt2giga_harness", "ui", "cockpit_v2", "assets"),
);

export function normalizePath(path) {
  return path.split(sep).join("/");
}

export function sha256(content) {
  return createHash("sha256").update(content).digest("hex");
}

export function canonicalJson(value) {
  return `${JSON.stringify(value, null, 2)}\n`;
}

function compareNames(left, right) {
  return left < right ? -1 : left > right ? 1 : 0;
}

export async function walkFiles(directory, { exclude = () => false } = {}) {
  const files = [];
  async function visit(current) {
    const entries = await readdir(current, { withFileTypes: true });
    for (const entry of entries.sort((left, right) => compareNames(left.name, right.name))) {
      const absolute = join(current, entry.name);
      const relativeName = normalizePath(relative(directory, absolute));
      if (exclude(relativeName, entry)) continue;
      const details = await lstat(absolute);
      if (details.isSymbolicLink()) {
        throw new Error(`Cockpit build input must not contain symlinks: ${relativeName}`);
      }
      if (details.isDirectory()) {
        await visit(absolute);
      } else if (details.isFile()) {
        files.push(absolute);
      } else {
        throw new Error(`Cockpit build input must be a regular file: ${relativeName}`);
      }
    }
  }
  await visit(directory);
  return files;
}

export async function frontendInputFiles() {
  const files = [
    join(frontendRoot, "eslint.config.js"),
    join(frontendRoot, "index.html"),
    join(frontendRoot, "package-lock.json"),
    join(frontendRoot, "package.json"),
    join(frontendRoot, "tsconfig.json"),
    join(frontendRoot, "vite.config.ts"),
    ...(await walkFiles(join(frontendRoot, "scripts"))),
    ...(await walkFiles(join(frontendRoot, "src"))),
    ...(await walkFiles(join(frontendRoot, "public"), {
      exclude: (name) => name === "brand" || name.startsWith("brand/"),
    })),
    join(projectRoot, "branding", "generate-assets.mjs"),
    canonicalBrandPath,
  ];
  return files.sort((left, right) => compareNames(
    normalizePath(relative(projectRoot, left)),
    normalizePath(relative(projectRoot, right)),
  ));
}

export async function namedFilesDigest(files, root = projectRoot) {
  const hash = createHash("sha256");
  for (const absolute of files) {
    const name = normalizePath(relative(root, absolute));
    hash.update(name);
    hash.update("\0");
    hash.update(await readFile(absolute));
    hash.update("\0");
  }
  return hash.digest("hex");
}

export async function treeDigest(directory, files) {
  const hash = createHash("sha256");
  const ordered = [...files].sort((left, right) => compareNames(
    normalizePath(relative(directory, left)),
    normalizePath(relative(directory, right)),
  ));
  for (const absolute of ordered) {
    hash.update(normalizePath(relative(directory, absolute)));
    hash.update("\0");
    hash.update(await readFile(absolute));
    hash.update("\0");
  }
  return hash.digest("hex");
}
