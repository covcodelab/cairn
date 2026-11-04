from sqlalchemy import select
from sqlalchemy.orm import Session

from cairn.models import (
    LawfulBasisRecord,
    LegalEntity,
    LegalEntityRoleType,
    LIARLIRecord,
    OrganisationProfile,
    PersonalDataCategory,
    ProcessingActivity,
    RegimeScope,
    RLICondition,
)
from cairn.rules import evaluate
from conftest import art6, s35, schedule8
from test_activities import _create_activity, _extract_csrf, _login, _token


def _basis_edit_token(client, activity_id: str, scope: str) -> str:
    page = client.get(f"/activities/{activity_id}/basis/{scope}/edit")
    return _extract_csrf(page.text)


def _add_data_category(engine, activity_id: str, *, label: str) -> None:
    with Session(engine) as db:
        activity = db.get(ProcessingActivity, activity_id)
        category = db.scalars(
            select(PersonalDataCategory).where(PersonalDataCategory.label == label)
        ).one()
        activity.data_categories.append(category)
        db.commit()


def _findings_for(engine, activity_id: str):
    with Session(engine) as db:
        profile = db.scalars(select(OrganisationProfile)).first()
        activity = db.get(ProcessingActivity, activity_id)
        return evaluate(activity, profile)


def test_basis_edit_contributor_forbidden(activities_client, activities_web_engine):
    activity_id = _create_activity(
        activities_client, activities_web_engine, login_as="Cara Curator"
    )
    _login(activities_client, activities_web_engine, "Cody Contributor")
    response = activities_client.get(f"/activities/{activity_id}/basis/part2/edit")
    assert response.status_code == 403


def test_basis_post_viewer_forbidden(activities_client, activities_web_engine):
    activity_id = _create_activity(
        activities_client, activities_web_engine, login_as="Cara Curator"
    )
    _login(activities_client, activities_web_engine, "Vic Viewer")
    response = activities_client.post(
        f"/activities/{activity_id}/basis/part2",
        data={"csrf_token": "no-token", "art6_basis_id": ""},
    )
    assert response.status_code == 403


def test_curator_can_create_and_edit_part2_basis(activities_client, activities_web_engine):
    activity_id = _create_activity(
        activities_client, activities_web_engine, login_as="Cara Curator"
    )
    token = _basis_edit_token(activities_client, activity_id, "part2")
    with Session(activities_web_engine) as db:
        e_id = art6(db, "e").id

    response = activities_client.post(
        f"/activities/{activity_id}/basis/part2",
        data={
            "csrf_token": token,
            "art6_basis_id": e_id,
            "art6_justification": "Statutory community fire safety function.",
        },
    )
    assert response.status_code == 302

    with Session(activities_web_engine) as db:
        basis = db.scalars(
            select(LawfulBasisRecord).where(
                LawfulBasisRecord.activity_id == activity_id,
                LawfulBasisRecord.regime_scope == RegimeScope.PART2,
            )
        ).one()
        assert basis.art6_basis_id == e_id
        assert basis.art6_justification == "Statutory community fire safety function."

    edit_token = _basis_edit_token(activities_client, activity_id, "part2")
    update = activities_client.post(
        f"/activities/{activity_id}/basis/part2",
        data={
            "csrf_token": edit_token,
            "art6_basis_id": e_id,
            "art6_justification": "Updated justification.",
            "change_note": "Clarified justification",
        },
    )
    assert update.status_code == 302
    with Session(activities_web_engine) as db:
        basis = db.scalars(
            select(LawfulBasisRecord).where(
                LawfulBasisRecord.activity_id == activity_id,
                LawfulBasisRecord.regime_scope == RegimeScope.PART2,
            )
        ).one()
        assert basis.art6_justification == "Updated justification."


def test_invalid_fk_in_basis_post_is_422(activities_client, activities_web_engine):
    activity_id = _create_activity(
        activities_client, activities_web_engine, login_as="Cara Curator"
    )
    token = _basis_edit_token(activities_client, activity_id, "part2")
    response = activities_client.post(
        f"/activities/{activity_id}/basis/part2",
        data={"csrf_token": token, "art6_basis_id": "not-a-real-id"},
    )
    assert response.status_code == 422


def test_dual_scope_authoring_and_retained_mapping(activities_client, activities_web_engine):
    activity_id = _create_activity(
        activities_client, activities_web_engine, login_as="Cara Curator"
    )
    with Session(activities_web_engine) as db:
        e_id = art6(db, "e").id
        s35_id = s35(db, "s35_task").id
        sch8_id = schedule8(db, 1).id

    part2_token = _basis_edit_token(activities_client, activity_id, "part2")
    activities_client.post(
        f"/activities/{activity_id}/basis/part2",
        data={
            "csrf_token": part2_token,
            "art6_basis_id": e_id,
            "art6_justification": "Statutory community fire safety function.",
        },
    )
    part3_token = _basis_edit_token(activities_client, activity_id, "part3")
    activities_client.post(
        f"/activities/{activity_id}/basis/part3",
        data={
            "csrf_token": part3_token,
            "s35_basis_id": s35_id,
            "schedule8_condition_id": sch8_id,
        },
    )

    detail = activities_client.get(f"/activities/{activity_id}")
    assert detail.status_code == 200
    assert "Retained — not the live mapping (Part 3 (law enforcement))" in detail.text
    assert "Statutory etc purposes" in detail.text
    assert "Public task" in detail.text

    _login(activities_client, activities_web_engine, "Ada Approver")
    override_token = _token(activities_client)
    flip = activities_client.post(
        f"/activities/{activity_id}/regime-override",
        data={
            "csrf_token": override_token,
            "target_regime": "law_enforcement",
            "reason": "Reclassified for dual-mapping test",
        },
    )
    assert flip.status_code == 302

    flipped_detail = activities_client.get(f"/activities/{activity_id}")
    assert "Retained — not the live mapping (Part 2 (general))" in flipped_detail.text


def test_part2_conditional_sections(activities_client, activities_web_engine):
    activity_id = _create_activity(
        activities_client, activities_web_engine, login_as="Cara Curator"
    )
    plain_form = activities_client.get(f"/activities/{activity_id}/basis/part2/edit")
    assert 'name="art9_condition_id"' not in plain_form.text
    assert 'name="art10_basis"' not in plain_form.text

    _add_data_category(activities_web_engine, activity_id, label="health data (casualty, OH, EMR)")
    special_form = activities_client.get(f"/activities/{activity_id}/basis/part2/edit")
    assert 'name="art9_condition_id"' in special_form.text
    assert 'name="art10_basis"' not in special_form.text

    _add_data_category(
        activities_web_engine,
        activity_id,
        label="criminal offence data (fire investigation / arson, employee vetting / DBS)",
    )
    criminal_form = activities_client.get(f"/activities/{activity_id}/basis/part2/edit")
    assert 'name="art10_basis"' in criminal_form.text


def test_guard_preselects_public_task_with_hint(activities_client, activities_web_engine):
    activity_id = _create_activity(
        activities_client,
        activities_web_engine,
        login_as="Cara Curator",
        is_statutory_task="true",
    )
    with Session(activities_web_engine) as db:
        e_id = art6(db, "e").id

    form = activities_client.get(f"/activities/{activity_id}/basis/part2/edit")
    assert form.status_code == 200
    assert f'value="{e_id}" selected' in form.text
    assert "flagged for DPO review" in form.text


def test_consent_flow_appears_and_clears_rule6(activities_client, activities_web_engine):
    activity_id = _create_activity(
        activities_client, activities_web_engine, login_as="Cara Curator", children_flag="true"
    )
    with Session(activities_web_engine) as db:
        a_id = art6(db, "a").id
    token = _basis_edit_token(activities_client, activity_id, "part2")
    activities_client.post(
        f"/activities/{activity_id}/basis/part2",
        data={"csrf_token": token, "art6_basis_id": a_id, "art6_justification": "Consent."},
    )

    detail = activities_client.get(f"/activities/{activity_id}")
    assert "Consent records" in detail.text
    assert any(f.rule_id == "6" for f in _findings_for(activities_web_engine, activity_id))

    consent_form = activities_client.get(
        f"/activities/{activity_id}/basis/part2/consents/new"
    )
    assert consent_form.status_code == 200
    assert 'name="age_check_outcome"' in consent_form.text
    consent_token = _extract_csrf(consent_form.text)

    add_consent = activities_client.post(
        f"/activities/{activity_id}/basis/part2/consents/new",
        data={
            "csrf_token": consent_token,
            "consented_to": "Contact for fire safety advice.",
            "wording_shown": "We will use your details to contact you about fire safety.",
            "consent_datetime": "2026-06-01T10:00",
            "consent_method": "online_form",
            "withdrawal_status": "active",
            "withdrawal_datetime": "",
            "review_due": "",
            "age_check_outcome": "adult",
        },
    )
    assert add_consent.status_code == 302

    assert not any(f.rule_id == "6" for f in _findings_for(activities_web_engine, activity_id))


def test_lia_flow_appears_and_clears_rule5(activities_client, activities_web_engine):
    activity_id = _create_activity(
        activities_client, activities_web_engine, login_as="Cara Curator"
    )
    with Session(activities_web_engine) as db:
        f_id = art6(db, "f").id
    token = _basis_edit_token(activities_client, activity_id, "part2")
    activities_client.post(
        f"/activities/{activity_id}/basis/part2",
        data={"csrf_token": token, "art6_basis_id": f_id, "art6_justification": "Interest."},
    )

    detail = activities_client.get(f"/activities/{activity_id}")
    assert "LIA / RLI records" in detail.text
    assert any(f.rule_id == "5" for f in _findings_for(activities_web_engine, activity_id))

    lia_form = activities_client.get(f"/activities/{activity_id}/basis/part2/lia/new")
    lia_token = _extract_csrf(lia_form.text)
    add_lia = activities_client.post(
        f"/activities/{activity_id}/basis/part2/lia/new",
        data={
            "csrf_token": lia_token,
            "interest_identified": "Legitimate interest in fire safety.",
            "necessity_test": "Necessary and proportionate.",
            "balancing_test": "Impact is minimal and proportionate.",
            "safeguards": "",
            "decision": "proceed",
            "decision_date": "2026-06-01",
        },
    )
    assert add_lia.status_code == 302

    assert not any(f.rule_id == "5" for f in _findings_for(activities_web_engine, activity_id))


def test_controllers_junction_only_for_processor_or_joint_and_clears_rule13(
    activities_client, activities_web_engine
):
    controller_activity_id = _create_activity(
        activities_client,
        activities_web_engine,
        login_as="Cara Curator",
        controller_or_processor="controller",
    )
    controller_detail = activities_client.get(f"/activities/{controller_activity_id}")
    assert 'id="controllers-section"' not in controller_detail.text

    processor_activity_id = _create_activity(
        activities_client,
        activities_web_engine,
        login_as="Cara Curator",
        controller_or_processor="processor",
        categories_of_processing="Call handling and incident logging.",
    )
    processor_detail = activities_client.get(f"/activities/{processor_activity_id}")
    assert 'id="controllers-section"' in processor_detail.text
    assert any(
        f.rule_id == "13" for f in _findings_for(activities_web_engine, processor_activity_id)
    )

    with Session(activities_web_engine) as db:
        neighbour = LegalEntity(
            label="Neighbouring Fire Authority", role_type=LegalEntityRoleType.PARTNER_AGENCY
        )
        db.add(neighbour)
        db.commit()
        neighbour_id = neighbour.id

    token = _token(activities_client)
    add_controller = activities_client.post(
        f"/activities/{processor_activity_id}/controllers",
        data={"csrf_token": token, "item_id": neighbour_id},
    )
    assert add_controller.status_code == 302

    assert not any(
        f.rule_id == "13" for f in _findings_for(activities_web_engine, processor_activity_id)
    )


def test_part2_blank_justification_rejected(activities_client, activities_web_engine):
    activity_id = _create_activity(
        activities_client, activities_web_engine, login_as="Cara Curator"
    )
    with Session(activities_web_engine) as db:
        e_id = art6(db, "e").id
    token = _basis_edit_token(activities_client, activity_id, "part2")
    response = activities_client.post(
        f"/activities/{activity_id}/basis/part2",
        data={"csrf_token": token, "art6_basis_id": e_id, "art6_justification": "  "},
    )
    assert response.status_code == 422
    assert "Enter the justification for the Art 6 basis" in response.text


def test_part3_does_not_require_justification(activities_client, activities_web_engine):
    activity_id = _create_activity(
        activities_client, activities_web_engine, login_as="Cara Curator"
    )
    with Session(activities_web_engine) as db:
        s35_id = s35(db, "s35_task").id
    token = _basis_edit_token(activities_client, activity_id, "part3")
    response = activities_client.post(
        f"/activities/{activity_id}/basis/part3",
        data={"csrf_token": token, "s35_basis_id": s35_id},
    )
    assert response.status_code == 302


def test_lia_form_records_rli_condition(activities_client, activities_web_engine):
    activity_id = _create_activity(
        activities_client, activities_web_engine, login_as="Cara Curator"
    )
    with Session(activities_web_engine) as db:
        ea_id = art6(db, "ea").id
    token = _basis_edit_token(activities_client, activity_id, "part2")
    activities_client.post(
        f"/activities/{activity_id}/basis/part2",
        data={"csrf_token": token, "art6_basis_id": ea_id, "art6_justification": "Emergency."},
    )
    form = activities_client.get(f"/activities/{activity_id}/basis/part2/lia/new")
    assert "Emergencies" in form.text
    response = activities_client.post(
        f"/activities/{activity_id}/basis/part2/lia/new",
        data={
            "csrf_token": _extract_csrf(form.text),
            "interest_identified": "Responding to an emergency.",
            "necessity_test": "Necessary.",
            "rli_condition": "emergencies",
            "decision": "proceed",
            "decision_date": "2026-06-01",
        },
    )
    assert response.status_code == 302
    with Session(activities_web_engine) as db:
        assert db.scalars(select(LIARLIRecord)).one().rli_condition == RLICondition.EMERGENCIES
