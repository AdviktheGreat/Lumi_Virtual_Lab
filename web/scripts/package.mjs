// Puts the built pages where the server looks for them in an install, which is src/virtual_lab/server/static, so that
// pip install carries the interface with it. Run it through `npm run package`, which builds the pages first.
import { cpSync, existsSync, rmSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const web = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const built = join(web, "out");
const packaged = resolve(web, "..", "src", "virtual_lab", "server", "static");

if (!existsSync(join(built, "index.html"))) {
  console.error(`There are no built pages in ${built}. Run npm run build first.`);
  process.exit(1);
}
rmSync(packaged, { recursive: true, force: true });
cpSync(built, packaged, { recursive: true });
console.log(`The pages are in ${packaged}.`);
