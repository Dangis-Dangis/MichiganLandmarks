// Assembles mobile/www from the repo-root UI + the generated data the app loads
// (index + per-record details). Other pipeline outputs (geojson, csv, kml, report)
// are excluded to keep the APK smaller.
import { rm, mkdir, cp, copyFile, stat } from "node:fs/promises";
import { existsSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, "..");
const www = join(here, "www");

const FILES = ["index.html", "app.js", "styles.css", "manifest.webmanifest", "legal.html"];
const DIRS = ["icons", "data/details"];
const DATA_FILES = ["data/landmarks.index.json"];

async function main() {
  if (!existsSync(join(root, "data", "landmarks.index.json"))) {
    console.error("ERROR: data/landmarks.index.json not found. Run `python -m pipeline.run` first.");
    process.exit(1);
  }

  await rm(www, { recursive: true, force: true });
  await mkdir(join(www, "data"), { recursive: true });

  for (const f of FILES) await copyFile(join(root, f), join(www, f));
  for (const f of DATA_FILES) await copyFile(join(root, f), join(www, f));

  // icons: copy everything except the generator script
  await cp(join(root, "icons"), join(www, "icons"), {
    recursive: true,
    filter: (src) => !src.endsWith(".py"),
  });
  await cp(join(root, "data", "details"), join(www, "data", "details"), { recursive: true });

  const details = await stat(join(www, "data", "details"));
  console.log(`www assembled at ${www}`);
  console.log(`  files: ${FILES.concat(DATA_FILES).join(", ")}`);
  console.log(`  dirs:  ${DIRS.join(", ")} (details present: ${details.isDirectory()})`);
}

main();
