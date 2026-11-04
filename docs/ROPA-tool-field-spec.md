# ROPA Tool — Field-Level Build Specification

**Status:** Spec v0.4 — for iteration. v0.4 applies two field-level clarifications validated by the Phase 1.7 architecture spike (`spike-findings.md`): the `regime_scope` dual-mapping discriminator (§6.1) and the unified regime enum (§2.2).
**Derived from:** *ROPA Tool — High-Level Plan & Data Architecture*, **Plan v0.12** (`ROPA-tool-plan.md`). Section references below (e.g. Plan §3.2) point to that document. This spec turns the agreed architecture into concrete, buildable fields; it does not re-argue design decisions.
**Convention for divergences:** where this spec makes a field-level decision the plan left implicit, it is tagged **[spec clarification]**. These refine, and never contradict, Plan v0.12.

---

## 1. How to read this spec

### 1.1 Type vocabulary

| Type | Meaning |
|------|---------|
| `uuid` | Primary key |
| `text` | Short single-line string |
| `longtext` | Multi-line string |
| `enum(a,b,…)` | One value from a fixed set (see §7) |
| `enum[](…)` | Multi-select from a fixed set |
| `bool` | True/false |
| `date` / `datetime` | Calendar date / timestamp |
| `int` | Integer |
| `fk → Entity` | Single foreign key |
| `fk[] → Entity` | Many, via a junction (§5) |
| `json` | Structured blob |

**Req** column: `Y` required, `N` optional, `C` conditional (condition stated in Notes), `D` derived (system-computed, not user-entered).

### 1.2 Fields present on every entity [spec clarification]

To avoid repetition, every entity carries these implicitly and they are **not** relisted per table:

| Field | Type | Req | Notes |
|-------|------|-----|-------|
| `id` | uuid | Y | Primary key |
| `created_at` / `updated_at` | datetime | D | System-set |
| `created_by` / `updated_by` | fk → User | D | System-set |
| `version` | int | D | Increments on change; prior versions retained (Plan rule 17) |
| `change_note` | text | N | Optional reason-for-change captured on edit |

### 1.3 Entity catalogue

Configuration (§2): Organisation Profile, Regime Policy, User & Role.
Core (§3): Processing Activity.
Reference/lookup (§4) and Controlled vocabularies (§7).
Junctions (§5). Supporting/linked records (§6).

---

## 2. Configuration entities

### 2.1 Organisation Profile (Plan §3.3, *Configuration & deployment model*)

Single row per deployment (single-tenant).

| Field | Type | Req | Default | Notes |
|-------|------|-----|---------|-------|
| `org_name` | text | Y | — | The controller/processor legal name shown on exports |
| `org_type` | enum(public_authority, private_body, mixed) | Y | — | Drives profile-conditioned rules (§8) |
| `sector_pack` | enum(frs, …) | Y | `frs` | Only `frs` exists in v1 |
| `legal_entity_topology` | enum(single, group, joint) | Y | `single` | Governs how many Legal Entities/relationships are modelled |
| `applicable_regimes` | enum[](general, law_enforcement) | Y | `general` | If `law_enforcement` absent, Part 3 UI/rules stay dormant |
| `active_modules` | enum[](breach, complaints, dpia, lia_rli, contracts, assets, external_data) | Y | see notes | `complaints` forced ON when `org_type` includes controller duties (§8, Plan §1.4) |
| `public_authority_guards` | bool | Y | `true` for public_authority | Toggles rule 4 |
| `commencement_watch` | json | N | — | Optional record of DUAA commencement dates in force for this org |

### 2.2 Regime Policy (Plan §1.6a, §3.3)

One row per enforcement-domain function; the switch behind the configurable Part 3 boundary.

| Field | Type | Req | Default | Notes |
|-------|------|-----|---------|-------|
| `activity_domain` | enum(fire_safety_enforcement, fire_investigation, firesetter_intervention, other) | Y | — | Per-function granularity (Plan §7) |
| `assigned_regime` | enum(general, law_enforcement) | Y | `general` | The default regime inherited by activities in this domain. **[spec clarification]** unified with the activity `regime` enum (§3) — Plan §1.6a's `part2` value corresponds to `general` here; `part2`/`part3` are reserved for the Lawful Basis Record's mapping scope (§6.1) |
| `rationale` | longtext | Y | — | Why this classification |
| `last_changed_by` | fk → User | D | — | Audited |
| `last_changed_at` | datetime | D | — | Audited |

### 2.3 User & Role (Plan §5.1)

| Field | Type | Req | Default | Notes |
|-------|------|-----|---------|-------|
| `display_name` | text | Y | — | |
| `role` | enum(contributor, curator, approver_dpo, viewer) | Y | `viewer` | Permission tier (Plan §5.1) |
| `business_function_id` | fk → BusinessFunction | C | — | Required for `contributor` — scopes editable activities |

---

## 3. Core entity: Processing Activity (Plan §3.2)

| Field | Type | Req | Default | Notes |
|-------|------|-----|---------|-------|
| `name` | text | Y | — | e.g. "Home Fire Safety Visits" |
| `reference` | text | N | — | Optional local reference code |
| `business_function_id` | fk → BusinessFunction | Y | — | |
| `description` | longtext | N | — | |
| `activity_type` | enum(operational, analytics_modelling) | Y | `operational` | Modelling recorded separately, linked via `activity_feeds` (§5) |
| `regime` | enum(general, law_enforcement) | Y | `general` | First router (Plan §1.6) |
| `regime_source` | enum(policy, manual_override) | Y | `policy` | If `manual_override`, `regime_override_reason` required |
| `regime_override_reason` | text | C | — | Required when `regime_source = manual_override` |
| `controller_or_processor` | enum(controller, processor, joint) | Y | `controller` | |
| `record_status` | enum(draft, in_review, active, retired) | Y | `draft` | **[spec clarification]** renamed from Plan's `status`; the record's authoring/approval state |
| `lifecycle_stage` | enum(trial, live, retired) | Y | `live` | **[spec clarification]** distinct from `record_status`: the *processing's* maturity (Plan §3.8) |
| `trial_start` | date | C | — | Required when `lifecycle_stage = trial` |
| `trial_end` | date | C | — | Required when `lifecycle_stage = trial`; drives expiry alerts |
| `purpose` | longtext | Y | — | Art 30 / s61 purpose(s) |
| `categories_of_processing` | longtext | C | — | Required when `controller_or_processor = processor` (Art 30(2)) |
| `personal_data_source` | enum[](from_data_subject, from_third_party, public_source) | Y | — | Drives Art 13 vs Art 14 transparency (Plan review R3) |
| `owner_id` | fk → User | Y | — | Accountable owner |
| `last_reviewed_at` | date | N | — | |
| `next_review_at` | date | Y | — | Overdue-review alerts (rule 16) |
| `special_category_flag` | bool | D | — | Derived from linked Personal Data Categories |
| `criminal_offence_flag` | bool | D | — | Derived |
| `vulnerable_or_safeguarding_flag` | bool | Y | `false` | Extra safeguards + DPIA (rule 7) |
| `children_flag` | bool | Y | `false` | Children's protections + consent handling (rules 6–7) |
| `external_data_use_mode` | enum(none, manual, automated) | Y | `none` | External-data pattern (Plan §3.6) |
| `lineage_granularity` | enum(activity, record) | Y | `activity` | `record` required for automated modelling affecting individuals (rule 10) |
| `adm_profiling_flag` | bool | D | — | Derived: true when `external_data_use_mode = automated` or solely-automated decisioning present |
| `high_risk_flag` | bool | Y | `false` | Triggers DPIA screening |

**Law-enforcement (regime = law_enforcement) additional fields** [spec clarification — surfacing Plan §1.6]:

| Field | Type | Req | Notes |
|-------|------|-----|-------|
| `le_data_subject_classification` | enum[](suspect, convicted, victim, witness, other) | C | s38 categorisation; required when regime = law_enforcement |
| `le_fact_vs_assessment_noted` | bool | C | s38 distinction between fact and personal assessment |
| `s62_logging_note` | longtext | N | Reference to where s62 logs live (Plan §1.6) |

---

## 4. Reference / lookup entities (Plan §3.3)

Each is a managed controlled vocabulary. Common shape: `id`, `label`, plus the attributes below. Seed values in §7.

| Entity | Distinct attributes | Seed → §7 |
|--------|--------------------|-----------|
| **Legal Entity** | `role_type` enum(own_org, joint_controller, representative, dpo, processor, sub_processor, data_supplier, partner_agency); `contact`; `address`; `country` | §7.9 |
| **Business Function** | — | §7.10 |
| **Data Subject Category** | `le_classification` enum(suspect,convicted,victim,witness,none) | §7.11 |
| **Personal Data Category** | `is_special_category` bool; `is_criminal_offence` bool | §7.12 |
| **Recipient** | `type` enum(internal, processor, joint_controller, public_body, other); `legal_entity_id` fk | §7.13 |
| **Lawful Basis — general (Art 6)** | `code`; `public_authority_restricted` bool | §7.1 |
| **Lawful Basis — LE (s35)** | `code` | §7.2 |
| **Special Category Condition (Art 9)** | `code`; `needs_schedule1` bool; `needs_apd` bool | §7.3 |
| **Schedule 1 Condition (DPA 2018)** | `paragraph`; `part`; `needs_apd` bool | §7.4 |
| **Schedule 8 Condition (Part 3)** | `paragraph` | §7.5 |
| **Security Measure** | `category` enum(technical, organisational) | §7.14 |
| **System / Asset** | `owner`; `location`; `hosting_country`; `security_measures` fk[]; `default_retention_id` fk; `s62_logging_in_scope` bool | — |
| **Third Country / Int'l Org** | `adequacy_status` enum(adequate, not_adequate, under_review) | — |
| **Transfer Mechanism** | `code` | §7.6 |
| **Retention Rule** | `period`; `trigger`; `legal_driver`; `disposal_method` | — |
| **External Data Source** | `supplier_legal_entity_id` fk; `supplier_role` enum(processor, separate_controller); `agreement_ref`; `data_categories` fk[]; `special_category` enum(none, inferred, direct); `art14_relationship` text | §7.7 |

---

## 5. Junction entities (Plan §3.4)

| Junction | A | B | Extra attributes |
|----------|---|---|------------------|
| `activity_datasubject` | Processing Activity | Data Subject Category | — |
| `activity_datacategory` | Processing Activity | Personal Data Category | `data_subject_scope` fk → Data Subject Category (optional — for HFSV divergence) |
| `activity_recipient` | Processing Activity | Recipient | — |
| `activity_security` | Processing Activity | Security Measure | `inherited_from_system` bool (D) |
| `activity_system` | Processing Activity | System / Asset | — |
| `activity_contract` | Processing Activity | Contract / DSA | — |
| `activity_privacynotice` | Processing Activity | Privacy Notice | — |
| `activity_datasource` | Processing Activity | External Data Source | activity-level lineage baseline |
| `activity_retention` | Processing Activity *(or data category)* | Retention Rule | `data_category_scope` fk (optional); overrides system default (Plan §3.9) |
| `activity_feeds` | Processing Activity *(analytics_modelling)* | Processing Activity *(operational)* | directional: source → consumer |
| `activity_controller` | Processing Activity *(processor/joint)* | Legal Entity | **[spec clarification]** the "each controller acted for" link the Art 30(2) view (§10.2) and rule 13 require; §9.3's `controllers` field — previously implied but missing from this table |

---

## 6. Supporting / linked records (Plan §3.5)

### 6.1 Lawful Basis Record

**[spec clarification]** The dual mapping (Plan §1.6a) is realised as **one Lawful Basis Record per regime per activity**, discriminated by `regime_scope` and unique on (`activity_id`, `regime_scope`). The record whose scope matches the activity's active `regime` (`general` → `part2`, `law_enforcement` → `part3`) is authoritative; the other is retained, dormant, and untouched by regime changes. Conditional requirements below therefore key off the **record's scope**, not the activity's live regime — a dormant mapping keeps its own completeness. Validated by the Phase 1.7 spike.

| Field | Type | Req | Notes |
|-------|------|-----|-------|
| `activity_id` | fk → Processing Activity | Y | Unique with `regime_scope` |
| `regime_scope` | enum(part2, part3) | Y | **[spec clarification]** dual-mapping discriminator (see note above) |
| `art6_basis` | fk → Lawful Basis general | C | Required on `part2`-scope records |
| `art6_justification` | longtext | C | Required on `part2`-scope records when an Art 6 basis is set (enforced on save; not required for `part3`) — **Revised 2026-11-04** |
| `art9_condition` | fk → Special Category Condition | C | Required when `special_category_flag` (`part2` scope) |
| `schedule1_condition` | fk → Schedule 1 Condition | C | Required when the Art 9 condition `needs_schedule1` |
| `art10_basis` | text | C | Required when `criminal_offence_flag` (official authority or Sch 1; `part2` scope) |
| `s35_basis` | fk → Lawful Basis LE | C | Required on `part3`-scope records |
| `schedule8_condition` | fk → Schedule 8 Condition | C | Required for LE sensitive processing (`part3` scope) |
| `apd_id` | fk → Appropriate Policy Document | C | Required when Art 9/Sch 1 or s42 needs an APD |

### 6.2 Consent Record (Plan review R1/R2; rule 6)
| Field | Type | Req | Notes |
|-------|------|-----|-------|
| `lawful_basis_record_id` | fk | Y | Present when basis = consent (a) |
| `consented_to` | longtext | Y | What was consented to |
| `wording_shown` | longtext | Y | The exact consent wording presented |
| `consent_datetime` | datetime | Y | |
| `consent_method` | enum(online_form, paper, verbal_logged, other) | Y | |
| `withdrawal_status` | enum(active, withdrawn) | Y | |
| `withdrawal_datetime` | datetime | C | Required when withdrawn |
| `review_due` | date | N | Proactive-review date |
| `age_check_outcome` | enum(adult, child_over_13, child_under_13, unknown) | C | Required when `children_flag` |
| `parental_consent_captured` | bool | C | Required when age indicates under-13 |

### 6.3 LIA / RLI Record
| Field | Type | Req | Notes |
|-------|------|-----|-------|
| `lawful_basis_record_id` | fk | Y | For (f) or (ea) |
| `interest_identified` | longtext | Y | |
| `rli_condition` | enum(national_security_defence, emergencies, crime, safeguarding_vulnerable, public_interest_disclosure_request) | C | Annex 1 recognised interest; required for (ea) (rule 5) — **Revised 2026-11-04** |
| `necessity_test` | longtext | Y | |
| `balancing_test` | longtext | C | Required for (f); **not** required for (ea) RLI |
| `safeguards` | longtext | N | |
| `decision` | enum(proceed, do_not_proceed) | Y | |
| `decision_date` | date | Y | |

### 6.4 Appropriate Policy Document
| Field | Type | Req | Notes |
|-------|------|-----|-------|
| `title` | text | Y | |
| `scope` | enum(schedule1, s42_part3) | Y | Distinguishes the two APD regimes |
| `document_ref` | text | Y | |
| `retain_until` | date | Y | 6 months after processing ends |

### 6.5 Transfer
| Field | Type | Req | Notes |
|-------|------|-----|-------|
| `activity_id` | fk | Y | |
| `recipient_id` | fk → Recipient | Y | |
| `third_country_id` | fk → Third Country | Y | |
| `mechanism_id` | fk → Transfer Mechanism | Y | |
| `data_protection_test` | longtext | C | "Not materially lower" test (DUAA s85) — required for appropriate-safeguards transfers |

### 6.6 DPIA
| Field | Type | Req | Notes |
|-------|------|-----|-------|
| `activity_id` | fk | Y | |
| `screening_outcome` | enum(required, not_required, documented_not_required) | Y | |
| `nature_scope_context_purposes` | longtext | C | Required when `screening_outcome = required` |
| `necessity_proportionality` | longtext | C | |
| `risks_to_individuals` | longtext | C | |
| `mitigations` | longtext | C | |
| `residual_risk` | enum(low, medium, high) | C | `high` → prior consultation with the Information Commission |
| `dpo_advice` | longtext | N | |
| `sign_off_by` | fk → User | C | approver_dpo role |
| `review_date` | date | C | |

### 6.7 Contract / DSA
| Field | Type | Req | Notes |
|-------|------|-----|-------|
| `activity_id` | fk | Y | |
| `parties` | fk[] → Legal Entity | Y | |
| `type` | enum(controller_processor, joint_controller, data_sharing) | Y | |
| `art28_checklist_complete` | bool | C | For controller_processor |
| `security_schedule` | longtext | N | |
| `sub_processor_authorisation` | enum(none, general, specific) | N | |
| `start_date` / `review_date` / `expiry_date` | date | Y/Y/N | |

### 6.8 Privacy Notice
| Field | Type | Req | Notes |
|-------|------|-----|-------|
| `activity_id` | fk | Y | |
| `version` | text | Y | |
| `publish_date` | date | Y | |
| `covers_art13` / `covers_art14` | bool | Y | Aligns with `personal_data_source` |

### 6.9 Breach Record *(module: breach)*
| Field | Type | Req | Notes |
|-------|------|-----|-------|
| `activity_id` | fk | N | |
| `summary` | longtext | Y | |
| `occurred_at` / `detected_at` | datetime | Y | |
| `reportable_to_ico` | bool | Y | 72-hour assessment |
| `individuals_notified` | bool | N | |

### 6.10 Complaints Record *(module: complaints — statutory for controllers, Plan §1.4)*
| Field | Type | Req | Notes |
|-------|------|-----|-------|
| `activity_id` | fk | N | Optional link to the processing complained about |
| `received_at` | datetime | Y | Starts the 30-day acknowledgement clock |
| `acknowledged_at` | datetime | C | Must be ≤ 30 days after `received_at` |
| `response_due` / `responded_at` | date/datetime | Y/C | |
| `outcome` | enum(upheld, partly_upheld, not_upheld, withdrawn) | C | |
| `outcome_communicated_at` | datetime | C | Required when `outcome` is set — s164A(4)(b) *(Revised 2026-11-04)* |
| `enquiries_note` | longtext | N | Enquiries made into the subject matter, s164A(5)(a) *(Revised 2026-11-04)* |
| `progress_updates` | longtext | N | Progress given to the complainant, s164A(5)(b) *(Revised 2026-11-04)* |
| `ico_escalation_flagged` | bool | Y | Complainant informed of Information Commission escalation route (column name unchanged) |

### 6.11 Decision-support / ADM Record (Plan §3.6)
| Field | Type | Req | Notes |
|-------|------|-----|-------|
| `activity_id` | fk | Y | |
| `data_source_ids` | fk[] → External Data Source | Y | |
| `use_mode` | enum(manual, automated) | Y | Mirrors activity `external_data_use_mode` |
| `technique` | longtext | C | For automated |
| `solely_automated` | bool | C | Art 22A–22D trigger |
| `significant_effects` | bool | C | With `solely_automated` → decides the safeguards path |
| `accuracy_bias_checks` | longtext | C | For automated |
| `human_review` | longtext | C | |
| `contestability` | longtext | C | |
| `transparency_ref` | fk → Privacy Notice | N | Art 14 |

---

## 7. Controlled vocabularies (seed values)

### 7.1 Lawful Basis — general (Art 6)
`a` Consent · `b` Contract · `c` Legal obligation · `d` Vital interests · `e` Public task *(default; `public_authority_restricted = false`)* · `ea` Recognised legitimate interest *(`restricted = true`)* · `f` Legitimate interests *(`restricted = true`)*.

### 7.2 Lawful Basis — LE (s35)
`s35_consent` (based on law + consent) · `s35_task` (based on law + necessary for a competent authority's law-enforcement task).

### 7.3 Special Category Condition (Art 9(2)) — `needs_schedule1` / `needs_apd`
`a` explicit consent (N/N) · `b` employment/social security (Y/**Y**) · `c` vital interests (N/N) · `d` not-for-profit body (N/N) · `e` made public by data subject (N/N) · `f` legal claims (N/N) · `g` substantial public interest (Y/**Y**) · `h` health/social care (Y/**N**) · `i` public health (Y/**N**) · `j` archiving/research/statistics (Y/**N**).

**Note on `needs_apd`:** the flag above is indicative at the Art 9 level; the **authoritative APD determinant is the specific Schedule 1 condition chosen** (§7.4). Health/social care (h→Sch 1 para 2), public health (i→para 3) and research (j→para 4) require a Schedule 1 condition but **no APD**, whereas employment (b→para 1) and substantial public interest (g→Part 2) do. The build should read `needs_apd` from the linked Schedule 1 condition, not from the Art 9 point.

### 7.4 Schedule 1 Condition (DPA 2018) — full vocabulary

Paragraphs 1–4 and 6–37 are the selectable conditions (36 in total); para 5 (the Part 2 APD requirement) and paras 38–41 are the APD/safeguards mechanics (§7.4.4), not selectable conditions. **[spec clarification]** `APD` = appropriate policy document required. Verify against the latest revised legislation for any DUAA amendments before seeding.

**7.4.1 Part 1 — employment, health and research** *(satisfies the "basis in law" requirement for Art 9(2)(b),(h),(i),(j))*

| Para | Condition | Supports | APD |
|------|-----------|----------|-----|
| 1 | Employment, social security and social protection | 9(2)(b) | **Yes** |
| 2 | Health or social care purposes | 9(2)(h) | No |
| 3 | Public health | 9(2)(i) | No |
| 4 | Research etc (archiving/research/statistics) | 9(2)(j) | No |

**7.4.2 Part 2 — substantial public interest** *(satisfies Art 9(2)(g); para 5 requires an APD for all Part 2 conditions except the noted disclosure carve-outs)*

| Para | Condition | APD |
|------|-----------|-----|
| 6 | Statutory etc and government purposes | Yes |
| 7 | Administration of justice and parliamentary purposes | Yes |
| 8 | Equality of opportunity or treatment | Yes |
| 9 | Racial and ethnic diversity at senior levels of organisations | Yes |
| 10 | Preventing or detecting unlawful acts | Yes *(not required when the processing is a disclosure to a competent authority — para 10(2))* |
| 11 | Protecting the public against dishonesty etc | Yes |
| 12 | Regulatory requirements relating to unlawful acts and dishonesty etc | Yes |
| 13 | Journalism etc in connection with unlawful acts and dishonesty etc | No *(para 13(3))* |
| 14 | Preventing fraud | Yes |
| 15 | Suspicion of terrorist financing or money laundering | Yes |
| 16 | Support for individuals with a particular disability or medical condition | Yes |
| 17 | Counselling etc | Yes |
| 18 | **Safeguarding of children and of individuals at risk** | Yes |
| 19 | Safeguarding of economic well-being of certain individuals | Yes |
| 20 | Insurance | Yes |
| 21 | Occupational pensions | Yes |
| 22 | Political parties | Yes |
| 23 | Elected representatives responding to requests | Yes |
| 24 | Disclosure to elected representatives | Yes |
| 25 | Informing elected representatives about prisoners | Yes |
| 26 | Publication of legal judgments | Yes |
| 27 | Anti-doping in sport | Yes *(not required for disclosure to a sporting body — para 27(3))* |
| 28 | Standards of behaviour in sport | Yes |

**7.4.3 Part 3 — additional conditions for criminal convictions etc** *(satisfies Art 10)*

| Para | Condition | APD |
|------|-----------|-----|
| 29 | Consent | No |
| 30 | Protecting individual's vital interests | No |
| 31 | Processing by not-for-profit bodies | No |
| 32 | Personal data in the public domain | No |
| 33 | Legal claims | No |
| 34 | Judicial acts | No |
| 35 | Administration of accounts used in commission of indecency offences involving children | Yes |
| 36 | Extension of Part 2 conditions (removes the "substantial public interest" requirement for criminal offence data) | per underlying Part 2 condition |
| 37 | Extension of insurance conditions | per para 20 |

**7.4.4 Part 4 — APD & safeguards (mechanics, not selectable conditions)**
Para 39 defines APD content (Art 5 compliance procedures + retention/erasure policy). Para 40 requires retention of the APD until 6 months after processing ends. **Para 41 requires the Art 30 record to state which condition is relied on, how Art 6 is satisfied, and the retention/erasure position** — a direct tie-in to the Lawful Basis Record (§6.1).

**FRS priority conditions:** Part 1 para 2 (health/social care — EMR/casualty); Part 2 paras 6 (statutory), 8 (equality — PSED), 10 (unlawful acts — fire safety), 18 (safeguarding); Part 3 paras 29, 30, 33 (criminal — fire investigation/vetting).

### 7.5 Schedule 8 Condition (Part 3 sensitive processing) — full vocabulary

Conditions for sensitive processing by a competent authority under DPA 2018 Part 3 (s35(5)). Sensitive processing requires **both** a Schedule 8 condition **and** an s42 Appropriate Policy Document. Verify against the latest revised legislation for DUAA amendments.

| Para | Condition |
|------|-----------|
| 1 | Statutory etc purposes (function conferred by law + substantial public interest) |
| 2 | Administration of justice |
| 3 | Protecting individual's vital interests |
| 4 | **Safeguarding of children and of individuals at risk** |
| 5 | Personal data already in the public domain (manifestly made public) |
| 6 | Legal claims |
| 7 | Judicial acts |
| 8 | Preventing fraud |
| 9 | Archiving etc (archiving in the public interest / research / statistics) |

*(Applicable only if the FRS operates any activities under the law-enforcement regime — Plan §1.6; otherwise this vocabulary stays dormant.)*

### 7.6 Transfer Mechanism
`adequacy` · `idta` (International Data Transfer Agreement) · `addendum` (UK Addendum to EU SCCs) · `bcr` (Binding Corporate Rules) · `art49_exception`.

### 7.7 External Data Source — `special_category` flag
`none` · `inferred` (e.g. Acorn geodemographic) · `direct` (e.g. Adult Care, NHS).

### 7.8 Supplier role
`processor` · `separate_controller`.

### 7.9–7.14 FRS pack seeds (full)

**7.9 Legal Entity role types:** own_org · joint_controller · representative · dpo · processor · sub_processor · data_supplier · partner_agency.

**7.10 Business Function:** Response / Operations · Prevention & Community Safety · Protection (Fire Safety Regulation & Enforcement) · Fire Investigation · Youth & Early Intervention · Emergency Medical Response · Control / Mobilising · Corporate Services · HR · Occupational Health · Finance & Procurement · Legal & Governance · ICT · Communications & Engagement · Data & Performance · Estates & Fleet.

**7.11 Data Subject Category:** members of the public · casualties / persons involved in incidents · vulnerable persons (HFSV / Safe & Well) · responsible persons / duty holders (fire safety) · business owners & occupiers · employees (current) · former employees · applicants / prospective employees · on-call / retained firefighters · volunteers · cadets & young people · parents / guardians · partner-agency staff · emergency-service contacts · complainants · FOI / SAR requesters · contractors & suppliers · witnesses · next of kin / emergency contacts.

**7.12 Personal Data Category** *(is_special_category / is_criminal_offence)*:
- contact details (N/N) · identifiers, e.g. reference numbers (N/N) · household & premises data (N/N) · employment / HR data (N/N) · financial data (N/N) · CCTV / imagery (N/N — may reveal special category) · location / telemetry (N/N)
- health data — casualty, OH, EMR (**Special**/N) · safeguarding concerns (**Special**/N) · racial or ethnic origin — PSED (**Special**/N) · religious or philosophical beliefs — PSED (**Special**/N) · sexual orientation — PSED (**Special**/N) · biometric data (**Special**/N) · genetic data (**Special**/N) · trade union membership (**Special**/N)
- criminal offence data — fire investigation / arson, employee vetting / DBS (N/**Criminal**).

**7.13 Recipient:** police · ambulance / NHS trusts · local authorities · adult social care · children's social care · other fire & rescue services · coroner · courts & tribunals · ICO (Information Commission) · Home Office / central government · National Fire Chiefs Council · insurers · IT / cloud processors · auditors · legal advisors · utility companies · contractors.

**7.14 Security Measure** *(technical / organisational)*: encryption at rest (T) · encryption in transit (T) · role-based access control (T) · multi-factor authentication (T) · mobile device management (T) · appliance / MDT controls (T) · pseudonymisation (T) · network firewalls (T) · anti-malware (T) · audit logging (T) · backup & recovery (T) · vulnerability & patch management (T) · secure disposal (T/O) · physical security & access (O) · staff training & awareness (O) · clear desk / clear screen (O) · access reviews (O) · supplier due diligence (O).

---

## 8. Validation rules (Plan §4, rules 1–17) — expressed against fields

Notation: **Trigger** (field condition) → **Requirement** (blocking unless stated). *[profile]* = applicability keyed to `Organisation Profile` (§2.1).

| # | Trigger | Requirement | Applies |
|---|---------|-------------|---------|
| 1 | any linked Personal Data Category `is_special_category = true` | require `Lawful Basis Record.art9_condition` (general) or LE sensitive route; set `special_category_flag` | all |
| 2 | chosen Art 9 condition `needs_schedule1 = true` | require a `schedule1_condition`; require `apd_id` **only when that Schedule 1 condition `needs_apd = true`** (§7.4) — so (b)/(g) conditions need an APD, but (h)/(i)/(j) do not | all |
| 3 | any linked Personal Data Category `is_criminal_offence = true` | require `art10_basis` (official authority or Sch 1) | general regime |
| 4 | `regime = general` AND activity is a statutory task | default `art6_basis = e`; **flag** `f`/`ea` for DPO review (warn, not block) | *[profile: public_authority]* |
| 5 | `art6_basis = f` or `ea` | `f`: require LIA/RLI Record with `balancing_test`; `ea`: require LIA/RLI Record with `rli_condition` set (Annex 1 interest) — **Revised 2026-11-04** | all |
| 6 | `art6_basis = a` | require Consent Record; if `children_flag` → require `age_check_outcome` + (`parental_consent_captured` when under-13) | all |
| 7 | `vulnerable_or_safeguarding_flag` OR `children_flag` | require DPIA screening; prompt extra safeguards; steer Art 9 → `g` + Sch 1 para 18 + APD | all |
| 8 | `external_data_use_mode ≠ none` | require ≥1 `activity_datasource` + Art 14 privacy-notice ref; if `automated` → require Decision-support/ADM Record + Art 22A–22D assessment (`solely_automated`,`significant_effects`); stricter path where it decides | *[module: external_data]* |
| 9 | linked External Data Source `special_category ∈ {inferred, direct}` | set Art 9 position; require DPIA screening (even if no special-category field collected directly) | *[module: external_data]* |
| 10 | `activity_type = analytics_modelling` | require ≥1 `activity_feeds` to an operational activity + DPIA; if automated & materially affects individuals → set `lineage_granularity = record` + require record-level provenance | all |
| 11 | a Transfer exists | require `mechanism_id` + safeguard; for appropriate-safeguards transfers require `data_protection_test` (s85) | all |
| 12 | `regime` from Regime Policy unless `regime_source = manual_override` (+reason) | if `law_enforcement` → s61 set + `s35_basis` + Sch 8 + s42 APD where sensitive + flag s62 systems; if `general` → Art 6/10 + Sch 1 set; retain inactive mapping; **audit every regime change** | all |
| 13 | `controller_or_processor = processor` | switch to Art 30(2); require `categories_of_processing` + ≥1 controller Legal Entity; if `joint` → require Art 26 arrangement | all |
| 14 | `lifecycle_stage = trial` | require DPIA + `trial_end`; block `→ live` without approver_dpo sign-off; alert near `trial_end` | all |
| 15 | always | security inherits from linked System/Asset (`activity_security.inherited_from_system`); retention set via `activity_retention` with system default overridable | all |
| 16 | always | require `owner_id` + `next_review_at`; surface overdue | all |
| 17 | always | maintain change history + prior versions on every record | all |

---

## 9. Worked example — HFSV risk model feeding operational targeting

Two linked activities demonstrating the external-data → modelling → lineage → operational chain (Plan §3.6).

### 9.1 Activity A — analytics/modelling
```json
{
  "name": "HFSV Household Risk Model",
  "business_function_id": "bf_prevention",
  "activity_type": "analytics_modelling",
  "regime": "general",
  "regime_source": "policy",
  "controller_or_processor": "controller",
  "record_status": "active",
  "lifecycle_stage": "live",
  "purpose": "Score households by fire risk to prioritise Home Fire Safety Visits.",
  "personal_data_source": ["from_third_party", "public_source"],
  "external_data_use_mode": "automated",
  "lineage_granularity": "record",
  "vulnerable_or_safeguarding_flag": true,
  "high_risk_flag": true,
  "owner_id": "user_prevention_lead",
  "next_review_at": "2026-12-01",

  "activity_datasource": ["eds_acorn", "eds_adultcare"],
  "activity_feeds": ["act_hfsv_operational"],
  "lawful_basis_record": {
    "regime_scope": "part2",
    "art6_basis": "e",
    "art6_justification": "Statutory community fire safety function (FRSA 2004 s6).",
    "art9_condition": "g",
    "schedule1_condition": "para_18_safeguarding",
    "apd_id": "apd_safeguarding"
  },
  "decision_support_adm_record": {
    "use_mode": "automated",
    "solely_automated": false,
    "significant_effects": false,
    "technique": "Weighted risk score combining incident history, Acorn segmentation and Adult Care flags.",
    "human_review": "Prevention officer reviews and schedules; model only prioritises.",
    "accuracy_bias_checks": "Quarterly review against actual incident outcomes."
  },
  "dpia": { "screening_outcome": "required", "residual_risk": "medium" }
}
```

Linked **External Data Source** `eds_acorn`:
```json
{ "name": "CACI Acorn", "supplier_role": "separate_controller",
  "special_category": "inferred", "agreement_ref": "CACI-2026-01",
  "art14_relationship": "Geodemographic data not collected from the individual." }
```

Rules fired: 1, 2, 7, 8 (automated), 9 (inferred), 10 (modelling + record lineage), 16, 17.

### 9.2 Activity B — operational (fed by A)
```json
{
  "name": "Home Fire Safety Visits (delivery)",
  "business_function_id": "bf_prevention",
  "activity_type": "operational",
  "regime": "general",
  "controller_or_processor": "controller",
  "record_status": "active",
  "lifecycle_stage": "live",
  "purpose": "Deliver home fire safety visits to prioritised and self-referred households.",
  "personal_data_source": ["from_data_subject", "from_third_party"],
  "external_data_use_mode": "none",
  "vulnerable_or_safeguarding_flag": true,
  "children_flag": false,
  "owner_id": "user_prevention_lead",
  "next_review_at": "2026-12-01",
  "lawful_basis_record": {
    "regime_scope": "part2",
    "art6_basis": "e",
    "art6_justification": "Statutory community fire safety function (FRSA 2004 s6).",
    "art9_condition": "g",
    "schedule1_condition": "para_18_safeguarding",
    "apd_id": "apd_safeguarding"
  }
}
```
`act_hfsv_operational` is the `activity_feeds` target of Activity A — so lineage from Acorn/Adult Care through the model to the operational visit is traceable (rule 10).

### 9.3 Activity C — processor (FRS acting for another controller)

The FRS operates its control room / mobilising service for a neighbouring fire authority under a shared-service arrangement. Here the FRS is a **processor**: it records categories of processing per controller and does **not** set the lawful basis (that is the controller's). Demonstrates rule 13 and the Art 30(2) field set.

```json
{
  "name": "Regional Control & Mobilising Service (for Neighbouring Fire Authority)",
  "business_function_id": "bf_control_mobilising",
  "activity_type": "operational",
  "regime": "general",
  "controller_or_processor": "processor",
  "record_status": "active",
  "lifecycle_stage": "live",
  "purpose": "Receive emergency calls and mobilise resources on behalf of the controlling authority.",
  "categories_of_processing": "Call handling, incident logging, resource mobilising and retention carried out on the controller's documented instructions.",
  "personal_data_source": ["from_data_subject", "from_third_party"],
  "owner_id": "user_control_manager",
  "next_review_at": "2026-11-01",

  "controllers": ["le_neighbour_fra"],
  "activity_contract": ["contract_control_art28"],
  "activity_security": ["sec_encryption_transit", "sec_rbac", "sec_audit_logging"]
}
```

Note the deliberate **absence of a Lawful Basis Record** — set by the controller, not the processor. Linked Art 28 contract:
```json
{ "type": "controller_processor", "parties": ["le_neighbour_fra", "le_own_org"],
  "art28_checklist_complete": true, "start_date": "2026-04-01", "review_date": "2027-04-01" }
```
Rules fired: 13 (processor → Art 30(2) set + `categories_of_processing` + ≥1 controller Legal Entity), 15, 16, 17.

### 9.4 Activity D — law-enforcement regime (s61)

Fire-safety enforcement, where the Regime Policy classifies `fire_safety_enforcement = law_enforcement` (Plan §1.6a). This switches the record to the s61 field set and the s35 / Schedule 8 / s42-APD lawful-basis path.

```json
{
  "name": "Fire Safety Enforcement & Prosecution",
  "business_function_id": "bf_protection",
  "activity_type": "operational",
  "regime": "law_enforcement",
  "regime_source": "policy",
  "controller_or_processor": "controller",
  "record_status": "active",
  "lifecycle_stage": "live",
  "purpose": "Investigate and prosecute breaches of the Regulatory Reform (Fire Safety) Order 2005.",
  "personal_data_source": ["from_data_subject", "from_third_party"],
  "le_data_subject_classification": ["suspect", "witness", "other"],
  "le_fact_vs_assessment_noted": true,
  "s62_logging_note": "Enforcement case-management system — s62 logs (collection/consultation/disclosure) held in the system audit trail.",
  "criminal_offence_flag": true,
  "owner_id": "user_protection_lead",
  "next_review_at": "2026-10-01",

  "lawful_basis_record": {
    "regime_scope": "part3",
    "s35_basis": "s35_task",
    "schedule8_condition": "sch8_1_statutory",
    "apd_id": "apd_s42_enforcement"
  },
  "dpia": { "screening_outcome": "required", "residual_risk": "medium" }
}
```

Rules fired: 12 (regime routing → s61 set + `s35_basis` + Sch 8 + s42 APD + flag s62 systems), 16, 17, plus DPIA. Note the general-regime rules 3 (Art 10) and 4 (public-authority guard) do **not** apply here — the LE regime uses s35, not Art 6/9/10.

**Configurable-boundary illustration (Plan §1.6a):** if the Regime Policy for this domain were flipped to `part2`, the *same* activity would instead require the general set — `art6_basis = e` (public task), `art10_basis` (criminal offence), a Schedule 1 condition (e.g. para 10, preventing/detecting unlawful acts) and an APD — with the s35/Sch 8 mapping retained but dormant. This is the "dual mapping, one active" behaviour — in field terms, each mapping is its own Lawful Basis Record distinguished by `regime_scope` (§6.1).

---

## 10. Export mappings (Plan §6.2)

Exports are a mapping layer over the canonical model, not a storage shape. The active regime and `controller_or_processor` select which view(s) an activity appears in.

### 10.1 Art 30(1) — controller view

| Art 30(1) column | Source |
|------------------|--------|
| Controller / joint controllers / representative / DPO details | Organisation Profile + Legal Entity (roles own_org, joint_controller, representative, dpo) |
| Purposes | `Processing Activity.purpose` |
| Categories of individuals | `activity_datasubject` → Data Subject Category |
| Categories of personal data | `activity_datacategory` → Personal Data Category |
| Categories of recipients | `activity_recipient` → Recipient |
| Third-country transfers + safeguards | Transfer (+ `mechanism_id`, `data_protection_test`) |
| Retention | `activity_retention` → Retention Rule |
| Security measures | `activity_security` → Security Measure (+ inherited from System/Asset) |

*Filter: `regime = general` AND `controller_or_processor ∈ {controller, joint}`.*

### 10.2 Art 30(2) — processor view

| Art 30(2) column | Source |
|------------------|--------|
| Processor name & contact / DPO | Organisation Profile + Legal Entity (dpo) |
| Each controller acted for (+ representative) | `controllers` link → Legal Entity (roles: controller, representative) |
| Categories of processing per controller | `Processing Activity.categories_of_processing`, grouped by controller |
| Third-country transfers + safeguards | Transfer (+ `mechanism_id`, `data_protection_test`) |
| Security measures | `activity_security` → Security Measure |

*Filter: `controller_or_processor = processor`. No lawful-basis columns — set by the controller.*

### 10.3 s61 — law-enforcement view

| s61 record element | Source |
|--------------------|--------|
| Controller / joint controllers / DPO contact | Organisation Profile + Legal Entity |
| Purposes | `Processing Activity.purpose` |
| Categories of recipients | `activity_recipient` → Recipient |
| Categories of data subjects (+ LE classification) | `activity_datasubject` + `le_data_subject_classification` |
| Categories of personal data | `activity_datacategory` |
| Use of profiling (where applicable) | Decision-support / ADM Record |
| Transfers to third countries | Transfer |
| General indication of legal basis | Lawful Basis Record (`s35_basis`, + Schedule 8 where sensitive) |
| Retention time limits (where possible) | `activity_retention` → Retention Rule |
| General description of security measures | `activity_security` → Security Measure |
| Systems in scope for s62 logging | `activity_system` where `s62_logging_in_scope` (+ `s62_logging_note`) |

*Filter: `regime = law_enforcement`. Generated only when the Organisation Profile has `law_enforcement` in `applicable_regimes`.*

A combined internal register exports all activities across every view for day-to-day management (Plan §1.5).

---

## 11. Open items carried from the plan

- **FRS pack content** — **done in this version**: the full Schedule 1 (§7.4) and Schedule 8 (§7.5) vocabularies and the FRS seed lists (§7.9–7.14) are now complete. Remaining for build 1a: load them as data and confirm the FRS-priority defaults.
- **Record vs authoring state** — **confirmed**. The `record_status` (draft/in_review/active/retired, the authoring/approval state) and `lifecycle_stage` (trial/live/retired, the processing's maturity) split defined in §3 is the agreed model, resolving the plan's overlapping single `status` field.
- **APD determination** — **[spec clarification]** the appropriate-policy-document requirement is read from the chosen **Schedule 1 condition** (§7.4), not the Art 9 point; (h)/(i)/(j) need a Schedule 1 condition but no APD. Rule 2 and §7.3 reflect this.
- **DUAA commencement watch** — **Revised 2026-11-04:** all the DUAA data-protection provisions Cairn tracks (principal provisions 5 Feb 2026, complaints duty 19 Jun 2026, and the Part 6 transfer of the regulator's functions to the Information Commission on 30 Sep 2026 by SI 2026/1015) are now in force; the `information_commission` watch key is merged into the dashboard from the statutory defaults. The remaining watch is the final ADM/AI statutory code and Information Commission guidance (Plan §1.4). Verify the Schedule 1/8 vocabularies against the latest *revised* legislation for any DUAA amendments before seeding.
- **Phase 1.7 spike outcomes** — **applied in v0.4**: the spike (`spike-findings.md`) validated the dual mapping and the profile-conditioned rule engine, and this version adopts its two clarifications — the `regime_scope` discriminator on the Lawful Basis Record (§6.1) and the unified `general`/`law_enforcement` regime enum on the Regime Policy (§2.2). Carried forward for the build: version capture must be enforced at the persistence layer (rule 17 is "always", not caller-optional).

---

*Derived from Plan v0.12 (`ROPA-tool-plan.md`). This spec is v0.4 and will iterate alongside it.*
