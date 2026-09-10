/**
 * Run a Gradle task with the platform wrapper (gradlew / gradlew.bat).
 * Loads repo-root `.env` (JAVA_HOME) the same way the pipeline does, so Cursor
 * tasks and a bare `npm run apk:debug` do not need the variable in the shell.
 * Usage: node gradle-run.mjs assembleDebug
 */
import { spawnSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

function loadDotenv(path) {
  if (!existsSync(path)) return;
  for (const raw of readFileSync(path, "utf8").split(/\r?\n/)) {
    const line = raw.trim();
    if (!line || line.startsWith("#") || !line.includes("=")) continue;
    const eq = line.indexOf("=");
    const key = line.slice(0, eq).trim();
    if (!key) continue;
    let value = line.slice(eq + 1).trim();
    if (
      value.length >= 2 &&
      value[0] === value[value.length - 1] &&
      (value[0] === '"' || value[0] === "'")
    ) {
      value = value.slice(1, -1);
    }
    if (process.env[key] === undefined) process.env[key] = value;
  }
}

const task = process.argv[2];
if (!task) {
  console.error("usage: node gradle-run.mjs <gradle-task>");
  process.exit(1);
}

const here = dirname(fileURLToPath(import.meta.url));
loadDotenv(resolve(here, "..", ".env"));

const javaHome = (process.env.JAVA_HOME || "").trim();
if (!javaHome) {
  console.error(
    "ERROR: JAVA_HOME is not set. Add the JDK 21 root (not bin/) to the repo-root .env (see .env.example) or export it in your shell.",
  );
  process.exit(1);
}

const android = join(here, "android");
if (!existsSync(android)) {
  console.error("ERROR: mobile/android is missing. Run `npm run add:android` first.");
  process.exit(1);
}

const isWin = process.platform === "win32";
const cmd = isWin ? "gradlew.bat" : "./gradlew";
const result = spawnSync(cmd, [task], {
  cwd: android,
  stdio: "inherit",
  shell: isWin,
  env: process.env,
});
process.exit(result.status === null ? 1 : result.status);
