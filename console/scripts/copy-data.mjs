// Copies the engine's precomputed output + organiser data into public/data.
// The console is static: it never calls an LLM (README says so).
import { readFileSync, writeFileSync, mkdirSync, existsSync } from "node:fs";
import { resolve } from "node:path";

const root = resolve(import.meta.dirname, "..", "..");
const out = resolve(import.meta.dirname, "..", "public", "data");
mkdirSync(out, { recursive: true });

const results = process.env.RESULTS ? resolve(root, process.env.RESULTS) : resolve(root, "results.json");
const record = process.env.RUN_RECORD ? resolve(root, process.env.RUN_RECORD) : resolve(root, "engine/out/run_record.json");
if (!existsSync(results)) { console.error(`missing ${results}`); process.exit(1); }

const copy = (src, name) => writeFileSync(resolve(out, name), readFileSync(src));
copy(results, "results.json");
for (const f of ["questions.json", "reports.json", "taxonomy.json"]) copy(resolve(root, "data", f), f);

// Slim run record: only what the card shows (which checks ran, solves, guard actions).
let slim = {};
if (existsSync(record)) {
  for (const r of JSON.parse(readFileSync(record, "utf8"))) {
    slim[r.reportId] = {
      checks: (r.checks || []).map(c => ({ id: c.id, passed: c.passed, detail: c.detail })),
      solves: Object.fromEntries(Object.entries(r.solves || {}).map(([k, v]) => [k, v.error ? { error: v.error } : { answer: v.answer, issue: v.issue }])),
      solution_final: r.proof?.solution_final ?? null,
      guard_log: r.guard_log || [],
      validator_errors: r.validator_errors || [],
    };
  }
}
writeFileSync(resolve(out, "run_record.json"), JSON.stringify(slim));
console.log(`console data ← ${results}`);
