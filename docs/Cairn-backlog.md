# Cairn — Retrospective, Known Gaps & Future Enhancements

**Status:** v0.1, 2026-07-17. Written at the completion of the pre-deployment build (intake, gaps curation, OIDC SSO) as the forward-looking record: what stands, what is knowingly missing, and what should come next. Review and re-prioritise at the P5 pilot retrospective and again before go-live.
**Relates to:** Project Plan v0.2 (phase framing), `admin-reference.md` §7 (operational gaps), Intake & Pilot Plan (pilot stages).

---

## 1. Where we are

Phases 1–2 complete and extended: the full application (2a–2f) plus the pulled-forward pilot enablers. Delivered in the July 2026 build cycle (PRs #2–#10):

| Delivered | Substance |
|---|---|
| Intake wizard | Information-audit question set (51 questions, B–K) as seeded configuration; each run creates a draft activity with junction links; propose-and-approve at source; "don't know" → gap records; Section K conditional on enforcement functions |
| Gaps curation | `/intake/gaps` queue; audited resolve (note required) / reopen |
| OIDC SSO | Authorization Code + PKCE against Entra ID; deny-by-default mapping (email first login → audited subject binding); startup config validation; secure cookies |
| Pilot runway | P1 seeding checklist, P2 dry-run script, communications pack — each linked from the pilot plan's stage table |
| Documentation | All architecture docs, admin reference (incl. §5 SSO runbook), product descriptions and doc indexes audited current |
| Security hardening (added post-retrospective, PRs #12–#14) | Session lifetime enforcement (12h absolute / 60m idle), JSON structured logging with security events, RBAC denial + logout auditing, healthz DB-reachability check, RP-initiated logout to the IdP |

Test suite 294 passing; CI green throughout. **Remaining work before go-live is operational (staging stand-up, pilot execution) and assurance (Phase 3) — plus the items below.**

**Addendum (2026-07-27):** the Information Asset Register slices **2g (IAR core) and 2h (ROPA coupling, CSV import, IAR export)** from the IAR plan (`Cairn-iar-plan.md`) are built — `SystemAsset` promoted to `InformationAsset` (migration `538c7c1b29ab`), the `/assets` module, rules 22–23, dashboard asset KPIs, the asset CSV import and the filtered IAR export. Suite 337 passing. Slice **2i (asset intake wizard)** is the next build slice — see item 25.

**Addendum (2026-07-30):** slice **2i (asset intake wizard)** is built — `question_set` generalisation, the `/intake/assets` wizard against the *IAR Question Set v0.1* (`Cairn-iar-questions.md`), and gaps-queue/asset-detail curation surfacing (`Cairn-2i-asset-intake-plan.md`). Item 25 closes below; all three asset capture routes (manual, CSV import, intake) are now complete. Suite 378 passing.

**Addendum (2026-07-31):** **asset supplier names now become approvable reference data** (PRs #31–#32), found in use — the wizard's "which company?" answer and the CSV import's `supplier` column matched against existing Legal Entity labels and discarded anything unmatched, so the asset was saved with no supplier at all. `LegalEntity` is now proposable (migration `babc0f3203da`); an unmatched name creates a proposed entity (role type `processor`), links it, and queues it for approval, from both routes. **Rule 24** closes the converse hole — the asset-side analogue of rule 18, blocking approval while an asset's supplier or security measure is unapproved, with the CSV import creating such rows as `proposed` rather than approved so it cannot bypass the gate. The `AS-D2_NAME` gap self-resolves when the proposed entity is approved. Suite 447 passing. Two knock-ons to watch in P4: a first bulk load full of new security-measure names will now land its assets in the approval queue rather than straight on the register (approve the measures first, then import), and de-duplicating by pointing an asset at an existing entity and rejecting the proposal still leaves its gap to be resolved by hand.

**Addendum (2026-11-04):** **Information Commission and lawful-basis evidence** — SI 2026/1015 commenced the Information Commission on 30 Sep 2026, so user-facing "ICO" wording is now "Information Commission" (complaints form/list, DPIA hint and tag, FRS recipient seed, rule text; the `ico_escalation_flagged` column is unchanged) and the dashboard commencement card merges the statutory defaults (incl. `information_commission`) with the stored profile. Complaints gain s164A evidence fields (`enquiries_note`, `progress_updates`, `outcome_communicated_at`, required once an outcome is set; migration `5c1e7a2d9b04`); Part 2 basis records now require `art6_justification` when an Art 6 basis is set; LIA/RLI records gain `rli_condition` over the five Annex 1 interests (migration `7d3f0b8e6a15`) and rule 5 now also BLOCKs an (ea) basis without one (rule 4 stays a WARN). Existing installs keep the old recipient label (no data migration; vocabulary is editable). Test suite 457 passing.

## 2. Gaps to close before or during staging *(ordered by risk)*

1. ~~**Session lifetime not enforced.**~~ **Done (2026-07-17):** idle timeout via rolling cookie `max_age` (`SESSION_IDLE_SECONDS`, default 60m); absolute lifetime via `auth_at` stamp checked in `current_user` (`SESSION_ABSOLUTE_SECONDS`, default 12h). Pre-existing sessions are invalidated on deploy (one-off re-login).
2. ~~**No RP-initiated logout.**~~ **Done (2026-07-17):** sign-out clears Cairn's session then redirects to the IdP's end-session endpoint (discovery-derived, with Entra `logout_hint`) and back to `/login`; local-only fallback if the IdP is unreachable. Requires the post-logout redirect URI in the app registration (admin ref §5.1).
3. ~~**RBAC denials are not audited.**~~ **Done (2026-07-17):** `require_role` failures write an `authorisation_denied` AuditEvent (path, required/actual roles) plus a structured security-log line; logout is audited too.
4. ~~**JSON structured logging.**~~ **Done (2026-07-17):** `src/cairn/logs.py` — JSON lines to stdout including uvicorn's loggers (`LOG_FORMAT`, default json outside dev); security events (`cairn.security`) carry structured fields, no personal data.
5. **Real Entra round-trip untested.** Everything up to the token exchange is exercised with a mocked IdP; the first staging deployment must include an explicit SSO verification step (admin ref §5.2.4) before users are invited.
6. **Cairn's own DPIA needs updating before real data.** The tool now processes more personal data than when the DPIA was scoped: user emails and IdP subjects, intake respondent contact details, free-text intake answers (which will contain incidental personal information). Phase 3 cross-cutting item; the delta is known and small — do it deliberately.
7. **Environments seeded before the intake wizard existed are missing `intake_question` rows.** `seed_frs_pack` only runs once, from the org setup wizard (`src/cairn/setup.py`) — it is not re-run on deploy. Any database seeded before the 2d intake-wizard slice (PR #2) has business functions, vocabularies etc. but an empty `intake_question` table, so intake sections render with no fields to answer (found 2026-07-21 against a pre-2d dev database, confirmed via `select count(*) from intake_question`). Fix is a one-off `seed_activity_questions(session)` call against the affected database (renamed from `seed_intake_questions` in slice 2i.1, which made seeding per question set) — safe and additive, it no-ops if that set's rows already exist. Check this explicitly before staging/UAT and before the pilot goes live: run the count check and backfill if zero, rather than assuming setup covered it. **Delivered (2i.1):** seeding is now per-set via `seed_question_set`, with `seed_activity_questions`/`seed_asset_questions` as the idempotent per-set entry points — the reseed mechanics this item asked for. **New instance of the same gap (2i.2):** any environment seeded **before** slice 2i.2 will have activity rows but an empty asset question set — `seed_frs_pack` now calls `seed_asset_questions(session)` too, but only runs once, so it never retroactively backfills an existing database. Same check, same fix: `select count(*) from intake_question where question_set = 'asset'`, backfill with a one-off `seed_asset_questions(session)` call if zero. Carried into the P1 checklist (`Cairn-pilot-p1-seeding-checklist.md` §D).

## 3. Items to hold until pilot evidence (P2–P5)

8. **Question-set admin screen.** Wording lives as configuration (`intake_question` rows) precisely so P2/P5 can iterate it — but there is no UI; edits need DB access. If P2 produces more than a handful of wording fixes, build a vocabularies-style admin editor; if not, a curated migration per revision is acceptable. **The `question_set` generalisation (2i.1) is now in place**, so such an editor would serve both sets (activity and asset) from one screen without further schema work — the discriminator and the per-set reseed helpers already exist; only the UI is missing.
9. **Reopen-after-submit for intake.** Submissions are immutable once submitted. The pilot will show whether respondents need a correction flow ("reopen my intake") or whether curation absorbs it. Don't build speculatively.
10. **Gap workflow depth.** Gaps are open/resolved with a note. An organisation-wide audit (P6, hundreds of gaps) may need assignment, due dates, and interview batching. Let P3/P4 volumes decide.
11. **Curation assists.** Three places intake hands curators free text that the model wants structured: retention answers (H3–H6 → `activity_retention` links), per-subject data scoping (E4 → `data_subject_scope`), per-category retention (H5). A "convert answer to link" affordance would cut curation time — measure it in P4 first (curation time per activity is already a pilot success measure).
12. **Surface the intake submission from the activity.** A draft created by intake links back only via the intake list; the activity detail page should show "created from intake" with the answers and open gaps. Cheap, high value for curators — a good first post-pilot slice.
13. **Multi-activity flow.** One wizard run = one activity (by design), but B1 asks respondents to list several. A "start next activity for this department" shortcut carrying forward section A/B context would reduce friction for multi-activity respondents. P3 observation will show if it matters.
14. **B4 discovery answers go nowhere.** The "anything not written down?" answers are stored on the submission but not surfaced as leads. Consider adding them to the gaps queue or a discovery list for IG follow-up.

## 4. Future enhancements (post-pilot / Phase 5–6 horizon)

15. **Notifications** (Integration Architecture #8): overdue-review, trial-expiry and complaint-acknowledgement emails via estate SMTP. Currently the dashboard is authoritative and nothing sends; acceptable for pilot, expected for BAU.
16. **Entra group → role mapping.** Roles are assigned manually in `/users`; mapping IdP group claims to Cairn roles would remove a manual step and an offboarding risk. Needs a design decision (who owns role truth — Cairn or the directory?).
17. **Client certificate instead of client secret** for the Entra app registration (removes the secret-expiry failure mode flagged in admin ref §5.1).
18. **Export formats**: XLSX and PDF renderings of the Art 30/s61 views; read-only JSON API for BI tooling (Integration Architecture #7 future options).
19. **Complaints intake endpoint** (Integration Architecture §3.2 future option): the narrow public submission surface, if the org decides Cairn should receive complaints directly.
20. **Privacy-notice link checker** (Integration Architecture #4 future option).
21. **Legacy ROPA reconciliation view** (Phase 4): the CSV import creates drafts; a side-by-side reconcile of legacy rows against audit-derived records would make the Phase 4 "migration as reconciliation" concrete. Decide when the legacy register's condition is known.
22. **Automated backup verification**: the quarterly restore test is a manual runbook; scripting restore + smoke into CI-adjacent automation would make it routinely cheap.
23. **Further sector packs** (Phase 6): police / ambulance / local authority / generic — the seams (Organisation Profile, pack seeds, profile-conditioned rules, per-pack question sets) are proven; each new pack is content work plus a legislation review.
24. **Question Set v0.2** (planned): P5 retrospective output, folding in dry-run and pilot findings; becomes the periodic-review questionnaire (Plan §5). One candidate is already known: **merge C4/C5 into a single choice** ("our own activity / for another organisation / jointly with another organisation"), eliminating the processor-and-joint contradiction *structurally* rather than by validation (the conditional-logic slice rejects the combination with an error today, which works with v0.1 as signed off). A wording/structure change to signed content, so it takes the v0.2 route with IG sign-off — the `single_choice` kind, `depends_on` config and the C4/C5 apply mapping already support it, so the build cost is a seed edit, a data migration for the changed rows, and test updates.
25. ~~**IAR slice 2i — asset intake wizard**~~ **Done (2026-07-30)** (plan: `Cairn-2i-asset-intake-plan.md`): the guided, jargon-free asset question set for asset owners, producing proposed assets and gap records, built across three sub-slices — the `question_set` discriminator (`activity` | `asset`) and per-set reseed mechanics (2i.1, serving items 7/8 below); the `/intake/assets` wizard, populates handlers and the seeded *IAR Question Set v0.1* (`Cairn-iar-questions.md`, 2i.2); and gaps-queue/asset-detail curation surfacing (2i.3). Rule 22 carries the pipeline forward into activity documentation once a personal-data asset is approved.

26. ~~**No inline styles anywhere — CSP blocks them**~~ **Resolved (2026-07-30): `src/cairn/static/cairn.css` added.** The app sends `Content-Security-Policy: default-src 'self'` with no `style-src 'unsafe-inline'`, so a `style="…"` attribute reaches the DOM but computes to nothing — proven twice with `getComputedStyle`. Ten such attributes were in the tree (all `display:inline` on paired action forms across `base.html`, the imports previews, `users/list.html`, a contract section and the asset detail page), so approve/reject, confirm/cancel and deactivate/reactivate buttons had been stacking rather than sitting side by side. The CSP was **not** relaxed: a same-origin stylesheet is already allowed by `default-src 'self'`. `tests/test_web.py::test_no_template_uses_an_inline_style_attribute` fails the build if one reappears. Keep `cairn.css` small — a rule belongs there only when no `govuk-*` class does the job. **When checking whether a govuk-frontend class exists, search for the escaped form** — the minified CSS writes override classes as `.govuk-\!-width-two-thirds`, so grepping the literal `govuk-!-width-two-thirds` finds nothing and wrongly suggests the class is missing (that mistake was made and corrected here on 2026-07-30; the width overrides do exist).
27. ~~**Intake-derived asset notes read as a run-on block.**~~ **Resolved (2026-07-30)** by `.cairn-preserve-lines` (item 26) on the textarea-backed rows of the asset detail summary list, so `notes` and `description` render their stored newlines. Partly pre-empted by 2i.3, whose "created from intake" panel already showed the submission's answers as their own rows.

28. **Multiple Art 6 bases per activity.** ICO guidance is to document all bases that apply; Cairn holds one per activity per regime. Workaround today: split the activity.
29. **Structured further-processing options for rule 21.** Replace the free-text compatibility note with the Annex 2 compatible-purpose route, the consent-origin reuse route and a compatibility assessment.
30. **Rule 4 could also flag consent (a) for public authorities** for DPO review, alongside (f)/(ea).
31. **Rights-by-basis view** (erasure / portability / objection) to feed privacy notices.
32. **Re-check the ADM safeguards (rule 19)** when the final ADM/AI statutory code is published.

## 5. Standing assurance items (Phase 3, unchanged but restated)

- **Penetration test** — now more urgent than when scoped: the attack surface grew (OIDC endpoints, intake forms).
- **Accessibility (WCAG 2.2 AA)** — the intake wizard and gaps queue are new user-facing surfaces built on GOV.UK components but not yet formally tested; respondents include the whole organisation, so intake is the highest-traffic screen Cairn has.
- **Rules-engine test formalisation** and UAT per Project Plan §6 — evidence packs, not new engineering.

---

## 6. Suggested order of attack

| When | Items |
|---|---|
| **Next build slice** | **None queued** — slice 2i closed the last planned build work (item 25, 2026-07-30). What remains is operational (staging stand-up, pilot execution) and assurance (§5), so the next move is a decision about sequencing those, not a slice to pick up. Nothing below 15 is a build slice; 8–14 wait on pilot evidence by design. |
| Before staging holds real data | 6 DPIA delta *(1, 3, 4 done 2026-07-17)* · 7 intake-question reseed check *(both question sets — 25 done 2026-07-30)* |
| At first staging deployment | 5 Entra round-trip verification *(2 done 2026-07-17)* |
| During pilot (as evidence arrives) | 8–14 |
| Before go-live | Phase 3 items (§5) · 15 notifications |
| Post go-live / roadmap | 16–24, 28–32 *(26, 27 done 2026-07-30)* |

---

*Backlog v0.1 — owner: IG lead + development. Re-baseline at the P5 retrospective; anything promoted from here into a build slice gets its own plan-and-spec treatment per the established pattern.*
