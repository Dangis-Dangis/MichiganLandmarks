/**
 * Copy the debug APK to a stable sideload path: dist/MichiganLandmarks-debug.apk
 */
import { copyFile, mkdir } from "node:fs/promises";
import { existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const src = join(here, "android", "app", "build", "outputs", "apk", "debug", "app-debug.apk");
const destDir = join(here, "dist");
const dest = join(destDir, "MichiganLandmarks-debug.apk");

if (!existsSync(src)) {
  console.error(
    "ERROR: debug APK not found. Build it first:\n" +
      "  npm run apk:debug\n" +
      "  or Android Studio → Build → Build APK(s)"
  );
  process.exit(1);
}

await mkdir(destDir, { recursive: true });
await copyFile(src, dest);
console.log(`developer APK: ${dest}`);
