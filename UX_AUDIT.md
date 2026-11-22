# RideOps Support: UX audit

> **Status:** Phase 1 (the five P0 items) is implemented: one escalation workflow on My desk (the Escalation gate page is retired), confirm and undo on log-writing actions, My desk opens on an actionable ticket, "Record call held" for second-escalation tickets, and known issues shown in the Escalate tab. Phase 2 is implemented too, except "cards as filters" on the Attention queue (it conflicts with the requested popup lists): welcome shown once, page titles, ticket search with status and "See all", pick-and-act on Escalations with lag/limit and time tracking as tabs, a slimmer Returns page, go-live date picker on Before / after, Account health find/tier/open tickets, and sidebar split into Data and Policy settings with changed markers. Phase 3 is implemented: short flag labels with a legend and tooltips, real tabs on Agent coaching, owner tabs on Root causes, whole-number counts, a Terms popover on every page, 24 px help targets, column help text, a gap column on the Scorecard targets, and one Load by agent section. Phase 4 is implemented: opt-in sign-in with named users and roles, person attribution, API field mapping, a scheduled-refresh script, recorded calls to at-risk accounts, and a Plain tables switch. Everything below is the original audit as written, before those changes.


Method: the running app (http://localhost:8502, Streamlit 1.67, built-in browser) at 1280, 768 and 375 px, light and dark; every page opened; DOM scans on all 13 pages (title, headings, labels, target sizes, contrast, overflow); keyboard run on the welcome popup; task walks (find a ticket, escalate, return, reassign, add a known issue, change go-live, fetch from an API). No code was changed.

**Could not inspect (so no findings):** screen-reader behaviour (no assistive technology available); keyboard sorting/selection inside the data grids (they are canvas, not DOM); other browsers; real touch devices; behaviour with a much larger export; the hosted deployment; PostgreSQL.

---

## 1. Navigation inventory

Sidebar (Streamlit page menu, grouped), identical for every user except the role filter:

| Group | Page | URL | In roles |
|---|---|---|---|
| Overview | Scorecard | /scorecard | All, Head of Ops |
| Support | Attention queue · N | /attention-queue | All, Support lead, L1 |
| Support | My desk | /my-desk | All, Support lead, L1 |
| Support | Account health | /account-health | All, Support lead |
| Support | Agent coaching (switch: Team overview / 1:1 prep) | /agent-coaching | All, Support lead |
| Engineering | Escalations · N | /escalations | All, Support lead, Eng lead |
| Engineering | Returns from engineering | /returns | All, Support lead, Eng lead |
| Engineering | Known-issue registry | /known-issues | All, Eng lead, L1 |
| Engineering | Root causes / feature gaps | /root-causes | All, Head of Ops, Eng lead |
| Agent tools | Escalation gate | /escalation-gate | All, Support lead, L1 |
| Insights | Before / after | /before-after | All, Head of Ops |
| Insights | Back-tests | /back-tests | All, Support lead, Eng lead, Head of Ops |
| Insights | Methodology | /methodology | everyone |

Sidebar furniture: "Viewing as" role picker, How to use, Tour, "Find a ticket" search (top 5 results), "Data & settings" expander (upload, saved-data picker, API connection, go-live date, 9 policy settings, reset), data-as-of footer. Top right: light/dark toggle. No top navigation, no global breadcrumbs beyond a text trail inside each page.

Popups: Welcome, Tour, Ticket details, ticket lists (from cards), draft client updates, account report. Drill-downs from cards open a popup that can open a ticket inside itself.

Inaccessible/untested: none were blocked; the data grids' internals are not inspectable (see above).

---

## 2. Cross-application findings (the ones that matter most)

| # | Finding | Evidence | Why it hurts | Priority | Effort |
|---|---|---|---|---|---|
| X1 | **Two escalation workflows.** Escalation gate builds a packet but records nothing; My desk > Escalation check sends and records. Same checklist, two entry points. | Both pages exercised; gate "Build escalation packet" only shows text. | A new agent cannot tell which is the real one; the quality table only counts My desk. Checks done in the gate are lost. | P0 | Medium |
| X2 | **No confirmation and no undo on actions that write to the permanent log** (Mark fixed, Return to L1, Reassign, Escalate to engineering head, Send to engineering). One click records. | Clicked Mark fixed: recorded immediately, count dropped 20 to 19, no undo. The log is append-only and has no correction event. | A mis-click on a shared, login-less system cannot be reversed by the user. | P0 | Medium |
| X3 | **The welcome popup opens at the start of every session** (every new tab, every restart). | Seen on every page load during the audit. | Daily users dismiss it every time; it also blocks first actions and traps focus. | P1 | Small |
| X4 | **Every page has the same document title, "RideOps Support".** | `document.title` on all 13 pages. | Browser tabs, history and screen-reader page announcements cannot tell pages apart (WCAG 2.4.2). | P1 | Small |
| X5 | **The Data & settings drawer is overloaded** (upload, data picker, API form with token, go-live date, 9 policy settings, reset) and hides settings that change every number. | Opened: about 20 controls in a narrow sidebar; changed settings are not marked. | People change a deadline without noticing it changes the north star; nothing shows which values differ from default. | P1 | Medium |
| X6 | **Stale copy:** the registry caption says "Edits are kept for this browser session", and Methodology's known limits say registry edits are kept "for the browser session only". Both are wrong now: edits are saved on the server. | Registry page text; `views/engineering.py:132`, `views/insights.py:174`. | Users distrust a tool that misdescribes itself; they may re-enter data. | P1 | Small |
| X7 | **Role picker is called "Viewing as" but does not restrict anything** and defaults to "All views". It changes the menu and which buttons appear (lead-only actions). | Behaviour in code and UI. | Users will assume it is access control. The label should say what it does. | P2 | Small |
| X8 | **Cards look clickable but the card is not; a separate "View tickets" button sits below it.** Eight cards produce eight extra buttons per page. | Attention queue, Escalations, My desk, Returns, Account health. | The affordance is weak and doubles the tab stops. Making the whole card one button gives one clear target. | P2 | Medium (Streamlit limits) |
| X9 | **Jargon without definition on first use:** L1, eng, bounce, handoff, settled, north star, lane. | Labels across pages. | New agents and operations staff do not know what "Bounced 2+ times" counts. | P2 | Small |
| X10 | **Tables are canvas grids** (about 5 to 20 per page). Text cannot be selected or read by a screen reader; sorting, column resizing and selection rely on mouse use. | 5 to 21 canvases per page in the DOM scan. | Accessibility risk (WCAG 1.3.1, 2.1.1 unverified) and no copy/paste of cell text. | P1 (verify) | Large |
| X11 | **Small targets:** the "?" help icons are 14x14 px; password-reveal and date-picker buttons 14 to 28 px tall. 13 to 23 controls per page are under 24 px. | DOM scan. | Fails WCAG 2.2 target size (2.5.8) and is hard on touch. | P2 | Small (native widgets; partly Streamlit) |
| X12 | **Search for tickets is shallow:** top 5 of N results, shows only ID and client, no status, no way to see the rest, only after pressing Enter. "orion" returned 113 matches, 5 shown. | Used the sidebar search. | The main "find a record" task fails when more than five match. | P1 | Medium |
| X13 | **Same task, different controls:** pick a ticket via table row (opens a popup), via a dropdown (Escalations, Gate), via a list (My desk). Filters are pills on one page, dropdowns on others, absent elsewhere. | Pages compared. | Users relearn how to select a record on each page. | P2 | Medium |

What is already consistent and should be kept: one header pattern (breadcrumb, title, one-line purpose, actions on the right); cards then chart then table order; empty states with a reason; status never by colour alone; contrast passes everywhere I measured (no text under 4.5:1 in light or dark, canvas excluded); visible focus ring; no sideways scroll at 375 px on any page; Esc and focus trap work in popups; toasts confirm saves.

---

## 3. Tab-by-tab audit

Priority: P0 blocks or misleads, P1 high impact, P2 medium, P3 optional. Effort: S/M/L.

### TAB: Scorecard
**A. Purpose.** Is support getting better: north star (on time and not reopened), open tickets, drivers, targets.
**B. Good.** Clear first card (north star with delta and target); two trend charts with "View chart data"; Targets table says how each target is set; drivers shown as four small trends.
**C. Problems.**
1. The page is long (7 charts, targets table, weekly detail) and the four driver charts are small, equal weight, each with its own data expander.
2. Every row in the targets table reads "Off track" because targets are the best agent's level; there is no sense of progress or gap size beyond the number.
3. Deltas mix units ("+19 vs 4 weeks ago" for tickets, "-5.8 pts") without a legend; "Need attention 34 of 48" is not defined here.
4. No link from a card or chart to the tickets or the page that fixes it (e.g. avoidable escalations to Returns).
**D. Impact.** A head of operations can read the north star but not act: the page ends in a table with no next step.
**E. Recommend.** (P1, S) Make each driver card link to its page ("Avoidable: see Returns"). (P2, S) Add a one-line "what changed this week" sentence under the north star. (P2, S) Targets table: add a gap column and sort by largest gap. (P3, S) Collapse weekly detail by default (already) and the four driver charts into a 2x2 with shared axis note.
**F. Layout.** North star + target + open tickets row; one "what moved" line; trend charts; drivers 2x2 with links; targets table.
**G. Missing.** Confirmed: none. Suggestion: a printable/leadership view (export exists as CSV only).
**H/I/J.** P1/P2 as above; faster path from a number to its cause; Small each.

### TAB: Attention queue
**A. Purpose.** Open tickets ranked by what needs action; counts by flag; filters; load by agent and suggested moves.
**B. Good.** Ranked table with a visible score bar; flags as pills; filters combine; card counts equal list lengths; popups open full ticket detail; Suggested moves appears only when someone is overloaded.
**C. Problems.**
1. Eight cards in two rows, each with its own "View tickets" button, then twelve filter pills duplicating the same flags: the same idea three times (cards, pills, flags column).
2. Flag names are long and the pill row wraps over three lines; "Call required: engineering + agent" and "Reopen risk: confirm before closing" are sentences, not labels.
3. Two sections named almost the same: "Open load by agent" (chart) and "Load by agent" (table) on one page.
4. The attention score is a bar with a number but no explanation of what makes it 9.
5. The table is a canvas grid (X10); the Flags column is truncated to about two pills so the reason a ticket is high is cut off.
6. "Suggested moves" assigns to the least-loaded agent with no context (that agent's skills, the client's account owner).
**D. Impact.** A lead scanning for "what do I do first" has to read cards, pills and columns that say the same thing.
**E. Recommend.** (P1, M) One control set: make the cards the filters (click a card to filter the table below, "x" to clear) and drop the separate pill row; keep a "View in popup" only if the table cannot show it. (P1, S) Shorten flag labels and put the full sentence in the tooltip/detail. (P2, S) Merge the chart and table into one "Load by agent" section. (P2, M) Show the top two flags and "+3" in the Flags column; open a ticket to see all. (P2, S) Explain the score in a tooltip on the column header.
**F. Layout.** Cards-as-filters row; search + agent; table; load section.
**G. Missing.** Suggestion: sort by age/priority/owner choice; saved filters for the day.
**H/I/J.** P1 Medium; fewer duplicate controls, less scanning.

### TAB: My desk
**A. Purpose.** One agent's open tickets with next step, context and escalation check.
**B. Good.** Next step in plain words; context bullets; priority suggestion with reasons; escalation form records checks and note; handover note.
**C. Problems.**
1. The first ticket auto-selected is often one already with engineering, so the first thing a user sees under "Escalation check" is "already with engineering": a dead end.
2. The queue column is narrow; headers ("Age (h)") and descriptions are cut; the ticket is picked through a checkbox in a canvas grid, which is not obvious.
3. "Agent" dropdown at the top right acts as sign-in (there are no logins); an agent can open someone else's desk and record escalations under their name. The record says the role, not the person.
4. Reply and Close tabs only produce drafts; this is stated in small caption text, but the buttons look like actions.
5. The escalation form lets you send with 0 checks and no note, and warns only in a caption.
**D. Impact.** First-time agents conclude the tool is broken; records are attributed to a role.
**E. Recommend.** (P0, S) Select the first ticket the agent can act on (with L1) by default. (P1, M) Replace the grid with a list of rows (ID, client, age, flag) as buttons. (P1, S) Label the tabs "Draft reply" and "Draft close message". (P1, S) On send with unchecked items or no note, show an inline confirm ("2 of 5 checks done, no note. Send anyway?"). (P2, M) Ask for a name once (saved) so records carry a person.
**F. Layout.** Left list (actionable first), right ticket card: facts, next step, context, then tabs.
**G. Missing.** Confirmed: none. Suggestion: "next ticket" button.
**H/I/J.** P0/P1; Small to Medium.

### TAB: Account health
**A. Purpose.** Accounts with repeated bad experiences; account report.
**B. Good.** Clear definition in the header; bad-experience card is a drill-down; report popup is complete and has a copy-ready text.
**C. Problems.**
1. The account report cannot lead to the account's open tickets or to a contact action.
2. "Report for any client" is a second control below the table; a user looking for a specific client scans 17 rows first.
3. "Bad experiences 62" is a ticket count shown beside account counts (17, 14): mixed units in one row.
4. No sort or filter by tier above the table (Enterprise first is the usual need).
**D. Impact.** The call-list task ends at information; the user must go to another page to act.
**E. Recommend.** (P1, S) Put a search box above the table that also finds non-at-risk clients (replace the lower dropdown). (P1, S) Add "Open tickets (n)" button in the report. (P2, S) Separate account cards from the ticket card. (P2, S) Tier filter.
**F.** Search + tier filter, table, popup report with ticket link.
**G.** Confirmed: none. Suggestion: mark "called" with a date (new data, needs agreement).
**H/I/J.** P1; Small.

### TAB: Agent coaching (Team overview, 1:1 prep)
**A. Purpose.** Compare agents; prepare a 1:1.
**B. Good.** Plain-language "main point per agent"; numbers recomputed from data; 1:1 page has strengths/gaps/evidence/agreements saved per agent; download summary.
**C. Problems.**
1. The two views are a small switch at the top; a first-time user may not see that 1:1 prep exists except via the per-agent button.
2. Overview is long: chart, per-agent cards, big table, return reasons, escalation quality (empty until tracking starts).
3. The switch is a button group, not tabs: the active view is not exposed to assistive technology as a tab (unverified).
4. Document title and breadcrumb read "Agent coaching" while the heading says "Agent 1:1 prep".
**D. Impact.** Discoverability and a mismatch between menu label and page heading.
**E. Recommend.** (P2, S) Use real tabs (st.tabs-like semantics) or label the switch "View:". (P2, S) Put "Escalation quality" under its own heading with the "tracking starts" date in the header. (P3, S) Keep breadcrumb as "Agent coaching / 1:1 prep".
**F.** Tabs: Team | 1:1 prep; team tab: summary, per-agent cards, table; quality table last.
**G.** None required.
**H/I/J.** P2; Small.

### TAB: Escalations
**A. Purpose.** Tickets with engineering now; return, fix, see call-required.
**B. Good.** Call-required rule is explicit; the disabled Return button explains why; counts match lists.
**C. Problems.**
1. Selecting a row opens a ticket popup, while acting requires a different dropdown ("Act on an escalation"): two ways to pick the same ticket.
2. "Verdict, status not updated 19" equals almost all open escalations; it reads as a data-quality finding but is shown as a normal KPI.
3. "Call required 16 of 20" with Return disabled leaves engineers with one action (Mark fixed), which is not what a second-escalation ticket needs (the call).
4. No place to record that the call happened.
5. Return reason selector appears even when Return is disabled.
**D. Impact.** The page's main action is unavailable for most rows, with no alternative.
**E. Recommend.** (P0, M) Add the action for call-required tickets ("Call held" with who and when). (P1, S) Merge pick-and-act: selecting a row shows the actions beside it. (P1, S) Move "verdict, status not updated" to a data-quality note. (P2, S) Hide the reason selector when disabled.
**F.** Cards; table; action panel bound to selected row.
**G.** Confirmed gap: nothing records the call; suggested: reason for "Mark fixed".
**H/I/J.** P0/P1; Medium.

### TAB: Returns from engineering
**A. Purpose.** Why escalations come back; engineering lag; time with engineering.
**B. Good.** Reasons by week and by category; lag baseline explained as a proxy; time table says tracking starts at first escalation.
**C. Problems.**
1. Seven sections on one page, mixing analysis (reasons) and operations (lag, escalate to head, SLA, mark lag): the longest page, 21 grids/charts.
2. Duplicate "Open escalations" table also exists on the Escalations page.
3. "Still returning after go-live" is empty until the go-live date is changed in the sidebar.
4. The SLA form and the lag actions appear only for some roles with no explanation when hidden.
**D. Impact.** Two audiences (analyst, engineering lead) share one scroll; actions are buried mid-page.
**E. Recommend.** (P1, M) Split into "Returns" (analysis) and move Engineering lag into Escalations as a tab. (P1, S) Remove the duplicate open-escalations table. (P2, S) Explain hidden controls ("Support leads can...").
**F.** Returns: cards, reasons chart, category table. Escalations: tabs Open | Lag & SLA | Time tracking.
**G.** Suggestion: weekly lag trend once data exists.
**H/I/J.** P1; Medium.

### TAB: Known-issue registry
**A. Purpose.** Confirmed engineering issues that agents link instead of escalating.
**B. Good.** Search; add form; editable table; export; reset.
**C. Problems.**
1. Caption says edits live "for this browser session": wrong now (X6).
2. Registry is edited in a spreadsheet grid; the Save button is at the bottom and unsaved edits are not flagged.
3. The registry is only used by the Escalation gate; My desk's escalation check does not consult it, so agents on My desk never see matching known issues.
4. "Duplicates explained 27, last 30 days" has no link to which tickets.
**D. Impact.** The feature meant to prevent duplicate escalations is absent from the main workflow.
**E. Recommend.** (P0, M) Show matching known issues inside My desk's Escalation check (as the gate does). (P1, S) Fix the caption. (P2, S) "Unsaved changes" indicator. (P2, S) Link the duplicates number to tickets.
**F.** Search, add, table; row detail with linked tickets.
**G.** Suggestion: link a ticket to an issue from My desk.
**H/I/J.** P0/P1; Medium.

### TAB: Root causes / feature gaps
**A. Purpose.** Recurring issues by support hours; feature requests; cab delays.
**B. Good.** Ranked by time cost; chart with data table; feature statuses can be set.
**C. Problems.**
1. A long page of three different subjects (technical issues, product requests, operations problems) with three different owners.
2. Feature and cab tables are plain grids with no owner shown per table except in a caption.
3. The feature status is set in a separate form below the table, not in the row.
**D. Impact.** Each owner scrolls past the others' content.
**E. Recommend.** (P2, S) Tabs by owner: Engineering | Product | Operations. (P2, M) Set status in the row. (P3, S) Owner name in each section title.
**G.** Suggestion: tickets behind each row (popup).
**H/I/J.** P2; Small to Medium.

### TAB: Escalation gate
**A. Purpose.** Pre-escalation check: known issues, priority, packet, reopen risk.
**B.** Good: ordered steps 1 to 4; required fields marked; explains why it never blocks.
**C. Problems.** See X1. Also: defaults to "New ticket" with Category and Agent preselected to the first options (an easy wrong submission); the packet is never saved or sent; "When you close it" is unrelated to escalating and sits last.
**E. Recommend.** (P0, M) Merge into My desk's escalation check or make the gate its single entry; (P1, S) no defaults for category and agent; (P2, S) move the close-time check to My desk > Close.
**H/I/J.** P0; Medium.

### TAB: Before / after
**A. Purpose.** Compare measures before and after the go-live date.
**B.** Good: honest empty state; caveats stated.
**C. Problems.** On first open it is empty because the default go-live date is the day after the data ends; the date control is in the sidebar drawer, not on this page. Values like "Tickets 1,444.0" and "Duplicate escalations 56.0" show decimals for counts; Before/After columns sit far to the right of the labels.
**E. Recommend.** (P1, S) Date picker on the page itself; (P1, S) format counts as integers; (P2, S) narrow table and align columns; (P2, S) default to a date that shows both sides (e.g. mid-period) with a visible note.
**H/I/J.** P1; Small.

### TAB: Back-tests
**A. Purpose.** Show which rules were tested on unseen tickets.
**B.** Good: states the limits of each rule.
**C. Problems.** Written for analysts: AUC, precision, recall unexplained to a lead; no "so what" summary at the top; sits in the main menu for roles that never need it.
**E. Recommend.** (P2, S) A three-line plain summary at the top ("the flag is useful / not useful, because"). (P3, S) Move under Methodology as a tab.
**H/I/J.** P2; Small.

### TAB: Methodology
**A. Purpose.** How every number is defined and where values come from.
**B.** Good: all figures computed from the loaded data; "where each value comes from" table.
**C. Problems.** 3,400 characters of dense text, no table of contents; settings it describes cannot be changed from here.
**E. Recommend.** (P2, S) On-page anchors; (P2, S) link each definition to the setting that changes it.
**H/I/J.** P2; Small.

### Subpages and popups
- **Ticket details popup:** complete (next move, history, timeline) but long; the two bottom buttons ("Open in My desk", "Open in escalation gate") point at the two workflows of X1. P1 Small: show one.
- **Ticket list popup:** good (count equals card); the grid inside needs a checkbox click to open a row: add a visible "Open" column or whole-row click hint. P2 Small.
- **Account report popup:** good; add the ticket link (P1 Small).
- **Welcome and Tour:** the tour walks all pages in the menu (13 for All views), which is long; offer a per-role short tour (P2 Small).

---

## 4. Task-based testing results

| Task | Result | Friction |
|---|---|---|
| Find a ticket by client | Completed (sidebar search) | Only 5 of 113 shown; no status; Enter needed (X12) |
| Escalate a ticket | Completed via My desk | Two entry points (X1); default selection is a ticket already escalated |
| Return an escalation to L1 | Completed on a first escalation; blocked on a second | No action offered instead of the blocked one |
| Mark fixed | Completed | No confirmation or undo (X2) |
| Reassign an overloaded agent's ticket | Completed | No confirmation; destination chosen by the app only |
| Add a known issue / search | Completed | Caption wrong (X6); grid edit needs a separate Save |
| Change a deadline | Completed | Changes the north star silently; setting not flagged as non-default |
| Fetch tickets from an API | Completed | Settings drawer very long; token field and URL in a narrow sidebar |
| Export | Download of the 1:1 summary verified | Other exports not clicked |
| Delete or archive | Not offered anywhere | Confirmed requirement unknown |

## 5. Responsive and accessibility
- **Desktop (1280):** good; dense pages (Returns, Scorecard) need a mini table of contents.
- **Tablet (768):** sidebar collapses behind an icon; cards in four columns; the table scrolls inside its own frame; usable.
- **Mobile (375):** no horizontal page scroll on any page; cards stack; popup fits the screen; tables scroll horizontally inside their frame (reading a wide table on a phone is hard; no card-style alternative). Touch targets under 24 px listed above.
- **WCAG 2.2 AA:** passes in my checks: text contrast (DOM text, both themes), focus visible, one H1 per page and sensible H2 order, language set, landmarks present (main, nav). Fails or at risk: 2.4.2 page titles (X4), 2.5.8 target size (X11), grids (X10, unverified), icon-only controls in the sidebar need verifying names (the scan listed three unnamed buttons per page, source not confirmed), no skip link issue found (a skip-to-content link exists).
- **Not tested:** screen readers, zoom to 400%, reduced motion, high-contrast mode.

---

## 6. Consolidated roadmap

**Phase 1: critical fixes (P0)**
| Page | Problem | Solution | Benefit | Effort | Depends on |
|---|---|---|---|---|---|
| Gate + My desk | Two escalation workflows (X1) | One entry; gate checks live inside My desk | One record of every escalation | M | none |
| All write actions | No confirm/undo (X2) | Inline confirm on irreversible actions; "undo last" correction event | Safe on a shared, login-less system | M | event log |
| My desk | Opens on a ticket already with engineering | Default to an actionable ticket | First use works | S | none |
| Escalations | Blocked return leaves no action | "Call held" action with who/when | The rule becomes workable | M | new event type |
| Registry / My desk | Known issues absent from main workflow | Show matches in My desk | Fewer duplicate escalations | M | none |

**Phase 2: high-impact UX**
Welcome only once (persist); unique page titles; ticket search with more results and status; cards as filters on Attention queue; merge pick-and-act on Escalations; split Returns and move lag to Escalations; Before/after date picker on the page; fix stale captions; account search and ticket link; settings drawer split into Data and Policy with "changed from default" markers.

**Phase 3: visual and interaction refinement**
Shorter flag labels with tooltips; real tabs for coaching; tab structure on Root causes; count formatting; defined terms (a glossary tooltip); larger help targets (custom help text beside labels); table column widths and a visible "open" affordance.

**Phase 4: advanced (only if needed)**
Named users and sign-in (needed before any public hosting: saved data is shared by everyone); person attribution on actions; field mapping for API data; scheduled fetch; "called" status on at-risk accounts; non-grid tables for accessibility.

## 7. UX maturity assessment
Strong on information design (consistent headers, honest empty states, numbers computed from data, contrast and focus handled), and on responsive behaviour. Weak on workflow coherence (two escalation paths, actions that cannot be undone), on discoverability (search depth, welcome popup, buried settings) and on accessibility of data tables. Overall: **developing, about 3 of 5**: a solid analytic product whose operational workflows still need consolidation before many daily users rely on it.

## 8. Observed in passing (real data)
The live database already holds one saved escalation made by someone using the app (SUP-11416, note "test", 4 of 4 checks). That is a real action and was left untouched; it is why Overdue L1 reads 4 now instead of 5.
