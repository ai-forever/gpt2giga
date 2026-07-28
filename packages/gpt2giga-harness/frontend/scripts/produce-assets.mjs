import { mkdtemp, rename, rm } from "node:fs/promises";
import { spawnSync } from "node:child_process";
import { dirname, join } from "node:path";
import process from "node:process";

import { frontendRoot, outputRoot, projectRoot } from "./asset-contract.mjs";

const requireClean = process.argv.includes("--require-clean");
const minimumNode = [22, 13, 0];
const minimumNpm = [11, 0, 0];
const releaseNode = "v22.13.0";
const releaseNpm = "11.17.0";

function versionTuple(value) {
  const match = String(value).match(/(\d+)\.(\d+)\.(\d+)/u);
  if (match === null) return null;
  return match.slice(1).map(Number);
}

function atLeast(actual, minimum) {
  return actual !== null && actual.some((part, index) => {
    if (part === minimum[index]) return false;
    return part > minimum[index]
      && actual.slice(0, index).every((previous, previousIndex) => previous === minimum[previousIndex]);
  }) || actual?.every((part, index) => part === minimum[index]);
}

function run(command, args, options = {}) {
  const result = spawnSync(command, args, {
    cwd: frontendRoot,
    encoding: "utf8",
    env: { ...process.env, ...options.env },
    stdio: options.capture ? "pipe" : "inherit",
  });
  if (result.status !== 0) {
    if (options.capture) {
      process.stderr.write(result.stdout ?? "");
      process.stderr.write(result.stderr ?? "");
    }
    process.exit(result.status ?? 1);
  }
  return (result.stdout ?? "").trim();
}

const npmCommand = process.platform === "win32" ? "npm.cmd" : "npm";
const npmVersion = run(npmCommand, ["--version"], { capture: true });
const nodeAccepted = atLeast(versionTuple(process.version), minimumNode);
const npmAccepted = atLeast(versionTuple(npmVersion), minimumNpm);
if (!nodeAccepted || !npmAccepted) {
  const message = (
    `Cockpit release assets require Node >=22.13.0 and npm >=11.0.0; `
    + `found ${process.version} and npm ${npmVersion}`
  );
  if (requireClean) throw new Error(message);
  process.stderr.write(`warning: ${message}\n`);
}
if (
  requireClean
  && (process.version !== releaseNode || npmVersion !== releaseNpm)
) {
  throw new Error(
    `Cockpit release assets require Node ${releaseNode} and npm ${releaseNpm}; `
    + `found ${process.version} and npm ${npmVersion}`,
  );
}

if (requireClean) {
  const status = run(
    "git",
    [
      "-C",
      projectRoot,
      "status",
      "--porcelain",
      "--untracked-files=all",
      "--",
      "frontend",
      "branding",
    ],
    { capture: true },
  );
  if (status !== "") {
    throw new Error("Release Cockpit assets require clean frontend and branding inputs");
  }
}

const parent = dirname(outputRoot);
const temporary = await mkdtemp(join(parent, ".cockpit-assets-build-"));
const backup = `${outputRoot}.previous-${process.pid}`;
const buildEnvironment = {
  GIGALOOM_COCKPIT_OUTPUT: temporary,
  GIGALOOM_NPM_VERSION: npmVersion,
};

try {
  run(
    process.execPath,
    [join(projectRoot, "branding", "generate-assets.mjs"), "--frontend-only"],
  );
  run(
    process.execPath,
    [join(frontendRoot, "node_modules", "vite", "bin", "vite.js"), "build"],
    { env: buildEnvironment },
  );
  run(process.execPath, [join(frontendRoot, "scripts", "package-assets.mjs")], {
    env: buildEnvironment,
  });
  run(process.execPath, [join(frontendRoot, "scripts", "verify-build.mjs")], {
    env: buildEnvironment,
  });

  await rm(backup, { force: true, recursive: true });
  try {
    await rename(outputRoot, backup);
  } catch (error) {
    if (error?.code !== "ENOENT") throw error;
  }
  try {
    await rename(temporary, outputRoot);
  } catch (error) {
    try {
      await rename(backup, outputRoot);
    } catch {
      // Preserve the original replacement error and leave the backup for recovery.
    }
    throw error;
  }
  await rm(backup, { force: true, recursive: true });
} finally {
  await rm(temporary, { force: true, recursive: true });
}

process.stdout.write(`produced verified Cockpit assets at ${outputRoot}\n`);
