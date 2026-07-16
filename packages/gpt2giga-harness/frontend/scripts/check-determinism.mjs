import { createHash } from "node:crypto";
import { readdir, readFile } from "node:fs/promises";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname, join, relative, sep } from "node:path";
import process from "node:process";

const frontendRoot = dirname(dirname(fileURLToPath(import.meta.url)));
const outputRoot = join(frontendRoot, "..", "src", "gpt2giga_harness", "ui", "cockpit_v2", "assets");

async function treeDigest(directory) {
  const hash = createHash("sha256");
  async function visit(current) {
    const entries = await readdir(current, { withFileTypes: true });
    for (const entry of entries.sort((left, right) => left.name.localeCompare(right.name))) {
      const absolute = join(current, entry.name);
      if (entry.isDirectory()) {
        await visit(absolute);
      } else if (entry.isFile()) {
        hash.update(relative(directory, absolute).split(sep).join("/"));
        hash.update(await readFile(absolute));
      }
    }
  }
  await visit(directory);
  return hash.digest("hex");
}

function build() {
  const result = spawnSync("npm", ["run", "build"], {
    cwd: frontendRoot,
    encoding: "utf8",
    stdio: "pipe",
  });
  if (result.status !== 0) {
    process.stderr.write(result.stdout);
    process.stderr.write(result.stderr);
    process.exit(result.status ?? 1);
  }
}

build();
const first = await treeDigest(outputRoot);
build();
const second = await treeDigest(outputRoot);
if (first !== second) {
  throw new Error(`Cockpit V2 build is not deterministic: ${first} != ${second}`);
}
process.stdout.write(`deterministic asset tree ${second}\n`);
