from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from cairn.models import (
    DPIA,
    EntryStatus,
    LifecycleStage,
    OrganisationProfile,
    ProcessingActivity,
    Recipient,
    RecipientType,
    RecordStatus,
    Regime,
    ScreeningOutcome,
)
from test_activities import _business_function_id, _extract_csrf, _login, _user_id


def _seed_dashboard_activities(engine) -> None:
    approver_id = _user_id(engine, "Ada Approver")
    prevention_id = _business_function_id(engine, "Prevention & Community Safety")
    protection_id = _business_function_id(
        engine, "Protection (Fire Safety Regulation & Enforcement)"
    )
    today = date.today()
    with Session(engine) as db:
        db.info["actor_id"] = approver_id
        trial_activity = ProcessingActivity(
            name="Trial Ending Activity",
            business_function_id=prevention_id,
            purpose="Purpose",
            personal_data_source=["from_data_subject"],
            owner_id=approver_id,
            next_review_at=today + timedelta(days=200),
            record_status=RecordStatus.DRAFT,
            lifecycle_stage=LifecycleStage.TRIAL,
            trial_start=today - timedelta(days=30),
            trial_end=today + timedelta(days=30),
        )
        db.add_all(
            [
                ProcessingActivity(
                    name="Overdue Review Activity",
                    business_function_id=prevention_id,
                    purpose="Purpose",
                    personal_data_source=["from_data_subject"],
                    owner_id=approver_id,
                    next_review_at=today - timedelta(days=10),
                    record_status=RecordStatus.ACTIVE,
                ),
                trial_activity,
                ProcessingActivity(
                    name="LE Register Activity",
                    business_function_id=protection_id,
                    purpose="Purpose",
                    personal_data_source=["from_data_subject"],
                    owner_id=approver_id,
                    next_review_at=today + timedelta(days=200),
                    record_status=RecordStatus.IN_REVIEW,
                    regime=Regime.LAW_ENFORCEMENT,
                ),
                ProcessingActivity(
                    name="Retired Old Activity",
                    business_function_id=protection_id,
                    purpose="Purpose",
                    personal_data_source=["from_data_subject"],
                    owner_id=approver_id,
                    next_review_at=today - timedelta(days=400),
                    record_status=RecordStatus.RETIRED,
                ),
            ]
        )
        db.flush()
        db.add(
            DPIA(
                activity_id=trial_activity.id,
                screening_outcome=ScreeningOutcome.REQUIRED,
            )
        )
        db.commit()


def test_dashboard_counts_and_lists(activities_client, activities_web_engine):
    _seed_dashboard_activities(activities_web_engine)
    _login(activities_client, activities_web_engine, "Ada Approver")
    response = activities_client.get("/")
    assert response.status_code == 200
    assert "4 processing activities recorded" in response.text

    assert "Overdue Review Activity" in response.text
    assert "Trial Ending Activity" in response.text
    assert "Ending soon" in response.text
    assert "Retired Old Activity" not in response.text

    assert "3 blocking" in response.text
    assert "0 warning" in response.text


def test_dashboard_empty_state(activities_client, activities_web_engine):
    _login(activities_client, activities_web_engine, "Ada Approver")
    response = activities_client.get("/")
    assert response.status_code == 200
    assert "0 processing activities recorded" in response.text
    assert "No overdue reviews" in response.text
    assert "No trials ending within 60 days" in response.text
    assert ">—<" in response.text


def test_dashboard_review_compliance_and_blocked(activities_client, activities_web_engine):
    _seed_dashboard_activities(activities_web_engine)
    with Session(activities_web_engine) as db:
        db.info["actor_id"] = _user_id(activities_web_engine, "Ada Approver")
        overdue = db.scalars(
            select(ProcessingActivity).where(
                ProcessingActivity.name == "Overdue Review Activity"
            )
        ).one()
        overdue.vulnerable_or_safeguarding_flag = True
        db.commit()

    _login(activities_client, activities_web_engine, "Ada Approver")
    response = activities_client.get("/")
    assert response.status_code == 200
    assert "67%" in response.text
    assert "4 blocking" in response.text
    assert "0 warning" in response.text
    marker = ">Activities blocked from approval</td>"
    start = response.text.index(marker) + len(marker)
    row_tail = response.text[start : start + 200]
    assert '--numeric">3</td>' in row_tail


def test_dashboard_review_compliance_full(activities_client, activities_web_engine):
    approver_id = _user_id(activities_web_engine, "Ada Approver")
    function_id = _business_function_id(activities_web_engine, "Prevention & Community Safety")
    today = date.today()
    with Session(activities_web_engine) as db:
        db.info["actor_id"] = approver_id
        db.add(
            ProcessingActivity(
                name="On Time Activity",
                business_function_id=function_id,
                purpose="Purpose",
                personal_data_source=["from_data_subject"],
                owner_id=approver_id,
                next_review_at=today + timedelta(days=200),
                record_status=RecordStatus.ACTIVE,
            )
        )
        db.commit()

    _login(activities_client, activities_web_engine, "Ada Approver")
    response = activities_client.get("/")
    assert response.status_code == 200
    assert "100%" in response.text


def test_dashboard_pending_proposals(activities_client, activities_web_engine):
    approver_id = _user_id(activities_web_engine, "Ada Approver")
    with Session(activities_web_engine) as db:
        db.info["actor_id"] = approver_id
        db.add(
            Recipient(
                label="Proposed Recipient",
                type=RecipientType.OTHER,
                entry_status=EntryStatus.PROPOSED,
            )
        )
        db.commit()

    _login(activities_client, activities_web_engine, "Ada Approver")
    response = activities_client.get("/")
    assert response.status_code == 200
    assert "Pending vocabulary proposals" in response.text
    assert '<a class="govuk-link" href="/vocabularies">1</a>' in response.text


def test_dashboard_export_coverage(activities_client, activities_web_engine):
    _seed_dashboard_activities(activities_web_engine)
    _login(activities_client, activities_web_engine, "Ada Approver")
    response = activities_client.get("/")
    assert response.status_code == 200
    assert "Art 30(1)" in response.text
    assert "DPA 2018 s61" in response.text
    assert "Combined internal register" in response.text
    register = activities_client.get("/register")
    assert '/register/export/art30_1"' in register.text
    assert '/register/export/combined"' in register.text


def test_dashboard_iar_export_row(activities_client, activities_web_engine):
    _seed_dashboard_activities(activities_web_engine)
    _login(activities_client, activities_web_engine, "Ada Approver")
    response = activities_client.get("/")
    assert response.status_code == 200
    assert "Information Asset Register" in response.text
    register = activities_client.get("/register")
    assert '/assets/export.csv"' in register.text


def test_dashboard_asset_kpis(activities_client, activities_web_engine):
    from cairn.models import InformationAsset

    with Session(activities_web_engine) as db:
        db.add_all(
            [
                InformationAsset(label="Case Management System", asset_type="system"),
                InformationAsset(
                    label="Paper Files",
                    asset_type="paper",
                    contains_personal_data=True,
                ),
                InformationAsset(
                    label="Overdue Asset",
                    asset_type="database",
                    next_review_date=date.today() - timedelta(days=5),
                ),
            ]
        )
        db.commit()
    _login(activities_client, activities_web_engine, "Ada Approver")
    response = activities_client.get("/")
    assert response.status_code == 200
    assert '/assets?contains_personal_data=true">1</a>' in response.text
    assert '/assets?review_overdue=true">1</a>' in response.text
    assert "Assets without an Information Asset Owner" in response.text


def test_dashboard_asset_kpi_excludes_proposed_supplier(
    activities_client, activities_web_engine
):
    from cairn.models import EntryStatus, InformationAsset, LegalEntity, LegalEntityRoleType

    with Session(activities_web_engine) as db:
        supplier = LegalEntity(
            label="Proposed Supplier Ltd",
            role_type=LegalEntityRoleType.PROCESSOR,
            entry_status=EntryStatus.PROPOSED,
        )
        db.add(supplier)
        db.flush()
        db.add(
            InformationAsset(
                label="Linked Asset With Proposed Supplier",
                supplier_entity_id=supplier.id,
                contains_personal_data=True,
            )
        )
        db.commit()
    _login(activities_client, activities_web_engine, "Ada Approver")
    response = activities_client.get("/")
    assert response.status_code == 200
    assert '/assets?contains_personal_data=true">1</a>' in response.text


def test_dashboard_commencement_watch_card_shows_statutory_defaults_without_stored_data(
    activities_client, activities_web_engine
):
    _login(activities_client, activities_web_engine, "Ada Approver")
    response = activities_client.get("/")
    assert response.status_code == 200
    assert "DUAA commencement" in response.text
    assert "in force since 2026-09-30" in response.text


def test_dashboard_commencement_watch_card(activities_client, activities_web_engine):
    approver_id = _user_id(activities_web_engine, "Ada Approver")
    with Session(activities_web_engine) as db:
        db.info["actor_id"] = approver_id
        profile = db.scalars(select(OrganisationProfile)).one()
        profile.commencement_watch = {
            "duaa_principal": "2026-02-05",
            "s164a_complaints": "2026-06-19",
        }
        db.commit()

    _login(activities_client, activities_web_engine, "Ada Approver")
    response = activities_client.get("/")
    assert response.status_code == 200
    assert "DUAA commencement" in response.text
    assert "in force since 2026-02-05" in response.text
    assert "in force since 2026-06-19" in response.text


def test_register_lists_all_activities_for_viewer(activities_client, activities_web_engine):
    _seed_dashboard_activities(activities_web_engine)
    _login(activities_client, activities_web_engine, "Vic Viewer")
    response = activities_client.get("/register")
    assert response.status_code == 200
    for name in (
        "Overdue Review Activity",
        "Trial Ending Activity",
        "LE Register Activity",
        "Retired Old Activity",
    ):
        assert name in response.text
    assert "Ada Approver" in response.text
    assert "s61" in response.text
    assert "art30_1" in response.text


def test_register_requires_login(activities_client):
    response = activities_client.get("/register")
    assert response.status_code == 302
    assert response.headers["location"] == "/login"


def test_mark_reviewed_removes_activity_from_overdue_dashboard(
    activities_client, activities_web_engine
):
    _seed_dashboard_activities(activities_web_engine)
    with Session(activities_web_engine) as db:
        activity_id = db.scalars(
            select(ProcessingActivity).where(
                ProcessingActivity.name == "Overdue Review Activity"
            )
        ).one().id

    _login(activities_client, activities_web_engine, "Ada Approver")
    before = activities_client.get("/")
    assert "Overdue Review Activity" in before.text

    detail_page = activities_client.get(f"/activities/{activity_id}")
    token = _extract_csrf(detail_page.text)
    future = (date.today() + timedelta(days=90)).isoformat()
    response = activities_client.post(
        f"/activities/{activity_id}/mark-reviewed",
        data={"csrf_token": token, "next_review_at": future},
    )
    assert response.status_code == 302

    after = activities_client.get("/")
    assert "Overdue Review Activity" not in after.text


# --- role-shaped dashboard -------------------------------------------------

def _start_intake(client, engine, name="Home fire safety visits"):
    from test_intake import _start

    return _start(client, engine, name=name)


def test_sections_for_role_membership():
    from cairn.dashboard import sections_for_role
    from cairn.models import Role

    contributor = sections_for_role(Role.CONTRIBUTOR)
    viewer = sections_for_role(Role.VIEWER)
    curator = sections_for_role(Role.CURATOR)
    approver = sections_for_role(Role.APPROVER_DPO)

    assert contributor == {"your_intake"}
    assert "register_overview" in viewer and "attention" not in viewer
    assert "attention" in curator and "assurance" not in curator
    assert "assurance" in approver and "commencement" in approver
    assert viewer < curator < approver


def test_contributor_dashboard_shows_own_work_only(activities_client, activities_web_engine):
    _seed_dashboard_activities(activities_web_engine)
    _login(activities_client, activities_web_engine, "Cody Contributor")
    response = activities_client.get("/")
    assert response.status_code == 200
    assert "Review compliance" not in response.text
    assert "DUAA commencement" not in response.text
    assert "Register overview" not in response.text
    assert "blocking" not in response.text
    assert "Describe an activity" in response.text


def test_contributor_dashboard_does_not_run_the_rules_engine(
    activities_client, activities_web_engine, monkeypatch
):
    _seed_dashboard_activities(activities_web_engine)

    def _boom(*args, **kwargs):
        raise AssertionError("rules engine must not run for a contributor")

    monkeypatch.setattr("cairn.dashboard.evaluate", _boom)
    _login(activities_client, activities_web_engine, "Cody Contributor")
    assert activities_client.get("/").status_code == 200


def test_contributor_sees_own_submissions_not_others(
    activities_client, activities_web_engine
):
    _login(activities_client, activities_web_engine, "Cody Contributor")
    _start_intake(activities_client, activities_web_engine, name="Cody's own intake")
    activities_client.post("/logout", data={"csrf_token": _extract_csrf(
        activities_client.get("/").text
    )})
    _login(activities_client, activities_web_engine, "Ollie OtherFunction")
    response = activities_client.get("/")
    assert response.status_code == 200
    assert "Cody's own intake" not in response.text


def test_contributor_empty_state_points_at_describe_actions(
    activities_client, activities_web_engine
):
    _login(activities_client, activities_web_engine, "Cody Contributor")
    response = activities_client.get("/")
    assert response.status_code == 200
    assert "not started" in response.text.lower()
    assert "/intake/new" in response.text
    assert "/intake/assets/new" in response.text


def test_contributor_in_progress_submission_is_listed_and_resumable(
    activities_client, activities_web_engine
):
    _login(activities_client, activities_web_engine, "Cody Contributor")
    submission_id = _start_intake(
        activities_client, activities_web_engine, name="Resume me"
    )
    response = activities_client.get("/")
    assert response.status_code == 200
    assert "Resume me" in response.text
    assert f"/intake/{submission_id}" in response.text


def test_viewer_sees_the_record_but_no_work_queues(
    activities_client, activities_web_engine
):
    _seed_dashboard_activities(activities_web_engine)
    _login(activities_client, activities_web_engine, "Vic Viewer")
    response = activities_client.get("/")
    assert response.status_code == 200
    assert "Register overview" in response.text
    assert "Overdue reviews" in response.text
    assert "Review compliance" not in response.text
    assert "Needs your attention" not in response.text
    assert "DUAA commencement" not in response.text


def test_curator_sees_attention_block_without_assurance(
    activities_client, activities_web_engine
):
    from cairn.models import InformationAsset

    with Session(activities_web_engine) as db:
        db.add(
            InformationAsset(
                label="Proposed Asset",
                asset_type="system",
                entry_status=EntryStatus.PROPOSED,
            )
        )
        db.commit()
    _login(activities_client, activities_web_engine, "Cara Curator")
    response = activities_client.get("/")
    assert response.status_code == 200
    assert "Needs your attention" in response.text
    assert "Information assets awaiting approval" in response.text
    assert "Review compliance" not in response.text


def test_curator_attention_counts_render_zero_rather_than_vanishing(
    activities_client, activities_web_engine
):
    _login(activities_client, activities_web_engine, "Cara Curator")
    response = activities_client.get("/")
    assert response.status_code == 200
    marker = ">Information assets awaiting approval</td>"
    start = response.text.index(marker) + len(marker)
    assert ">0<" in response.text[start : start + 200]


def test_dashboard_no_longer_offers_csv_downloads(
    activities_client, activities_web_engine
):
    _seed_dashboard_activities(activities_web_engine)
    _login(activities_client, activities_web_engine, "Ada Approver")
    response = activities_client.get("/")
    assert response.status_code == 200
    assert "Download CSV" not in response.text
    assert "Art 30(1)" in response.text
    assert 'href="/register"' in response.text


def test_dashboard_commencement_merges_statutory_defaults(
    activities_client, activities_web_engine
):
    approver_id = _user_id(activities_web_engine, "Ada Approver")
    with Session(activities_web_engine) as db:
        db.info["actor_id"] = approver_id
        profile = db.scalars(select(OrganisationProfile)).one()
        profile.commencement_watch = {"duaa_principal": "2026-02-05"}
        db.commit()

    _login(activities_client, activities_web_engine, "Ada Approver")
    response = activities_client.get("/")
    assert "Information Commission replaces the ICO" in response.text
    assert "in force since 2026-09-30" in response.text
