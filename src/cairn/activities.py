from dataclasses import dataclass
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from cairn.audit import record_event
from cairn.auth import current_user, get_csrf_token, verify_csrf
from cairn.basis import basis_detail_context
from cairn.db import get_session
from cairn.export import export_views
from cairn.inheritance import sync_inherited_security
from cairn.models import (
    ActivityDataCategory,
    ActivityDomain,
    ActivityType,
    AuditEvent,
    BusinessFunction,
    ControllerOrProcessor,
    DataSubjectCategory,
    EntryStatus,
    ExternalDataSource,
    ExternalDataUseMode,
    InformationAsset,
    LEClassification,
    LegalEntity,
    LifecycleStage,
    LineageGranularity,
    OrganisationProfile,
    PersonalDataCategory,
    PersonalDataSource,
    PrivacyNotice,
    ProcessingActivity,
    Recipient,
    RecordStatus,
    RecordVersion,
    Regime,
    RegimeSource,
    Role,
    User,
)
from cairn.regime import override_activity_regime, resolve_regime
from cairn.registers import register_detail_context
from cairn.rules import Severity, evaluate
from cairn.templating import templates

router = APIRouter()

ACTIVITY_TYPE_LABELS = {
    ActivityType.OPERATIONAL: "Operational",
    ActivityType.ANALYTICS_MODELLING: "Analytics / modelling",
}
ACTIVITY_DOMAIN_LABELS = {
    ActivityDomain.FIRE_SAFETY_ENFORCEMENT: "Fire safety enforcement",
    ActivityDomain.FIRE_INVESTIGATION: "Fire investigation",
    ActivityDomain.FIRESETTER_INTERVENTION: "Firesetter intervention",
    ActivityDomain.OTHER: "Other",
}
CONTROLLER_OR_PROCESSOR_LABELS = {
    ControllerOrProcessor.CONTROLLER: "Controller",
    ControllerOrProcessor.PROCESSOR: "Processor",
    ControllerOrProcessor.JOINT: "Joint controller",
}
LIFECYCLE_STAGE_LABELS = {
    LifecycleStage.TRIAL: "Trial",
    LifecycleStage.LIVE: "Live",
    LifecycleStage.RETIRED: "Retired",
}
PERSONAL_DATA_SOURCE_LABELS = {
    PersonalDataSource.FROM_DATA_SUBJECT: "From the data subject",
    PersonalDataSource.FROM_THIRD_PARTY: "From a third party",
    PersonalDataSource.PUBLIC_SOURCE: "Public source",
}
EXTERNAL_DATA_USE_MODE_LABELS = {
    ExternalDataUseMode.NONE: "None",
    ExternalDataUseMode.MANUAL: "Manual",
    ExternalDataUseMode.AUTOMATED: "Automated",
}
LINEAGE_GRANULARITY_LABELS = {
    LineageGranularity.ACTIVITY: "Activity-level",
    LineageGranularity.RECORD: "Record-level",
}
LE_CLASSIFICATION_LABELS = {
    LEClassification.SUSPECT: "Suspect",
    LEClassification.CONVICTED: "Convicted",
    LEClassification.VICTIM: "Victim",
    LEClassification.WITNESS: "Witness",
    LEClassification.OTHER: "Other",
}
RECORD_STATUS_LABELS = {
    RecordStatus.DRAFT: "Draft",
    RecordStatus.IN_REVIEW: "In review",
    RecordStatus.ACTIVE: "Active",
    RecordStatus.RETIRED: "Retired",
}
REGIME_LABELS = {
    Regime.GENERAL: "General (UK GDPR / DPA 2018 Part 2)",
    Regime.LAW_ENFORCEMENT: "Law enforcement (DPA 2018 Part 3)",
}

NEW_ACTIVITY_DEFAULTS = {
    "name": "",
    "reference": "",
    "business_function_id": "",
    "description": "",
    "activity_type": ActivityType.OPERATIONAL.value,
    "activity_domain": "",
    "controller_or_processor": ControllerOrProcessor.CONTROLLER.value,
    "lifecycle_stage": LifecycleStage.LIVE.value,
    "trial_start": "",
    "trial_end": "",
    "purpose": "",
    "categories_of_processing": "",
    "is_further_processing": False,
    "further_processing_note": "",
    "personal_data_source": [],
    "is_statutory_task": False,
    "vulnerable_or_safeguarding_flag": False,
    "children_flag": False,
    "online_childrens_service_flag": False,
    "childrens_matters_note": "",
    "external_data_use_mode": ExternalDataUseMode.NONE.value,
    "lineage_granularity": LineageGranularity.ACTIVITY.value,
    "high_risk_flag": False,
    "owner_id": "",
    "last_reviewed_at": "",
    "next_review_at": "",
    "le_data_subject_classification": [],
    "le_fact_vs_assessment_noted": False,
    "s62_logging_note": "",
}

STATUS_TRANSITIONS = {
    (RecordStatus.DRAFT, RecordStatus.IN_REVIEW),
    (RecordStatus.IN_REVIEW, RecordStatus.DRAFT),
    (RecordStatus.IN_REVIEW, RecordStatus.ACTIVE),
    (RecordStatus.ACTIVE, RecordStatus.RETIRED),
}


@dataclass(frozen=True)
class SimpleJunction:
    attr: str
    model: type
    label: str


SIMPLE_JUNCTIONS: dict[str, SimpleJunction] = {
    "data-subjects": SimpleJunction("data_subjects", DataSubjectCategory, "data subject"),
    "recipients": SimpleJunction("recipients", Recipient, "recipient"),
    "assets": SimpleJunction("assets", InformationAsset, "asset"),
    "data-sources": SimpleJunction("data_sources", ExternalDataSource, "external data source"),
    "controllers": SimpleJunction("controllers", LegalEntity, "controller (legal entity)"),
    "privacy-notices": SimpleJunction("privacy_notices", PrivacyNotice, "privacy notice"),
}

SECTION_TITLES = {
    "data-subjects": "Data subjects",
    "recipients": "Recipients",
    "assets": "Assets",
    "data-sources": "External data sources",
    "controllers": "Controllers",
    "privacy-notices": "Privacy notices",
}

ADD_LABELS = {
    "data-subjects": "Data subject to add",
    "recipients": "Recipient to add",
    "assets": "Asset to link",
    "data-sources": "External data source to add",
    "controllers": "Controller to add",
    "privacy-notices": "Privacy notice to add",
}

JUNCTION_CONTEXT_KEYS = {
    "data-subjects": ("data_subjects", "data_subject_options"),
    "recipients": ("recipients", "recipient_options"),
    "assets": ("assets", "asset_options"),
    "data-sources": ("data_sources", "data_source_options"),
    "controllers": ("controllers", "controller_options"),
    "privacy-notices": ("privacy_notices", "privacy_notice_options"),
}


def _display_label(obj) -> str:
    label = (
        getattr(obj, "label", None)
        or getattr(obj, "name", None)
        or getattr(obj, "notice_version", None)
        or str(obj.id)
    )
    if getattr(obj, "entry_status", None) == EntryStatus.PROPOSED:
        return f"{label} (proposed)"
    return label


def _get_activity(session: Session, activity_id: str) -> ProcessingActivity:
    activity = session.get(ProcessingActivity, activity_id)
    if activity is None:
        raise HTTPException(status_code=404)
    return activity


def _get_profile(session: Session) -> OrganisationProfile:
    profile = session.scalars(select(OrganisationProfile)).first()
    if profile is None:
        raise HTTPException(status_code=404)
    return profile


def _can_edit_activity(user: User, activity: ProcessingActivity) -> bool:
    if user.role in (Role.CURATOR, Role.APPROVER_DPO):
        return True
    if user.role == Role.CONTRIBUTOR:
        return user.business_function_id == activity.business_function_id
    return False


def _require_can_edit(user: User, activity: ProcessingActivity) -> None:
    if not _can_edit_activity(user, activity):
        raise HTTPException(status_code=403, detail="Not permitted to edit this activity")


def _require_can_create(user: User) -> None:
    if user.role not in (Role.CONTRIBUTOR, Role.CURATOR, Role.APPROVER_DPO):
        raise HTTPException(status_code=403, detail="Not permitted to create activities")


def _own_function(user: User, business_function_id: str) -> bool:
    return business_function_id == user.business_function_id


def _business_function_options(session: Session) -> list[tuple[str, str]]:
    functions = session.scalars(select(BusinessFunction).order_by(BusinessFunction.label)).all()
    return [(f.id, f.label) for f in functions]


def _user_options(session: Session) -> list[tuple[str, str]]:
    users = session.scalars(
        select(User).where(User.is_active).order_by(User.display_name)
    ).all()
    return [(u.id, u.display_name) for u in users]


def _available_options(
    session: Session, model: type, linked_ids: set[str]
) -> list[tuple[str, str]]:
    items = session.scalars(select(model)).all()
    return [
        (item.id, _display_label(item))
        for item in items
        if item.id not in linked_ids
        and getattr(item, "entry_status", None) != EntryStatus.REJECTED
    ]


def _parse_activity_form(form) -> dict:
    return {
        "name": form.get("name", "").strip(),
        "reference": form.get("reference", "").strip(),
        "business_function_id": form.get("business_function_id", ""),
        "description": form.get("description", "").strip(),
        "activity_type": form.get("activity_type", ActivityType.OPERATIONAL.value),
        "activity_domain": form.get("activity_domain", ""),
        "controller_or_processor": form.get(
            "controller_or_processor", ControllerOrProcessor.CONTROLLER.value
        ),
        "lifecycle_stage": form.get("lifecycle_stage", LifecycleStage.LIVE.value),
        "trial_start": form.get("trial_start", ""),
        "trial_end": form.get("trial_end", ""),
        "purpose": form.get("purpose", "").strip(),
        "categories_of_processing": form.get("categories_of_processing", "").strip(),
        "is_further_processing": form.get("is_further_processing") is not None,
        "further_processing_note": form.get("further_processing_note", "").strip(),
        "personal_data_source": form.getlist("personal_data_source"),
        "is_statutory_task": form.get("is_statutory_task") is not None,
        "vulnerable_or_safeguarding_flag": form.get("vulnerable_or_safeguarding_flag") is not None,
        "children_flag": form.get("children_flag") is not None,
        "online_childrens_service_flag": form.get("online_childrens_service_flag") is not None,
        "childrens_matters_note": form.get("childrens_matters_note", "").strip(),
        "external_data_use_mode": form.get(
            "external_data_use_mode", ExternalDataUseMode.NONE.value
        ),
        "lineage_granularity": form.get("lineage_granularity", LineageGranularity.ACTIVITY.value),
        "high_risk_flag": form.get("high_risk_flag") is not None,
        "owner_id": form.get("owner_id", ""),
        "last_reviewed_at": form.get("last_reviewed_at", ""),
        "next_review_at": form.get("next_review_at", ""),
        "le_data_subject_classification": form.getlist("le_data_subject_classification"),
        "le_fact_vs_assessment_noted": form.get("le_fact_vs_assessment_noted") is not None,
        "s62_logging_note": form.get("s62_logging_note", "").strip(),
    }


def _valid_date(value: str) -> bool:
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _validate_activity(session: Session, values: dict, *, is_law_enforcement: bool) -> list[dict]:
    errors = []
    if not values["name"]:
        errors.append({"field": "name", "message": "Enter a name"})
    if not values["business_function_id"] or session.get(
        BusinessFunction, values["business_function_id"]
    ) is None:
        errors.append({"field": "business_function_id", "message": "Select a business function"})
    if not values["purpose"]:
        errors.append({"field": "purpose", "message": "Enter a purpose"})
    if not values["personal_data_source"]:
        errors.append(
            {"field": "personal_data_source", "message": "Select at least one personal data source"}
        )
    if not values["owner_id"] or session.get(User, values["owner_id"]) is None:
        errors.append({"field": "owner_id", "message": "Select an owner"})
    if not values["next_review_at"]:
        errors.append({"field": "next_review_at", "message": "Enter a next review date"})
    elif not _valid_date(values["next_review_at"]):
        errors.append({"field": "next_review_at", "message": "Enter a valid date"})
    if values["last_reviewed_at"] and not _valid_date(values["last_reviewed_at"]):
        errors.append({"field": "last_reviewed_at", "message": "Enter a valid date"})
    if values["lifecycle_stage"] == LifecycleStage.TRIAL.value:
        if not values["trial_start"]:
            errors.append({"field": "trial_start", "message": "Enter a trial start date"})
        if not values["trial_end"]:
            errors.append({"field": "trial_end", "message": "Enter a trial end date"})
    for field in ("trial_start", "trial_end"):
        if values[field] and not _valid_date(values[field]):
            errors.append({"field": field, "message": "Enter a valid date"})
    if (
        values["controller_or_processor"] == ControllerOrProcessor.PROCESSOR.value
        and not values["categories_of_processing"]
    ):
        errors.append(
            {
                "field": "categories_of_processing",
                "message": "Enter categories of processing (required for a processor)",
            }
        )
    if is_law_enforcement and not values["le_data_subject_classification"]:
        errors.append(
            {
                "field": "le_data_subject_classification",
                "message": "Select at least one data subject classification",
            }
        )
    return errors


def _apply_activity_values(activity: ProcessingActivity, values: dict) -> None:
    activity.name = values["name"]
    activity.reference = values["reference"] or None
    activity.business_function_id = values["business_function_id"]
    activity.description = values["description"] or None
    activity.activity_type = ActivityType(values["activity_type"])
    activity.activity_domain = (
        ActivityDomain(values["activity_domain"]) if values["activity_domain"] else None
    )
    activity.controller_or_processor = ControllerOrProcessor(values["controller_or_processor"])
    activity.lifecycle_stage = LifecycleStage(values["lifecycle_stage"])
    activity.trial_start = (
        date.fromisoformat(values["trial_start"]) if values["trial_start"] else None
    )
    activity.trial_end = date.fromisoformat(values["trial_end"]) if values["trial_end"] else None
    activity.purpose = values["purpose"]
    activity.categories_of_processing = values["categories_of_processing"] or None
    activity.is_further_processing = values["is_further_processing"]
    activity.further_processing_note = values["further_processing_note"] or None
    activity.personal_data_source = values["personal_data_source"]
    activity.is_statutory_task = values["is_statutory_task"]
    activity.vulnerable_or_safeguarding_flag = values["vulnerable_or_safeguarding_flag"]
    activity.children_flag = values["children_flag"]
    activity.online_childrens_service_flag = values["online_childrens_service_flag"]
    activity.childrens_matters_note = values["childrens_matters_note"] or None
    activity.external_data_use_mode = ExternalDataUseMode(values["external_data_use_mode"])
    activity.lineage_granularity = LineageGranularity(values["lineage_granularity"])
    activity.high_risk_flag = values["high_risk_flag"]
    activity.owner_id = values["owner_id"]
    activity.last_reviewed_at = (
        date.fromisoformat(values["last_reviewed_at"]) if values["last_reviewed_at"] else None
    )
    activity.next_review_at = date.fromisoformat(values["next_review_at"])
    if activity.regime == Regime.LAW_ENFORCEMENT:
        activity.le_data_subject_classification = values["le_data_subject_classification"]
        activity.le_fact_vs_assessment_noted = values["le_fact_vs_assessment_noted"]
        activity.s62_logging_note = values["s62_logging_note"] or None


def _activity_to_values(activity: ProcessingActivity) -> dict:
    return {
        "name": activity.name,
        "reference": activity.reference or "",
        "business_function_id": activity.business_function_id,
        "description": activity.description or "",
        "activity_type": activity.activity_type.value,
        "activity_domain": activity.activity_domain.value if activity.activity_domain else "",
        "controller_or_processor": activity.controller_or_processor.value,
        "lifecycle_stage": activity.lifecycle_stage.value,
        "trial_start": activity.trial_start.isoformat() if activity.trial_start else "",
        "trial_end": activity.trial_end.isoformat() if activity.trial_end else "",
        "purpose": activity.purpose,
        "categories_of_processing": activity.categories_of_processing or "",
        "is_further_processing": activity.is_further_processing,
        "further_processing_note": activity.further_processing_note or "",
        "personal_data_source": list(activity.personal_data_source or []),
        "is_statutory_task": activity.is_statutory_task,
        "vulnerable_or_safeguarding_flag": activity.vulnerable_or_safeguarding_flag,
        "children_flag": activity.children_flag,
        "online_childrens_service_flag": activity.online_childrens_service_flag,
        "childrens_matters_note": activity.childrens_matters_note or "",
        "external_data_use_mode": activity.external_data_use_mode.value,
        "lineage_granularity": activity.lineage_granularity.value,
        "high_risk_flag": activity.high_risk_flag,
        "owner_id": activity.owner_id,
        "last_reviewed_at": (
            activity.last_reviewed_at.isoformat() if activity.last_reviewed_at else ""
        ),
        "next_review_at": activity.next_review_at.isoformat() if activity.next_review_at else "",
        "le_data_subject_classification": list(activity.le_data_subject_classification or []),
        "le_fact_vs_assessment_noted": bool(activity.le_fact_vs_assessment_noted),
        "s62_logging_note": activity.s62_logging_note or "",
    }


def _form_context(
    session: Session,
    user: User,
    *,
    activity: ProcessingActivity | None,
    values: dict,
    errors: list[dict],
    csrf_token: str,
    is_edit: bool = False,
) -> dict:
    error_map = {e["field"]: e["message"] for e in errors}
    is_law_enforcement = activity.regime == Regime.LAW_ENFORCEMENT if activity else False
    trial_hint = activity is not None and activity.lifecycle_stage == LifecycleStage.TRIAL
    return {
        "user": user,
        "activity": activity,
        "is_edit": is_edit,
        "values": values,
        "errors": errors,
        "error_map": error_map,
        "csrf_token": csrf_token,
        "is_law_enforcement": is_law_enforcement,
        "trial_hint": trial_hint,
        "regime_labels": REGIME_LABELS,
        "business_function_options": _business_function_options(session),
        "user_options": _user_options(session),
        "activity_type_options": list(ACTIVITY_TYPE_LABELS.items()),
        "activity_domain_options": [("", "None")] + list(ACTIVITY_DOMAIN_LABELS.items()),
        "controller_or_processor_options": list(CONTROLLER_OR_PROCESSOR_LABELS.items()),
        "lifecycle_stage_options": list(LIFECYCLE_STAGE_LABELS.items()),
        "personal_data_source_options": list(PERSONAL_DATA_SOURCE_LABELS.items()),
        "external_data_use_mode_options": list(EXTERNAL_DATA_USE_MODE_LABELS.items()),
        "lineage_granularity_options": list(LINEAGE_GRANULARITY_LABELS.items()),
        "le_classification_options": list(LE_CLASSIFICATION_LABELS.items()),
    }


def _junction_context(session: Session, activity: ProcessingActivity) -> dict:
    linked_subject_ids = {s.id for s in activity.data_subjects}
    linked_recipient_ids = {r.id for r in activity.recipients}
    linked_asset_ids = {s.id for s in activity.assets}
    linked_source_ids = {s.id for s in activity.data_sources}
    linked_controller_ids = {c.id for c in activity.controllers}
    linked_notice_ids = {n.id for n in activity.privacy_notices}
    linked_category_ids = {link.category_id for link in activity.data_category_links}
    subject_labels = {
        s.id: _display_label(s) for s in session.scalars(select(DataSubjectCategory)).all()
    }
    return {
        "data_subjects": [(s.id, _display_label(s)) for s in activity.data_subjects],
        "data_subject_options": _available_options(
            session, DataSubjectCategory, linked_subject_ids
        ),
        "recipients": [(r.id, _display_label(r)) for r in activity.recipients],
        "recipient_options": _available_options(session, Recipient, linked_recipient_ids),
        "assets": [(s.id, _display_label(s)) for s in activity.assets],
        "asset_options": _available_options(session, InformationAsset, linked_asset_ids),
        "data_sources": [(s.id, _display_label(s)) for s in activity.data_sources],
        "data_source_options": _available_options(session, ExternalDataSource, linked_source_ids),
        "controllers": [(c.id, _display_label(c)) for c in activity.controllers],
        "controller_options": _available_options(session, LegalEntity, linked_controller_ids),
        "privacy_notices": [(n.id, _display_label(n)) for n in activity.privacy_notices],
        "privacy_notice_options": _available_options(session, PrivacyNotice, linked_notice_ids),
        "data_category_rows": [
            {
                "link_id": link.id,
                "category_label": _display_label(link.category),
                "scope_label": subject_labels.get(link.data_subject_scope_id),
            }
            for link in activity.data_category_links
        ],
        "data_category_options": _available_options(
            session, PersonalDataCategory, linked_category_ids
        ),
        "data_subject_scope_options": [(s.id, _display_label(s)) for s in activity.data_subjects],
    }


def _findings_context(activity: ProcessingActivity, profile: OrganisationProfile) -> dict:
    findings = evaluate(activity, profile)
    return {"findings": findings, "has_block": any(f.severity == Severity.BLOCK for f in findings)}


def _render_detail(
    request: Request,
    session: Session,
    activity: ProcessingActivity,
    user: User,
    *,
    error: str | None = None,
    status_code: int = 200,
):
    profile = _get_profile(session)
    versions = session.scalars(
        select(RecordVersion)
        .where(
            RecordVersion.entity_type == "processing_activity",
            RecordVersion.entity_id == activity.id,
        )
        .order_by(RecordVersion.changed_at.desc())
    ).all()
    regime_events = session.scalars(
        select(AuditEvent)
        .where(
            AuditEvent.entity_type == "processing_activity",
            AuditEvent.entity_id == activity.id,
            AuditEvent.event.in_(("regime_change", "status_change", "review_completed")),
        )
        .order_by(AuditEvent.occurred_at.desc())
    ).all()
    users_by_id = {u.id: u.display_name for u in session.scalars(select(User)).all()}
    function_labels = dict(_business_function_options(session))
    context = {
        "user": user,
        "activity": activity,
        "profile": profile,
        "business_function_label": function_labels.get(activity.business_function_id, ""),
        "export_views": sorted(export_views(activity, profile)),
        "versions": versions,
        "regime_events": regime_events,
        "users_by_id": users_by_id,
        "can_edit": _can_edit_activity(user, activity),
        "can_activate": user.role == Role.APPROVER_DPO,
        "can_override_regime": user.role == Role.APPROVER_DPO,
        "csrf_token": get_csrf_token(request),
        "add_labels": ADD_LABELS,
        "record_status_labels": RECORD_STATUS_LABELS,
        "regime_labels": REGIME_LABELS,
        "error": error,
        **_findings_context(activity, profile),
        **_junction_context(session, activity),
        **basis_detail_context(session, activity, user),
        **register_detail_context(session, activity, user),
    }
    return templates.TemplateResponse(
        request, "activities/detail.html", context, status_code=status_code
    )


def _junction_fragment_response(
    request: Request, session: Session, activity: ProcessingActivity, kind: str
):
    profile = _get_profile(session)
    junction_context = _junction_context(session, activity)
    if kind == "data-categories":
        template_name = "activities/_data_categories_section.html"
        context = {
            "activity": activity,
            "csrf_token": get_csrf_token(request),
            "data_category_rows": junction_context["data_category_rows"],
            "data_category_options": junction_context["data_category_options"],
            "data_subject_scope_options": junction_context["data_subject_scope_options"],
            **_findings_context(activity, profile),
        }
    else:
        template_name = "activities/_simple_junction_section.html"
        items_key, options_key = JUNCTION_CONTEXT_KEYS[kind]
        context = {
            "activity": activity,
            "csrf_token": get_csrf_token(request),
            "kind": kind,
            "section_title": SECTION_TITLES[kind],
            "add_label": ADD_LABELS[kind],
            "items": junction_context[items_key],
            "options": junction_context[options_key],
            **_findings_context(activity, profile),
        }
    if request.headers.get("HX-Request") == "true":
        return templates.TemplateResponse(request, template_name, context)
    return RedirectResponse(f"/activities/{activity.id}", status_code=302)


@router.get("/activities")
def list_activities(
    request: Request,
    business_function: str | None = None,
    record_status: str | None = None,
    regime: str | None = None,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    profile = _get_profile(session)
    query = select(ProcessingActivity).order_by(ProcessingActivity.name)
    if business_function:
        query = query.where(ProcessingActivity.business_function_id == business_function)
    if record_status:
        try:
            query = query.where(ProcessingActivity.record_status == RecordStatus(record_status))
        except ValueError:
            pass
    if regime:
        try:
            query = query.where(ProcessingActivity.regime == Regime(regime))
        except ValueError:
            pass
    activities = session.scalars(query).all()
    function_labels = dict(_business_function_options(session))
    rows = [
        {
            "activity": activity,
            "export_views": sorted(export_views(activity, profile)),
            "business_function_label": function_labels.get(activity.business_function_id, ""),
        }
        for activity in activities
    ]
    return templates.TemplateResponse(
        request,
        "activities/list.html",
        {
            "user": user,
            "rows": rows,
            "business_function_options": _business_function_options(session),
            "record_status_options": list(RECORD_STATUS_LABELS.items()),
            "regime_options": list(REGIME_LABELS.items()),
            "record_status_labels": RECORD_STATUS_LABELS,
            "regime_labels": REGIME_LABELS,
            "filters": {
                "business_function": business_function or "",
                "record_status": record_status or "",
                "regime": regime or "",
            },
            "csrf_token": get_csrf_token(request),
        },
    )


@router.get("/activities/new")
def new_activity_form(
    request: Request, user: User = Depends(current_user), session: Session = Depends(get_session)
):
    _require_can_create(user)
    values = dict(NEW_ACTIVITY_DEFAULTS)
    if user.role == Role.CONTRIBUTOR:
        values["business_function_id"] = user.business_function_id or ""
    context = _form_context(
        session, user, activity=None, values=values, errors=[], csrf_token=get_csrf_token(request)
    )
    return templates.TemplateResponse(request, "activities/form.html", context)


@router.post("/activities")
async def create_activity(
    request: Request, user: User = Depends(current_user), session: Session = Depends(get_session)
):
    _require_can_create(user)
    form = await request.form()
    verify_csrf(request, form.get("csrf_token"))
    values = _parse_activity_form(form)
    if user.role == Role.CONTRIBUTOR and not _own_function(user, values["business_function_id"]):
        raise HTTPException(
            status_code=403,
            detail="Contributors may only create activities in their own business function",
        )
    errors = _validate_activity(session, values, is_law_enforcement=False)
    if errors:
        context = _form_context(
            session,
            user,
            activity=None,
            values=values,
            errors=errors,
            csrf_token=get_csrf_token(request),
        )
        return templates.TemplateResponse(
            request, "activities/form.html", context, status_code=422
        )
    activity = ProcessingActivity(record_status=RecordStatus.DRAFT)
    _apply_activity_values(activity, values)
    activity.regime = resolve_regime(session, activity)
    activity.regime_source = RegimeSource.POLICY
    session.add(activity)
    session.flush()
    return RedirectResponse(f"/activities/{activity.id}", status_code=302)


@router.get("/activities/{activity_id}")
def activity_detail(
    activity_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    activity = _get_activity(session, activity_id)
    return _render_detail(request, session, activity, user)


@router.get("/activities/{activity_id}/edit")
def edit_activity_form(
    activity_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    activity = _get_activity(session, activity_id)
    _require_can_edit(user, activity)
    values = _activity_to_values(activity)
    context = _form_context(
        session,
        user,
        activity=activity,
        values=values,
        errors=[],
        csrf_token=get_csrf_token(request),
        is_edit=True,
    )
    return templates.TemplateResponse(request, "activities/form.html", context)


@router.post("/activities/{activity_id}")
async def update_activity(
    activity_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    activity = _get_activity(session, activity_id)
    _require_can_edit(user, activity)
    form = await request.form()
    verify_csrf(request, form.get("csrf_token"))
    values = _parse_activity_form(form)
    if user.role == Role.CONTRIBUTOR and not _own_function(user, values["business_function_id"]):
        raise HTTPException(
            status_code=403,
            detail="Contributors may only edit activities within their own business function",
        )
    if (
        activity.lifecycle_stage == LifecycleStage.TRIAL
        and values["lifecycle_stage"] == LifecycleStage.LIVE.value
        and user.role != Role.APPROVER_DPO
    ):
        errors = [
            {
                "field": "lifecycle_stage",
                "message": "Only the DPO/approver may move a trial to live",
            }
        ]
        context = _form_context(
            session,
            user,
            activity=activity,
            values=values,
            errors=errors,
            csrf_token=get_csrf_token(request),
            is_edit=True,
        )
        return templates.TemplateResponse(
            request, "activities/form.html", context, status_code=403
        )
    errors = _validate_activity(
        session, values, is_law_enforcement=activity.regime == Regime.LAW_ENFORCEMENT
    )
    if errors:
        context = _form_context(
            session,
            user,
            activity=activity,
            values=values,
            errors=errors,
            csrf_token=get_csrf_token(request),
            is_edit=True,
        )
        return templates.TemplateResponse(
            request, "activities/form.html", context, status_code=422
        )
    change_note = form.get("change_note", "").strip()
    _apply_activity_values(activity, values)
    if change_note:
        activity.change_note = change_note
    session.flush()
    return RedirectResponse(f"/activities/{activity.id}", status_code=302)


@router.post("/activities/{activity_id}/status")
async def transition_status(
    activity_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    activity = _get_activity(session, activity_id)
    form = await request.form()
    verify_csrf(request, form.get("csrf_token"))
    try:
        target = RecordStatus(form.get("target_status"))
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid target status") from None
    current = activity.record_status
    if (current, target) not in STATUS_TRANSITIONS:
        raise HTTPException(
            status_code=422, detail=f"Cannot transition from {current.value} to {target.value}"
        )
    if target == RecordStatus.ACTIVE:
        if user.role != Role.APPROVER_DPO:
            raise HTTPException(status_code=403, detail="Only approver_dpo may activate a record")
        profile = _get_profile(session)
        if any(f.severity == Severity.BLOCK for f in evaluate(activity, profile)):
            return _render_detail(
                request,
                session,
                activity,
                user,
                error="Cannot activate: blocking findings must be resolved first",
                status_code=422,
            )
    elif target == RecordStatus.RETIRED:
        if user.role != Role.APPROVER_DPO:
            raise HTTPException(status_code=403, detail="Only approver_dpo may retire a record")
    else:
        _require_can_edit(user, activity)
    activity.change_note = f"Status: {current.value} → {target.value}"
    activity.record_status = target
    session.flush()
    record_event(
        session,
        entity=activity,
        event="status_change",
        actor=user,
        old_value={"record_status": current.value},
        new_value={"record_status": target.value},
    )
    return RedirectResponse(f"/activities/{activity.id}", status_code=302)


@router.post("/activities/{activity_id}/regime-override")
async def regime_override(
    activity_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    activity = _get_activity(session, activity_id)
    if user.role != Role.APPROVER_DPO:
        raise HTTPException(
            status_code=403, detail="Only approver_dpo may override an activity's regime"
        )
    form = await request.form()
    verify_csrf(request, form.get("csrf_token"))
    reason = form.get("reason", "").strip()
    try:
        target_regime = Regime(form.get("target_regime"))
    except ValueError:
        return _render_detail(
            request, session, activity, user, error="Select a valid regime", status_code=422
        )
    try:
        override_activity_regime(session, activity, regime=target_regime, reason=reason, actor=user)
    except ValueError as exc:
        return _render_detail(request, session, activity, user, error=str(exc), status_code=422)
    session.flush()
    return RedirectResponse(f"/activities/{activity.id}", status_code=302)


@router.post("/activities/{activity_id}/mark-reviewed")
async def mark_reviewed(
    activity_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    activity = _get_activity(session, activity_id)
    _require_can_edit(user, activity)
    form = await request.form()
    verify_csrf(request, form.get("csrf_token"))
    next_review_at = form.get("next_review_at", "")
    if not _valid_date(next_review_at) or date.fromisoformat(next_review_at) <= date.today():
        return _render_detail(
            request,
            session,
            activity,
            user,
            error="Enter a future next review date",
            status_code=422,
        )
    old_value = {
        "last_reviewed_at": (
            activity.last_reviewed_at.isoformat() if activity.last_reviewed_at else None
        ),
        "next_review_at": (
            activity.next_review_at.isoformat() if activity.next_review_at else None
        ),
    }
    activity.last_reviewed_at = date.today()
    activity.next_review_at = date.fromisoformat(next_review_at)
    activity.change_note = "Review completed"
    session.flush()
    record_event(
        session,
        entity=activity,
        event="review_completed",
        actor=user,
        old_value=old_value,
        new_value={
            "last_reviewed_at": activity.last_reviewed_at.isoformat(),
            "next_review_at": activity.next_review_at.isoformat(),
        },
    )
    return RedirectResponse(f"/activities/{activity.id}", status_code=302)


@router.post("/activities/{activity_id}/data-categories")
async def add_data_category(
    activity_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    activity = _get_activity(session, activity_id)
    _require_can_edit(user, activity)
    form = await request.form()
    verify_csrf(request, form.get("csrf_token"))
    category_id = form.get("category_id")
    category = session.get(PersonalDataCategory, category_id) if category_id else None
    if category is None:
        raise HTTPException(status_code=422, detail="Select a personal data category")
    if category.entry_status == EntryStatus.REJECTED:
        raise HTTPException(status_code=422, detail="This entry has been rejected")
    scope_id = form.get("data_subject_scope_id") or None
    if scope_id and scope_id not in {s.id for s in activity.data_subjects}:
        raise HTTPException(
            status_code=422,
            detail="Scope must be a data subject already linked to this activity",
        )
    existing = session.scalars(
        select(ActivityDataCategory).where(
            ActivityDataCategory.activity_id == activity.id,
            ActivityDataCategory.category_id == category.id,
        )
    ).first()
    if existing is None:
        session.add(
            ActivityDataCategory(
                activity_id=activity.id, category_id=category.id, data_subject_scope_id=scope_id
            )
        )
        session.flush()
    return _junction_fragment_response(request, session, activity, "data-categories")


@router.post("/activities/{activity_id}/data-categories/{link_id}/remove")
async def remove_data_category(
    activity_id: str,
    link_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    activity = _get_activity(session, activity_id)
    _require_can_edit(user, activity)
    form = await request.form()
    verify_csrf(request, form.get("csrf_token"))
    link = session.get(ActivityDataCategory, link_id)
    if link is not None and link.activity_id == activity.id:
        session.delete(link)
        session.flush()
    return _junction_fragment_response(request, session, activity, "data-categories")


@router.post("/activities/{activity_id}/{kind}")
async def add_simple_junction(
    activity_id: str,
    kind: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    junction = SIMPLE_JUNCTIONS.get(kind)
    if junction is None:
        raise HTTPException(status_code=404)
    activity = _get_activity(session, activity_id)
    _require_can_edit(user, activity)
    form = await request.form()
    verify_csrf(request, form.get("csrf_token"))
    item_id = form.get("item_id")
    item = session.get(junction.model, item_id) if item_id else None
    if item is None:
        raise HTTPException(status_code=422, detail=f"Select a {junction.label}")
    if getattr(item, "entry_status", None) == EntryStatus.REJECTED:
        raise HTTPException(status_code=422, detail="This entry has been rejected")
    collection = getattr(activity, junction.attr)
    if item not in collection:
        collection.append(item)
        session.flush()
        if kind == "assets":
            sync_inherited_security(session, activity)
    return _junction_fragment_response(request, session, activity, kind)


@router.post("/activities/{activity_id}/{kind}/{item_id}/remove")
async def remove_simple_junction(
    activity_id: str,
    kind: str,
    item_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    junction = SIMPLE_JUNCTIONS.get(kind)
    if junction is None:
        raise HTTPException(status_code=404)
    activity = _get_activity(session, activity_id)
    _require_can_edit(user, activity)
    form = await request.form()
    verify_csrf(request, form.get("csrf_token"))
    item = session.get(junction.model, item_id)
    collection = getattr(activity, junction.attr)
    if item is not None and item in collection:
        collection.remove(item)
        session.flush()
        if kind == "assets":
            sync_inherited_security(session, activity)
    return _junction_fragment_response(request, session, activity, kind)
