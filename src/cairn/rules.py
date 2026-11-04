from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum

from cairn.models import (
    ActivityType,
    AgeCheckOutcome,
    AssetStatus,
    ContractType,
    ControllerOrProcessor,
    EntryStatus,
    ExternalDataUseMode,
    InformationAsset,
    LifecycleStage,
    LineageGranularity,
    OrganisationProfile,
    OrgType,
    ProcessingActivity,
    Regime,
    RegimeScope,
    SourceSpecialCategory,
)
from cairn.regime import active_basis


class Severity(StrEnum):
    BLOCK = "block"
    WARN = "warn"


@dataclass(frozen=True)
class Applicability:
    org_type: OrgType | None = None
    required_module: str | None = None
    requires_guard: bool = False
    regime: Regime | None = None

    def applies(self, activity: ProcessingActivity, profile: OrganisationProfile) -> bool:
        if self.org_type is not None and profile.org_type != self.org_type:
            return False
        if self.required_module is not None and self.required_module not in profile.active_modules:
            return False
        if self.requires_guard and not profile.public_authority_guards:
            return False
        if self.regime is not None and activity.regime != self.regime:
            return False
        return True


@dataclass(frozen=True)
class Rule:
    id: str
    description: str
    severity: Severity
    trigger: str
    requirement: str
    applicability: Applicability = field(default_factory=Applicability)


@dataclass(frozen=True)
class Finding:
    rule_id: str
    severity: Severity
    message: str


def _active_basis_needs_schedule1(activity: ProcessingActivity) -> bool:
    basis = active_basis(activity)
    return (
        basis is not None
        and basis.art9_condition is not None
        and basis.art9_condition.needs_schedule1
    )


def _active_basis_art6_f(activity: ProcessingActivity) -> bool:
    basis = active_basis(activity)
    return (
        basis is not None
        and basis.regime_scope == RegimeScope.PART2
        and basis.art6_basis is not None
        and basis.art6_basis.code in ("f", "ea")
    )


def _active_basis_art6_a(activity: ProcessingActivity) -> bool:
    basis = active_basis(activity)
    return (
        basis is not None
        and basis.regime_scope == RegimeScope.PART2
        and basis.art6_basis is not None
        and basis.art6_basis.code == "a"
    )


def _not_controller(activity: ProcessingActivity) -> bool:
    return activity.controller_or_processor != ControllerOrProcessor.CONTROLLER


def _external_data_source_special_category(activity: ProcessingActivity) -> bool:
    return any(
        source.special_category
        in (SourceSpecialCategory.INFERRED, SourceSpecialCategory.DIRECT)
        for source in activity.data_sources
    )


def _adm_solely_automated_significant(activity: ProcessingActivity) -> bool:
    return any(r.solely_automated and r.significant_effects for r in activity.adm_records)


TRIGGERS: dict[str, Callable[[ProcessingActivity], bool]] = {
    "always": lambda a: True,
    "has_special_category_data": lambda a: a.special_category_flag,
    "has_criminal_offence_data": lambda a: a.criminal_offence_flag,
    "is_statutory_task": lambda a: a.is_statutory_task,
    "uses_external_data": lambda a: a.external_data_use_mode != ExternalDataUseMode.NONE,
    "active_basis_needs_schedule1": _active_basis_needs_schedule1,
    "active_basis_art6_f": _active_basis_art6_f,
    "active_basis_art6_a": _active_basis_art6_a,
    "not_controller": _not_controller,
    "vulnerable_or_children": lambda a: a.vulnerable_or_safeguarding_flag or a.children_flag,
    "external_data_source_special_category": _external_data_source_special_category,
    "is_analytics_modelling": lambda a: a.activity_type == ActivityType.ANALYTICS_MODELLING,
    "has_transfers": lambda a: bool(a.transfers),
    "is_trial": lambda a: a.lifecycle_stage == LifecycleStage.TRIAL,
    "adm_solely_automated_significant": _adm_solely_automated_significant,
    "online_childrens_service": lambda a: a.online_childrens_service_flag,
    "is_further_processing": lambda a: a.is_further_processing,
    "has_data_categories": lambda a: bool(a.data_category_links),
}


def _sensitive_condition(activity: ProcessingActivity) -> str | None:
    basis = active_basis(activity)
    if activity.regime == Regime.GENERAL:
        if basis is None or not basis.art9_condition_id:
            return "Special-category data requires an Art 9 condition on the active basis record"
        return None
    if basis is None or not basis.schedule8_condition_id or not basis.apd_id:
        return "LE sensitive processing requires a Schedule 8 condition and an s42 APD reference"
    return None


def _art10_present(activity: ProcessingActivity) -> str | None:
    basis = active_basis(activity)
    if basis is None or not basis.art10_basis:
        return "Criminal-offence data requires an Art 10 basis (official authority or Schedule 1)"
    return None


def _flag_f_ea(activity: ProcessingActivity) -> str | None:
    basis = active_basis(activity)
    if basis is not None and basis.art6_basis is not None and basis.art6_basis.code in ("f", "ea"):
        return (
            f"Basis ({basis.art6_basis.code}) on a statutory task — public task (e) is the "
            "natural basis; flag for DPO review"
        )
    return None


def _external_data_requirements(activity: ProcessingActivity) -> str | None:
    if not activity.data_sources:
        return "External data use requires at least one linked External Data Source"
    if not any(notice.covers_art14 for notice in activity.privacy_notices):
        return "External data requires a linked privacy notice covering Art 14"
    if (
        activity.external_data_use_mode == ExternalDataUseMode.AUTOMATED
        and not activity.adm_records
    ):
        return "Automated external-data use requires a Decision-support/ADM record"
    return None


def _active_regime_basis(activity: ProcessingActivity) -> str | None:
    if activity.controller_or_processor == ControllerOrProcessor.PROCESSOR:
        return None
    basis = active_basis(activity)
    if activity.regime == Regime.LAW_ENFORCEMENT:
        if basis is None or not basis.s35_basis_id:
            return "Law-enforcement regime requires an s35 basis on the active (Part 3) record"
        return None
    if basis is None or not basis.art6_basis_id:
        return "General regime requires an Art 6 basis on the active (Part 2) record"
    return None


def _schedule1_and_apd_present(activity: ProcessingActivity) -> str | None:
    basis = active_basis(activity)
    if basis.schedule1_condition is None:
        return "Special-category data on this Art 9 condition requires a Schedule 1 condition"
    if basis.schedule1_condition.needs_apd and basis.apd_id is None:
        return "This Schedule 1 condition requires an Appropriate Policy Document (APD)"
    return None


def _lia_balancing_test_present(activity: ProcessingActivity) -> str | None:
    basis = active_basis(activity)
    if basis.art6_basis.code == "ea":
        if not any(r.rli_condition for r in basis.lia_rli_records):
            return (
                "Art 6(ea) recognised legitimate interest requires an LIA/RLI record "
                "identifying the Annex 1 recognised interest relied on"
            )
        return None
    if not any(r.balancing_test for r in basis.lia_rli_records):
        return (
            "Art 6(f) legitimate interests requires an LIA/RLI record with a completed "
            "balancing test"
        )
    return None


def _consent_requirements_met(activity: ProcessingActivity) -> str | None:
    basis = active_basis(activity)
    if not basis.consent_records:
        return "Art 6(a) consent requires at least one linked Consent record"
    if not activity.children_flag:
        return None
    for consent in basis.consent_records:
        if consent.age_check_outcome is None:
            return "Children's data requires an age-check outcome on each consent record"
        if (
            consent.age_check_outcome == AgeCheckOutcome.CHILD_UNDER_13
            and not consent.parental_consent_captured
        ):
            return "Under-13 consent requires parental consent to be captured"
    return None


def _processor_or_joint_arrangement_present(activity: ProcessingActivity) -> str | None:
    if activity.controller_or_processor == ControllerOrProcessor.PROCESSOR:
        if not activity.categories_of_processing:
            return "Processor activities require categories_of_processing to be documented"
        if not activity.controllers:
            return "Processor activities require at least one linked controller (Legal Entity)"
        return None
    if not any(c.type == ContractType.JOINT_CONTROLLER for c in activity.contracts):
        return "Joint controller arrangements require a linked Art 26 joint-controller contract"
    return None


def _dpia_screening_present(activity: ProcessingActivity) -> str | None:
    if not activity.dpias:
        return "Safeguarding/children processing requires DPIA screening"
    return None


def _external_data_dpia_present(activity: ProcessingActivity) -> str | None:
    if not activity.dpias:
        return "External data that is or infers special-category data requires DPIA screening"
    return None


def _analytics_modelling_requirements(activity: ProcessingActivity) -> str | None:
    if not activity.feeds:
        return "Analytics/modelling activities must feed at least one operational activity"
    if not activity.dpias:
        return "Analytics/modelling activities require a DPIA"
    if activity.external_data_use_mode == ExternalDataUseMode.AUTOMATED and any(
        record.significant_effects for record in activity.adm_records
    ):
        if activity.lineage_granularity != LineageGranularity.RECORD:
            return "Automated modelling with significant effects requires record-level lineage"
    return None


APPROPRIATE_SAFEGUARDS_MECHANISMS = {"idta", "addendum", "bcr"}


def _transfer_safeguards_test_present(activity: ProcessingActivity) -> str | None:
    for transfer in activity.transfers:
        if (
            transfer.mechanism is not None
            and transfer.mechanism.code in APPROPRIATE_SAFEGUARDS_MECHANISMS
            and not transfer.data_protection_test
        ):
            return (
                "Appropriate-safeguards transfers require the s85 'not materially lower' "
                "data protection test"
            )
    return None


def _trial_requirements(activity: ProcessingActivity) -> str | None:
    if activity.trial_end is None or not activity.dpias:
        return "Trial activities require a DPIA and a trial end date"
    return None


def _no_unapproved_references(activity: ProcessingActivity) -> str | None:
    entries = [
        *activity.data_subjects,
        *activity.recipients,
        *activity.assets,
        *activity.data_sources,
        *(link.category for link in activity.data_category_links),
        *(link.rule for link in activity.retention_links),
        *(link.measure for link in activity.security_links),
    ]
    labels = {
        getattr(entry, "label", None) or getattr(entry, "name", None) or str(entry.id)
        for entry in entries
        if getattr(entry, "entry_status", None) in (EntryStatus.PROPOSED, EntryStatus.REJECTED)
    }
    if labels:
        return f"References vocabulary entries that are not approved: {', '.join(sorted(labels))}"
    return None


def _adm_art22_safeguards(activity: ProcessingActivity) -> str | None:
    for record in activity.adm_records:
        if not (record.solely_automated and record.significant_effects):
            continue
        if not (record.human_review and record.contestability and record.accuracy_bias_checks):
            return (
                "Solely-automated decisions with significant effects require the Art 22C "
                "safeguards: human review, contestability, and accuracy/bias checks"
            )
        if activity.special_category_flag:
            basis = active_basis(activity)
            if (
                basis is None
                or basis.art9_condition is None
                or basis.art9_condition.code not in ("a", "g")
            ):
                return (
                    "Art 22B: solely-automated significant decisions using special-category "
                    "data are only permitted with explicit consent (Art 9(2)(a)) or "
                    "substantial public interest (Art 9(2)(g)) on the active basis record"
                )
    return None


def _childrens_service_protections(activity: ProcessingActivity) -> str | None:
    if not activity.children_flag:
        return (
            "Online children's-service flag is set but 'Involves children' is not — "
            "review the flags for consistency"
        )
    if not activity.childrens_matters_note:
        return (
            "Record the 'likely to be accessed' assessment and how children's "
            "higher-protection matters were taken into account (Art 25(1), DUAA s81)"
        )
    if not activity.dpias:
        return (
            "An online service likely to be accessed by children requires DPIA screening "
            "(children's higher-protection duty)"
        )
    return None


def _further_processing_note_present(activity: ProcessingActivity) -> str | None:
    if not activity.further_processing_note:
        return (
            "Further processing requires a recorded compatibility assessment "
            "(purpose-limitation)"
        )
    return None


def _asset_linked_present(activity: ProcessingActivity) -> str | None:
    if not activity.assets:
        return "Documented processing should name the information asset(s) where the data lives"
    return None


REQUIREMENTS: dict[str, Callable[[ProcessingActivity], str | None]] = {
    "active_sensitive_condition": _sensitive_condition,
    "art10_basis_present": _art10_present,
    "flag_f_ea_for_dpo": _flag_f_ea,
    "external_data_requirements": _external_data_requirements,
    "active_regime_basis_set": _active_regime_basis,
    "schedule1_and_apd_present": _schedule1_and_apd_present,
    "lia_balancing_test_present": _lia_balancing_test_present,
    "consent_requirements_met": _consent_requirements_met,
    "processor_or_joint_arrangement_present": _processor_or_joint_arrangement_present,
    "dpia_screening_present": _dpia_screening_present,
    "external_data_dpia_present": _external_data_dpia_present,
    "analytics_modelling_requirements": _analytics_modelling_requirements,
    "transfer_safeguards_test_present": _transfer_safeguards_test_present,
    "trial_requirements": _trial_requirements,
    "no_unapproved_references": _no_unapproved_references,
    "adm_art22_safeguards": _adm_art22_safeguards,
    "childrens_service_protections": _childrens_service_protections,
    "further_processing_note_present": _further_processing_note_present,
    "asset_linked_present": _asset_linked_present,
}


RULES: list[Rule] = [
    Rule(
        id="1",
        description="Special-category data needs an Art 9 condition (general) or Sch 8 route (LE)",
        severity=Severity.BLOCK,
        trigger="has_special_category_data",
        requirement="active_sensitive_condition",
    ),
    Rule(
        id="2",
        description="Art 9 condition needing Schedule 1 must cite one, with APD where required",
        severity=Severity.BLOCK,
        trigger="active_basis_needs_schedule1",
        requirement="schedule1_and_apd_present",
    ),
    Rule(
        id="3",
        description="Criminal-offence data needs an Art 10 basis (general regime only)",
        severity=Severity.BLOCK,
        trigger="has_criminal_offence_data",
        requirement="art10_basis_present",
        applicability=Applicability(regime=Regime.GENERAL),
    ),
    Rule(
        id="4",
        description="Public-authority guard: flag (f)/(ea) on statutory tasks for DPO review",
        severity=Severity.WARN,
        trigger="is_statutory_task",
        requirement="flag_f_ea_for_dpo",
        applicability=Applicability(
            org_type=OrgType.PUBLIC_AUTHORITY, requires_guard=True, regime=Regime.GENERAL
        ),
    ),
    Rule(
        id="5",
        description="Art 6(f) legitimate interests needs a completed LIA/RLI balancing test; "
        "Art 6(ea) recognised legitimate interest needs the Annex 1 condition recorded",
        severity=Severity.BLOCK,
        trigger="active_basis_art6_f",
        requirement="lia_balancing_test_present",
    ),
    Rule(
        id="6",
        description="Art 6(a) consent needs a Consent record, plus age checks for children",
        severity=Severity.BLOCK,
        trigger="active_basis_art6_a",
        requirement="consent_requirements_met",
    ),
    Rule(
        id="7",
        description="Safeguarding/children processing needs DPIA screening",
        severity=Severity.BLOCK,
        trigger="vulnerable_or_children",
        requirement="dpia_screening_present",
    ),
    Rule(
        id="8",
        description="External data use requires sources, an Art 14 notice, and an ADM record "
        "when automated",
        severity=Severity.BLOCK,
        trigger="uses_external_data",
        requirement="external_data_requirements",
        applicability=Applicability(required_module="external_data"),
    ),
    Rule(
        id="9",
        description="External data that is or infers special-category data needs DPIA screening",
        severity=Severity.BLOCK,
        trigger="external_data_source_special_category",
        requirement="external_data_dpia_present",
        applicability=Applicability(required_module="external_data"),
    ),
    Rule(
        id="10",
        description="Analytics/modelling activities need a feeds link, a DPIA, and record "
        "lineage when automated with significant effects",
        severity=Severity.BLOCK,
        trigger="is_analytics_modelling",
        requirement="analytics_modelling_requirements",
    ),
    Rule(
        id="11",
        description="Appropriate-safeguards transfers need the s85 data protection test",
        severity=Severity.BLOCK,
        trigger="has_transfers",
        requirement="transfer_safeguards_test_present",
    ),
    Rule(
        id="12",
        description="The active regime selects the required lawful-basis set",
        severity=Severity.BLOCK,
        trigger="always",
        requirement="active_regime_basis_set",
    ),
    Rule(
        id="13",
        description="Processor/joint activities need the Art 26/28 links (controller, arrangement)",
        severity=Severity.BLOCK,
        trigger="not_controller",
        requirement="processor_or_joint_arrangement_present",
    ),
    Rule(
        id="14",
        description="Trial activities need a DPIA and a trial end date",
        severity=Severity.BLOCK,
        trigger="is_trial",
        requirement="trial_requirements",
    ),
    Rule(
        id="18",
        description="Activities must not reference unapproved vocabulary entries",
        severity=Severity.BLOCK,
        trigger="always",
        requirement="no_unapproved_references",
    ),
    Rule(
        id="19",
        description="Solely-automated significant decisions need Art 22B/22C conditions and "
        "safeguards",
        severity=Severity.BLOCK,
        trigger="adm_solely_automated_significant",
        requirement="adm_art22_safeguards",
        applicability=Applicability(regime=Regime.GENERAL),
    ),
    Rule(
        id="20",
        description="Online children's services must evidence the higher-protection matters "
        "(spec clarification pending final Information Commission guidance)",
        severity=Severity.WARN,
        trigger="online_childrens_service",
        requirement="childrens_service_protections",
    ),
    Rule(
        id="21",
        description="Further processing needs a compatibility assessment "
        "(spec clarification pending final Information Commission guidance)",
        severity=Severity.WARN,
        trigger="is_further_processing",
        requirement="further_processing_note_present",
    ),
    Rule(
        id="23",
        description="Documented processing should name the information asset(s) where the "
        "data lives",
        severity=Severity.WARN,
        trigger="has_data_categories",
        requirement="asset_linked_present",
    ),
]


def _asset_unapproved_references(asset: InformationAsset) -> str | None:
    entries = [asset.supplier, *asset.security_measures]
    labels = {
        getattr(entry, "label", None) or str(entry.id)
        for entry in entries
        if entry is not None
        and getattr(entry, "entry_status", None) in (EntryStatus.PROPOSED, EntryStatus.REJECTED)
    }
    if labels:
        return f"References vocabulary entries that are not approved: {', '.join(sorted(labels))}"
    return None


def _asset_undocumented(asset: InformationAsset, linked_activity_count: int) -> str | None:
    if asset.entry_status != EntryStatus.APPROVED:
        return None
    if not asset.contains_personal_data:
        return None
    if asset.status == AssetStatus.DISPOSED:
        return None
    if linked_activity_count > 0:
        return None
    return (
        "This asset holds personal data but is not linked to any processing activity — "
        "possible undocumented processing"
    )


def evaluate_asset(asset: InformationAsset, linked_activity_count: int) -> list[Finding]:
    findings = []
    message = _asset_undocumented(asset, linked_activity_count)
    if message is not None:
        findings.append(Finding(rule_id="22", severity=Severity.WARN, message=message))
    message = _asset_unapproved_references(asset)
    if message is not None:
        findings.append(Finding(rule_id="24", severity=Severity.BLOCK, message=message))
    return findings


def evaluate(activity: ProcessingActivity, profile: OrganisationProfile) -> list[Finding]:
    findings = []
    for rule in RULES:
        if not rule.applicability.applies(activity, profile):
            continue
        if not TRIGGERS[rule.trigger](activity):
            continue
        message = REQUIREMENTS[rule.requirement](activity)
        if message is not None:
            findings.append(Finding(rule_id=rule.id, severity=rule.severity, message=message))
    return findings
