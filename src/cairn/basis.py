from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from cairn.auth import current_user, get_csrf_token, verify_csrf
from cairn.db import get_session
from cairn.models import (
    ACTIVE_SCOPE,
    AgeCheckOutcome,
    APDScope,
    AppropriatePolicyDocument,
    ConsentMethod,
    ConsentRecord,
    LawfulBasisGeneral,
    LawfulBasisLE,
    LawfulBasisRecord,
    LIADecision,
    LIARLIRecord,
    OrganisationProfile,
    ProcessingActivity,
    RegimeScope,
    RLICondition,
    Role,
    Schedule1Condition,
    Schedule8Condition,
    SpecialCategoryCondition,
    User,
    WithdrawalStatus,
)
from cairn.regime import active_basis, inactive_basis
from cairn.templating import templates

router = APIRouter()

REGIME_SCOPE_LABELS = {
    RegimeScope.PART2: "Part 2 (general)",
    RegimeScope.PART3: "Part 3 (law enforcement)",
}
CONSENT_METHOD_LABELS = {
    ConsentMethod.ONLINE_FORM: "Online form",
    ConsentMethod.PAPER: "Paper",
    ConsentMethod.VERBAL_LOGGED: "Verbal (logged)",
    ConsentMethod.OTHER: "Other",
}
WITHDRAWAL_STATUS_LABELS = {
    WithdrawalStatus.ACTIVE: "Active",
    WithdrawalStatus.WITHDRAWN: "Withdrawn",
}
AGE_CHECK_OUTCOME_LABELS = {
    AgeCheckOutcome.ADULT: "Adult",
    AgeCheckOutcome.CHILD_OVER_13: "Child (13 or over)",
    AgeCheckOutcome.CHILD_UNDER_13: "Child (under 13)",
    AgeCheckOutcome.UNKNOWN: "Unknown",
}
RLI_CONDITION_LABELS = {
    RLICondition.NATIONAL_SECURITY_DEFENCE: "National security, public security and defence",
    RLICondition.EMERGENCIES: "Emergencies",
    RLICondition.CRIME: "Crime",
    RLICondition.SAFEGUARDING_VULNERABLE: "Safeguarding vulnerable individuals",
    RLICondition.PUBLIC_INTEREST_DISCLOSURE_REQUEST: (
        "Disclosure to a public-interest body on request"
    ),
}

LIA_DECISION_LABELS = {
    LIADecision.PROCEED: "Proceed",
    LIADecision.DO_NOT_PROCEED: "Do not proceed",
}


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


def _require_can_author_basis(user: User) -> None:
    if user.role not in (Role.CURATOR, Role.APPROVER_DPO):
        raise HTTPException(status_code=403, detail="Not permitted to author lawful basis records")


def _parse_scope(scope: str) -> RegimeScope:
    try:
        return RegimeScope(scope)
    except ValueError:
        raise HTTPException(status_code=404) from None


def _valid_date(value: str) -> bool:
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _valid_datetime(value: str) -> bool:
    try:
        datetime.fromisoformat(value)
    except ValueError:
        return False
    return True


def _existing_basis(activity: ProcessingActivity, scope: RegimeScope) -> LawfulBasisRecord | None:
    return next((b for b in activity.basis_records if b.regime_scope == scope), None)


def _get_or_create_basis(
    session: Session, activity: ProcessingActivity, scope: RegimeScope
) -> LawfulBasisRecord:
    basis = _existing_basis(activity, scope)
    if basis is not None:
        return basis
    basis = LawfulBasisRecord(activity_id=activity.id, regime_scope=scope)
    session.add(basis)
    session.flush()
    return basis


def _art6_options(session: Session) -> list[tuple[str, str]]:
    rows = session.scalars(select(LawfulBasisGeneral).order_by(LawfulBasisGeneral.code)).all()
    return [("", "Not set")] + [(r.id, f"{r.code} — {r.label}") for r in rows]


def _art9_options(session: Session) -> list[tuple[str, str]]:
    rows = session.scalars(
        select(SpecialCategoryCondition).order_by(SpecialCategoryCondition.code)
    ).all()
    return [("", "Not set")] + [(r.id, f"{r.code} — {r.label}") for r in rows]


def _schedule1_options(session: Session) -> list[tuple[str, str]]:
    rows = session.scalars(select(Schedule1Condition).order_by(Schedule1Condition.paragraph)).all()
    return [("", "Not set")] + [(r.id, f"Para {r.paragraph} — {r.label}") for r in rows]


def _s35_options(session: Session) -> list[tuple[str, str]]:
    rows = session.scalars(select(LawfulBasisLE).order_by(LawfulBasisLE.code)).all()
    return [("", "Not set")] + [(r.id, f"{r.code} — {r.label}") for r in rows]


def _schedule8_options(session: Session) -> list[tuple[str, str]]:
    rows = session.scalars(select(Schedule8Condition).order_by(Schedule8Condition.paragraph)).all()
    return [("", "Not set")] + [(r.id, f"Para {r.paragraph} — {r.label}") for r in rows]


def _apd_options(session: Session, scope: APDScope) -> list[tuple[str, str]]:
    rows = session.scalars(
        select(AppropriatePolicyDocument)
        .where(AppropriatePolicyDocument.scope == scope)
        .order_by(AppropriatePolicyDocument.title)
    ).all()
    return [("", "Not set")] + [(r.id, r.title) for r in rows]


def _part2_values(basis: LawfulBasisRecord | None) -> dict:
    if basis is None:
        return {
            "art6_basis_id": "",
            "art6_justification": "",
            "art9_condition_id": "",
            "schedule1_condition_id": "",
            "art10_basis": "",
            "apd_id": "",
        }
    return {
        "art6_basis_id": basis.art6_basis_id or "",
        "art6_justification": basis.art6_justification or "",
        "art9_condition_id": basis.art9_condition_id or "",
        "schedule1_condition_id": basis.schedule1_condition_id or "",
        "art10_basis": basis.art10_basis or "",
        "apd_id": basis.apd_id or "",
    }


def _part3_values(basis: LawfulBasisRecord | None) -> dict:
    if basis is None:
        return {"s35_basis_id": "", "schedule8_condition_id": "", "apd_id": ""}
    return {
        "s35_basis_id": basis.s35_basis_id or "",
        "schedule8_condition_id": basis.schedule8_condition_id or "",
        "apd_id": basis.apd_id or "",
    }


def _apply_guard_preselect(
    session: Session, values: dict, activity: ProcessingActivity, profile: OrganisationProfile
) -> bool:
    if not (profile.public_authority_guards and activity.is_statutory_task):
        return False
    e_basis = session.scalars(
        select(LawfulBasisGeneral).where(LawfulBasisGeneral.code == "e")
    ).first()
    if e_basis is None:
        return False
    values["art6_basis_id"] = e_basis.id
    return True


def _parse_part2_form(form) -> dict:
    return {
        "art6_basis_id": form.get("art6_basis_id", ""),
        "art6_justification": form.get("art6_justification", "").strip(),
        "art9_condition_id": form.get("art9_condition_id", ""),
        "schedule1_condition_id": form.get("schedule1_condition_id", ""),
        "art10_basis": form.get("art10_basis", "").strip(),
        "apd_id": form.get("apd_id", ""),
    }


def _parse_part3_form(form) -> dict:
    return {
        "s35_basis_id": form.get("s35_basis_id", ""),
        "schedule8_condition_id": form.get("schedule8_condition_id", ""),
        "apd_id": form.get("apd_id", ""),
    }


def _validate_fk(session: Session, model: type, value: str, field: str, label: str) -> dict | None:
    if value and session.get(model, value) is None:
        return {"field": field, "message": f"Select a valid {label}"}
    return None


def _validate_part2(session: Session, values: dict) -> list[dict]:
    errors = []
    for model, field, label in [
        (LawfulBasisGeneral, "art6_basis_id", "Art 6 basis"),
        (SpecialCategoryCondition, "art9_condition_id", "Art 9 condition"),
        (Schedule1Condition, "schedule1_condition_id", "Schedule 1 condition"),
        (AppropriatePolicyDocument, "apd_id", "Appropriate Policy Document"),
    ]:
        error = _validate_fk(session, model, values[field], field, label)
        if error:
            errors.append(error)
    if values["art6_basis_id"] and not values["art6_justification"]:
        errors.append(
            {
                "field": "art6_justification",
                "message": "Enter the justification for the Art 6 basis",
            }
        )
    return errors


def _validate_part3(session: Session, values: dict) -> list[dict]:
    errors = []
    for model, field, label in [
        (LawfulBasisLE, "s35_basis_id", "s35 basis"),
        (Schedule8Condition, "schedule8_condition_id", "Schedule 8 condition"),
        (AppropriatePolicyDocument, "apd_id", "Appropriate Policy Document"),
    ]:
        error = _validate_fk(session, model, values[field], field, label)
        if error:
            errors.append(error)
    return errors


def _apply_part2_values(basis: LawfulBasisRecord, values: dict) -> None:
    basis.art6_basis_id = values["art6_basis_id"] or None
    basis.art6_justification = values["art6_justification"] or None
    basis.art9_condition_id = values["art9_condition_id"] or None
    basis.schedule1_condition_id = values["schedule1_condition_id"] or None
    basis.art10_basis = values["art10_basis"] or None
    basis.apd_id = values["apd_id"] or None


def _apply_part3_values(basis: LawfulBasisRecord, values: dict) -> None:
    basis.s35_basis_id = values["s35_basis_id"] or None
    basis.schedule8_condition_id = values["schedule8_condition_id"] or None
    basis.apd_id = values["apd_id"] or None


def _basis_form_context(
    session: Session,
    user: User,
    activity: ProcessingActivity,
    profile: OrganisationProfile,
    scope: RegimeScope,
    basis: LawfulBasisRecord | None,
    *,
    values: dict | None,
    errors: list[dict],
    csrf_token: str,
) -> dict:
    error_map = {e["field"]: e["message"] for e in errors}
    context = {
        "user": user,
        "activity": activity,
        "scope": scope.value,
        "basis": basis,
        "errors": errors,
        "error_map": error_map,
        "csrf_token": csrf_token,
        "guard_hint": False,
    }
    if scope == RegimeScope.PART2:
        if values is None:
            values = _part2_values(basis)
            context["guard_hint"] = basis is None and _apply_guard_preselect(
                session, values, activity, profile
            )
        context.update(
            {
                "values": values,
                "art6_options": _art6_options(session),
                "art9_options": _art9_options(session),
                "schedule1_options": _schedule1_options(session),
                "apd_options": _apd_options(session, APDScope.SCHEDULE1),
                "show_art9": activity.special_category_flag,
                "show_art10": activity.criminal_offence_flag,
            }
        )
        return context
    if values is None:
        values = _part3_values(basis)
    context.update(
        {
            "values": values,
            "s35_options": _s35_options(session),
            "schedule8_options": _schedule8_options(session),
            "apd_options": _apd_options(session, APDScope.S42_PART3),
        }
    )
    return context


@router.get("/activities/{activity_id}/basis/{scope}/edit")
def basis_edit_form(
    activity_id: str,
    scope: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    activity = _get_activity(session, activity_id)
    _require_can_author_basis(user)
    regime_scope = _parse_scope(scope)
    profile = _get_profile(session)
    basis = _existing_basis(activity, regime_scope)
    context = _basis_form_context(
        session,
        user,
        activity,
        profile,
        regime_scope,
        basis,
        values=None,
        errors=[],
        csrf_token=get_csrf_token(request),
    )
    return templates.TemplateResponse(request, "activities/basis_form.html", context)


@router.post("/activities/{activity_id}/basis/{scope}")
async def basis_save(
    activity_id: str,
    scope: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    activity = _get_activity(session, activity_id)
    _require_can_author_basis(user)
    regime_scope = _parse_scope(scope)
    profile = _get_profile(session)
    form = await request.form()
    verify_csrf(request, form.get("csrf_token"))
    existing = _existing_basis(activity, regime_scope)
    if regime_scope == RegimeScope.PART2:
        values = _parse_part2_form(form)
        errors = _validate_part2(session, values)
    else:
        values = _parse_part3_form(form)
        errors = _validate_part3(session, values)
    if errors:
        context = _basis_form_context(
            session,
            user,
            activity,
            profile,
            regime_scope,
            existing,
            values=values,
            errors=errors,
            csrf_token=get_csrf_token(request),
        )
        return templates.TemplateResponse(
            request, "activities/basis_form.html", context, status_code=422
        )
    basis = _get_or_create_basis(session, activity, regime_scope)
    if regime_scope == RegimeScope.PART2:
        _apply_part2_values(basis, values)
    else:
        _apply_part3_values(basis, values)
    change_note = form.get("change_note", "").strip()
    if change_note:
        basis.change_note = change_note
    session.flush()
    return RedirectResponse(f"/activities/{activity.id}", status_code=302)


def _new_consent_values() -> dict:
    return {
        "consented_to": "",
        "wording_shown": "",
        "consent_datetime": "",
        "consent_method": ConsentMethod.ONLINE_FORM.value,
        "withdrawal_status": WithdrawalStatus.ACTIVE.value,
        "withdrawal_datetime": "",
        "review_due": "",
        "age_check_outcome": "",
        "parental_consent_captured": False,
    }


def _consent_to_values(consent: ConsentRecord) -> dict:
    return {
        "consented_to": consent.consented_to,
        "wording_shown": consent.wording_shown,
        "consent_datetime": consent.consent_datetime.strftime("%Y-%m-%dT%H:%M"),
        "consent_method": consent.consent_method.value,
        "withdrawal_status": consent.withdrawal_status.value,
        "withdrawal_datetime": (
            consent.withdrawal_datetime.strftime("%Y-%m-%dT%H:%M")
            if consent.withdrawal_datetime
            else ""
        ),
        "review_due": consent.review_due.isoformat() if consent.review_due else "",
        "age_check_outcome": (
            consent.age_check_outcome.value if consent.age_check_outcome else ""
        ),
        "parental_consent_captured": bool(consent.parental_consent_captured),
    }


def _parse_consent_form(form) -> dict:
    return {
        "consented_to": form.get("consented_to", "").strip(),
        "wording_shown": form.get("wording_shown", "").strip(),
        "consent_datetime": form.get("consent_datetime", ""),
        "consent_method": form.get("consent_method", ConsentMethod.ONLINE_FORM.value),
        "withdrawal_status": form.get("withdrawal_status", WithdrawalStatus.ACTIVE.value),
        "withdrawal_datetime": form.get("withdrawal_datetime", ""),
        "review_due": form.get("review_due", ""),
        "age_check_outcome": form.get("age_check_outcome", ""),
        "parental_consent_captured": form.get("parental_consent_captured") is not None,
    }


def _validate_consent(values: dict) -> list[dict]:
    errors = []
    if not values["consented_to"]:
        errors.append({"field": "consented_to", "message": "Enter what was consented to"})
    if not values["wording_shown"]:
        errors.append({"field": "wording_shown", "message": "Enter the consent wording shown"})
    if not values["consent_datetime"]:
        errors.append({"field": "consent_datetime", "message": "Enter the consent date and time"})
    elif not _valid_datetime(values["consent_datetime"]):
        errors.append({"field": "consent_datetime", "message": "Enter a valid date and time"})
    try:
        ConsentMethod(values["consent_method"])
    except ValueError:
        errors.append({"field": "consent_method", "message": "Select a valid consent method"})
    try:
        withdrawal_status = WithdrawalStatus(values["withdrawal_status"])
    except ValueError:
        withdrawal_status = None
        errors.append(
            {"field": "withdrawal_status", "message": "Select a valid withdrawal status"}
        )
    if withdrawal_status == WithdrawalStatus.WITHDRAWN:
        if not values["withdrawal_datetime"]:
            errors.append(
                {
                    "field": "withdrawal_datetime",
                    "message": "Enter the withdrawal date and time",
                }
            )
        elif not _valid_datetime(values["withdrawal_datetime"]):
            errors.append(
                {"field": "withdrawal_datetime", "message": "Enter a valid date and time"}
            )
    elif values["withdrawal_datetime"] and not _valid_datetime(values["withdrawal_datetime"]):
        errors.append({"field": "withdrawal_datetime", "message": "Enter a valid date and time"})
    if values["review_due"] and not _valid_date(values["review_due"]):
        errors.append({"field": "review_due", "message": "Enter a valid date"})
    if values["age_check_outcome"]:
        try:
            AgeCheckOutcome(values["age_check_outcome"])
        except ValueError:
            errors.append(
                {"field": "age_check_outcome", "message": "Select a valid age-check outcome"}
            )
    return errors


def _apply_consent_values(consent: ConsentRecord, values: dict) -> None:
    consent.consented_to = values["consented_to"]
    consent.wording_shown = values["wording_shown"]
    consent.consent_datetime = datetime.fromisoformat(values["consent_datetime"])
    consent.consent_method = ConsentMethod(values["consent_method"])
    consent.withdrawal_status = WithdrawalStatus(values["withdrawal_status"])
    consent.withdrawal_datetime = (
        datetime.fromisoformat(values["withdrawal_datetime"])
        if values["withdrawal_datetime"]
        else None
    )
    consent.review_due = date.fromisoformat(values["review_due"]) if values["review_due"] else None
    consent.age_check_outcome = (
        AgeCheckOutcome(values["age_check_outcome"]) if values["age_check_outcome"] else None
    )
    consent.parental_consent_captured = values["parental_consent_captured"]


def _consent_form_context(
    activity: ProcessingActivity,
    basis: LawfulBasisRecord,
    user: User,
    *,
    values: dict,
    errors: list[dict],
    csrf_token: str,
    is_edit: bool,
    consent_id: str | None = None,
) -> dict:
    error_map = {e["field"]: e["message"] for e in errors}
    return {
        "user": user,
        "activity": activity,
        "basis": basis,
        "is_edit": is_edit,
        "consent_id": consent_id,
        "values": values,
        "errors": errors,
        "error_map": error_map,
        "csrf_token": csrf_token,
        "consent_method_options": list(CONSENT_METHOD_LABELS.items()),
        "withdrawal_status_options": list(WITHDRAWAL_STATUS_LABELS.items()),
        "age_check_outcome_options": [("", "Not set")] + list(AGE_CHECK_OUTCOME_LABELS.items()),
    }


def _get_part2_basis_or_404(session: Session, activity: ProcessingActivity) -> LawfulBasisRecord:
    basis = _existing_basis(activity, RegimeScope.PART2)
    if basis is None:
        raise HTTPException(status_code=404)
    return basis


def _get_consent_or_404(
    session: Session, basis: LawfulBasisRecord, consent_id: str
) -> ConsentRecord:
    consent = session.get(ConsentRecord, consent_id)
    if consent is None or consent.lawful_basis_record_id != basis.id:
        raise HTTPException(status_code=404)
    return consent


@router.get("/activities/{activity_id}/basis/part2/consents/new")
def consent_new_form(
    activity_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    activity = _get_activity(session, activity_id)
    _require_can_author_basis(user)
    basis = _get_part2_basis_or_404(session, activity)
    context = _consent_form_context(
        activity,
        basis,
        user,
        values=_new_consent_values(),
        errors=[],
        csrf_token=get_csrf_token(request),
        is_edit=False,
    )
    return templates.TemplateResponse(request, "activities/consent_form.html", context)


@router.post("/activities/{activity_id}/basis/part2/consents/new")
async def consent_create(
    activity_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    activity = _get_activity(session, activity_id)
    _require_can_author_basis(user)
    basis = _get_part2_basis_or_404(session, activity)
    form = await request.form()
    verify_csrf(request, form.get("csrf_token"))
    values = _parse_consent_form(form)
    errors = _validate_consent(values)
    if errors:
        context = _consent_form_context(
            activity,
            basis,
            user,
            values=values,
            errors=errors,
            csrf_token=get_csrf_token(request),
            is_edit=False,
        )
        return templates.TemplateResponse(
            request, "activities/consent_form.html", context, status_code=422
        )
    consent = ConsentRecord(lawful_basis_record_id=basis.id)
    _apply_consent_values(consent, values)
    session.add(consent)
    session.flush()
    return RedirectResponse(f"/activities/{activity.id}", status_code=302)


@router.get("/activities/{activity_id}/basis/part2/consents/{consent_id}/edit")
def consent_edit_form(
    activity_id: str,
    consent_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    activity = _get_activity(session, activity_id)
    _require_can_author_basis(user)
    basis = _get_part2_basis_or_404(session, activity)
    consent = _get_consent_or_404(session, basis, consent_id)
    context = _consent_form_context(
        activity,
        basis,
        user,
        values=_consent_to_values(consent),
        errors=[],
        csrf_token=get_csrf_token(request),
        is_edit=True,
        consent_id=consent.id,
    )
    return templates.TemplateResponse(request, "activities/consent_form.html", context)


@router.post("/activities/{activity_id}/basis/part2/consents/{consent_id}/edit")
async def consent_update(
    activity_id: str,
    consent_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    activity = _get_activity(session, activity_id)
    _require_can_author_basis(user)
    basis = _get_part2_basis_or_404(session, activity)
    consent = _get_consent_or_404(session, basis, consent_id)
    form = await request.form()
    verify_csrf(request, form.get("csrf_token"))
    values = _parse_consent_form(form)
    errors = _validate_consent(values)
    if errors:
        context = _consent_form_context(
            activity,
            basis,
            user,
            values=values,
            errors=errors,
            csrf_token=get_csrf_token(request),
            is_edit=True,
            consent_id=consent.id,
        )
        return templates.TemplateResponse(
            request, "activities/consent_form.html", context, status_code=422
        )
    _apply_consent_values(consent, values)
    change_note = form.get("change_note", "").strip()
    if change_note:
        consent.change_note = change_note
    session.flush()
    return RedirectResponse(f"/activities/{activity.id}", status_code=302)


def _new_lia_values() -> dict:
    return {
        "interest_identified": "",
        "rli_condition": "",
        "necessity_test": "",
        "balancing_test": "",
        "safeguards": "",
        "decision": LIADecision.PROCEED.value,
        "decision_date": "",
    }


def _lia_to_values(lia: LIARLIRecord) -> dict:
    return {
        "interest_identified": lia.interest_identified,
        "rli_condition": lia.rli_condition.value if lia.rli_condition else "",
        "necessity_test": lia.necessity_test,
        "balancing_test": lia.balancing_test or "",
        "safeguards": lia.safeguards or "",
        "decision": lia.decision.value,
        "decision_date": lia.decision_date.isoformat(),
    }


def _parse_lia_form(form) -> dict:
    return {
        "interest_identified": form.get("interest_identified", "").strip(),
        "rli_condition": form.get("rli_condition", ""),
        "necessity_test": form.get("necessity_test", "").strip(),
        "balancing_test": form.get("balancing_test", "").strip(),
        "safeguards": form.get("safeguards", "").strip(),
        "decision": form.get("decision", LIADecision.PROCEED.value),
        "decision_date": form.get("decision_date", ""),
    }


def _validate_lia(values: dict) -> list[dict]:
    errors = []
    if not values["interest_identified"]:
        errors.append({"field": "interest_identified", "message": "Enter the interest identified"})
    if not values["necessity_test"]:
        errors.append({"field": "necessity_test", "message": "Enter the necessity test"})
    if values["rli_condition"] not in ("", *RLICondition):
        errors.append({"field": "rli_condition", "message": "Select a valid recognised interest"})
    try:
        LIADecision(values["decision"])
    except ValueError:
        errors.append({"field": "decision", "message": "Select a valid decision"})
    if not values["decision_date"]:
        errors.append({"field": "decision_date", "message": "Enter the decision date"})
    elif not _valid_date(values["decision_date"]):
        errors.append({"field": "decision_date", "message": "Enter a valid date"})
    return errors


def _apply_lia_values(lia: LIARLIRecord, values: dict) -> None:
    lia.interest_identified = values["interest_identified"]
    lia.rli_condition = RLICondition(values["rli_condition"]) if values["rli_condition"] else None
    lia.necessity_test = values["necessity_test"]
    lia.balancing_test = values["balancing_test"] or None
    lia.safeguards = values["safeguards"] or None
    lia.decision = LIADecision(values["decision"])
    lia.decision_date = date.fromisoformat(values["decision_date"])


def _lia_form_context(
    activity: ProcessingActivity,
    basis: LawfulBasisRecord,
    user: User,
    *,
    values: dict,
    errors: list[dict],
    csrf_token: str,
    is_edit: bool,
    lia_id: str | None = None,
) -> dict:
    error_map = {e["field"]: e["message"] for e in errors}
    return {
        "user": user,
        "activity": activity,
        "basis": basis,
        "is_edit": is_edit,
        "lia_id": lia_id,
        "values": values,
        "errors": errors,
        "error_map": error_map,
        "csrf_token": csrf_token,
        "decision_options": list(LIA_DECISION_LABELS.items()),
        "rli_options": [("", "Not applicable")]
        + [(c.value, label) for c, label in RLI_CONDITION_LABELS.items()],
    }


def _get_lia_or_404(session: Session, basis: LawfulBasisRecord, lia_id: str) -> LIARLIRecord:
    lia = session.get(LIARLIRecord, lia_id)
    if lia is None or lia.lawful_basis_record_id != basis.id:
        raise HTTPException(status_code=404)
    return lia


@router.get("/activities/{activity_id}/basis/part2/lia/new")
def lia_new_form(
    activity_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    activity = _get_activity(session, activity_id)
    _require_can_author_basis(user)
    basis = _get_part2_basis_or_404(session, activity)
    context = _lia_form_context(
        activity,
        basis,
        user,
        values=_new_lia_values(),
        errors=[],
        csrf_token=get_csrf_token(request),
        is_edit=False,
    )
    return templates.TemplateResponse(request, "activities/lia_form.html", context)


@router.post("/activities/{activity_id}/basis/part2/lia/new")
async def lia_create(
    activity_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    activity = _get_activity(session, activity_id)
    _require_can_author_basis(user)
    basis = _get_part2_basis_or_404(session, activity)
    form = await request.form()
    verify_csrf(request, form.get("csrf_token"))
    values = _parse_lia_form(form)
    errors = _validate_lia(values)
    if errors:
        context = _lia_form_context(
            activity,
            basis,
            user,
            values=values,
            errors=errors,
            csrf_token=get_csrf_token(request),
            is_edit=False,
        )
        return templates.TemplateResponse(
            request, "activities/lia_form.html", context, status_code=422
        )
    lia = LIARLIRecord(lawful_basis_record_id=basis.id)
    _apply_lia_values(lia, values)
    session.add(lia)
    session.flush()
    return RedirectResponse(f"/activities/{activity.id}", status_code=302)


@router.get("/activities/{activity_id}/basis/part2/lia/{lia_id}/edit")
def lia_edit_form(
    activity_id: str,
    lia_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    activity = _get_activity(session, activity_id)
    _require_can_author_basis(user)
    basis = _get_part2_basis_or_404(session, activity)
    lia = _get_lia_or_404(session, basis, lia_id)
    context = _lia_form_context(
        activity,
        basis,
        user,
        values=_lia_to_values(lia),
        errors=[],
        csrf_token=get_csrf_token(request),
        is_edit=True,
        lia_id=lia.id,
    )
    return templates.TemplateResponse(request, "activities/lia_form.html", context)


@router.post("/activities/{activity_id}/basis/part2/lia/{lia_id}/edit")
async def lia_update(
    activity_id: str,
    lia_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    activity = _get_activity(session, activity_id)
    _require_can_author_basis(user)
    basis = _get_part2_basis_or_404(session, activity)
    lia = _get_lia_or_404(session, basis, lia_id)
    form = await request.form()
    verify_csrf(request, form.get("csrf_token"))
    values = _parse_lia_form(form)
    errors = _validate_lia(values)
    if errors:
        context = _lia_form_context(
            activity,
            basis,
            user,
            values=values,
            errors=errors,
            csrf_token=get_csrf_token(request),
            is_edit=True,
            lia_id=lia.id,
        )
        return templates.TemplateResponse(
            request, "activities/lia_form.html", context, status_code=422
        )
    _apply_lia_values(lia, values)
    change_note = form.get("change_note", "").strip()
    if change_note:
        lia.change_note = change_note
    session.flush()
    return RedirectResponse(f"/activities/{activity.id}", status_code=302)


def _basis_view(basis: LawfulBasisRecord) -> dict:
    return {
        "scope": basis.regime_scope.value,
        "art6": f"{basis.art6_basis.code} — {basis.art6_basis.label}" if basis.art6_basis else "",
        "art6_justification": basis.art6_justification or "",
        "art9": (
            f"{basis.art9_condition.code} — {basis.art9_condition.label}"
            if basis.art9_condition
            else ""
        ),
        "schedule1": (
            f"Para {basis.schedule1_condition.paragraph} — {basis.schedule1_condition.label}"
            if basis.schedule1_condition
            else ""
        ),
        "art10": basis.art10_basis or "",
        "s35": f"{basis.s35_basis.code} — {basis.s35_basis.label}" if basis.s35_basis else "",
        "schedule8": (
            f"Para {basis.schedule8_condition.paragraph} — {basis.schedule8_condition.label}"
            if basis.schedule8_condition
            else ""
        ),
        "apd": basis.apd.title if basis.apd else "",
    }


def basis_detail_context(session: Session, activity: ProcessingActivity, user: User) -> dict:
    can_author = user.role in (Role.CURATOR, Role.APPROVER_DPO)
    active = active_basis(activity)
    inactive = inactive_basis(activity)
    active_scope = ACTIVE_SCOPE[activity.regime]
    show_consents = (
        active is not None
        and active.regime_scope == RegimeScope.PART2
        and active.art6_basis is not None
        and active.art6_basis.code == "a"
    )
    show_lia = (
        active is not None
        and active.regime_scope == RegimeScope.PART2
        and active.art6_basis is not None
        and active.art6_basis.code in ("f", "ea")
    )
    return {
        "can_author_basis": can_author,
        "active_scope": active_scope.value,
        "active_basis_view": _basis_view(active) if active else None,
        "inactive_basis_view": _basis_view(inactive) if inactive else None,
        "regime_scope_labels": {k.value: v for k, v in REGIME_SCOPE_LABELS.items()},
        "show_consents": show_consents,
        "show_lia": show_lia,
        "consent_records": active.consent_records if show_consents else [],
        "lia_records": active.lia_rli_records if show_lia else [],
        "consent_method_labels": CONSENT_METHOD_LABELS,
        "withdrawal_status_labels": WITHDRAWAL_STATUS_LABELS,
        "age_check_outcome_labels": AGE_CHECK_OUTCOME_LABELS,
        "lia_decision_labels": LIA_DECISION_LABELS,
        "rli_condition_labels": RLI_CONDITION_LABELS,
    }
