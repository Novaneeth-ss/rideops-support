# RideOps Support Control Room

An internal tool for RideOps support leadership: one data engine, a view for each role.

## Run locally

Needs Python 3.10+.

```
pip install -r requirements.txt
streamlit run app.py          # run from this folder so .streamlit/config.toml is picked up
python test_engine.py         # engine reproduces the diagnosis numbers
python test_design.py         # theme matches tokens; every text colour meets WCAG AA
python test_theme.py          # theme patch + injected script (needs Node.js)
python test_coaching.py       # 1:1 numbers recomputed independently from the raw CSV
python test_app.py            # interaction checks: navigation, roles, search, filters, forms, dialogs, odd exports
ruff check .                  # lint (config in ruff.toml)
```

## Host (Streamlit Community Cloud, free)

See [DEPLOY.md](DEPLOY.md): a hosted PostgreSQL database, a private GitHub repository, the secrets, and the first-visit steps.

## Views by role

Pick a role under **Viewing as** in the sidebar.

| Group | View | Who uses it | What it does |
|---|---|---|---|
| Overview | Scorecard | Head of Operations | North star vs target, open tickets, drivers and guardrails with on-track status |
| Support | Attention queue | Support lead, L1 | Open tickets ranked by flags; search, filter, select for details, bulk export, draft client updates |
| Support | Agent 1:1 prep | Support lead | One agent against the other agents: what is going well, what to discuss (with the evidence), the tickets to review together, an agreement box and a downloadable summary |
| Support | Agent coaching |  Support lead | Per-agent outcomes, coaching notes, load balance |
| Engineering | Returns from engineering | Eng lead, Support lead | Return reasons by week and category, open escalations, returns after go-live |
| Engineering | Known-issue registry | Eng lead | Editable list with validation; shown to agents on My desk |
| Engineering | Root causes | Eng lead, Head of Ops | Recurring issues ranked by resolution hours |
| Support | My desk > Escalate | L1 agent | One escalation workflow: known-issue link, checks and note recorded, confirm before an incomplete send, closure-risk prompt |
| Insights | Before / after, Back-tests, Methodology | Everyone | Go-live comparison, what was tested and dropped, metric definitions |

**How-to guide.** A welcome dialog opens on the first visit in each browser session: pick your role, then jump
to one of three starter tasks. **How to use** in the sidebar reopens it; **Tour** steps through your role's pages
one by one (Back / Next / End tour), moving to each page so it is visible behind the dialog. Text lives in
`guide.py`.

The sidebar also has ticket search (opens the ticket details) and **Data & settings**: upload a newer export and
set the workflow go-live date.

## Architecture

```
app.py            shell: sidebar, role-based navigation, search, data settings
state.py          cached data context, ticket details dialog, selectable ticket table, client-update drafts
engine.py         all metrics, flags, back-tests (no UI code)
tokens.py         design tokens (colour, type, spacing, radius, elevation, motion, layout)
ui.py             components: page header, KPI cards, badges, tables, empty states, themed charts
views/            one module per area: overview, support, engineering, agent, insights
.streamlit/       theme config that mirrors tokens.py for Streamlit's own widgets
```

## Design system

- **Tokens** live in `tokens.py`: semantic colours for light and dark (primary, surfaces, text, border, focus,
  success/warning/danger/info), a type scale, a 4px spacing scale, radius, 4 elevation levels and motion timings.
  `ui.inject_css()` exposes them as CSS variables; `.streamlit/config.toml` mirrors them for built-in widgets, and
  `test_design.py` fails if the two drift.
- **Theme:** light is the default for every new visitor (the OS setting is ignored). The sun/moon button at the
  top right switches to dark and back; the choice is saved in localStorage key `theme` (`light` | `dark`) and
  restored on every later visit, on every page. See "Light/dark theme" below.
- **Type:** Inter, falling back to Segoe UI or the system font. Tabular numbers everywhere for scanning.
- **Colour use:** one blue accent; green and red only for status. Chart series use a fixed six-colour order.

## Accessibility and responsiveness

- One H1 per page, KPI cards labelled as groups, status changes also stated in
  text, chart descriptions plus a **View chart data** table under each chart.
- All text colours checked at 4.5:1 or better in both themes (`test_design.py`). Visible focus ring; reduced motion
  respected.
- KPI grids reflow 6 → 3 → 2 columns; the sidebar becomes a drawer on phones; wide tables scroll inside their own
  frame, so the page never scrolls sideways (checked on all 10 views at 375px).

## Agent 1:1 prep (how the notes are made)

`coaching.py` builds every note from the loaded tickets; no number is typed in. For one agent it:

1. compares 17 measures with the **other agents pooled** (escalation, avoidable escalations, reopens, on-time rate,
   return reasons, hours to close, first response, CSAT);
2. tests each gap against chance (two-proportion z-test for rates, Mann-Whitney for hours and CSAT). **Clear gap** is
   about 1 in 100 by chance, **Worth a look** about 1 in 20, and the gap must also be big enough to matter;
3. turns clear gaps into plain-language findings with the evidence, an action and questions to ask. Composite
   findings (escalates a lot and many come back; closes fast but fixes do not hold) are checked first;
4. shows what the other agents' own rates would give for the same mix of ticket types, so "is it just harder tickets?"
   has a number;
5. lists the tickets to review together (reopened, avoidable escalations, slow, open now).

Safeguards: fewer than 20 tickets on a side shows "Not enough data"; a low "avoidable" number that comes from
escalating less is never credited as a strength; small, unproven differences are listed separately and labelled.
`python test_coaching.py` recomputes every agent x measure from the raw CSV with plain pandas and checks they match.

## Light/dark theme

Streamlit can't default to light or run code before the first paint, so `theme_patch.py` inserts a small block
(built by `theme_head.py` from `tokens.py`) at the top of Streamlit's own `index.html`. It:

1. reads `localStorage.theme`; anything but `dark` (including a first visit) means light;
2. sets `<html data-theme>`, `color-scheme` and the page background before anything is drawn (no flash);
3. answers Streamlit's per-page `stActiveTheme-*` storage keys from that single key, so every page agrees;
4. adds the header button: a real `<button>` whose `aria-label` reads "Switch to dark mode" / "Switch to light
   mode". It drives Streamlit's built-in theme (no reload, session kept) and asks Streamlit to rerun so charts
   recolour; if that isn't possible it saves the choice and reloads.

The app's own colours are keyed on `data-theme`, so they restyle instantly.

- Apply it before starting the server with `python run.py` (patches, then starts Streamlit), or
  `python theme_patch.py`. The app also applies it on start-up, which covers `streamlit run app.py`; in that
  case the first page load after a fresh install is served before the patch exists, so reload once.
- `python theme_patch.py --remove` restores Streamlit's original file from `index.html.rideops-orig`.
- The patch edits Streamlit's installed package, so it is lost on reinstall or upgrade (re-applied on start-up),
  and it needs write access to that folder. If it can't be applied the sidebar says so and Streamlit's own menu
  (⋮) is shown instead.

## No fixed figures: where every value comes from

Nothing the app shows is typed in. Each value is one of three kinds, listed on the **Methodology** page:

| Kind | Examples | Where it lives |
|---|---|---|
| **Derived from your data** | targets, benchmarks, days before a ticket is scored for reopens, what counts as a fast close, the high-impact threshold, back-test results, every number in the text | computed on load (`engine.py`, `targets.py`, `coaching.py`) |
| **Your policy settings** | on-time deadlines for tickets that are / are not escalated, recent weeks counted as "now", known-issue lookback, reopen-flag share, high-impact share | Data & settings in the sidebar (`engine.Settings`); defaults are starting points, change them to your policy |
| **Statistical conventions** | chance levels (1 in 20, 1 in 100), minimum tickets for a comparison, smoothing | `coaching.METHOD`, `engine.METHOD`, shown on Methodology |

- **Targets:** drivers use the best agent's level today (an agent who simply escalates clearly less than the others
  is not used for the avoidable-escalation benchmark); guardrails mean no worse than the whole period.
- **Metric definitions:** the north star is the share of settled tickets closed within the relevant deadline and
  never reopened. An avoidable escalation is one engineering sent back as missing info, config, duplicate, how-to or
  not reproducible.
- `python test_data_driven.py` scans every string in the app for embedded figures, then changes the data and the
  settings and checks the targets, thresholds and page text follow an independent recomputation.

## What was tested, and what was dropped

The **Back-tests** page computes these from the loaded data, so the numbers always match it:

- **Reopen-risk flag:** trained on earlier months, tested on the latest settled month (AUC, precision, recall).
  It prompts a closure check and never blocks a closure.
- **Predicting avoidable escalations:** an issue-type / agent score tested on the latest month. The app only uses
  a risk score if the history predicts better than chance; read the AUC on the page.
- **Automatic escalation blocking:** every rule is replayed on past escalations and shows how many real bugs it
  would have stopped. The Escalate tab on My desk suggests known issues and records the checks, but does not block.

## Limits

- With sign-in off, the role picker filters views but does not restrict access. Turn sign-in on (`RIDEOPS_REQUIRE_LOGIN=1`) before hosting.
- Registry edits and known-issue links are saved in the database (see What is saved).
- Checklists per category are v1 hypotheses to validate with L1 and engineering.
- Deadlines and the other policy settings are your choices, not measurements; see "No fixed figures" above.
- No engineering pickup/return timestamps, so engineering queue time cannot be split from bounce time.
- Charts label their axes for screen readers but have no overall chart label (Altair in Streamlit); each chart has a
  **View chart data** table instead. Two unlabelled controls found by audit are Streamlit internals (a hidden helper
  date field and the file-upload button markup).
- Tables are drawn on a canvas by Streamlit, so their internal styling can't be themed with CSS. Table contents
  are themed by Streamlit's own light/dark theme, which the toggle switches.
- The theme patch modifies an installed package file (see above) and was verified against Streamlit 1.67.0 only:
  it relies on Streamlit's `stActiveTheme-*` storage keys and menu test ids.

## What is saved, and where
Everything the app saves goes into one database, so it is still there after a restart or a redeploy:
- **Uploaded and API-fetched exports** (every one is kept; pick which is in use under Data & settings). Everyone on the server uses the active one.
- **Actions** (escalations sent from My desk, returns, "mark fixed", reassignments, engineering-head escalations, lag marks, feature statuses, the engineering limit). Kept per export, so actions on one export never touch another.
- **Known-issue registry and 1:1 agreements**, per export.
- **Role, policy settings and go-live date**.

The export has no time into and out of engineering, no escalation note and no record of the checks done, so those are recorded from the first action onward and nothing is back-filled. Times are real wall-clock times.

**Database.** By default a SQLite file, `store/rideops.db` (or the folder in `RIDEOPS_STORE`). That is enough on a server or container with a persistent disk: mount a volume on that folder. Hosts with a temporary disk (e.g. Streamlit Community Cloud, most free tiers) lose the file on restart, so set `DATABASE_URL` to a hosted PostgreSQL database (Supabase, Neon, Railway and similar), for example `postgresql://user:password@host:5432/dbname`. Tables are created on first start. Both SQLite and PostgreSQL were tested.

**API.** Data & settings > Connect an API: give a URL that returns CSV or a JSON list of tickets with the same fields as the export (a JSON object holding the list under `tickets`, `data`, `results`, `items` or `records` also works). The token is sent in the header you name and is never saved; or set `RIDEOPS_API_TOKEN` on the server. Each fetch is saved as a new export and becomes the active one. Set `RIDEOPS_API_ALLOWED_HOSTS` (comma separated) to limit which hosts the server may call. Fetching is on demand (a button), not on a schedule.

**Limits.** With sign-in off, everything saved is shared by everyone who can open the app; turn sign-in on before hosting it where others can reach it. Search boxes and open pages are not saved.

- A ticket on its second escalation cannot be returned to L1: it is flagged "Call required: engineering + agent".
- Engineering limit: baseline = 75th percentile of created-to-close hours of closed escalated tickets (a proxy, it includes L1 time). A lead can save one value that replaces it.
- Without sign-in, roles only shape the menu and who sees the lead actions. This is not security. With sign-in on, the role comes from the account.
- If the app misbehaves right after an update, restart the server: Streamlit can keep an old copy of a changed module in memory.

## Sign-in, field mapping, scheduled refresh, plain tables
- **Sign-in (off by default).** Set `RIDEOPS_REQUIRE_LOGIN=1` on the server before hosting. The first visit creates the administrator; administrators add users and set roles on the Users page. The role comes from the account (no "Viewing as" picker), and every saved action carries the person's name. Passwords are stored only as salted scrypt hashes (minimum 10 characters); five wrong passwords lock that user for five minutes. Limits: a browser refresh signs you out; no email password reset (an administrator sets a new one); it is a small built-in system, not single sign-on; serve the app over HTTPS.
- **API field mapping.** If the API's field names differ, the app lists the fields it could not find, suggests the closest names, and saves your choices for the next fetch. It maps names only, not values: `status` must still read "Closed", "Open - with L1" or "Open - with Engineering".
- **Scheduled refresh.** The app cannot run background jobs. Run `python refresh.py` from cron, Windows Task Scheduler or a GitHub Action (same `DATABASE_URL`/`RIDEOPS_STORE`, token in `RIDEOPS_API_TOKEN`). It saves a new export only when the data changed and reads as a ticket export, and the app shows the last result under the API form.
- **Account calls.** On Account health, record that you called an at-risk client (with a note); the table shows who and when, and "Only accounts not called yet" filters the list. Undo is available.
- **Plain tables.** The sidebar switch turns the scrolling grids into ordinary HTML tables a screen reader can read (first 300 rows; ticket tables get an "Open a ticket" picker). Tables where you select a row (account list, popups) stay grids.
