"""Pre-paint theme block for Streamlit's index.html <head>.

Streamlit gives apps no hook to run code before the first paint and no way to default to light, so
theme_patch.py inserts the block built here into Streamlit's own index.html. The block:

1. Picks the theme from localStorage key "theme" ("light" | "dark"). Anything else, including a first
   visit, means light. The OS setting is never consulted.
2. Sets <html data-theme> and color-scheme and the page background before the first paint.
3. Makes Streamlit start in that theme: it reads/writes its own per-page "stActiveTheme-<path>-v2" keys,
   and this block answers those reads from the single "theme" key, so every page agrees.
4. Adds the header toggle, a real <button> whose aria-label tracks the state. It switches Streamlit's
   built-in theme through Streamlit's own (visually hidden) menu, so there is no reload and the session
   is kept. If that menu is not available it saves the choice and reloads instead.

Colours come from tokens.py so the pre-paint background can never drift from the theme.
"""
import tokens as T

BEGIN = "<!-- rideops-theme:begin v1 -->"
END = "<!-- rideops-theme:end -->"

_JS = r"""
(function () {
  'use strict';
  var KEY = 'theme', MENU = '[data-testid="stMainMenu"] button';
  var root = document.documentElement, theme = 'light', btn = null;
  var ls = window.localStorage, proto = Object.getPrototypeOf(ls);
  var rawGet = proto.getItem, rawSet = proto.setItem;
  try { theme = rawGet.call(ls, KEY) === 'dark' ? 'dark' : 'light'; } catch (e) {}

  function isStreamlitKey(k) { return typeof k === 'string' && k.indexOf('stActiveTheme-') === 0; }
  function label() { return theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'; }
  function paint() {
    root.setAttribute('data-theme', theme);
    if (btn) {
      btn.setAttribute('aria-label', label());
      btn.setAttribute('title', label());
      btn.firstChild.textContent = theme === 'dark' ? 'light_mode' : 'dark_mode';
    }
  }
  function save(next) { theme = next; try { rawSet.call(ls, KEY, next); } catch (e) {} paint(); }

  // Streamlit asks for / stores its theme per page. Answer from the single key and map its writes back.
  proto.getItem = function (k) {
    if (this === ls && isStreamlitKey(k)) { return JSON.stringify(theme === 'dark' ? 'Dark' : 'Light'); }
    return rawGet.apply(this, arguments);
  };
  proto.setItem = function (k, v) {
    if (this === ls && isStreamlitKey(k)) {
      var n; try { n = JSON.parse(v); } catch (e) {}
      if (n === 'Dark') { save('dark'); } else if (n === 'Light') { save('light'); }
      return; // "System" and per-page copies are never stored
    }
    return rawSet.apply(this, arguments);
  };
  paint();

  // Charts bake their colours in when the script runs, so ask Streamlit to rerun (its own "r" shortcut)
  function rerun() {
    var ev = { key: 'r', code: 'KeyR', keyCode: 82, which: 82, bubbles: true, cancelable: true };
    document.dispatchEvent(new KeyboardEvent('keydown', ev));
    document.dispatchEvent(new KeyboardEvent('keyup', ev));
  }

  function drive(next) {
    var want = next === 'dark' ? 'Dark' : 'Light', t0 = Date.now();
    var menuBtn = document.querySelector(MENU);
    if (!menuBtn) { window.location.reload(); return; }
    root.setAttribute('data-theme-switching', '');
    menuBtn.click();
    (function poll() {
      var item = document.querySelector('[data-testid="stMainMenuItem-theme-' + want + '"]');
      if (item) {
        item.click();
        setTimeout(function () {
          if (document.querySelector('[data-testid="stMainMenuPopover"]')) { menuBtn.click(); }
          setTimeout(function () { root.removeAttribute('data-theme-switching'); if (btn) { btn.focus(); } }, 250);
          rerun();
        }, 120);
      } else if (Date.now() - t0 > 1500) { window.location.reload(); } else { setTimeout(poll, 40); }
    })();
  }

  function mount() {
    btn = document.createElement('button');
    btn.id = 'rx-theme-toggle';
    btn.type = 'button';
    var icon = document.createElement('span');
    icon.className = 'rx-theme-icon';
    icon.setAttribute('aria-hidden', 'true');
    icon.textContent = 'dark_mode';
    btn.appendChild(icon);
    btn.addEventListener('click', function () { var next = theme === 'dark' ? 'light' : 'dark'; save(next); drive(next); });
    // first in the page so keyboard users reach it on the first Tab, as header controls should
    document.body.insertBefore(btn, document.body.firstChild);
    paint();
  }
  if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', mount); } else { mount(); }

  window.addEventListener('storage', function (e) {
    if (e.key === KEY && (e.newValue === 'dark' || e.newValue === 'light') && e.newValue !== theme) {
      save(e.newValue); drive(e.newValue);
    }
  });
})();
"""


def _css() -> str:
    L, D = T.COLORS["light"], T.COLORS["dark"]

    def btn(c: dict, sel: str) -> str:
        return (f"{sel} #rx-theme-toggle {{ background: {c['surface-elevated']}; color: {c['text-primary']}; "
                f"border-color: {c['border']}; }} {sel} #rx-theme-toggle:hover {{ background: {c['surface-subtle']}; }} "
                f"{sel} #rx-theme-toggle:focus-visible {{ outline: 2px solid {c['focus-ring']}; outline-offset: 2px; }}")

    return f"""
:root[data-theme="light"] {{ color-scheme: light; background: {L['background']}; }}
:root[data-theme="dark"] {{ color-scheme: dark; background: {D['background']}; }}
#rx-theme-toggle {{ position: fixed; top: 6px; right: 16px; z-index: 1000000; width: 40px; height: 40px; padding: 0;
  display: inline-flex; align-items: center; justify-content: center; border: 1px solid; border-radius: 6px;
  cursor: pointer; transition: background 150ms cubic-bezier(.2, 0, 0, 1); }}
#rx-theme-toggle .rx-theme-icon {{ font-family: "Material Symbols Rounded"; font-size: 20px; line-height: 1;
  font-weight: normal; font-style: normal; letter-spacing: normal; text-transform: none; white-space: nowrap;
  font-feature-settings: "liga"; -webkit-font-feature-settings: "liga"; -webkit-font-smoothing: antialiased; }}
@media (max-width: 768px) {{ #rx-theme-toggle {{ width: 44px; height: 44px; top: 4px; right: 12px; }} }}
@media (prefers-reduced-motion: reduce) {{ #rx-theme-toggle {{ transition: none; }} }}
/* Streamlit's own menu stays in the page (the toggle drives it) but is not shown or focusable */
[data-testid="stMainMenu"] {{ visibility: hidden; }}
:root[data-theme-switching] [data-testid="stMainMenuPopover"] {{ visibility: hidden !important; }}
{btn(L, ':root[data-theme="light"]')}
{btn(D, ':root[data-theme="dark"]')}
"""


def build() -> str:
    """The full block, ready to insert after <head>."""
    # first visit and any unreadable value mean light: _JS never calls matchMedia
    return f"{BEGIN}\n<style id=\"rx-theme-css\">{_css()}</style>\n<script id=\"rx-theme-js\">{_JS}</script>\n{END}"

