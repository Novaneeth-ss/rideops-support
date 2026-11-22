"""Design-system checks: config.toml matches tokens.py, and text colours meet WCAG AA (4.5:1).
Run: python test_design.py"""
import tomllib
from pathlib import Path

import tokens as T

cfg = tomllib.loads((Path(__file__).parent / ".streamlit" / "config.toml").read_text(encoding="utf-8"))["theme"]

MIRROR = {"primaryColor": "primary", "backgroundColor": "background", "secondaryBackgroundColor": "surface-subtle",
          "textColor": "text-primary", "borderColor": "border", "redColor": "danger", "orangeColor": "warning",
          "greenColor": "success", "blueColor": "info", "grayColor": "text-muted",
          "redBackgroundColor": "danger-bg", "greenBackgroundColor": "success-bg", "blueBackgroundColor": "info-bg",
          "orangeBackgroundColor": "warning-bg"}
for theme in ("light", "dark"):
    for key, tok in MIRROR.items():
        assert cfg[theme][key].upper() == T.COLORS[theme][tok].upper(), (theme, key)
    assert cfg[theme]["chartCategoricalColors"] == T.CHART[theme], theme
    assert cfg[theme]["sidebar"]["backgroundColor"].upper() == T.COLORS[theme]["sidebar"].upper()


def lum(h):
    c = [int(h.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def contrast(a, b):
    hi, lo = sorted([lum(a), lum(b)], reverse=True)
    return (hi + 0.05) / (lo + 0.05)


for theme, c in T.COLORS.items():
    for fg in ("text-primary", "text-secondary", "text-muted", "primary", "success", "warning", "danger", "info"):
        for bg in ("background", "sidebar", "surface-subtle", "surface-elevated"):
            r = contrast(c[fg], c[bg])
            assert r >= 4.5, f"{theme}: {fg} on {bg} = {r:.2f}"
    for s in ("success", "warning", "danger", "info"):
        r = contrast(c[s], c[f"{s}-bg"])
        assert r >= 4.5, f"{theme}: {s} badge = {r:.2f}"
    assert contrast(c["on-primary"], c["primary"]) >= 4.5, theme         # primary button text
    assert contrast(c["on-primary"], c["primary-hover"]) >= 4.5, theme   # ...and on hover

print("design checks pass")
