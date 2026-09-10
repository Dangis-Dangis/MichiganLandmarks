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

const FILES = ["index.html", "app.js", "wiki.js", "styles.css", "manifest.webmanifest", "legal.html", "CHANGELOG.md"];
const DIRS = ["icons", "vendor", "docs", "data/details"];
const DATA_FILES = ["data/landmarks.index.json"];

function posixPath(p) {
  return String(p).replace(/\\/g, "/");
}

/** User Help docs only — skip maintainer handbooks and this folder README. */
function includeUserDocs(src) {
  const n = posixPath(src);
  if (n.includes("/docs/dev/") || n.endsWith("/docs/dev")) return false;
  if (n.endsWith("/docs/README.md")) return false;
  return true;
}

async function main() {
  if (!existsSync(join(root, "data", "landmarks.index.json"))) {
    console.error("ERROR: data/landmarks.index.json not found. Run `python -m pipeline.run` first.");
    process.exit(1);
  }
  if (!existsSync(join(root, "vendor", "marked.min.js"))) {
    console.error("ERROR: vendor/marked.min.js not found.");
    process.exit(1);
  }
  if (!existsSync(join(root, "docs", "index.json"))) {
    console.error("ERROR: docs/index.json not found.");
    process.exit(1);
  }
  if (!existsSync(join(root, "docs", "roadmap", "ios.md"))) {
    console.error("ERROR: docs/roadmap/ios.md not found.");
    process.exit(1);
  }

  await rm(www, { recursive: true, force: true });
  await mkdir(join(www, "data"), { recursive: true });

  for (const f of FILES) await copyFile(join(root, f), join(www, f));
  for (const f of DATA_FILES) await copyFile(join(root, f), join(www, f));

  await cp(join(root, "vendor"), join(www, "vendor"), { recursive: true });
  await cp(join(root, "docs"), join(www, "docs"), {
    recursive: true,
    filter: includeUserDocs,
  });
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
