// Builds ESM (dist/esm) and CommonJS (dist/cjs) with tsc; no bundler needed.
import { execFileSync } from "node:child_process";
import { rmSync, writeFileSync } from "node:fs";

const tsc = (project) =>
  execFileSync(process.execPath, ["node_modules/typescript/bin/tsc", "-p", project], { stdio: "inherit" });

rmSync("dist", { recursive: true, force: true });
tsc("tsconfig.json");
tsc("tsconfig.cjs.json");
writeFileSync("dist/esm/package.json", '{ "type": "module" }\n');
writeFileSync("dist/cjs/package.json", '{ "type": "commonjs" }\n');
console.log("built dist/esm + dist/cjs");
