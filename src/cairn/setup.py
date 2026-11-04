from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from cairn.audit import record_event
from cairn.auth import get_csrf_token, start_authenticated_session, verify_csrf
from cairn.db import get_session
from cairn.models import LegalEntityTopology, OrganisationProfile, OrgType, Regime, Role, User
from cairn.seeds import seed_frs_pack, seed_legal
from cairn.templating import templates

router = APIRouter()

ACTIVE_MODULE_OPTIONS = [
    ("breach", "Breach"),
    ("complaints", "Complaints"),
    ("dpia", "DPIA"),
    ("lia_rli", "LIA / RLI"),
    ("contracts", "Contracts"),
    ("assets", "Assets"),
    ("external_data", "External data"),
]

ORG_TYPE_LABELS = {
    OrgType.PUBLIC_AUTHORITY: "Public authority",
    OrgType.PRIVATE_BODY: "Private body",
    OrgType.MIXED: "Mixed",
}

TOPOLOGY_LABELS = {
    LegalEntityTopology.SINGLE: "Single legal entity",
    LegalEntityTopology.GROUP: "Group",
    LegalEntityTopology.JOINT: "Joint",
}

REGIME_LABELS = {
    Regime.GENERAL: "General (UK GDPR / DPA 2018 Part 2)",
    Regime.LAW_ENFORCEMENT: "Law enforcement (DPA 2018 Part 3)",
}

COMMENCEMENT_WATCH = {
    "duaa_principal": "2026-02-05",
    "s164a_complaints": "2026-06-19",
    "information_commission": "2026-09-30",
}


def _guard(session: Session) -> None:
    existing = session.scalars(select(OrganisationProfile)).first()
    if existing is not None:
        raise HTTPException(status_code=404)


@router.get("/setup")
def setup_form(request: Request, session: Session = Depends(get_session)):
    _guard(session)
    return templates.TemplateResponse(
        request,
        "setup.html",
        {
            "org_type_options": list(ORG_TYPE_LABELS.items()),
            "topology_options": list(TOPOLOGY_LABELS.items()),
            "regime_options": list(REGIME_LABELS.items()),
            "module_options": ACTIVE_MODULE_OPTIONS,
            "csrf_token": get_csrf_token(request),
        },
    )


@router.post("/setup")
async def setup_submit(request: Request, session: Session = Depends(get_session)):
    _guard(session)
    form = await request.form()
    verify_csrf(request, form.get("csrf_token"))

    org_name = form.get("org_name", "").strip()
    org_type = OrgType(form.get("org_type"))
    legal_entity_topology = LegalEntityTopology(
        form.get("legal_entity_topology", LegalEntityTopology.SINGLE.value)
    )
    display_name = form.get("display_name", "").strip()
    if not org_name or not display_name:
        raise HTTPException(status_code=422, detail="org_name and display_name are required")

    applicable_regimes = {Regime.GENERAL.value, *form.getlist("applicable_regimes")}
    active_modules = {"complaints", *form.getlist("active_modules")}
    public_authority_guards = form.get("public_authority_guards") is not None

    profile = OrganisationProfile(
        org_name=org_name,
        org_type=org_type,
        legal_entity_topology=legal_entity_topology,
        applicable_regimes=sorted(applicable_regimes),
        active_modules=sorted(active_modules),
        public_authority_guards=public_authority_guards,
        commencement_watch=COMMENCEMENT_WATCH,
    )
    session.add(profile)
    session.flush()

    seed_legal(session)
    seed_frs_pack(session)

    bootstrap_email = form.get("bootstrap_email", "").strip().lower() or None
    bootstrap_user = User(
        display_name=display_name, email=bootstrap_email, role=Role.APPROVER_DPO
    )
    session.add(bootstrap_user)
    session.flush()

    record_event(
        session,
        entity=profile,
        event="organisation_setup",
        actor=bootstrap_user,
        new_value={"org_name": org_name, "org_type": org_type.value},
    )

    start_authenticated_session(request, bootstrap_user.id)

    return RedirectResponse("/", status_code=302)
