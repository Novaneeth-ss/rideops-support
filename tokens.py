"""Design tokens: the single source for colour, type, spacing, radius, elevation and motion.

.streamlit/config.toml mirrors the colour tokens for Streamlit's own widgets
(test_design.py fails if the two drift). Custom components read the CSS variables
that ui.inject_css() emits from this file.
"""

COLORS = {
    "light": {
        "primary": "#2F54EB", "primary-hover": "#2443C4", "primary-active": "#1D36A0", "on-primary": "#FFFFFF",
        "secondary": "#4B5563", "accent": "#0F766E",
        "background": "#FFFFFF", "sidebar": "#F7F8FA", "header": "#FFFFFF",
        "surface": "#FFFFFF", "surface-elevated": "#FFFFFF", "surface-subtle": "#F3F4F6",
        "text-primary": "#111827", "text-secondary": "#4B5563", "text-muted": "#5F6673",
        "border": "#E3E6EA", "border-subtle": "#EEF0F2", "focus-ring": "#2F54EB",
        "success": "#15803D", "success-bg": "#ECFDF3",
        "warning": "#B45309", "warning-bg": "#FFF7ED",
        "danger": "#B91C1C", "danger-bg": "#FEF2F2",
        "info": "#1D4ED8", "info-bg": "#EFF4FF",
        "disabled": "#9CA3AF", "overlay": "rgba(17, 24, 39, 0.48)",
    },
    "dark": {
        "primary": "#7C9BFF", "primary-hover": "#99B1FF", "primary-active": "#B4C6FF", "on-primary": "#0D0F14",
        "secondary": "#A1A8B5", "accent": "#2DD4BF",
        "background": "#0D0F14", "sidebar": "#12151B", "header": "#0D0F14",
        "surface": "#0D0F14", "surface-elevated": "#161A21", "surface-subtle": "#1A1E26",
        "text-primary": "#E5E7EB", "text-secondary": "#A1A8B5", "text-muted": "#8B94A3",
        "border": "#262B35", "border-subtle": "#1D2129", "focus-ring": "#7C9BFF",
        "success": "#4ADE80", "success-bg": "#0F2A1C",
        "warning": "#FBBF24", "warning-bg": "#2E2410",
        "danger": "#F87171", "danger-bg": "#341A1A",
        "info": "#60A5FA", "info-bg": "#14233A",
        "disabled": "#4B5363", "overlay": "rgba(0, 0, 0, 0.6)",
    },
}

# Chart series: colour-blind-aware, same order in both themes so a series keeps its meaning.
CHART = {
    "light": ["#2F54EB", "#0F766E", "#B45309", "#7C3AED", "#BE185D", "#64748B"],
    "dark": ["#7C9BFF", "#2DD4BF", "#FBBF24", "#C4B5FD", "#F9A8D4", "#94A3B8"],
}
RETURN_REASON_ORDER = ["Missing info", "Config", "Duplicate", "How-to", "Not reproducible"]

FONT = "Inter, 'Segoe UI', system-ui, -apple-system, Roboto, 'Helvetica Neue', Arial, sans-serif"
MONO = "'JetBrains Mono', 'Cascadia Code', Consolas, 'SFMono-Regular', monospace"

# size / line-height / weight / letter-spacing
TYPE = {
    "display": ("2rem", 1.2, 650, "-0.02em"),
    "page-title": ("1.625rem", 1.25, 650, "-0.015em"),
    "section": ("1.125rem", 1.35, 600, "-0.01em"),
    "card-title": ("0.9375rem", 1.4, 600, "0"),
    "body-lg": ("1rem", 1.55, 400, "0"),
    "body": ("0.875rem", 1.55, 400, "0"),
    "body-sm": ("0.8125rem", 1.5, 400, "0"),
    "caption": ("0.75rem", 1.45, 450, "0.01em"),
    "label": ("0.75rem", 1.3, 550, "0.04em"),
    "metric": ("1.75rem", 1.15, 600, "-0.02em"),
}

SPACE = [4, 8, 12, 16, 20, 24, 32, 40, 48, 64]
RADIUS = {"sm": "4px", "md": "6px", "lg": "10px", "xl": "14px", "pill": "999px"}
ELEVATION = {
    "light": ["none", "0 1px 2px rgba(17,24,39,.05)", "0 4px 12px rgba(17,24,39,.08)", "0 12px 32px rgba(17,24,39,.16)"],
    "dark": ["none", "0 1px 2px rgba(0,0,0,.4)", "0 4px 12px rgba(0,0,0,.5)", "0 12px 32px rgba(0,0,0,.6)"],
}
MOTION = {"fast": "150ms", "base": "200ms", "ease": "cubic-bezier(.2, 0, 0, 1)"}
LAYOUT = {"content-max": "1440px", "page-pad-x": "40px", "page-pad-x-mobile": "16px", "sidebar": "272px"}


def _static_vars() -> list:
    lines = [f"--space-{i + 1}: {v}px;" for i, v in enumerate(SPACE)]
    lines += [f"--radius-{k}: {v};" for k, v in RADIUS.items()]
    lines += [f"--motion-{k}: {v};" for k, v in MOTION.items()]
    lines += [f"--font-sans: {FONT};", f"--font-mono: {MONO};"]
    for k, (size, lh, w, ls) in TYPE.items():
        lines += [f"--type-{k}-size: {size};", f"--type-{k}-lh: {lh};", f"--type-{k}-weight: {w};",
                  f"--type-{k}-ls: {ls};"]
    return lines


def _theme_vars(theme: str) -> str:
    lines = [f"--color-{k}: {v};" for k, v in COLORS[theme].items()]
    lines += [f"--elevation-{i}: {v};" for i, v in enumerate(ELEVATION[theme])]
    return " ".join(lines)


def css_vars(current: str) -> str:
    """All CSS variables. Colours are keyed on <html data-theme> (set before first paint by the theme patch),
    so a theme switch restyles the page without waiting for a Streamlit rerun. Without the patch there is no
    data-theme attribute, so fall back to the theme Streamlit reported for this run."""
    return (":root {" + " ".join(_static_vars()) + "} "
            f":root:not([data-theme]) {{{_theme_vars(current)}}} "
            f':root[data-theme="light"] {{{_theme_vars("light")}}} '
            f':root[data-theme="dark"] {{{_theme_vars("dark")}}}')
