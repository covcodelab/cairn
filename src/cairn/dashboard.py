from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cairn.activities import RECORD_STATUS_LABELS, REGIME_LABELS
from cairn.audit import record_event
from cairn.auth import current_user, get_csrf_token, require_role
from cairn.complaints import complaint_status
from cairn.db import get_session
from cairn.export import EXPORT_VIEWS, build_export_context, export_views, render_csv
from cairn.models import (
    AssetType,
    BusinessFunction,
    ComplaintRecord,
    EntryStatus,
    InformationAsset,
    IntakeGap,
    IntakeStatus,
    IntakeSubmission,
    LifecycleStage,
    OrganisationProfile,
    ProcessingActivity,
    RecordStatus,
    Regime,
    Role,
    User,
    activity_asset,
)
from cairn.rules import Severity, evaluate, evaluate_asset
from cairn.setup import COMMENCEMENT_WATCH
from cairn.templating import templates
from cairn.vocabularies import pending_proposals_count

router = APIRouter()

TRIAL_WINDOW_DAYS = 60

require_add_user = require_role(Role.CONTRIBUTOR, Role.CURATOR, Role.APPROVER_DPO)
require_review_user = require_role(Role.CURATOR, Role.APPROVER_DPO)
require_manage_user = require_role(Role.APPROVER_DPO)

COMMENCEMENT_LABELS = {
    "duaa_principal": (
        "DUAA principal provisions — Arts 22A–22D ADM, s85 transfer test, "
        "purpose limitation (SI 2026/82)"
    ),
    "s164a_complaints": "DPA 2018 s164A complaints-handling duty",
    "information_commission": (
        "Information Commission replaces the ICO — DUAA ss 118–119 (SI 2026/1015)"
    ),
}


def _function_labels(session: Session) -> dict[str, str]:
    return {
        f.id: f.label
        for f in session.scalars(select(BusinessFunction).order_by(BusinessFunction.label)).all()
    }


def _asset_kpis(session: Session, today: date) -> dict:
    assets = session.scalars(select(InformationAsset)).all()
    type_counts = {t: 0 for t in AssetType}
    for asset in assets:
        type_counts[asset.asset_type] += 1
    linked_counts = dict(
        session.execute(
            select(activity_asset.c.asset_id, func.count(activity_asset.c.activity_id)).group_by(
                activity_asset.c.asset_id
            )
        ).all()
    )
    undocumented = sum(
        1
        for asset in assets
        if any(
            f.rule_id == "22" for f in evaluate_asset(asset, linked_counts.get(asset.id, 0))
        )
    )
    without_iao = sum(1 for asset in assets if asset.iao_user_id is None)
    review_overdue = sum(
        1
        for asset in assets
        if asset.next_review_date is not None and asset.next_review_date < today
    )
    return {
        "total_assets": len(assets),
        "asset_type_counts": [
            (t.value.replace("_", " ").capitalize(), count) for t, count in type_counts.items()
        ],
        "assets_undocumented_count": undocumented,
        "assets_without_iao_count": without_iao,
        "assets_review_overdue_count": review_overdue,
    }


_VIEWER_SECTIONS = frozenset({"register_overview", "asset_types", "overdue"})
_CURATOR_SECTIONS = _VIEWER_SECTIONS | {"attention", "complaints", "trials", "asset_attention"}
_APPROVER_SECTIONS = _CURATOR_SECTIONS | {"assurance", "commencement"}

SECTIONS_BY_ROLE: dict[Role, frozenset[str]] = {
    # A contributor is a respondent from anywhere in the organisation, often
    # visiting once — they get their own work, not the governance picture.
    Role.CONTRIBUTOR: frozenset({"your_intake"}),
    Role.VIEWER: _VIEWER_SECTIONS,
    Role.CURATOR: frozenset(_CURATOR_SECTIONS),
    Role.APPROVER_DPO: frozenset(_APPROVER_SECTIONS),
}


def sections_for_role(role: Role) -> frozenset[str]:
    return SECTIONS_BY_ROLE[role]


def _your_intake(session: Session, user: User) -> dict:
    submissions = session.scalars(
        select(IntakeSubmission)
        .where(IntakeSubmission.respondent_id == user.id)
        .order_by(IntakeSubmission.created_at.desc())
    ).all()
    return {
        "my_in_progress": [s for s in submissions if s.status == IntakeStatus.IN_PROGRESS],
        "my_submitted_count": sum(
            1 for s in submissions if s.status == IntakeStatus.SUBMITTED
        ),
        "my_open_gaps": sum(1 for s in submissions for g in s.gaps if not g.resolved),
        "my_total": len(submissions),
    }


def _findings(non_retired, profile) -> dict:
    block_count = 0
    warn_count = 0
    blocked_activities = 0
    for activity in non_retired:
        activity_blocked = False
        for finding in evaluate(activity, profile):
            if finding.severity == Severity.BLOCK:
                block_count += 1
                activity_blocked = True
            else:
                warn_count += 1
        if activity_blocked:
            blocked_activities += 1
    return {
        "block_count": block_count,
        "warn_count": warn_count,
        "blocked_activities": blocked_activities,
    }


def _queue_counts(session: Session) -> dict:
    return {
        "open_gap_count": session.scalar(
            select(func.count()).select_from(IntakeGap).where(IntakeGap.resolved.is_(False))
        ),
        "proposed_asset_count": session.scalar(
            select(func.count())
            .select_from(InformationAsset)
            .where(InformationAsset.entry_status == EntryStatus.PROPOSED)
        ),
        "pending_proposals": pending_proposals_count(session),
    }


def _function_counts(activities, function_labels: dict[str, str]) -> list[tuple[str, int]]:
    counts: dict[str, int] = {}
    for activity in activities:
        counts[activity.business_function_id] = counts.get(activity.business_function_id, 0) + 1
    ranked = sorted(counts.items(), key=lambda item: (-item[1], function_labels.get(item[0], "")))
    top = [(function_labels.get(fid, fid), count) for fid, count in ranked[:5]]
    other = sum(count for _, count in ranked[5:])
    if other:
        top.append(("Other", other))
    return top


@router.get("/")
def dashboard(
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    profile = session.scalars(select(OrganisationProfile)).first()
    if profile is None:
        return RedirectResponse("/setup", status_code=302)
    today = date.today()
    sections = sections_for_role(user.role)
    context: dict = {
        "user": user,
        "profile": profile,
        "sections": sections,
        "today": today,
        "csrf_token": get_csrf_token(request),
    }

    if "your_intake" in sections:
        return templates.TemplateResponse(
            request, "home.html", context | _your_intake(session, user)
        )

    activities = session.scalars(
        select(ProcessingActivity).order_by(ProcessingActivity.name)
    ).all()
    function_labels = _function_labels(session)

    status_counts = {status: 0 for status in RECORD_STATUS_LABELS}
    regime_counts = {regime: 0 for regime in REGIME_LABELS}
    for activity in activities:
        status_counts[activity.record_status] += 1
        regime_counts[activity.regime] += 1

    non_retired = [a for a in activities if a.record_status != RecordStatus.RETIRED]
    overdue = [a for a in non_retired if a.next_review_at and a.next_review_at < today]
    trial_horizon = today + timedelta(days=TRIAL_WINDOW_DAYS)
    trials_due = [
        a
        for a in non_retired
        if a.lifecycle_stage == LifecycleStage.TRIAL
        and a.trial_end is not None
        and a.trial_end <= trial_horizon
    ]

    # The rules engine runs over every non-retired activity, so only pay for it
    # where the role's shape actually shows findings or assurance.
    if {"attention", "assurance"} & sections:
        context |= _findings(non_retired, profile)
    if "attention" in sections:
        context |= _queue_counts(session)

    if "assurance" in sections:
        context["review_compliance"] = (
            round(100 * (len(non_retired) - len(overdue)) / len(non_retired))
            if non_retired
            else None
        )
        show_s61 = Regime.LAW_ENFORCEMENT in profile.applicable_regimes
        export_keys = ["art30_1", "art30_2", *(["s61"] if show_s61 else [])]
        export_coverage = [
            (
                EXPORT_VIEWS[key].title,
                sum(1 for a in activities if EXPORT_VIEWS[key].include(a, profile)),
            )
            for key in export_keys
        ]
        export_coverage.append(("Combined internal register", len(activities)))
        context["export_coverage"] = export_coverage

    if "complaints" in sections:
        open_complaints = session.scalars(
            select(ComplaintRecord).where(ComplaintRecord.responded_at.is_(None))
        ).all()
        complaints_attention = []
        for complaint in open_complaints:
            label, colour = complaint_status(complaint, today)
            if colour in ("red", "yellow"):
                complaints_attention.append((complaint, label, colour))
        context["open_complaints_count"] = len(open_complaints)
        context["complaints_attention"] = complaints_attention

    if "commencement" in sections:
        context["commencement_watch"] = [
            (COMMENCEMENT_LABELS.get(k, k), v)
            for k, v in sorted({**COMMENCEMENT_WATCH, **(profile.commencement_watch or {})}.items())
        ]

    context |= {
        "total_activities": len(activities),
        "status_counts": [
            (label, status_counts[status]) for status, label in RECORD_STATUS_LABELS.items()
        ],
        "regime_counts": [
            (label, regime_counts[regime]) for regime, label in REGIME_LABELS.items()
        ],
        "function_counts": _function_counts(activities, function_labels),
        "overdue": overdue,
        "trials_due": trials_due,
        "function_labels": function_labels,
        **_asset_kpis(session, today),
    }
    return templates.TemplateResponse(request, "home.html", context)


@router.get("/add")
def add_information(
    request: Request,
    user: User = Depends(require_add_user),
):
    return templates.TemplateResponse(
        request,
        "add.html",
        {
            "user": user,
            "can_curate": user.role in (Role.CURATOR, Role.APPROVER_DPO),
            "csrf_token": get_csrf_token(request),
        },
    )


@router.get("/review")
def review(
    request: Request,
    user: User = Depends(require_review_user),
):
    return templates.TemplateResponse(
        request,
        "review.html",
        {"user": user, "csrf_token": get_csrf_token(request)},
    )


@router.get("/manage")
def manage(
    request: Request,
    user: User = Depends(require_manage_user),
):
    return templates.TemplateResponse(
        request,
        "manage.html",
        {"user": user, "csrf_token": get_csrf_token(request)},
    )


@router.get("/register")
def register(
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    profile = session.scalars(select(OrganisationProfile)).first()
    if profile is None:
        return RedirectResponse("/setup", status_code=302)
    activities = session.scalars(
        select(ProcessingActivity).order_by(ProcessingActivity.name)
    ).all()
    function_labels = _function_labels(session)
    users_by_id = {u.id: u.display_name for u in session.scalars(select(User)).all()}
    show_s61 = Regime.LAW_ENFORCEMENT in profile.applicable_regimes
    export_keys = ["art30_1", "art30_2", *(["s61"] if show_s61 else []), "combined"]
    export_links = [(EXPORT_VIEWS[key].title, key) for key in export_keys]
    rows = [
        {
            "activity": activity,
            "business_function_label": function_labels.get(activity.business_function_id, ""),
            "export_views": sorted(export_views(activity, profile)),
            "owner": users_by_id.get(activity.owner_id, ""),
        }
        for activity in activities
    ]
    return templates.TemplateResponse(
        request,
        "register.html",
        {
            "user": user,
            "rows": rows,
            "record_status_labels": RECORD_STATUS_LABELS,
            "regime_labels": REGIME_LABELS,
            "show_s61": show_s61,
            "export_links": export_links,
            "csrf_token": get_csrf_token(request),
        },
    )


@router.get("/register/export/{view_key}")
def register_export(
    view_key: str,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    profile = session.scalars(select(OrganisationProfile)).first()
    if profile is None:
        return RedirectResponse("/setup", status_code=302)
    view = EXPORT_VIEWS.get(view_key)
    if view is None:
        raise HTTPException(status_code=404)
    if view_key == "s61" and Regime.LAW_ENFORCEMENT not in profile.applicable_regimes:
        raise HTTPException(status_code=404)
    activities = session.scalars(
        select(ProcessingActivity).order_by(ProcessingActivity.name)
    ).all()
    ctx = build_export_context(session, profile)
    text, row_count = render_csv(view, activities, ctx)
    record_event(
        session,
        entity=profile,
        event="register_exported",
        actor=user,
        new_value={"view": view_key, "rows": row_count},
    )
    filename = f"{view.filename_stem}-{date.today().isoformat()}.csv"
    return Response(
        content=text,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
