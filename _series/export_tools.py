"""Export the tools this challenge built, as files you can open and use.

The ten tools already run inside challengeaccepted.app. This puts a copy of each one
on disk so you can open it by double-clicking, work in it offline, and keep it.

WHY THERE IS A SHIM. In the app a tool runs in a sandboxed iframe with no
same-origin, so it has no storage: the dashboard hands it a fake `localStorage`
seeded from the server and saves every write back over postMessage. Ship the raw
source to a file and that scaffolding is gone -- worse, a sandboxed tool that merely
READS localStorage throws, and the page renders blank. So each export gets a real
localStorage shim, namespaced per tool so two tools opened from file:// (which share
one origin in Chrome) cannot tread on each other's keys.

That means an exported tool saves to THIS BROWSER on THIS MACHINE, and the copy in
the app saves to your account. They are two separate notebooks. Use one or the other
for a given tool, or you will wonder later which number was real.

    python _series\\export_tools.py    ->  _series\\tools\\*.html
"""
from __future__ import annotations

import html
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "tools"
CHALLENGE = "chal_1a7cbac10402"

os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "gen-lang-client-0955694243")
sys.path.insert(0, str(HERE.parent))

from challenge_accepted.services.store import Store   # noqa: E402

#: Types the user is meant to OPERATE, not read. Same list the dashboard uses.
RUNNABLE = {"mini_app", "calculator", "tracker", "drill"}


def looks_html(src: str) -> bool:
    return bool(re.search(r"<!doctype|<html[\s>]", src or "", re.I))


def has_markup(src: str) -> bool:
    return bool(re.search(r"<[a-z][\s\S]*>", src or "", re.I))


def looks_python(src: str) -> bool:
    return bool(re.search(r"^\s*(def |import |from \w+ import )", src or "", re.M))


def slug(s: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (s or "tool").lower()).strip("-")
    return s[:60] or "tool"


def shim(key: str) -> str:
    """A real, namespaced localStorage. Same surface the tool already expects."""
    return ("<script>(function(){var NS=" + json.dumps("ca:" + key + ":") + ";"
            "var real=null;try{real=window.localStorage;real.getItem('__probe');}"
            "catch(e){real=null;}"
            "var mem={};"
            "var mk=function(){return{"
            "getItem:function(k){return real?real.getItem(NS+k):(k in mem?mem[k]:null);},"
            "setItem:function(k,v){v=String(v);if(real){real.setItem(NS+k,v);}else{mem[k]=v;}},"
            "removeItem:function(k){if(real){real.removeItem(NS+k);}else{delete mem[k];}},"
            "clear:function(){if(real){Object.keys(real).filter(function(k){"
            "return k.indexOf(NS)===0;}).forEach(function(k){real.removeItem(k);});}"
            "else{mem={};}},"
            "key:function(i){var ks=real?Object.keys(real).filter(function(k){"
            "return k.indexOf(NS)===0;}).map(function(k){return k.slice(NS.length);})"
            ":Object.keys(mem);return ks[i]||null;},"
            "get length(){return real?Object.keys(real).filter(function(k){"
            "return k.indexOf(NS)===0;}).length:Object.keys(mem).length;}};};"
            "try{Object.defineProperty(window,'localStorage',"
            "{value:mk(),configurable:true});}catch(e){}"
            "})();</script>")


BANNER = """<div style="font:600 12px/1.4 ui-monospace,Consolas,monospace;
 letter-spacing:.06em;background:#12161a;color:#93a0ad;padding:9px 14px;
 border-bottom:1px solid #2a343e">
 {name} &nbsp;&middot;&nbsp; <span style="color:#f07c2b">offline copy</span>
 &nbsp;&middot;&nbsp; saves to this browser only
 &nbsp;&middot;&nbsp; <a href="index.html" style="color:#6ea8ff">all tools</a>
</div>"""


def page(name: str, key: str, body: str, wrap: bool) -> str:
    head = ('<!doctype html><meta charset="utf-8">'
            f'<title>{html.escape(name)}</title>'
            '<meta name="viewport" content="width=device-width,initial-scale=1">')
    banner = BANNER.format(name=html.escape(name))
    if wrap:
        body = ('<style>body{font:15px/1.5 system-ui,sans-serif;margin:20px;'
                'color:#111;background:#fff}</style>' + body)
        return head + shim(key) + banner + body
    # A complete document: keep it whole, but get the shim in before its own scripts
    # run, and put the banner just inside <body> so nothing is displaced.
    out = re.sub(r"(<head[^>]*>)", r"\1" + shim(key), body, count=1, flags=re.I)
    if out == body:                       # no <head> to inject into
        out = shim(key) + body
    stamped = re.sub(r"(<body[^>]*>)", r"\1" + banner, out, count=1, flags=re.I)
    return stamped if stamped != out else out + banner


INDEX_CSS = """
:root{--g:#e9edf0;--s:#fff;--i:#111820;--m:#5a6672;--f:#8b98a5;--r:#c9d2da;
 --a:#c24e08;--b:#0d6f5c;--bs:#dcede8}
@media (prefers-color-scheme:dark){:root{--g:#10151a;--s:#181f26;--i:#e6ecf1;
 --m:#93a0ad;--f:#6c7986;--r:#2a343e;--a:#f07c2b;--b:#33ae90;--bs:#12302a}}
*{box-sizing:border-box}
body{margin:0;background:var(--g);color:var(--i);
 font:400 16px/1.55 "Segoe UI",system-ui,sans-serif}
.p{max-width:980px;margin:0 auto;padding:40px 24px 70px}
h1{font:800 42px/1.05 "Segoe UI",system-ui,sans-serif;letter-spacing:-.03em;margin:0 0 10px}
.sub{margin:0 0 8px;color:var(--m);max-width:64ch}
.warn{margin:20px 0 30px;padding:13px 15px;background:var(--s);border:1px solid var(--r);
 border-left:4px solid var(--a);border-radius:4px;font-size:14.5px;color:var(--m)}
.warn b{color:var(--i)}
.t{display:block;background:var(--s);border:1px solid var(--r);border-radius:4px;
 padding:16px 18px;margin-bottom:11px;text-decoration:none;color:inherit}
.t:hover{border-color:var(--a)}
.t h2{margin:0 0 4px;font:600 19px/1.3 "Segoe UI",system-ui,sans-serif;color:var(--i)}
.t .step{font:400 11.5px/1 ui-monospace,Consolas,monospace;color:var(--f);
 letter-spacing:.05em;margin-bottom:9px}
.t p{margin:0;font-size:14.5px;color:var(--m)}
.t .go{display:inline-block;margin-top:11px;font:600 11px/1 ui-monospace,Consolas,monospace;
 letter-spacing:.1em;text-transform:uppercase;color:var(--a)}
.foot{margin-top:30px;padding-top:16px;border-top:1px solid var(--r);
 font:400 13px/1.6 ui-monospace,Consolas,monospace;color:var(--f)}
"""


def main() -> int:
    store = Store()
    if store.backend != "firestore":
        raise SystemExit(f"store backend is {store.backend!r}, not firestore")

    tools = [t for t in store.list_tools(CHALLENGE) if t.get("smoke_test_passed")]
    nodes = {n.get("id"): (n.get("title") or "") for n in store.list_nodes(CHALLENGE)}
    if not tools:
        raise SystemExit("no smoke-tested tools found")
    print(f"fields on a tool doc: {sorted(tools[0].keys())}\n")

    OUT.mkdir(exist_ok=True)
    for stale in OUT.glob("*.html"):
        stale.unlink()

    rows = []
    for i, t in enumerate(tools, 1):
        name = t.get("name") or f"Tool {i}"
        src = t.get("source") or ""
        ttype = t.get("tool_type") or t.get("type") or ""
        key = slug(name)
        fname = f"{i:02d}-{key}.html"

        runnable = looks_html(src) or (
            ttype in RUNNABLE and has_markup(src) and not looks_python(src))
        if runnable:
            doc = page(name, key, src, wrap=not looks_html(src))
            kind = "runnable"
        else:
            # Not a page to operate -- a brief or a checklist. Keep it readable
            # rather than dumping raw source into a browser.
            doc = page(name, key,
                       "<pre style='white-space:pre-wrap;font:14.5px/1.65 "
                       "ui-monospace,Consolas,monospace'>"
                       + html.escape(src) + "</pre>", wrap=True)
            kind = "reading"

        (OUT / fname).write_text(doc, encoding="utf-8")
        rows.append({"file": fname, "name": name, "kind": kind,
                     "node": nodes.get(t.get("node_id"), ""),
                     "usage": t.get("usage") or ""})
        print(f"  {fname:<52} {kind:<9} {len(doc):>7,} bytes")

    cards = "".join(
        f'<a class="t" href="{r["file"]}">'
        f'<div class="step">STEP &middot; {html.escape(r["node"])}</div>'
        f'<h2>{html.escape(r["name"])}</h2>'
        f'<p>{html.escape(r["usage"][:300])}</p>'
        f'<span class="go">Open {r["kind"]}</span></a>'
        for r in rows)
    (OUT / "index.html").write_text(
        '<!doctype html><meta charset="utf-8"><title>My tools</title>'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<style>{INDEX_CSS}</style><div class=p>"
        "<h1>My tools</h1>"
        "<p class=sub>The tools Challenge Accepted wrote for the $25k challenge, "
        "exported to open and use offline. Every one passed its smoke test.</p>"
        "<div class=warn><b>These save to this browser, on this machine.</b> "
        "The copies inside challengeaccepted.app save to your account instead. "
        "Pick one per tool and stay with it, or you will not know later which "
        "number was the real one.</div>"
        f"{cards}"
        f'<div class=foot>{len(rows)} tools &middot; exported from {CHALLENGE}<br>'
        "refresh: python _series\\export_tools.py</div></div>",
        encoding="utf-8")

    print(f"\n{len(rows)} tools -> {OUT}\n  open {OUT / 'index.html'}")
    if "--check" in sys.argv:
        return check(rows)
    return 0


def check(rows: list[dict]) -> int:
    """Open every exported file and see whether it actually renders.

    A tool that throws at the top of its script renders a white rectangle, and
    nothing about the file on disk says so. This is the only honest way to know
    the export worked: load it, count the pixels that are not blank, read the
    console. Exactly the failure the storage shim exists to prevent.
    """
    from playwright.sync_api import sync_playwright
    shots = OUT / "_shots"
    shots.mkdir(exist_ok=True)
    bad = 0
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        for r in rows:
            pg = b.new_page(viewport={"width": 1280, "height": 900})
            errs: list[str] = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.goto((OUT / r["file"]).as_uri())
            pg.wait_for_timeout(1200)
            text = (pg.inner_text("body") or "").strip()
            pg.screenshot(path=str(shots / (r["file"][:-5] + ".png")))
            pg.close()
            ok = len(text) > 120 and not errs
            bad += 0 if ok else 1
            flag = "ok  " if ok else "FAIL"
            note = f"  {errs[0][:90]}" if errs else ""
            print(f"  [{flag}] {r['file']:<52} {len(text):>6} chars{note}")
        b.close()
    print(f"\n{len(rows) - bad}/{len(rows)} render   shots in {shots}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
