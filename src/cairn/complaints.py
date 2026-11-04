from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from cairn.auth import get_csrf_token, require_role, verify_csrf
from cairn.db import get_session
from cairn.models import ComplaintOutcome, ComplaintRecord, ProcessingActivity, Role, User
from cairn.templating import templates

router = APIRouter()

require_complaints_access = require_role(Role.CURATOR, Role.APPROVER_DPO)

ACK_DEADLINE_DAYS = 30
ACK_WARNING_DAYS = 7

OUTCOME_LABELS = {
    ComplaintOutcome.UPHELD: "Upheld",
    ComplaintOutcome.PARTLY_UPHELD: "Partly upheld",
    ComplaintOutcome.NOT_UPHELD: "Not upheld",
    ComplaintOutcome.WITHDRAWN: "Withdrawn",
}


def complaint_status(complaint: ComplaintRecord, today: date) -> tuple[str, str]:
    if complaint.outcome == ComplaintOutcome.WITHDRAWN:
        return "Withdrawn", "grey"
    if complaint.responded_at is not None:
        return "Responded", "green"
    if complaint.acknowledged_at is None:
        received_date = complaint.received_at.date()
        if today > received_date + timedelta(days=ACK_DEADLINE_DAYS):
            return "Acknowledgement overdue", "red"
        if today >= received_date + timedelta(days=ACK_DEADLINE_DAYS - ACK_WARNING_DAYS):
            return "Acknowledgement due soon", "yellow"
        return "Awaiting acknowledgement", "blue"
    if complaint.response_due < today:
        return "Response overdue", "red"
    return "Awaiting response", "blue"


def _activity_options(session: Session) -> list[tuple[str, str]]:
    activities = session.scalars(
        select(ProcessingActivity).order_by(ProcessingActivity.name)
    ).all()
    return [("", "Not linked")] + [(a.id, a.name) for a in activities]


def _new_values() -> dict:
    return {
        "activity_id": "",
        "received_at": "",
        "acknowledged_at": "",
        "response_due": "",
        "responded_at": "",
        "outcome": "",
        "outcome_communicated_at": "",
        "enquiries_note": "",
        "progress_updates": "",
        "ico_escalation_flagged": False,
    }


def _to_values(target: ComplaintRecord) -> dict:
    return {
        "activity_id": target.activity_id or "",
        "received_at": target.received_at.date().isoformat(),
        "acknowledged_at": target.acknowledged_at.date().isoformat()
        if target.acknowledged_at
        else "",
        "response_due": target.response_due.isoformat(),
        "responded_at": target.responded_at.date().isoformat() if target.responded_at else "",
        "outcome": target.outcome.value if target.outcome else "",
        "outcome_communicated_at": target.outcome_communicated_at.date().isoformat()
        if target.outcome_communicated_at
        else "",
        "enquiries_note": target.enquiries_note or "",
        "progress_updates": target.progress_updates or "",
        "ico_escalation_flagged": target.ico_escalation_flagged,
    }


def _parse_form(form) -> dict:
    return {
        "activity_id": form.get("activity_id", ""),
        "received_at": form.get("received_at", "").strip(),
        "acknowledged_at": form.get("acknowledged_at", "").strip(),
        "response_due": form.get("response_due", "").strip(),
        "responded_at": form.get("responded_at", "").strip(),
        "outcome": form.get("outcome", ""),
        "outcome_communicated_at": form.get("outcome_communicated_at", "").strip(),
        "enquiries_note": form.get("enquiries_note", "").strip(),
        "progress_updates": form.get("progress_updates", "").strip(),
        "ico_escalation_flagged": form.get("ico_escalation_flagged") is not None,
    }


def _valid_date(value: str) -> bool:
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _validate(session: Session, values: dict) -> list[dict]:
    errors = []
    if not values["received_at"]:
        errors.append(
            {"field": "received_at", "message": "Enter the date the complaint was received"}
        )
    elif not _valid_date(values["received_at"]):
        errors.append({"field": "received_at", "message": "Enter a valid date"})

    for field in ("acknowledged_at", "response_due", "responded_at", "outcome_communicated_at"):
        if values[field] and not _valid_date(values[field]):
            errors.append({"field": field, "message": "Enter a valid date"})

    received_valid = values["received_at"] and _valid_date(values["received_at"])
    received = date.fromisoformat(values["received_at"]) if received_valid else None

    if received and values["acknowledged_at"] and _valid_date(values["acknowledged_at"]):
        acknowledged = date.fromisoformat(values["acknowledged_at"])
        if acknowledged < received:
            errors.append(
                {
                    "field": "acknowledged_at",
                    "message": "Acknowledgement date cannot be before the date received",
                }
            )

    if received and values["responded_at"] and _valid_date(values["responded_at"]):
        responded = date.fromisoformat(values["responded_at"])
        if responded < received:
            errors.append(
                {
                    "field": "responded_at",
                    "message": "Response date cannot be before the date received",
                }
            )

    if values["outcome"] and not values["responded_at"]:
        errors.append({"field": "responded_at", "message": "Enter the date the response was sent"})

    if values["outcome"] and not values["outcome_communicated_at"]:
        errors.append(
            {
                "field": "outcome_communicated_at",
                "message": "Enter the date the outcome was communicated to the complainant",
            }
        )

    if values["activity_id"] and session.get(ProcessingActivity, values["activity_id"]) is None:
        errors.append({"field": "activity_id", "message": "Select a valid activity"})

    return errors


def _apply(target: ComplaintRecord, values: dict) -> None:
    received = date.fromisoformat(values["received_at"])
    target.activity_id = values["activity_id"] or None
    target.received_at = datetime.combine(received, time.min)
    target.acknowledged_at = (
        datetime.combine(date.fromisoformat(values["acknowledged_at"]), time.min)
        if values["acknowledged_at"]
        else None
    )
    target.response_due = (
        date.fromisoformat(values["response_due"])
        if values["response_due"]
        else received + timedelta(days=ACK_DEADLINE_DAYS)
    )
    target.responded_at = (
        datetime.combine(date.fromisoformat(values["responded_at"]), time.min)
        if values["responded_at"]
        else None
    )
    target.outcome = ComplaintOutcome(values["outcome"]) if values["outcome"] else None
    target.outcome_communicated_at = (
        datetime.combine(date.fromisoformat(values["outcome_communicated_at"]), time.min)
        if values["outcome_communicated_at"]
        else None
    )
    target.enquiries_note = values["enquiries_note"] or None
    target.progress_updates = values["progress_updates"] or None
    target.ico_escalation_flagged = values["ico_escalation_flagged"]


def _form_context(
    session: Session,
    user: User,
    *,
    values: dict,
    errors: list[dict],
    csrf_token: str,
    is_edit: bool,
    target_id: str | None = None,
) -> dict:
    error_map = {e["field"]: e["message"] for e in errors}
    return {
        "user": user,
        "is_edit": is_edit,
        "target_id": target_id,
        "values": values,
        "errors": errors,
        "error_map": error_map,
        "csrf_token": csrf_token,
        "activity_options": _activity_options(session),
        "outcome_options": [("", "Not decided")]
        + [(o.value, label) for o, label in OUTCOME_LABELS.items()],
    }


def _get_or_404(session: Session, complaint_id: str) -> ComplaintRecord:
    target = session.get(ComplaintRecord, complaint_id)
    if target is None:
        raise HTTPException(status_code=404)
    return target


@router.get("/complaints")
def complaint_list(
    request: Request,
    user: User = Depends(require_complaints_access),
    session: Session = Depends(get_session),
):
    activity_names = {
        a.id: a.name for a in session.scalars(select(ProcessingActivity)).all()
    }
    complaints = session.scalars(
        select(ComplaintRecord).order_by(ComplaintRecord.received_at.desc())
    ).all()
    today = date.today()
    rows = []
    for complaint in complaints:
        status_label, status_colour = complaint_status(complaint, today)
        rows.append(
            {
                "complaint": complaint,
                "activity_name": activity_names.get(complaint.activity_id, "—"),
                "status_label": status_label,
                "status_colour": status_colour,
                "outcome_label": OUTCOME_LABELS.get(complaint.outcome, "—"),
            }
        )
    return templates.TemplateResponse(
        request,
        "complaints/list.html",
        {"user": user, "rows": rows, "csrf_token": get_csrf_token(request)},
    )


@router.get("/complaints/new")
def complaint_new_form(
    request: Request,
    user: User = Depends(require_complaints_access),
    session: Session = Depends(get_session),
):
    context = _form_context(
        session,
        user,
        values=_new_values(),
        errors=[],
        csrf_token=get_csrf_token(request),
        is_edit=False,
    )
    return templates.TemplateResponse(request, "complaints/form.html", context)


@router.post("/complaints")
async def complaint_create(
    request: Request,
    user: User = Depends(require_complaints_access),
    session: Session = Depends(get_session),
):
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
        return templates.TemplateResponse(
            request, "complaints/form.html", context, status_code=422
        )
    target = ComplaintRecord()
    _apply(target, values)
    session.add(target)
    session.flush()
    return RedirectResponse("/complaints", status_code=302)


@router.get("/complaints/{complaint_id}/edit")
def complaint_edit_form(
    complaint_id: str,
    request: Request,
    user: User = Depends(require_complaints_access),
    session: Session = Depends(get_session),
):
    target = _get_or_404(session, complaint_id)
    context = _form_context(
        session,
        user,
        values=_to_values(target),
        errors=[],
        csrf_token=get_csrf_token(request),
        is_edit=True,
        target_id=target.id,
    )
    return templates.TemplateResponse(request, "complaints/form.html", context)


@router.post("/complaints/{complaint_id}")
async def complaint_update(
    complaint_id: str,
    request: Request,
    user: User = Depends(require_complaints_access),
    session: Session = Depends(get_session),
):
    target = _get_or_404(session, complaint_id)
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
            target_id=target.id,
        )
        return templates.TemplateResponse(
            request, "complaints/form.html", context, status_code=422
        )
    _apply(target, values)
    change_note = form.get("change_note", "").strip()
    if change_note:
        target.change_note = change_note
    session.flush()
    return RedirectResponse("/complaints", status_code=302)
