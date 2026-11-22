"""Proves the app's figures come from the loaded data, not from typed-in values. Run: python test_data_driven.py

Part 1 scans every string in the app code for embedded figures (percentages, hours, decimals, thresholds).
Part 2 changes the data or the policy settings and checks that targets, thresholds and page text change to
what an independent recomputation gives, so a value copied from the sample could not pass.
"""
import ast
import io
import math
import os
import pathlib
import re
import sys
import tempfile

import numpy as np
import pandas as pd
from streamlit.testing.v1 import AppTest

import engine as E
import targets as TG

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# ---------------------------------------------------------------- part 1: no figures in code or copy
FILES = ["app.py", "state.py", "guide.py", "coaching.py", "targets.py", "engine.py"] + \
        sorted(str(p) for p in pathlib.Path("views").glob("*.py"))
FIGURE = re.compile(r"(?<![\w.%-])\d+(\.\d+)?\s?(%|h\b|hours?\b|days?\b|weeks?\b|pts\b|×)|\b\d+\.\d+\b|\b\d+ in \d+\b|[<>≤≥] ?\d")
# Allowed: the AUC scale is a definition (0.5 = chance, 1.0 = perfect); CSS sizes in guide.py are styling.
ALLOWED = [re.compile(r"0\.5 = chance"), re.compile(r"close to 0\.5 means"), re.compile(r"\.rx-dots")]
hits = []
for f in FILES:
    tree = ast.parse(pathlib.Path(f).read_text(encoding="utf-8"))
    docs = {id(n.body[0].value) for n in ast.walk(tree) if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef))
            and n.body and isinstance(n.body[0], ast.Expr) and isinstance(getattr(n.body[0], "value", None), ast.Constant)}
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs:
            if any(a.search(node.value) for a in ALLOWED):
                continue
            for m in FIGURE.finditer(node.value):
                hits.append(f"{f}:{node.lineno}: {m.group(0)!r} in {node.value[:80]!r}")
assert not hits, "figures typed into the app:\n" + "\n".join(hits)
print("no figures embedded in app code or copy: ok")

# ---------------------------------------------------------------- part 2: change the data, the answers change
RAW = pd.read_csv("data/rideops_support_tickets.csv")


def build(df: pd.DataFrame, cfg: E.Settings | None = None):
    buf = io.BytesIO(df.to_csv(index=False).encode())
    raw = E.load(buf)
    as_of = raw.created_at.max().normalize() + pd.Timedelta(hours=23, minutes=59)
    return raw, as_of, E.enrich(raw, as_of, cfg or E.Settings())


def indep_north_star(df: pd.DataFrame, l1: int, eng: int, settle: int, as_of) -> pd.Series:
    r = df.copy()
    for c in ("created_at", "first_closed_at", "final_closed_at"):
        r[c] = pd.to_datetime(r[c])
    esc = r.escalated_to_eng == "Yes"
    hrs = (r.final_closed_at - r.created_at).dt.total_seconds() / 3600
    ok = np.where(esc, hrs <= eng, hrs <= l1) & ~(r.reopen_count > 0)
    r["ok"] = ok
    r = r[r.created_at <= as_of - pd.Timedelta(days=settle)]
    return r.groupby("assigned_agent").ok.agg(["mean", "size"])


# 1. drop the best agent: the benchmark moves to the next one, with the new name and value
_, as_of, d = build(RAW)
full = TG.targets(d)
best_full = full["North star: on-time, no reopen"]["agent"]
sub = RAW[RAW.assigned_agent != best_full]
raw_s, as_of_s, d_s = build(sub)
t_s = TG.targets(d_s)
ns = indep_north_star(sub, 24, 72, E.settle_days(raw_s), as_of_s)
ns = ns[ns["size"] >= 20]["mean"]
assert t_s["North star: on-time, no reopen"]["agent"] == ns.idxmax() != best_full
assert math.isclose(t_s["North star: on-time, no reopen"]["value"], ns.max(), rel_tol=1e-12)
assert best_full not in t_s["North star: on-time, no reopen"]["rule"]
print(f"target follows the data: best agent {best_full} -> {ns.idxmax()}: ok")

# 2. guardrails are the whole-period level of whatever data is loaded
base_s = E.scorecard(d_s)
assert math.isclose(t_s["CSAT (avg)"]["value"], sub.csat_score.mean(), rel_tol=1e-12)
assert math.isclose(t_s["First response median (h)"]["value"], base_s["First response median (h)"], rel_tol=1e-12)
print("guardrails equal the loaded data's level: ok")

# 3. policy settings change the metric, and match an independent recomputation
cfg = E.Settings(l1_hours=12, eng_hours=48)
raw_c, as_of_c, d_c = build(RAW, cfg)
sc = E.scorecard(d_c)["North star: on-time, no reopen"]
ind = indep_north_star(RAW, 12, 48, E.settle_days(raw_c), as_of_c)
assert math.isclose(sc, (ind["mean"] * ind["size"]).sum() / ind["size"].sum(), rel_tol=1e-12)
assert sc != E.scorecard(d)["North star: on-time, no reopen"]
assert (d_c.deadline_h.isin([12, 48])).all()
print("deadline settings drive the north star: ok")

# 4. settle days come from the longest reopen gap in the data
r0 = RAW.copy()
r0["reopen_count"] = 0
assert E.settle_days(E.load(io.BytesIO(r0.to_csv(index=False).encode()))) == 1             # no reopens: nothing to wait for
stretch = RAW.copy()
for c in ("first_closed_at", "final_closed_at"):
    stretch[c] = pd.to_datetime(stretch[c])
idx = stretch.index[stretch.reopen_count > 0][0]
stretch.loc[idx, "final_closed_at"] = stretch.loc[idx, "first_closed_at"] + pd.Timedelta(days=20, hours=3)
for c in ("first_closed_at", "final_closed_at"):
    stretch[c] = stretch[c].dt.strftime("%Y-%m-%d %H:%M")
assert E.settle_days(E.load(io.BytesIO(stretch.to_csv(index=False).encode()))) == 22        # ceil(20.125) + 1
print("settle days derived from the data: ok")

# 5. high-impact threshold is a quantile of the data's own counts
aff = d.affected.dropna()
assert math.isclose(E.high_impact_threshold(d), aff.quantile(0.75))
assert E.high_impact_threshold(d, E.Settings(high_impact_share=0.5)) == aff.quantile(0.5)
print("high-impact threshold derived: ok")

# 6. the same, through the pages: upload a different file and read the rendered text
tmp = pathlib.Path(tempfile.mkdtemp()) / "sub.csv"
sub.to_csv(tmp, index=False)
ns_period = indep_north_star(sub, 24, 72, E.settle_days(raw_s), as_of_s)
period_ns = (ns_period["mean"] * ns_period["size"]).sum() / ns_period["size"].sum()


def page(mod, fn, setup=""):
    src = (f"import sys; sys.path.insert(0, r'{HERE}')\nimport streamlit as st, ui, state\n"
           f"st.session_state.raw = open(r'{tmp}', 'rb').read()\n{setup}\nfrom views import {mod}\nui.inject_css()\n{mod}.{fn}()\n")
    at = AppTest.from_string(src, default_timeout=120).run()
    assert not at.exception, [e.message for e in at.exception]
    return at


def alltext(at):
    parts = [m.value for m in at.markdown] + [str(h.value) for h in at.get("html")] + [c.value for c in at.caption]
    return " ".join(parts)


sc_page = alltext(page("overview", "scorecard"))
assert f"Best agent today ({ns.idxmax()})" in sc_page and best_full not in sc_page.split("Best agent today")[1][:40]
meth = alltext(page("insights", "methodology"))
assert f"{period_ns:.1%}" in meth, "methodology must quote the loaded data's own north star"
assert f"**{E.settle_days(raw_s)} days**" in meth or f"{E.settle_days(raw_s)} days" in meth
eng48 = alltext(page("overview", "scorecard", "st.session_state.set_eng_hours = 48"))
assert "48h (escalated)" in eng48 and "72h (escalated)" not in eng48
print("pages show the loaded data's own figures and the chosen settings: ok")
print("data-driven tests pass")
