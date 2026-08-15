// Checks the chat renderer without a browser.
//
// Two things have gone wrong here before and both are invisible to every other check:
//   1. app.html's <script> is never parsed by any test, so a syntax error ships.
//   2. An agent with an `output_schema` had its raw JSON payload rendered verbatim
//      into a speech bubble. Every assertion passed; the user saw the wire format.
//
// Run: node scripts/check_render.mjs
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import vm from 'node:vm';

const here = dirname(fileURLToPath(import.meta.url));
const html = readFileSync(join(here, '..', 'challenge_accepted', 'static', 'app.html'), 'utf8');

const fail = (m) => { console.error('FAIL: ' + m); process.exitCode = 1; };
const ok = (m) => console.log('ok  : ' + m);

// ---- 1. the whole script block must parse -------------------------------------
const blocks = [...html.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/gi)]
  .map(m => m[1]);
if (!blocks.length) fail('no inline <script> found in app.html');
let src = '';
for (const [i, b] of blocks.entries()) {
  try { new vm.Script(b, { filename: `app.html:script[${i}]` }); }
  catch (e) { fail(`script block ${i} does not parse: ${e.message}`); }
  src += b + '\n';
}
if (!process.exitCode) ok(`${blocks.length} inline script block(s) parse`);

// ---- 2. the payload guard must be wired into the render loop -------------------
for (const needle of ['looksStructured', 'specSummary', 'flushHeld']) {
  if (!src.includes(needle)) fail(`${needle} is missing from app.html`);
}
// Defined but unused is exactly the state this file exists to catch.
const uses = (name) => (src.match(new RegExp(`\\b${name}\\b`, 'g')) || []).length;
if (uses('looksStructured') < 2) fail('looksStructured is defined but never called');
if (uses('specSummary') < 2) fail('specSummary is defined but never called');
if (uses('flushHeld') < 3) fail('flushHeld is defined but not called on both paths');
if (!process.exitCode) ok('payload guard is wired into the stream loop');

// ---- 3. behaviour of the two pure helpers --------------------------------------
const ctx = vm.createContext({});
const helpers = src.match(/const looksStructured[\s\S]*?\n}\n/)?.[0];
if (!helpers) fail('could not extract the helpers from app.html');
// `const` inside a vm script does not land on the context object -- hand them over.
vm.runInContext(
  helpers + '\nthis.looksStructured = looksStructured; this.specSummary = specSummary;',
  ctx);
const { looksStructured, specSummary } = ctx;

const payload = JSON.stringify({
  specs: [
    { node_id: 'audit-34-sites', needed: true, tool_type: 'checklist',
      name: 'Site Tier Audit & Prioritization Checklist' },
    { node_id: 'outreach', needed: true, tool_type: 'tracker', name: 'Outreach Tracker' },
    { node_id: 'think-about-it', needed: false, name: 'Reflect' },
  ],
});

if (!looksStructured(payload)) fail('a bare JSON object is not detected as structured');
if (!looksStructured('```json\n{"specs": []}\n```')) fail('a fenced payload is not detected');
if (looksStructured('Here is the plan: build two tools.')) fail('prose detected as structured');

const summary = specSummary(payload);
if (!summary) fail('specSummary returned null for a real spec list');
else {
  if (/node_id|needed|"/.test(summary)) fail('summary still contains wire format: ' + summary);
  if (!summary.includes('Planned 2 tools')) fail('wrong count: ' + summary);
  if (!summary.includes('Site Tier Audit & Prioritization Checklist'))
    fail('tool name missing from summary');
  if (!/judged 1 step/.test(summary)) fail('skipped specs not accounted for: ' + summary);
}
if (specSummary('not json at all') !== null) fail('specSummary should return null on prose');
if (specSummary('{"specs": []}') !== null) fail('specSummary should return null on empty specs');
if (!process.exitCode) {
  ok('specSummary renders a sentence, not a payload');
  console.log('\n--- what the user now sees instead of JSON ---\n' + summary + '\n');
  console.log('PASS');
}
