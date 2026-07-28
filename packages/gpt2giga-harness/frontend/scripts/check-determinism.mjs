import { spawnSync } from "node:child_process";
import process from "node:process";

import {
  frontendRoot,
  outputRoot,
  treeDigest,
  walkFiles,
} from "./asset-contract.mjs";

function build() {
  const result = spawnSync(process.execPath, ["scripts/produce-assets.mjs"], {
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

async function completeTreeDigest() {
  const files = await walkFiles(outputRoot);
  return treeDigest(outputRoot, files);
}

build();
const first = await completeTreeDigest();
build();
const second = await completeTreeDigest();
if (first !== second) {
  throw new Error(`Cockpit V2 build is not deterministic: ${first} != ${second}`);
}
process.stdout.write(`deterministic verified asset tree ${second}\n`);
