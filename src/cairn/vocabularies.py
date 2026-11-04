from dataclasses import dataclass
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cairn.audit import record_event
from cairn.auth import current_user, get_csrf_token, verify_csrf
from cairn.db import get_session
from cairn.intake import resolve_supplier_gaps
from cairn.models import (
    AdequacyStatus,
    APDScope,
    AppropriatePolicyDocument,
    BusinessFunction,
    DataSubjectCategory,
    EntryStatus,
    ExternalDataSource,
    LawfulBasisGeneral,
    LawfulBasisLE,
    LEClassification,
    LegalEntity,
    LegalEntityRoleType,
    PersonalDataCategory,
    PrivacyNotice,
    Recipient,
    RecipientType,
    RetentionRule,
    Role,
    Schedule1Condition,
    Schedule8Condition,
    SecurityMeasure,
    SecurityMeasureCategory,
    SourceSpecialCategory,
    SpecialCategoryCondition,
    SupplierRole,
    ThirdCountry,
    TransferMechanism,
    User,
)
from cairn.templating import templates

router = APIRouter()


@dataclass(frozen=True)
class VocabField:
    name: str
    label: str
    kind: str
    required: bool = False
    enum_cls: type | None = None
    fk_model: type | None = None
    fk_label_attr: str = "label"
    default: str | None = None
    hint: str | None = None


@dataclass(frozen=True)
class VocabSpec:
    key: str
    model: type
    display_name: str
    label_attr: str
    fields: list[VocabField]
    editable: bool = True
    accepts_proposals: bool = False


VOCABULARIES: dict[str, VocabSpec] = {
    spec.key: spec
    for spec in [
        VocabSpec(
            key="business-functions",
            model=BusinessFunction,
            display_name="Business function",
            label_attr="label",
            fields=[VocabField("label", "Label", "text", required=True)],
        ),
        VocabSpec(
            key="data-subject-categories",
            model=DataSubjectCategory,
            display_name="Data subject category",
            label_attr="label",
            accepts_proposals=True,
            fields=[
                VocabField(
                    "label", "Label", "text", required=True,
                    hint="For example 'Members of the public' or 'Employees'",
                ),
                VocabField(
                    "le_classification",
                    "Law enforcement classification",
                    "enum",
                    required=True,
                    enum_cls=LEClassification,
                    default=LEClassification.NONE.value,
                    hint="Law enforcement processing only. Leave as None for everyone else",
                ),
            ],
        ),
        VocabSpec(
            key="personal-data-categories",
            model=PersonalDataCategory,
            display_name="Personal data category",
            label_attr="label",
            accepts_proposals=True,
            fields=[
                VocabField("label", "Label", "text", required=True),
                VocabField(
                    "is_special_category", "Special category", "bool",
                    hint="Tick for data such as health, ethnicity or religion (UK GDPR Art 9)",
                ),
                VocabField(
                    "is_criminal_offence", "Criminal offence", "bool",
                    hint="Tick for data about offences, convictions or cautions (UK GDPR Art 10)",
                ),
            ],
        ),
        VocabSpec(
            key="recipients",
            model=Recipient,
            display_name="Recipient",
            label_attr="label",
            accepts_proposals=True,
            fields=[
                VocabField("label", "Label", "text", required=True),
                VocabField("type", "Type", "enum", required=True, enum_cls=RecipientType),
                VocabField(
                    "legal_entity_id", "Legal entity", "fk", fk_model=LegalEntity,
                    hint="The organisation this recipient belongs to, if it is listed",
                ),
            ],
        ),
        VocabSpec(
            key="security-measures",
            model=SecurityMeasure,
            display_name="Security measure",
            label_attr="label",
            accepts_proposals=True,
            fields=[
                VocabField("label", "Label", "text", required=True),
                VocabField(
                    "category", "Category", "enum", required=True, enum_cls=SecurityMeasureCategory,
                    hint=(
                        "Technical (for example encryption), organisational (for example "
                        "training) or physical (for example locks)"
                    ),
                ),
            ],
        ),
        VocabSpec(
            key="retention-rules",
            model=RetentionRule,
            display_name="Retention rule",
            label_attr="label",
            accepts_proposals=True,
            fields=[
                VocabField("label", "Label", "text", required=True),
                VocabField("period", "Period", "text", required=True, hint="For example '6 years'"),
                VocabField(
                    "trigger", "Trigger", "text", required=True,
                    hint="What starts the clock, for example 'End of employment'",
                ),
                VocabField(
                    "legal_driver", "Legal driver", "textarea",
                    hint="The law or policy that sets this period, if there is one",
                ),
                VocabField(
                    "disposal_method", "Disposal method", "text",
                    hint="For example 'Secure shredding' or 'Deleted from the system'",
                ),
            ],
        ),
        VocabSpec(
            key="legal-entities",
            model=LegalEntity,
            display_name="Legal entity",
            label_attr="label",
            accepts_proposals=True,
            fields=[
                VocabField("label", "Label", "text", required=True),
                VocabField(
                    "role_type", "Role type", "enum", required=True, enum_cls=LegalEntityRoleType,
                    hint=(
                        "How this organisation relates to us, for example processor or partner "
                        "agency"
                    ),
                ),
                VocabField(
                    "contact", "Contact", "text",
                    hint="A name, role and email or phone number",
                ),
                VocabField("address", "Address", "textarea"),
                VocabField(
                    "country", "Country", "text",
                    hint="Where the organisation is based",
                ),
            ],
        ),
        VocabSpec(
            key="external-data-sources",
            model=ExternalDataSource,
            display_name="External data source",
            label_attr="name",
            accepts_proposals=True,
            fields=[
                VocabField("name", "Name", "text", required=True),
                VocabField(
                    "supplier_legal_entity_id",
                    "Supplier legal entity",
                    "fk",
                    fk_model=LegalEntity,
                ),
                VocabField(
                    "supplier_role", "Supplier role", "enum", enum_cls=SupplierRole,
                    hint=(
                        "Whether the supplier acts on our instructions (processor) or decides "
                        "for itself (separate controller)"
                    ),
                ),
                VocabField(
                    "agreement_ref", "Agreement reference", "text",
                    hint="The contract or data-sharing agreement number, if there is one",
                ),
                VocabField(
                    "special_category",
                    "Special category",
                    "enum",
                    required=True,
                    enum_cls=SourceSpecialCategory,
                    default=SourceSpecialCategory.NONE.value,
                    hint=(
                        "Does the source supply special category data directly, or can it be "
                        "inferred from the data?"
                    ),
                ),
                VocabField(
                    "art14_relationship", "Art 14 relationship", "textarea",
                    hint=(
                        "How the people concerned are told we hold their data when we did not "
                        "collect it from them (UK GDPR Art 14)"
                    ),
                ),
            ],
        ),
        VocabSpec(
            key="third-countries",
            model=ThirdCountry,
            display_name="Third country",
            label_attr="label",
            fields=[
                VocabField("label", "Label", "text", required=True),
                VocabField(
                    "adequacy_status",
                    "Adequacy status",
                    "enum",
                    required=True,
                    enum_cls=AdequacyStatus,
                    hint=(
                        "Whether the UK recognises this country as providing adequate data "
                        "protection"
                    ),
                ),
            ],
        ),
        VocabSpec(
            key="transfer-mechanisms",
            model=TransferMechanism,
            display_name="Transfer mechanism",
            label_attr="label",
            fields=[
                VocabField(
                    "code", "Code", "text", required=True,
                    hint="A short reference, for example 'IDTA'",
                ),
                VocabField("label", "Label", "text", required=True),
            ],
        ),
        VocabSpec(
            key="lawful-bases-general",
            model=LawfulBasisGeneral,
            display_name="Lawful basis (Art 6 / s35)",
            label_attr="label",
            editable=False,
            fields=[
                VocabField("code", "Code", "text"),
                VocabField("label", "Label", "text"),
                VocabField("public_authority_restricted", "Public authority restricted", "bool"),
            ],
        ),
        VocabSpec(
            key="lawful-bases-le",
            model=LawfulBasisLE,
            display_name="Lawful basis (s35, law enforcement)",
            label_attr="label",
            editable=False,
            fields=[
                VocabField("code", "Code", "text"),
                VocabField("label", "Label", "text"),
            ],
        ),
        VocabSpec(
            key="special-category-conditions",
            model=SpecialCategoryCondition,
            display_name="Special category condition (Art 9)",
            label_attr="label",
            editable=False,
            fields=[
                VocabField("code", "Code", "text"),
                VocabField("label", "Label", "text"),
                VocabField("needs_schedule1", "Needs Schedule 1", "bool"),
                VocabField("needs_apd", "Needs APD", "bool"),
            ],
        ),
        VocabSpec(
            key="schedule1-conditions",
            model=Schedule1Condition,
            display_name="Schedule 1 condition",
            label_attr="label",
            editable=False,
            fields=[
                VocabField("paragraph", "Paragraph", "text"),
                VocabField("label", "Label", "text"),
                VocabField("part", "Part", "text"),
                VocabField("needs_apd", "Needs APD", "bool"),
            ],
        ),
        VocabSpec(
            key="schedule8-conditions",
            model=Schedule8Condition,
            display_name="Schedule 8 condition",
            label_attr="label",
            editable=False,
            fields=[
                VocabField("paragraph", "Paragraph", "text"),
                VocabField("label", "Label", "text"),
            ],
        ),
        VocabSpec(
            key="privacy-notices",
            model=PrivacyNotice,
            display_name="Privacy notice",
            label_attr="notice_version",
            fields=[
                VocabField(
                    "notice_version", "Notice version", "text", required=True,
                    hint="For example 'Staff privacy notice v3'",
                ),
                VocabField("publish_date", "Publish date", "date", required=True),
                VocabField(
                    "covers_art13", "Covers Art 13", "bool",
                    hint="Tick if it tells people what we do with data we collect from them",
                ),
                VocabField(
                    "covers_art14", "Covers Art 14", "bool",
                    hint="Tick if it tells people what we do with data we get from someone else",
                ),
            ],
        ),
        VocabSpec(
            key="appropriate-policy-documents",
            model=AppropriatePolicyDocument,
            display_name="Appropriate Policy Document",
            label_attr="title",
            fields=[
                VocabField("title", "Title", "text", required=True),
                VocabField(
                    "scope", "Scope", "enum", required=True, enum_cls=APDScope,
                    hint=(
                        "Whether the document supports general processing (Schedule 1) or law "
                        "enforcement processing (s42)"
                    ),
                ),
                VocabField(
                    "document_ref", "Document reference", "text", required=True,
                    hint="Where the document is held, for example a policy number or link",
                ),
                VocabField(
                    "retain_until", "Retain until", "date", required=True,
                    hint=(
                        "The document must be kept until 6 months after the processing it "
                        "covers ends (DPA 2018 Sch 1 para 40)"
                    ),
                ),
            ],
        ),
    ]
}


def _enum_option_label(member) -> str:
    return member.value.replace("_", " ").capitalize().replace("Dpo", "DPO")


def _get_spec(key: str) -> VocabSpec:
    spec = VOCABULARIES.get(key)
    if spec is None:
        raise HTTPException(status_code=404)
    return spec


def _get_editable_spec(key: str) -> VocabSpec:
    spec = _get_spec(key)
    if not spec.editable:
        raise HTTPException(status_code=404)
    return spec


def _require_editor(user: User) -> None:
    if user.role not in (Role.CURATOR, Role.APPROVER_DPO):
        raise HTTPException(status_code=403, detail="Not permitted to edit vocabularies")


def _require_can_add(user: User, spec: VocabSpec) -> None:
    if user.role in (Role.CURATOR, Role.APPROVER_DPO):
        return
    if user.role == Role.CONTRIBUTOR and spec.accepts_proposals:
        return
    raise HTTPException(status_code=403, detail="Not permitted to add entries to this vocabulary")


def _fk_maps(session: Session, spec: VocabSpec) -> dict[str, dict[str, str]]:
    maps = {}
    for f in spec.fields:
        if f.kind == "fk":
            maps[f.name] = {
                o.id: getattr(o, f.fk_label_attr) for o in session.scalars(select(f.fk_model)).all()
            }
    return maps


def _valid_date(value: str) -> bool:
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _format_value(entry, f: VocabField, fk_maps: dict[str, dict[str, str]]):
    raw = getattr(entry, f.name)
    if f.kind == "bool":
        return "Yes" if raw else "No"
    if f.kind == "enum":
        return _enum_option_label(raw) if raw is not None else ""
    if f.kind == "fk":
        return fk_maps.get(f.name, {}).get(raw, "") if raw else ""
    if f.kind == "date":
        return raw.isoformat() if raw else ""
    return raw if raw is not None else ""


def _new_values(spec: VocabSpec) -> dict:
    values = {}
    for f in spec.fields:
        if f.kind == "bool":
            values[f.name] = False
        elif f.kind == "enum":
            values[f.name] = f.default if f.default is not None else next(iter(f.enum_cls)).value
        else:
            values[f.name] = ""
    return values


def _entity_to_values(entity, spec: VocabSpec) -> dict:
    values = {}
    for f in spec.fields:
        raw = getattr(entity, f.name)
        if f.kind == "bool":
            values[f.name] = bool(raw)
        elif f.kind == "enum":
            values[f.name] = raw.value if raw is not None else ""
        elif f.kind == "date":
            values[f.name] = raw.isoformat() if raw else ""
        else:
            values[f.name] = raw if raw is not None else ""
    return values


def _parse_vocab_form(form, spec: VocabSpec) -> dict:
    values = {}
    for f in spec.fields:
        if f.kind == "bool":
            values[f.name] = form.get(f.name) is not None
        elif f.kind in ("text", "textarea"):
            values[f.name] = form.get(f.name, "").strip()
        else:
            values[f.name] = form.get(f.name, "")
    return values


def _validate_vocab(session: Session, spec: VocabSpec, values: dict) -> list[dict]:
    errors = []
    for f in spec.fields:
        value = values[f.name]
        if f.kind in ("text", "textarea"):
            if f.required and not value:
                errors.append({"field": f.name, "message": f"Enter {f.label.lower()}"})
        elif f.kind == "enum":
            if not value:
                if f.required:
                    errors.append({"field": f.name, "message": f"Select {f.label.lower()}"})
            else:
                try:
                    f.enum_cls(value)
                except ValueError:
                    errors.append({"field": f.name, "message": "Select a valid option"})
        elif f.kind == "fk" and value and session.get(f.fk_model, value) is None:
            errors.append({"field": f.name, "message": f"Select a valid {f.label.lower()}"})
        elif f.kind == "date":
            if not value:
                if f.required:
                    errors.append({"field": f.name, "message": f"Enter {f.label.lower()}"})
            elif not _valid_date(value):
                errors.append({"field": f.name, "message": "Enter a valid date"})
    return errors


def _apply_vocab_values(entity, spec: VocabSpec, values: dict) -> None:
    for f in spec.fields:
        value = values[f.name]
        if f.kind == "bool":
            setattr(entity, f.name, value)
        elif f.kind == "enum":
            setattr(entity, f.name, f.enum_cls(value) if value else None)
        elif f.kind == "fk":
            setattr(entity, f.name, value or None)
        elif f.kind == "date":
            setattr(entity, f.name, date.fromisoformat(value) if value else None)
        else:
            setattr(entity, f.name, value if (f.required or value) else None)


def _field_rows(session: Session, spec: VocabSpec, values: dict, error_map: dict) -> list[dict]:
    rows = []
    for f in spec.fields:
        row = {
            "name": f.name,
            "label": f.label,
            "hint": f.hint,
            "kind": f.kind,
            "value": values[f.name],
            "error": error_map.get(f.name),
        }
        if f.kind == "enum":
            row["options"] = [(m.value, _enum_option_label(m)) for m in f.enum_cls]
        elif f.kind == "fk":
            options = session.scalars(
                select(f.fk_model).order_by(getattr(f.fk_model, f.fk_label_attr))
            ).all()
            row["options"] = [("", "None")] + [
                (o.id, getattr(o, f.fk_label_attr)) for o in options
            ]
        rows.append(row)
    return rows


def _vocab_form_context(
    session: Session,
    user: User,
    spec: VocabSpec,
    *,
    values: dict,
    errors: list[dict],
    csrf_token: str,
    is_edit: bool,
    entry_id: str | None = None,
) -> dict:
    error_map = {e["field"]: e["message"] for e in errors}
    return {
        "user": user,
        "spec": spec,
        "is_edit": is_edit,
        "entry_id": entry_id,
        "errors": errors,
        "csrf_token": csrf_token,
        "field_rows": _field_rows(session, spec, values, error_map),
    }


def _pending_count(session: Session, spec: VocabSpec) -> int:
    if not spec.accepts_proposals:
        return 0
    return session.scalar(
        select(func.count())
        .select_from(spec.model)
        .where(spec.model.entry_status == EntryStatus.PROPOSED)
    )


def pending_proposals_count(session: Session) -> int:
    return sum(_pending_count(session, spec) for spec in VOCABULARIES.values())


@router.get("/vocabularies")
def vocab_index(
    request: Request, user: User = Depends(current_user), session: Session = Depends(get_session)
):
    rows = [
        {
            "key": spec.key,
            "display_name": spec.display_name,
            "editable": spec.editable,
            "count": session.scalar(select(func.count()).select_from(spec.model)),
            "pending_count": _pending_count(session, spec),
        }
        for spec in VOCABULARIES.values()
    ]
    return templates.TemplateResponse(
        request,
        "vocabularies/index.html",
        {"user": user, "rows": rows, "csrf_token": get_csrf_token(request)},
    )


@router.get("/vocabularies/{key}")
def vocab_list(
    key: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    spec = _get_spec(key)
    entries = session.scalars(
        select(spec.model).order_by(getattr(spec.model, spec.label_attr))
    ).all()
    fk_maps = _fk_maps(session, spec)
    rows = [
        {
            "id": entry.id,
            "cells": [_format_value(entry, f, fk_maps) for f in spec.fields],
            "entry_status": getattr(entry, "entry_status", None),
        }
        for entry in entries
    ]
    can_edit = spec.editable and user.role in (Role.CURATOR, Role.APPROVER_DPO)
    can_moderate = user.role in (Role.CURATOR, Role.APPROVER_DPO)
    can_add = spec.editable and (
        can_edit or (spec.accepts_proposals and user.role == Role.CONTRIBUTOR)
    )
    return templates.TemplateResponse(
        request,
        "vocabularies/list.html",
        {
            "user": user,
            "spec": spec,
            "columns": [f.label for f in spec.fields],
            "rows": rows,
            "can_edit": can_edit,
            "can_add": can_add,
            "can_moderate": can_moderate,
            "csrf_token": get_csrf_token(request),
        },
    )


@router.get("/vocabularies/{key}/new")
def vocab_new_form(
    key: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    spec = _get_editable_spec(key)
    _require_can_add(user, spec)
    values = _new_values(spec)
    context = _vocab_form_context(
        session,
        user,
        spec,
        values=values,
        errors=[],
        csrf_token=get_csrf_token(request),
        is_edit=False,
    )
    return templates.TemplateResponse(request, "vocabularies/form.html", context)


@router.post("/vocabularies/{key}")
async def vocab_create(
    key: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    spec = _get_editable_spec(key)
    _require_can_add(user, spec)
    form = await request.form()
    verify_csrf(request, form.get("csrf_token"))
    values = _parse_vocab_form(form, spec)
    errors = _validate_vocab(session, spec, values)
    if errors:
        context = _vocab_form_context(
            session,
            user,
            spec,
            values=values,
            errors=errors,
            csrf_token=get_csrf_token(request),
            is_edit=False,
        )
        return templates.TemplateResponse(
            request, "vocabularies/form.html", context, status_code=422
        )
    entity = spec.model()
    _apply_vocab_values(entity, spec, values)
    if hasattr(entity, "entry_status") and user.role == Role.CONTRIBUTOR:
        entity.entry_status = EntryStatus.PROPOSED
    session.add(entity)
    session.flush()
    return RedirectResponse(f"/vocabularies/{key}", status_code=302)


@router.get("/vocabularies/{key}/{entry_id}/edit")
def vocab_edit_form(
    key: str,
    entry_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    spec = _get_editable_spec(key)
    _require_editor(user)
    entity = session.get(spec.model, entry_id)
    if entity is None:
        raise HTTPException(status_code=404)
    values = _entity_to_values(entity, spec)
    context = _vocab_form_context(
        session,
        user,
        spec,
        values=values,
        errors=[],
        csrf_token=get_csrf_token(request),
        is_edit=True,
        entry_id=entry_id,
    )
    return templates.TemplateResponse(request, "vocabularies/form.html", context)


@router.post("/vocabularies/{key}/{entry_id}")
async def vocab_update(
    key: str,
    entry_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    spec = _get_editable_spec(key)
    _require_editor(user)
    entity = session.get(spec.model, entry_id)
    if entity is None:
        raise HTTPException(status_code=404)
    form = await request.form()
    verify_csrf(request, form.get("csrf_token"))
    values = _parse_vocab_form(form, spec)
    errors = _validate_vocab(session, spec, values)
    if errors:
        context = _vocab_form_context(
            session,
            user,
            spec,
            values=values,
            errors=errors,
            csrf_token=get_csrf_token(request),
            is_edit=True,
            entry_id=entry_id,
        )
        return templates.TemplateResponse(
            request, "vocabularies/form.html", context, status_code=422
        )
    change_note = form.get("change_note", "").strip()
    _apply_vocab_values(entity, spec, values)
    if change_note:
        entity.change_note = change_note
    session.flush()
    return RedirectResponse(f"/vocabularies/{key}", status_code=302)


@router.post("/vocabularies/{key}/{entry_id}/approve")
async def vocab_approve(
    key: str,
    entry_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    spec = _get_spec(key)
    _require_editor(user)
    if not spec.accepts_proposals:
        raise HTTPException(status_code=404)
    entity = session.get(spec.model, entry_id)
    if entity is None:
        raise HTTPException(status_code=404)
    form = await request.form()
    verify_csrf(request, form.get("csrf_token"))
    if entity.entry_status != EntryStatus.PROPOSED:
        raise HTTPException(status_code=422, detail="Entry is not pending approval")
    entity.entry_status = EntryStatus.APPROVED
    entity.change_note = "Proposal approved"
    session.flush()
    record_event(session, entity=entity, event="vocab_approved", actor=user)
    if isinstance(entity, LegalEntity):
        resolve_supplier_gaps(session, entity, user)
    return RedirectResponse(f"/vocabularies/{key}", status_code=302)


@router.post("/vocabularies/{key}/{entry_id}/reject")
async def vocab_reject(
    key: str,
    entry_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    spec = _get_spec(key)
    _require_editor(user)
    if not spec.accepts_proposals:
        raise HTTPException(status_code=404)
    entity = session.get(spec.model, entry_id)
    if entity is None:
        raise HTTPException(status_code=404)
    form = await request.form()
    verify_csrf(request, form.get("csrf_token"))
    if entity.entry_status != EntryStatus.PROPOSED:
        raise HTTPException(status_code=422, detail="Entry is not pending approval")
    reason = form.get("reason", "").strip() or None
    entity.entry_status = EntryStatus.REJECTED
    entity.change_note = "Proposal rejected"
    session.flush()
    record_event(session, entity=entity, event="vocab_rejected", actor=user, reason=reason)
    return RedirectResponse(f"/vocabularies/{key}", status_code=302)
