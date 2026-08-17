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
// The Quartermaster is allowed to decide nothing needs building. That must still be a
// sentence -- returning null here put the whole payload back on screen as JSON.
const noneNeeded = specSummary(JSON.stringify({
  specs: [{ node_id: 'a', needed: false }, { node_id: 'b', needed: false }],
}));
if (!noneNeeded) fail('an all-skipped spec list falls back to raw JSON');
else if (/node_id|"/.test(noneNeeded)) fail('all-skipped summary leaks wire format');

if (specSummary('not json at all') !== null) fail('specSummary should return null on prose');
if (specSummary('{"specs": []}') !== null) fail('specSummary should return null on empty specs');

// ---- 4. checklistItems, which decides whether a tool is usable or just readable --
// A `checklist` that fails to parse into items falls through to `<pre class="src">`,
// so this function is the whole difference between a tool you tick and a tool you
// read. Both cases below are VERBATIM shapes from tools the Toolwright built on
// production -- not invented ones. The first shipped broken.
const clSrc = src.match(/function checklistItems\(src\)[\s\S]*?\n}\n/)?.[0];
if (!clSrc) fail('could not extract checklistItems from app.html');
else {
  const c2 = vm.createContext({ JSON });
  vm.runInContext(clSrc + '\nthis.checklistItems = checklistItems;', c2);
  const { checklistItems } = c2;

  // Nested one level down, with no array at the top level at all.
  const nested = checklistItems(JSON.stringify({
    tool_name: 'Race Week Taper', target_finish_time: '54:50',
    taper_workout_schedule: {
      volume_reduction: 'Reduce volume 40% race week',
      schedule: [
        { day: 'Sunday (-7 days)', workout: 'Final light long run: 8 km easy pace' },
        { day: 'Monday (-6 days)', workout: 'Rest day / Foam rolling' },
      ],
    },
  }));
  if (!nested) fail('a checklist whose items are nested one level renders as raw JSON');
  else {
    if (nested.length !== 2) fail(`nested checklist: ${nested.length} items, expected 2`);
    // `{day, workout}` uses none of the known text keys. Dropping it lost the tool.
    if (!/Sunday/.test(nested[0]?.text || ''))
      fail('unfamiliar item keys were discarded: ' + JSON.stringify(nested[0]));
  }

  // A top-level array must still win over anything buried deeper.
  const top = checklistItems(JSON.stringify({
    title: 'Winter Gear',
    checklist_items: [{ step: 1, item: 'Gait test', description: 'At a running shop' }],
    appendix: { notes: { extra: ['not these'] } },
  }));
  if (!top || top.length !== 1 || top[0].text !== 'Gait test')
    fail('a top-level checklist lost to a nested array: ' + JSON.stringify(top));

  if (checklistItems('def main():') !== null) fail('Python parsed as a checklist');
  if (checklistItems('{"a": 1}') !== null) fail('an object with no list became items');
  if (!process.exitCode) ok('checklistItems finds items in the shapes the model emits');
}

if (!process.exitCode) {
  ok('specSummary renders a sentence, not a payload');
  console.log('\n--- what the user now sees instead of JSON ---\n' + summary + '\n');
  console.log('PASS');
}
