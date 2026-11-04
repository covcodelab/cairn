import csv
import io
from dataclasses import dataclass
from datetime import date, timedelta
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from cairn.audit import record_event
from cairn.auth import current_user, get_csrf_token, verify_csrf
from cairn.db import get_session
from cairn.inheritance import sync_inherited_security
from cairn.intake import submission_view
from cairn.models import (
    AssetStatus,
    AssetType,
    BusinessFunction,
    EntryStatus,
    InformationAsset,
    IntakeSubmission,
    LegalEntity,
    OrganisationProfile,
    ProcessingActivity,
    RecordStatus,
    RegimeSource,
    RetentionRule,
    Role,
    SecurityClassification,
    SecurityMeasure,
    User,
)
from cairn.regime import resolve_regime
from cairn.rules import Severity, evaluate_asset
from cairn.templating import templates

router = APIRouter()


@dataclass(frozen=True)
class AssetField:
    name: str
    label: str
    kind: str
    required: bool = False
    enum_cls: type | None = None
    fk_model: type | None = None
    fk_label_attr: str = "label"
    hint: str | None = None


ASSET_FIELDS: list[AssetField] = [
    AssetField(
        "label", "Label", "text", required=True,
        hint="The name people use, for example 'HR system' or 'Station log books'",
    ),
    AssetField("asset_type", "Asset type", "enum", required=True, enum_cls=AssetType),
    AssetField(
        "description", "Description", "textarea",
        hint="What it is and what information it holds",
    ),
    AssetField(
        "iao_user_id", "Information Asset Owner", "fk", fk_model=User,
        fk_label_attr="display_name",
        hint="The senior person accountable for this asset",
    ),
    AssetField(
        "custodian", "Custodian", "text",
        hint="Who looks after it day to day, for example 'IT service desk'",
    ),
    AssetField(
        "classification", "Classification", "enum", required=True, enum_cls=SecurityClassification,
        hint="The government security classification of the information",
    ),
    AssetField("contains_personal_data", "Contains personal data", "bool"),
    AssetField("status", "Status", "enum", required=True, enum_cls=AssetStatus),
    AssetField(
        "next_review_date", "Next review date", "date",
        hint="When the entry for this asset should next be checked",
    ),
    AssetField(
        "supplier_entity_id", "Supplier / hosting provider", "fk", fk_model=LegalEntity,
        hint="If the supplier is missing, ask a curator to add it",
    ),
    AssetField(
        "owner", "Owner (legacy)", "text",
        hint="Kept from an older record. Use Information Asset Owner for new entries",
    ),
    AssetField(
        "location", "Location", "text",
        hint="For example 'Server room' or 'Station 4 office'",
    ),
    AssetField(
        "hosting_country", "Hosting country", "text",
        hint="Where the data is stored, if it is a hosted service",
    ),
    AssetField(
        "default_retention_id", "Default retention rule", "fk", fk_model=RetentionRule,
        hint="How long information in this asset is usually kept",
    ),
    AssetField(
        "s62_logging_in_scope", "s62 logging in scope", "bool",
        hint=(
            "Law enforcement processing only. Tick if the asset must log who "
            "accessed or disclosed records (DPA 2018 s62)"
        ),
    ),
    AssetField("notes", "Notes", "textarea"),
]


def _enum_option_label(member) -> str:
    return member.value.replace("_", " ").capitalize()


def _display_label(entity) -> str:
    label = (
        getattr(entity, "label", None)
        or getattr(entity, "display_name", None)
        or str(entity.id)
    )
    if getattr(entity, "entry_status", None) == EntryStatus.PROPOSED:
        return f"{label} (proposed)"
    return label


def _get_asset(session: Session, asset_id: str) -> InformationAsset:
    asset = session.get(InformationAsset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404)
    return asset


def _require_editor(user: User) -> None:
    if user.role not in (Role.CURATOR, Role.APPROVER_DPO):
        raise HTTPException(status_code=403, detail="Not permitted to edit information assets")


def _require_can_add(user: User) -> None:
    if user.role in (Role.CURATOR, Role.APPROVER_DPO, Role.CONTRIBUTOR):
        return
    raise HTTPException(status_code=403, detail="Not permitted to add information assets")


def _require_can_create_activity(user: User) -> None:
    if user.role not in (Role.CONTRIBUTOR, Role.CURATOR, Role.APPROVER_DPO):
        raise HTTPException(status_code=403, detail="Not permitted to create activities")


def _valid_date(value: str) -> bool:
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _fk_maps(session: Session) -> dict[str, dict[str, str]]:
    maps = {}
    for f in ASSET_FIELDS:
        if f.kind == "fk":
            maps[f.name] = {
                o.id: getattr(o, f.fk_label_attr) for o in session.scalars(select(f.fk_model)).all()
            }
    return maps


def _new_values() -> dict:
    values = {}
    for f in ASSET_FIELDS:
        if f.kind == "bool":
            values[f.name] = False
        elif f.kind == "enum":
            values[f.name] = next(iter(f.enum_cls)).value
        else:
            values[f.name] = ""
    values["business_functions"] = []
    return values


def _entity_to_values(asset: InformationAsset) -> dict:
    values = {}
    for f in ASSET_FIELDS:
        raw = getattr(asset, f.name)
        if f.kind == "bool":
            values[f.name] = bool(raw)
        elif f.kind == "enum":
            values[f.name] = raw.value if raw is not None else ""
        elif f.kind == "date":
            values[f.name] = raw.isoformat() if raw else ""
        else:
            values[f.name] = raw if raw is not None else ""
    values["business_functions"] = [bf.id for bf in asset.business_functions]
    return values


def _parse_form(form) -> dict:
    values = {}
    for f in ASSET_FIELDS:
        if f.kind == "bool":
            values[f.name] = form.get(f.name) is not None
        elif f.kind in ("text", "textarea"):
            values[f.name] = form.get(f.name, "").strip()
        else:
            values[f.name] = form.get(f.name, "")
    values["business_functions"] = form.getlist("business_functions")
    return values


def _validate(session: Session, values: dict) -> list[dict]:
    errors = []
    for f in ASSET_FIELDS:
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
            if value and not _valid_date(value):
                errors.append({"field": f.name, "message": "Enter a valid date"})
    for bf_id in values["business_functions"]:
        if session.get(BusinessFunction, bf_id) is None:
            errors.append(
                {"field": "business_functions", "message": "Select a valid business function"}
            )
            break
    return errors


def _apply_values(session: Session, asset: InformationAsset, values: dict) -> None:
    for f in ASSET_FIELDS:
        value = values[f.name]
        if f.kind == "bool":
            setattr(asset, f.name, value)
        elif f.kind == "enum":
            setattr(asset, f.name, f.enum_cls(value) if value else None)
        elif f.kind == "fk":
            setattr(asset, f.name, value or None)
        elif f.kind == "date":
            setattr(asset, f.name, date.fromisoformat(value) if value else None)
        else:
            setattr(asset, f.name, value or None)
    target_ids = set(values["business_functions"])
    with session.no_autoflush:
        current = {bf.id: bf for bf in asset.business_functions}
        for bf_id, bf in current.items():
            if bf_id not in target_ids:
                asset.business_functions.remove(bf)
        for bf_id in target_ids:
            if bf_id not in current:
                bf = session.get(BusinessFunction, bf_id)
                if bf is not None:
                    asset.business_functions.append(bf)


def _format_value(asset: InformationAsset, f: AssetField, fk_maps: dict[str, dict[str, str]]):
    raw = getattr(asset, f.name)
    if f.kind == "bool":
        return "Yes" if raw else "No"
    if f.kind == "enum":
        return _enum_option_label(raw) if raw is not None else ""
    if f.kind == "fk":
        return fk_maps.get(f.name, {}).get(raw, "") if raw else ""
    if f.kind == "date":
        return raw.isoformat() if raw else ""
    return raw if raw is not None else ""


def _business_functions_label(asset: InformationAsset) -> str:
    return "; ".join(sorted(bf.label for bf in asset.business_functions))


def _detail_rows(session: Session, asset: InformationAsset) -> list[dict]:
    fk_maps = _fk_maps(session)
    rows = [
        {
            "label": f.label,
            "value": _format_value(asset, f, fk_maps),
            # Free text can hold newlines — intake writes multi-line notes.
            "multiline": f.kind == "textarea",
        }
        for f in ASSET_FIELDS
    ]
    insert_at = next((i + 1 for i, r in enumerate(rows) if r["label"] == "Custodian"), len(rows))
    bf_row = {
        "label": "Business functions",
        "value": _business_functions_label(asset),
        "multiline": False,
    }
    rows.insert(insert_at, bf_row)
    return rows


def _field_rows(session: Session, values: dict, error_map: dict) -> list[dict]:
    rows = []
    for f in ASSET_FIELDS:
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


def _form_context(
    session: Session,
    user: User,
    *,
    values: dict,
    errors: list[dict],
    csrf_token: str,
    is_edit: bool,
    asset_id: str | None = None,
) -> dict:
    error_map = {e["field"]: e["message"] for e in errors}
    return {
        "user": user,
        "is_edit": is_edit,
        "asset_id": asset_id,
        "errors": errors,
        "csrf_token": csrf_token,
        "field_rows": _field_rows(session, values, error_map),
        "business_functions": values["business_functions"],
        "business_function_options": _business_function_options(session),
        "business_functions_error": error_map.get("business_functions"),
    }


def _user_options(session: Session) -> list[tuple[str, str]]:
    users = session.scalars(select(User).where(User.is_active).order_by(User.display_name)).all()
    return [(u.id, u.display_name) for u in users]


def _business_function_options(session: Session) -> list[tuple[str, str]]:
    functions = session.scalars(select(BusinessFunction).order_by(BusinessFunction.label)).all()
    return [(f.id, f.label) for f in functions]


def _gap_flags(asset: InformationAsset, linked_activity_count: int, today: date) -> list[str]:
    gaps = []
    if asset.iao_user_id is None:
        gaps.append("No Information Asset Owner is set for this asset.")
    gaps.extend(finding.message for finding in evaluate_asset(asset, linked_activity_count))
    if asset.next_review_date is not None and asset.next_review_date < today:
        gaps.append(f"Review was due on {asset.next_review_date} and is now overdue.")
    return gaps


def _intake_context(session: Session, asset: InformationAsset) -> dict | None:
    submission = session.scalars(
        select(IntakeSubmission).where(IntakeSubmission.asset_id == asset.id)
    ).first()
    if submission is None:
        return None
    return submission_view(session, submission)


def _linked_activities(session: Session, asset: InformationAsset) -> list[ProcessingActivity]:
    return session.scalars(
        select(ProcessingActivity)
        .where(ProcessingActivity.assets.any(InformationAsset.id == asset.id))
        .order_by(ProcessingActivity.name)
    ).all()


def _filtered_assets_query(
    *,
    asset_type: str | None,
    business_function_id: str | None,
    iao_user_id: str | None,
    classification: str | None,
    contains_personal_data: str | None,
    status: str | None,
    review_overdue: str | None,
    mine: str | None,
    user: User,
    today: date,
):
    query = select(InformationAsset).order_by(InformationAsset.label)
    if asset_type:
        try:
            query = query.where(InformationAsset.asset_type == AssetType(asset_type))
        except ValueError:
            pass
    if business_function_id:
        query = query.where(
            InformationAsset.business_functions.any(BusinessFunction.id == business_function_id)
        )
    if iao_user_id:
        query = query.where(InformationAsset.iao_user_id == iao_user_id)
    if classification:
        try:
            query = query.where(
                InformationAsset.classification == SecurityClassification(classification)
            )
        except ValueError:
            pass
    if contains_personal_data in ("true", "false"):
        query = query.where(
            InformationAsset.contains_personal_data == (contains_personal_data == "true")
        )
    if status:
        try:
            query = query.where(InformationAsset.status == AssetStatus(status))
        except ValueError:
            pass
    if review_overdue == "true":
        query = query.where(
            InformationAsset.next_review_date.is_not(None),
            InformationAsset.next_review_date < today,
        )
    if mine == "true":
        query = query.where(InformationAsset.iao_user_id == user.id)
    return query


def _export_href(
    *,
    asset_type: str | None,
    business_function_id: str | None,
    iao_user_id: str | None,
    classification: str | None,
    contains_personal_data: str | None,
    status: str | None,
    review_overdue: str | None,
    mine: str | None,
) -> str:
    params = {
        "asset_type": asset_type or "",
        "business_function_id": business_function_id or "",
        "iao_user_id": iao_user_id or "",
        "classification": classification or "",
        "contains_personal_data": contains_personal_data or "",
        "status": status or "",
        "review_overdue": review_overdue or "",
        "mine": mine or "",
    }
    qs = urlencode({k: v for k, v in params.items() if v})
    return f"/assets/export.csv?{qs}" if qs else "/assets/export.csv"


@router.get("/assets")
def list_assets(
    request: Request,
    asset_type: str | None = None,
    business_function_id: str | None = None,
    iao_user_id: str | None = None,
    classification: str | None = None,
    contains_personal_data: str | None = None,
    status: str | None = None,
    review_overdue: str | None = None,
    mine: str | None = None,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    today = date.today()
    query = _filtered_assets_query(
        asset_type=asset_type,
        business_function_id=business_function_id,
        iao_user_id=iao_user_id,
        classification=classification,
        contains_personal_data=contains_personal_data,
        status=status,
        review_overdue=review_overdue,
        mine=mine,
        user=user,
        today=today,
    )
    assets = session.scalars(query).all()
    user_labels = dict(_user_options(session))
    rows = [
        {
            "asset": asset,
            "type_label": _enum_option_label(asset.asset_type),
            "iao_label": user_labels.get(asset.iao_user_id, ""),
            "business_function_label": _business_functions_label(asset),
            "classification_label": _enum_option_label(asset.classification),
            "status_label": _enum_option_label(asset.status),
            "overdue": asset.next_review_date is not None and asset.next_review_date < today,
        }
        for asset in assets
    ]
    can_add = user.role in (Role.CURATOR, Role.APPROVER_DPO, Role.CONTRIBUTOR)
    can_moderate = user.role in (Role.CURATOR, Role.APPROVER_DPO)
    export_href = _export_href(
        asset_type=asset_type,
        business_function_id=business_function_id,
        iao_user_id=iao_user_id,
        classification=classification,
        contains_personal_data=contains_personal_data,
        status=status,
        review_overdue=review_overdue,
        mine=mine,
    )
    return templates.TemplateResponse(
        request,
        "assets/list.html",
        {
            "user": user,
            "rows": rows,
            "can_add": can_add,
            "can_moderate": can_moderate,
            "export_href": export_href,
            "asset_type_options": [(m.value, _enum_option_label(m)) for m in AssetType],
            "classification_options": [
                (m.value, _enum_option_label(m)) for m in SecurityClassification
            ],
            "status_options": [(m.value, _enum_option_label(m)) for m in AssetStatus],
            "business_function_options": _business_function_options(session),
            "user_options": _user_options(session),
            "filters": {
                "asset_type": asset_type or "",
                "business_function_id": business_function_id or "",
                "iao_user_id": iao_user_id or "",
                "classification": classification or "",
                "contains_personal_data": contains_personal_data or "",
                "status": status or "",
                "review_overdue": review_overdue == "true",
                "mine": mine == "true",
            },
            "csrf_token": get_csrf_token(request),
        },
    )


@router.get("/assets/export.csv")
def export_assets_csv(
    asset_type: str | None = None,
    business_function_id: str | None = None,
    iao_user_id: str | None = None,
    classification: str | None = None,
    contains_personal_data: str | None = None,
    status: str | None = None,
    review_overdue: str | None = None,
    mine: str | None = None,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    query = _filtered_assets_query(
        asset_type=asset_type,
        business_function_id=business_function_id,
        iao_user_id=iao_user_id,
        classification=classification,
        contains_personal_data=contains_personal_data,
        status=status,
        review_overdue=review_overdue,
        mine=mine,
        user=user,
        today=date.today(),
    )
    assets = session.scalars(query).all()
    fk_maps = _fk_maps(session)
    headers = [f.label for f in ASSET_FIELDS]
    bf_index = headers.index("Custodian") + 1
    headers.insert(bf_index, "Business functions")
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(headers + ["Entry status", "Security measures"])
    for asset in assets:
        row = [_format_value(asset, f, fk_maps) for f in ASSET_FIELDS]
        row.insert(bf_index, _business_functions_label(asset))
        writer.writerow(
            row
            + [
                _enum_option_label(asset.entry_status),
                "; ".join(sorted(m.label for m in asset.security_measures)),
            ]
        )
    profile = session.scalars(select(OrganisationProfile)).first()
    if profile is not None:
        record_event(
            session,
            entity=profile,
            event="iar_exported",
            actor=user,
            new_value={
                "filters": {
                    "asset_type": asset_type or "",
                    "business_function_id": business_function_id or "",
                    "iao_user_id": iao_user_id or "",
                    "classification": classification or "",
                    "contains_personal_data": contains_personal_data or "",
                    "status": status or "",
                    "review_overdue": review_overdue or "",
                    "mine": mine or "",
                },
                "rows": len(assets),
            },
        )
    filename = f"information-asset-register-{date.today().isoformat()}.csv"
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/assets/new")
def new_asset_form(
    request: Request, user: User = Depends(current_user), session: Session = Depends(get_session)
):
    _require_can_add(user)
    context = _form_context(
        session,
        user,
        values=_new_values(),
        errors=[],
        csrf_token=get_csrf_token(request),
        is_edit=False,
    )
    return templates.TemplateResponse(request, "assets/form.html", context)


@router.post("/assets")
async def create_asset(
    request: Request, user: User = Depends(current_user), session: Session = Depends(get_session)
):
    _require_can_add(user)
    form = await request.form()
    verify_csrf(request, form.get("csrf_token"))
    values = _parse_form(form)
    errors = _validate(session, values)
    if errors:
        context = _form_context(
            session,
            user,
            values=values,
            errors=errors,
            csrf_token=get_csrf_token(request),
            is_edit=False,
        )
        return templates.TemplateResponse(request, "assets/form.html", context, status_code=422)
    asset = InformationAsset()
    _apply_values(session, asset, values)
    if user.role == Role.CONTRIBUTOR:
        asset.entry_status = EntryStatus.PROPOSED
    session.add(asset)
    session.flush()
    record_event(session, entity=asset, event="asset_created", actor=user)
    return RedirectResponse(f"/assets/{asset.id}", status_code=302)


@router.get("/assets/{asset_id}")
def asset_detail(
    asset_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    asset = _get_asset(session, asset_id)
    linked_activities = _linked_activities(session, asset)
    linked_measure_ids = {m.id for m in asset.security_measures}
    available_measures = session.scalars(
        select(SecurityMeasure)
        .where(SecurityMeasure.entry_status != EntryStatus.REJECTED)
        .order_by(SecurityMeasure.label)
    ).all()
    context = {
        "user": user,
        "asset": asset,
        "can_edit": user.role in (Role.CURATOR, Role.APPROVER_DPO),
        "can_moderate": user.role in (Role.CURATOR, Role.APPROVER_DPO),
        "can_create_activity": user.role in (Role.CONTRIBUTOR, Role.CURATOR, Role.APPROVER_DPO),
        "detail_rows": _detail_rows(session, asset),
        "linked_activities": linked_activities,
        "security_measures": [(m.id, _display_label(m)) for m in asset.security_measures],
        "security_measure_options": [
            (m.id, _display_label(m)) for m in available_measures if m.id not in linked_measure_ids
        ],
        "gap_flags": _gap_flags(asset, len(linked_activities), date.today()),
        "intake": _intake_context(session, asset),
        "csrf_token": get_csrf_token(request),
    }
    return templates.TemplateResponse(request, "assets/detail.html", context)


@router.get("/assets/{asset_id}/edit")
def edit_asset_form(
    asset_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    asset = _get_asset(session, asset_id)
    _require_editor(user)
    context = _form_context(
        session,
        user,
        values=_entity_to_values(asset),
        errors=[],
        csrf_token=get_csrf_token(request),
        is_edit=True,
        asset_id=asset_id,
    )
    return templates.TemplateResponse(request, "assets/form.html", context)


@router.post("/assets/{asset_id}")
async def update_asset(
    asset_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    asset = _get_asset(session, asset_id)
    _require_editor(user)
    form = await request.form()
    verify_csrf(request, form.get("csrf_token"))
    values = _parse_form(form)
    errors = _validate(session, values)
    if errors:
        context = _form_context(
            session,
            user,
            values=values,
            errors=errors,
            csrf_token=get_csrf_token(request),
            is_edit=True,
            asset_id=asset_id,
        )
        return templates.TemplateResponse(request, "assets/form.html", context, status_code=422)
    change_note = form.get("change_note", "").strip()
    _apply_values(session, asset, values)
    if change_note:
        asset.change_note = change_note
    session.flush()
    record_event(session, entity=asset, event="asset_updated", actor=user)
    return RedirectResponse(f"/assets/{asset.id}", status_code=302)


@router.post("/assets/{asset_id}/approve")
async def approve_asset(
    asset_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    asset = _get_asset(session, asset_id)
    _require_editor(user)
    form = await request.form()
    verify_csrf(request, form.get("csrf_token"))
    if asset.entry_status != EntryStatus.PROPOSED:
        raise HTTPException(status_code=422, detail="Entry is not pending approval")
    if any(f.severity == Severity.BLOCK for f in evaluate_asset(asset, 0)):
        raise HTTPException(
            status_code=422,
            detail="Cannot approve: this asset references reference data that is not "
            "approved yet",
        )
    asset.entry_status = EntryStatus.APPROVED
    asset.change_note = "Proposal approved"
    session.flush()
    record_event(session, entity=asset, event="asset_approved", actor=user)
    return RedirectResponse("/assets", status_code=302)


@router.post("/assets/{asset_id}/reject")
async def reject_asset(
    asset_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    asset = _get_asset(session, asset_id)
    _require_editor(user)
    form = await request.form()
    verify_csrf(request, form.get("csrf_token"))
    if asset.entry_status != EntryStatus.PROPOSED:
        raise HTTPException(status_code=422, detail="Entry is not pending approval")
    reason = form.get("reason", "").strip() or None
    asset.entry_status = EntryStatus.REJECTED
    asset.change_note = "Proposal rejected"
    session.flush()
    record_event(session, entity=asset, event="asset_rejected", actor=user, reason=reason)
    return RedirectResponse("/assets", status_code=302)


@router.post("/assets/{asset_id}/security-measures")
async def add_security_measure(
    asset_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    asset = _get_asset(session, asset_id)
    _require_editor(user)
    form = await request.form()
    verify_csrf(request, form.get("csrf_token"))
    measure_id = form.get("item_id")
    measure = session.get(SecurityMeasure, measure_id) if measure_id else None
    if measure is None:
        raise HTTPException(status_code=422, detail="Select a security measure")
    if measure.entry_status == EntryStatus.REJECTED:
        raise HTTPException(status_code=422, detail="This entry has been rejected")
    if measure not in asset.security_measures:
        asset.security_measures.append(measure)
        session.flush()
        for activity in _linked_activities(session, asset):
            sync_inherited_security(session, activity)
    return RedirectResponse(f"/assets/{asset.id}", status_code=302)


@router.post("/assets/{asset_id}/security-measures/{item_id}/remove")
async def remove_security_measure(
    asset_id: str,
    item_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    asset = _get_asset(session, asset_id)
    _require_editor(user)
    form = await request.form()
    verify_csrf(request, form.get("csrf_token"))
    measure = session.get(SecurityMeasure, item_id)
    if measure is not None and measure in asset.security_measures:
        asset.security_measures.remove(measure)
        session.flush()
        for activity in _linked_activities(session, asset):
            sync_inherited_security(session, activity)
    return RedirectResponse(f"/assets/{asset.id}", status_code=302)


@router.post("/assets/{asset_id}/document-processing")
async def document_processing(
    asset_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    asset = _get_asset(session, asset_id)
    _require_can_create_activity(user)
    form = await request.form()
    verify_csrf(request, form.get("csrf_token"))
    if asset.entry_status != EntryStatus.APPROVED:
        raise HTTPException(
            status_code=422, detail="Only approved assets can start a processing activity"
        )
    if len(asset.business_functions) == 1:
        business_function_id = asset.business_functions[0].id
    else:
        business_function_id = user.business_function_id
    if business_function_id is None:
        raise HTTPException(
            status_code=422,
            detail=(
                "Set a business function on the asset or your account "
                "before starting an activity"
            ),
        )
    if user.role == Role.CONTRIBUTOR and business_function_id != user.business_function_id:
        raise HTTPException(
            status_code=403,
            detail="Contributors may only create activities in their own business function",
        )
    activity = ProcessingActivity(
        name=f"Processing on {asset.label}",
        business_function_id=business_function_id,
        purpose="(not yet stated — describe the processing carried out using this asset)",
        personal_data_source=[],
        owner_id=user.id,
        next_review_at=date.today() + timedelta(days=365),
        record_status=RecordStatus.DRAFT,
    )
    activity.regime = resolve_regime(session, activity)
    activity.regime_source = RegimeSource.POLICY
    session.add(activity)
    session.flush()
    activity.assets.append(asset)
    session.flush()
    sync_inherited_security(session, activity)
    record_event(
        session,
        entity=activity,
        event="activity_created_from_asset",
        actor=user,
        new_value={"asset_id": asset.id},
    )
    return RedirectResponse(f"/activities/{activity.id}", status_code=302)
