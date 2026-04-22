import { spawnSync } from "node:child_process";

const ADMIN_ASSETS_DIR = "packages/gpt2giga-ui/src/gpt2giga_ui/static/admin";

function runGitStatus() {
  return spawnSync("git", ["status", "--short", "--", ADMIN_ASSETS_DIR], {
    encoding: "utf8",
  });
}

const result = runGitStatus();

if (result.status !== 0) {
  const stderr = result.stderr.trim();
  if (stderr) {
    console.error(stderr);
  }
  process.exit(result.status ?? 1);
}

const changedAssets = result.stdout
  .split("\n")
  .map((line) => line.trimEnd())
  .filter(Boolean);

if (changedAssets.length === 0) {
  console.log(`Admin assets are in sync under ${ADMIN_ASSETS_DIR}.`);
  process.exit(0);
}

console.error(
  [
    "Compiled admin assets are stale.",
    "Run 'npm run sync:admin' and commit the updated files under",
    `${ADMIN_ASSETS_DIR}.`,
    "",
    "Changed files:",
    ...changedAssets,
  ].join("\n"),
);
process.exit(1);
