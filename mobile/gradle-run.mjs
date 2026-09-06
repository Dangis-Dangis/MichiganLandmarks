/**
 * Run a Gradle task with the platform wrapper (gradlew / gradlew.bat).
 * Usage: node gradle-run.mjs assembleDebug
 */
import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const task = process.argv[2];
if (!task) {
  console.error("usage: node gradle-run.mjs <gradle-task>");
  process.exit(1);
}

const here = dirname(fileURLToPath(import.meta.url));
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
});
process.exit(result.status === null ? 1 : result.status);
