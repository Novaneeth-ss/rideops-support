"""Insert (or remove) the pre-paint theme block in Streamlit's index.html.

    python theme_patch.py            apply (safe to repeat)
    python theme_patch.py --remove   restore Streamlit's original file
    python theme_patch.py --status

Streamlit serves index.html from disk on every request, so a change takes effect on the next page load.
The original is kept next to it as index.html.rideops-orig. The app also calls apply() on start-up.
"""
import re
import sys
from pathlib import Path

import theme_head


def index_path() -> Path:
    import streamlit
    return Path(streamlit.__file__).parent / "static" / "index.html"


def _strip(html: str) -> str:
    return re.sub(re.escape(theme_head.BEGIN) + r".*?" + re.escape(theme_head.END) + r"\n?", "", html, flags=re.S)


def is_active(path: Path | None = None) -> bool:
    path = path or index_path()
    try:
        return theme_head.build() in path.read_text(encoding="utf-8")
    except OSError:
        return False


def apply(path: Path | None = None) -> str:
    """Return 'patched', 'updated', 'already' or 'failed: <reason>'."""
    path = path or index_path()
    try:
        html = path.read_text(encoding="utf-8")
        block = theme_head.build()
        if block in html:
            return "already"
        had = theme_head.BEGIN in html
        clean = _strip(html)
        head = re.search(r"<head[^>]*>", clean)
        if not head:
            return "failed: no <head> found in index.html"
        backup = path.with_name(path.name + ".rideops-orig")
        if not had and not backup.exists():
            backup.write_text(clean, encoding="utf-8")
        out = clean[:head.end()] + "\n" + block + "\n" + clean[head.end():]
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(out, encoding="utf-8")
        tmp.replace(path)
        return "updated" if had else "patched"
    except OSError as e:
        return f"failed: {e}"


def remove(path: Path | None = None) -> str:
    """Restore Streamlit's original index.html (byte for byte, from the saved copy)."""
    path = path or index_path()
    try:
        html = path.read_text(encoding="utf-8")
        if theme_head.BEGIN not in html:
            return "not patched"
        backup = path.with_name(path.name + ".rideops-orig")
        path.write_text(backup.read_text(encoding="utf-8") if backup.exists() else _strip(html), encoding="utf-8")
        return "removed"
    except OSError as e:
        return f"failed: {e}"


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    print({"--remove": remove, "--status": lambda: "active" if is_active() else "inactive"}.get(arg, apply)())
