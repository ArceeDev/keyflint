// Builds ESM with tsc, then derives a CJS bundle from the single-file ESM output.
import { execFileSync } from "node:child_process";
import { mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";

rmSync("dist", { recursive: true, force: true });
execFileSync(process.execPath, ["node_modules/typescript/bin/tsc", "-p", "tsconfig.json"], { stdio: "inherit" });

const esm = readFileSync("dist/esm/index.js", "utf8");
const names = [...esm.matchAll(/^export (?:async )?(?:function|const|class) (\w+)/gm)].map((m) => m[1]);
const cjs =
  '"use strict";\n' +
  esm.replace(/^export (?=(?:async )?(?:function|const|class) )/gm, "") +
  `\nmodule.exports = { ${names.join(", ")} };\n`;
mkdirSync("dist/cjs", { recursive: true });
writeFileSync("dist/cjs/index.cjs", cjs);
writeFileSync("dist/cjs/index.d.cts", readFileSync("dist/esm/index.d.ts", "utf8"));
console.log(`built esm + cjs (${names.length} exports)`);
