"""Theme tests. Run: python test_theme.py

Part 1 checks the patcher on a temporary copy of index.html (never the installed one).
Part 2 runs the injected script under Node with a fake window/document/localStorage, so the storage rules
(light default, OS ignored, Streamlit key mapping, toggle label) are tested without a browser.
Part 3 checks both themes' colours used by the block match tokens.py and meet contrast.
"""
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import theme_head
import theme_patch
import tokens as T

HTML = "<!doctype html><html><head>\n<meta charset=\"utf-8\" />\n<script type=\"module\" src=\"./app.js\"></script>\n</head><body></body></html>\n"
tmp = Path(tempfile.mkdtemp())
try:
    # ---------- part 1: patcher ----------
    idx = tmp / "index.html"
    idx.write_text(HTML, encoding="utf-8")
    assert theme_patch.apply(idx) == "patched"
    once = idx.read_text(encoding="utf-8")
    assert once.count(theme_head.BEGIN) == 1 and once.count(theme_head.END) == 1
    assert once.index(theme_head.BEGIN) < once.index("<script type=\"module\""), "block must run before the app bundle"
    assert theme_patch.apply(idx) == "already" and idx.read_text(encoding="utf-8") == once   # idempotent
    assert theme_patch.is_active(idx)
    idx.write_text(once.replace("rx-theme-toggle", "old-toggle", 1), encoding="utf-8")        # stale block
    assert theme_patch.apply(idx) == "updated"
    assert idx.read_text(encoding="utf-8").count(theme_head.BEGIN) == 1
    assert theme_patch.remove(idx) == "removed" and idx.read_text(encoding="utf-8") == HTML    # byte-identical
    assert theme_patch.remove(idx) == "not patched"
    ro = tmp / "missing" / "index.html"
    assert theme_patch.apply(ro).startswith("failed")                                          # no crash
    print("patcher: pass")

    # ---------- part 2: injected script under Node ----------
    js = theme_head._JS
    (tmp / "head.js").write_text(js, encoding="utf-8")
    harness = r"""
const fs = require('fs'); const code = fs.readFileSync(process.argv[2], 'utf8');
function el(tag){ const e={tag, attrs:{}, children:[], handlers:{}, firstChild:null, textContent:'', id:'', type:'', className:''};
  e.setAttribute=(k,v)=>{e.attrs[k]=String(v)}; e.getAttribute=k=>e.attrs[k]??null; e.removeAttribute=k=>{delete e.attrs[k]};
  e.appendChild=c=>{e.children.push(c); if(!e.firstChild) e.firstChild=c; return c};
  e.insertBefore=(c,ref)=>{e.children.unshift(c); return c};
  e.addEventListener=(t,f)=>{e.handlers[t]=f}; return e; }
function run(initial, opts={}){
  const store=new Map(Object.entries(initial)); const calls={matchMedia:0, reload:0};
  class Storage{ getItem(k){return store.has(k)?store.get(k):null} setItem(k,v){store.set(k,String(v))} removeItem(k){store.delete(k)} }
  const localStorage=new Storage();
  const root=el('html'), body=el('body'); const menu = opts.menu ? el('button') : null; let clickedMenu=0; if(menu) menu.click=()=>{clickedMenu++};
  const doc={documentElement:root, body, readyState:'loading', createElement:el, head:el('head'),
    addEventListener:(t,f)=>{doc.h=f}, querySelector:s=>s.includes('stMainMenu"] button')?menu:null};
  const win={localStorage, matchMedia:()=>{calls.matchMedia++; return {matches:true}}, addEventListener:()=>{}, location:{reload:()=>{calls.reload++}}};
  new Function('window','document','Object',code)(win,doc,Object);
  doc.h();            // DOMContentLoaded -> mounts the toggle
  return {store, root, btn:body.children[0], calls, localStorage, clickedMenu:()=>clickedMenu};
}
const out={};
let r=run({}); out.fresh={theme:r.root.attrs['data-theme'], saved:r.store.get('theme')??null, st:r.localStorage.getItem('stActiveTheme-/scorecard-v2'), mm:r.calls.matchMedia, label:r.btn.attrs['aria-label'], tag:r.btn.tag, type:r.btn.type};
r=run({theme:'dark'}); out.saved_dark={theme:r.root.attrs['data-theme'], st:r.localStorage.getItem('stActiveTheme-/-v2'), label:r.btn.attrs['aria-label'], icon:r.btn.firstChild.textContent};
r=run({theme:'banana'}); out.garbage={theme:r.root.attrs['data-theme']};
r=run({}); r.localStorage.setItem('stActiveTheme-/x-v2','"Dark"'); out.st_dark={theme:r.root.attrs['data-theme'], saved:r.store.get('theme'), copy:r.store.has('stActiveTheme-/x-v2'), label:r.btn.attrs['aria-label']};
r=run({theme:'dark'}); r.localStorage.setItem('stActiveTheme-/x-v2','"System"'); out.st_system={theme:r.root.attrs['data-theme'], saved:r.store.get('theme')};
r=run({}); r.btn.handlers.click(); out.toggle_no_menu={theme:r.root.attrs['data-theme'], saved:r.store.get('theme'), label:r.btn.attrs['aria-label'], reload:r.calls.reload, icon:r.btn.firstChild.textContent};
r=run({},{menu:true}); r.btn.handlers.click(); out.toggle_menu={saved:r.store.get('theme'), reload:r.calls.reload, menuClicks:r.clickedMenu(), switching:r.root.attrs['data-theme-switching']!==undefined};
r=run({}); r.localStorage.setItem('other','v'); out.passthrough={other:r.localStorage.getItem('other')};
console.log(JSON.stringify(out));
"""
    (tmp / "harness.js").write_text(harness, encoding="utf-8")
    res = subprocess.run(["node", str(tmp / "harness.js"), str(tmp / "head.js")], capture_output=True, text=True, timeout=30)
    assert res.returncode == 0, res.stderr
    o = json.loads(res.stdout)
    assert o["fresh"] == {"theme": "light", "saved": None, "st": "\"Light\"", "mm": 0,
                          "label": "Switch to dark mode", "tag": "button", "type": "button"}, o["fresh"]
    assert o["saved_dark"] == {"theme": "dark", "st": "\"Dark\"", "label": "Switch to light mode", "icon": "light_mode"}
    assert o["garbage"]["theme"] == "light"
    assert o["st_dark"] == {"theme": "dark", "saved": "dark", "copy": False, "label": "Switch to light mode"}
    assert o["st_system"] == {"theme": "dark", "saved": "dark"}, o["st_system"]   # "System" is ignored
    assert o["toggle_no_menu"] == {"theme": "dark", "saved": "dark", "label": "Switch to light mode",
                                   "reload": 1, "icon": "light_mode"}, o["toggle_no_menu"]
    assert o["toggle_menu"]["saved"] == "dark" and o["toggle_menu"]["reload"] == 0
    assert o["toggle_menu"]["menuClicks"] == 1 and o["toggle_menu"]["switching"]
    assert o["passthrough"]["other"] == "v"
    print("script under node: pass")

    # ---------- part 3: colours ----------
    css = theme_head._css()
    for theme in ("light", "dark"):
        for tok in ("background", "surface-elevated", "text-primary", "border", "focus-ring"):
            assert T.COLORS[theme][tok] in css, (theme, tok)

    def lum(h):
        c = [int(h.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4)]
        c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
        return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]

    def ratio(a, b):
        hi, lo = sorted([lum(a), lum(b)], reverse=True)
        return (hi + 0.05) / (lo + 0.05)
    for theme, c in T.COLORS.items():
        assert ratio(c["text-primary"], c["surface-elevated"]) >= 4.5, theme   # icon on the toggle
        assert ratio(c["focus-ring"], c["background"]) >= 3, theme               # focus ring (UI component)
        assert ratio(c["border"], c["surface-elevated"]) >= 1.0
    print("toggle colours: pass")
finally:
    shutil.rmtree(tmp, ignore_errors=True)
print("theme tests pass")
