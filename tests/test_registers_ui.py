from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from cairn.models import (
    ActivityFeeds,
    ActivityRetention,
    ActivitySecurity,
    AdequacyStatus,
    ContractDSA,
    DecisionSupportADM,
    ExternalDataSource,
    InformationAsset,
    LegalEntity,
    LegalEntityRoleType,
    LifecycleStage,
    OrganisationProfile,
    PrivacyNotice,
    ProcessingActivity,
    Recipient,
    RetentionRule,
    SecurityMeasure,
    SecurityMeasureCategory,
    ThirdCountry,
    Transfer,
    User,
)
from cairn.rules import evaluate
from conftest import business_function, transfer_mechanism
from test_activities import _create_activity, _extract_csrf, _login, _minimal_create_data, _token


def _findings_for(engine, activity_id: str):
    with Session(engine) as db:
        profile = db.scalars(select(OrganisationProfile)).first()
        activity = db.get(ProcessingActivity, activity_id)
        return evaluate(activity, profile)


def _has_rule(engine, activity_id: str, rule_id: str) -> bool:
    return any(f.rule_id == rule_id for f in _findings_for(engine, activity_id))


def _get_token_for(client, url: str) -> str:
    return _extract_csrf(client.get(url).text)


def _first_recipient_id(engine) -> str:
    with Session(engine) as db:
        return db.scalars(select(Recipient)).first().id


def _add_third_country(engine, *, label="Testland"):
    with Session(engine) as db:
        country = ThirdCountry(label=label, adequacy_status=AdequacyStatus.NOT_ADEQUATE)
        db.add(country)
        db.commit()
        return country.id


def _add_security_measure(engine, *, label):
    with Session(engine) as db:
        measure = SecurityMeasure(label=label, category=SecurityMeasureCategory.TECHNICAL)
        db.add(measure)
        db.commit()
        return measure.id


def _add_retention_rule(engine, *, label="Standard retention"):
    with Session(engine) as db:
        rule = RetentionRule(label=label, period="6 years", trigger="closure")
        db.add(rule)
        db.commit()
        return rule.id


def _add_system(engine, *, label="Case Management System", default_retention_id=None):
    with Session(engine) as db:
        system = InformationAsset(label=label, default_retention_id=default_retention_id)
        db.add(system)
        db.commit()
        return system.id


def _add_legal_entity(engine, *, label="Neighbouring Fire Authority"):
    with Session(engine) as db:
        entity = LegalEntity(label=label, role_type=LegalEntityRoleType.PARTNER_AGENCY)
        db.add(entity)
        db.commit()
        return entity.id


def _add_data_source(engine, *, name="CACI Acorn"):
    with Session(engine) as db:
        source = ExternalDataSource(name=name)
        db.add(source)
        db.commit()
        return source.id


def _add_privacy_notice(engine, *, notice_version="v1"):
    with Session(engine) as db:
        notice = PrivacyNotice(
            notice_version=notice_version,
            publish_date=date(2026, 1, 1),
            covers_art13=True,
            covers_art14=False,
        )
        db.add(notice)
        db.commit()
        return notice.id


def test_dpia_round_trip_clears_rule7_and_sign_off_limited_to_approver(
    activities_client, activities_web_engine
):
    activity_id = _create_activity(
        activities_client,
        activities_web_engine,
        login_as="Cara Curator",
        vulnerable_or_safeguarding_flag="true",
    )
    assert _has_rule(activities_web_engine, activity_id, "7")

    detail = activities_client.get(f"/activities/{activity_id}")
    assert "Consider Art 9(2)(g)" in detail.text

    new_form = activities_client.get(f"/activities/{activity_id}/dpias/new")
    assert new_form.status_code == 200
    with Session(activities_web_engine) as db:
        cara_id = db.scalars(select(User).where(User.display_name == "Cara Curator")).one().id
    assert 'name="sign_off_by"' in new_form.text
    sign_off_select = new_form.text.split('name="sign_off_by"')[1].split("</select>")[0]
    assert "Ada Approver" in sign_off_select
    assert cara_id not in sign_off_select
    token = _extract_csrf(new_form.text)

    created = activities_client.post(
        f"/activities/{activity_id}/dpias/new",
        data={
            "csrf_token": token,
            "screening_outcome": "required",
            "residual_risk": "high",
            "review_date": "2026-12-01",
        },
    )
    assert created.status_code == 302
    assert not _has_rule(activities_web_engine, activity_id, "7")

    detail_after = activities_client.get(f"/activities/{activity_id}")
    assert "Consult Information Commission" in detail_after.text


def test_dpia_author_forbidden_for_contributor(activities_client, activities_web_engine):
    activity_id = _create_activity(
        activities_client, activities_web_engine, login_as="Cara Curator"
    )
    _login(activities_client, activities_web_engine, "Cody Contributor")
    response = activities_client.get(f"/activities/{activity_id}/dpias/new")
    assert response.status_code == 403


def test_transfer_round_trip_clears_rule11_adequacy_exempt(
    activities_client, activities_web_engine
):
    activity_id = _create_activity(
        activities_client, activities_web_engine, login_as="Cara Curator"
    )
    country_id = _add_third_country(activities_web_engine)
    recipient_id = _first_recipient_id(activities_web_engine)
    with Session(activities_web_engine) as db:
        idta_id = transfer_mechanism(db, "idta").id
        adequacy_id = transfer_mechanism(db, "adequacy").id

    new_form = activities_client.get(f"/activities/{activity_id}/transfers/new")
    assert new_form.status_code == 200
    token = _extract_csrf(new_form.text)
    created = activities_client.post(
        f"/activities/{activity_id}/transfers/new",
        data={
            "csrf_token": token,
            "recipient_id": recipient_id,
            "third_country_id": country_id,
            "mechanism_id": idta_id,
            "data_protection_test": "",
        },
    )
    assert created.status_code == 302
    assert _has_rule(activities_web_engine, activity_id, "11")

    with Session(activities_web_engine) as db:
        transfer_id = (
            db.scalars(select(Transfer).where(Transfer.activity_id == activity_id)).one().id
        )

    edit_form = activities_client.get(f"/activities/{activity_id}/transfers/{transfer_id}/edit")
    edit_token = _extract_csrf(edit_form.text)
    updated = activities_client.post(
        f"/activities/{activity_id}/transfers/{transfer_id}/edit",
        data={
            "csrf_token": edit_token,
            "recipient_id": recipient_id,
            "third_country_id": country_id,
            "mechanism_id": idta_id,
            "data_protection_test": "Assessed as not materially lower.",
        },
    )
    assert updated.status_code == 302
    assert not _has_rule(activities_web_engine, activity_id, "11")

    adequacy_activity_id = _create_activity(
        activities_client, activities_web_engine, login_as="Cara Curator"
    )
    adequacy_form_token = _get_token_for(
        activities_client, f"/activities/{adequacy_activity_id}/transfers/new"
    )
    activities_client.post(
        f"/activities/{adequacy_activity_id}/transfers/new",
        data={
            "csrf_token": adequacy_form_token,
            "recipient_id": recipient_id,
            "third_country_id": country_id,
            "mechanism_id": adequacy_id,
            "data_protection_test": "",
        },
    )
    assert not _has_rule(activities_web_engine, adequacy_activity_id, "11")


def test_transfer_author_forbidden_for_contributor(activities_client, activities_web_engine):
    activity_id = _create_activity(
        activities_client, activities_web_engine, login_as="Cara Curator"
    )
    _login(activities_client, activities_web_engine, "Cody Contributor")
    response = activities_client.get(f"/activities/{activity_id}/transfers/new")
    assert response.status_code == 403


def test_contract_create_link_unlink_clears_rule13_for_joint(
    activities_client, activities_web_engine
):
    joint_activity_id = _create_activity(
        activities_client,
        activities_web_engine,
        login_as="Cara Curator",
        controller_or_processor="joint",
    )
    assert _has_rule(activities_web_engine, joint_activity_id, "13")
    entity_id = _add_legal_entity(activities_web_engine)

    new_form = activities_client.get(f"/activities/{joint_activity_id}/contracts/new")
    assert new_form.status_code == 200
    token = _extract_csrf(new_form.text)
    created = activities_client.post(
        f"/activities/{joint_activity_id}/contracts/new",
        data={
            "csrf_token": token,
            "type": "joint_controller",
            "parties": [entity_id],
            "start_date": "2026-01-01",
            "review_date": "2027-01-01",
            "expiry_date": "",
        },
    )
    assert created.status_code == 302
    assert not _has_rule(activities_web_engine, joint_activity_id, "13")

    with Session(activities_web_engine) as db:
        contract_id = db.scalars(select(ContractDSA)).one().id

    other_activity_id = _create_activity(
        activities_client,
        activities_web_engine,
        login_as="Cara Curator",
        controller_or_processor="joint",
    )
    link_token = _token(activities_client)
    link_response = activities_client.post(
        f"/activities/{other_activity_id}/contracts/link",
        data={"csrf_token": link_token, "contract_id": contract_id},
    )
    assert link_response.status_code == 302
    assert not _has_rule(activities_web_engine, other_activity_id, "13")

    unlink_token = _token(activities_client)
    unlink_response = activities_client.post(
        f"/activities/{other_activity_id}/contracts/{contract_id}/unlink",
        data={"csrf_token": unlink_token},
    )
    assert unlink_response.status_code == 302
    assert _has_rule(activities_web_engine, other_activity_id, "13")
    assert not _has_rule(activities_web_engine, joint_activity_id, "13")


def test_contract_author_forbidden_for_contributor(activities_client, activities_web_engine):
    activity_id = _create_activity(
        activities_client, activities_web_engine, login_as="Cara Curator"
    )
    _login(activities_client, activities_web_engine, "Cody Contributor")
    response = activities_client.get(f"/activities/{activity_id}/contracts/new")
    assert response.status_code == 403


def test_adm_section_shown_only_when_relevant(activities_client, activities_web_engine):
    plain_id = _create_activity(
        activities_client, activities_web_engine, login_as="Cara Curator"
    )
    plain_detail = activities_client.get(f"/activities/{plain_id}")
    assert "Decision-support / ADM" not in plain_detail.text

    adm_id = _create_activity(
        activities_client,
        activities_web_engine,
        login_as="Cara Curator",
        external_data_use_mode="manual",
    )
    adm_detail = activities_client.get(f"/activities/{adm_id}")
    assert "Decision-support / ADM" in adm_detail.text


def test_adm_round_trip_data_sources_limited_to_linked(activities_client, activities_web_engine):
    activity_id = _create_activity(
        activities_client,
        activities_web_engine,
        login_as="Cara Curator",
        external_data_use_mode="manual",
    )
    source_id = _add_data_source(activities_web_engine)
    link_token = _token(activities_client)
    activities_client.post(
        f"/activities/{activity_id}/data-sources",
        data={"csrf_token": link_token, "item_id": source_id},
    )

    new_form = activities_client.get(f"/activities/{activity_id}/adm/new")
    assert new_form.status_code == 200
    assert f'value="{source_id}"' in new_form.text
    token = _extract_csrf(new_form.text)

    created = activities_client.post(
        f"/activities/{activity_id}/adm/new",
        data={
            "csrf_token": token,
            "use_mode": "manual",
            "data_sources": [source_id],
        },
    )
    assert created.status_code == 302

    detail = activities_client.get(f"/activities/{activity_id}")
    assert "Decision-support / ADM" in detail.text


def test_adm_author_forbidden_for_contributor(activities_client, activities_web_engine):
    activity_id = _create_activity(
        activities_client,
        activities_web_engine,
        login_as="Cara Curator",
        external_data_use_mode="manual",
    )
    _login(activities_client, activities_web_engine, "Cody Contributor")
    response = activities_client.get(f"/activities/{activity_id}/adm/new")
    assert response.status_code == 403


def test_adm_automated_requires_explicit_tristate_answers(
    activities_client, activities_web_engine
):
    activity_id = _create_activity(
        activities_client,
        activities_web_engine,
        login_as="Cara Curator",
        external_data_use_mode="manual",
    )
    source_id = _add_data_source(activities_web_engine)
    link_token = _token(activities_client)
    activities_client.post(
        f"/activities/{activity_id}/data-sources",
        data={"csrf_token": link_token, "item_id": source_id},
    )
    token = _get_token_for(activities_client, f"/activities/{activity_id}/adm/new")

    response = activities_client.post(
        f"/activities/{activity_id}/adm/new",
        data={
            "csrf_token": token,
            "use_mode": "automated",
            "data_sources": [source_id],
        },
    )
    assert response.status_code == 422
    assert "Answer whether decisions are solely automated" in response.text
    assert "Answer whether decisions have legal or similarly significant effects" in response.text


def test_adm_automated_round_trip_persists_tristate_answers(
    activities_client, activities_web_engine
):
    activity_id = _create_activity(
        activities_client,
        activities_web_engine,
        login_as="Cara Curator",
        external_data_use_mode="manual",
    )
    source_id = _add_data_source(activities_web_engine)
    link_token = _token(activities_client)
    activities_client.post(
        f"/activities/{activity_id}/data-sources",
        data={"csrf_token": link_token, "item_id": source_id},
    )
    token = _get_token_for(activities_client, f"/activities/{activity_id}/adm/new")

    response = activities_client.post(
        f"/activities/{activity_id}/adm/new",
        data={
            "csrf_token": token,
            "use_mode": "automated",
            "solely_automated": "true",
            "significant_effects": "false",
            "data_sources": [source_id],
        },
    )
    assert response.status_code == 302

    with Session(activities_web_engine) as db:
        adm = db.scalars(
            select(DecisionSupportADM).where(DecisionSupportADM.activity_id == activity_id)
        ).one()
        assert adm.solely_automated is True
        assert adm.significant_effects is False


def test_adm_manual_round_trip_persists_none_when_unanswered(
    activities_client, activities_web_engine
):
    activity_id = _create_activity(
        activities_client,
        activities_web_engine,
        login_as="Cara Curator",
        external_data_use_mode="manual",
    )
    source_id = _add_data_source(activities_web_engine)
    link_token = _token(activities_client)
    activities_client.post(
        f"/activities/{activity_id}/data-sources",
        data={"csrf_token": link_token, "item_id": source_id},
    )
    token = _get_token_for(activities_client, f"/activities/{activity_id}/adm/new")

    response = activities_client.post(
        f"/activities/{activity_id}/adm/new",
        data={
            "csrf_token": token,
            "use_mode": "manual",
            "data_sources": [source_id],
        },
    )
    assert response.status_code == 302

    with Session(activities_web_engine) as db:
        adm = db.scalars(
            select(DecisionSupportADM).where(DecisionSupportADM.activity_id == activity_id)
        ).one()
        assert adm.solely_automated is None
        assert adm.significant_effects is None
        adm_id = adm.id

    edit_form = activities_client.get(f"/activities/{activity_id}/adm/{adm_id}/edit")
    assert 'name="solely_automated" type="radio" value="true" checked' not in edit_form.text
    assert 'name="solely_automated" type="radio" value="false" checked' not in edit_form.text
    assert 'name="significant_effects" type="radio" value="true" checked' not in edit_form.text
    assert 'name="significant_effects" type="radio" value="false" checked' not in edit_form.text

    detail = activities_client.get(f"/activities/{activity_id}")
    assert detail.text.count("Not assessed") == 2


def test_feeds_editor_and_fed_by_and_rule10(activities_client, activities_web_engine):
    analytics_id = _create_activity(
        activities_client,
        activities_web_engine,
        login_as="Cara Curator",
        activity_type="analytics_modelling",
    )
    consumer_id = _create_activity(
        activities_client,
        activities_web_engine,
        login_as="Cara Curator",
        name="Consumer Activity",
    )

    analytics_detail = activities_client.get(f"/activities/{analytics_id}")
    assert "Feeds (consumer activities)" in analytics_detail.text
    assert "Fed by" not in analytics_detail.text

    consumer_detail = activities_client.get(f"/activities/{consumer_id}")
    assert "Fed by" in consumer_detail.text
    assert "Feeds (consumer activities)" not in consumer_detail.text

    assert _has_rule(activities_web_engine, analytics_id, "10")

    token = _token(activities_client)
    add_feed = activities_client.post(
        f"/activities/{analytics_id}/feeds",
        data={"csrf_token": token, "consumer_activity_id": consumer_id},
    )
    assert add_feed.status_code == 302

    dpia_form = activities_client.get(f"/activities/{analytics_id}/dpias/new")
    dpia_token = _extract_csrf(dpia_form.text)
    activities_client.post(
        f"/activities/{analytics_id}/dpias/new",
        data={"csrf_token": dpia_token, "screening_outcome": "not_required"},
    )

    assert not _has_rule(activities_web_engine, analytics_id, "10")

    consumer_detail_after = activities_client.get(f"/activities/{consumer_id}")
    assert "Test Activity" in consumer_detail_after.text

    with Session(activities_web_engine) as db:
        feed = db.scalars(
            select(ActivityFeeds).where(ActivityFeeds.source_activity_id == analytics_id)
        ).one()
        feed_id = feed.id

    remove_token = _token(activities_client)
    remove_feed = activities_client.post(
        f"/activities/{analytics_id}/feeds/{feed_id}/remove",
        data={"csrf_token": remove_token},
    )
    assert remove_feed.status_code == 302
    assert _has_rule(activities_web_engine, analytics_id, "10")


def test_feeds_author_forbidden_for_contributor(activities_client, activities_web_engine):
    analytics_id = _create_activity(
        activities_client,
        activities_web_engine,
        login_as="Cara Curator",
        activity_type="analytics_modelling",
    )
    _login(activities_client, activities_web_engine, "Cody Contributor")
    token = _token(activities_client)
    response = activities_client.post(
        f"/activities/{analytics_id}/feeds",
        data={"csrf_token": token, "consumer_activity_id": "nope"},
    )
    assert response.status_code == 403


def test_retention_suggestion_prefill_and_add_remove(activities_client, activities_web_engine):
    activity_id = _create_activity(
        activities_client, activities_web_engine, login_as="Cara Curator"
    )
    rule_id = _add_retention_rule(activities_web_engine, label="6-year retention")
    system_id = _add_system(
        activities_web_engine, label="Records System", default_retention_id=rule_id
    )
    token = _token(activities_client)
    activities_client.post(
        f"/activities/{activity_id}/assets",
        data={"csrf_token": token, "item_id": system_id},
    )

    detail = activities_client.get(f"/activities/{activity_id}")
    assert "Suggested from Records System: 6-year retention" in detail.text

    suggest_token = _token(activities_client)
    add_response = activities_client.post(
        f"/activities/{activity_id}/retention",
        data={"csrf_token": suggest_token, "retention_rule_id": rule_id},
    )
    assert add_response.status_code == 302

    after_add = activities_client.get(f"/activities/{activity_id}")
    assert "Suggested from Records System" not in after_add.text
    assert "6-year retention" in after_add.text

    with Session(activities_web_engine) as db:
        link_id = (
            db.scalars(
                select(ActivityRetention).where(ActivityRetention.activity_id == activity_id)
            )
            .one()
            .id
        )

    remove_token = _token(activities_client)
    remove_response = activities_client.post(
        f"/activities/{activity_id}/retention/{link_id}/remove",
        data={"csrf_token": remove_token},
    )
    assert remove_response.status_code == 302
    after_remove = activities_client.get(f"/activities/{activity_id}")
    assert "No retention rules linked" in after_remove.text
    assert "Suggested from Records System: 6-year retention" in after_remove.text


def test_retention_author_forbidden_for_contributor(activities_client, activities_web_engine):
    activity_id = _create_activity(
        activities_client, activities_web_engine, login_as="Cara Curator"
    )
    rule_id = _add_retention_rule(activities_web_engine)
    _login(activities_client, activities_web_engine, "Cody Contributor")
    token = _token(activities_client)
    response = activities_client.post(
        f"/activities/{activity_id}/retention",
        data={"csrf_token": token, "retention_rule_id": rule_id},
    )
    assert response.status_code == 403


def test_security_inheritance_on_system_link_unlink(activities_client, activities_web_engine):
    activity_id = _create_activity(
        activities_client, activities_web_engine, login_as="Cara Curator"
    )
    system_id = _add_system(activities_web_engine, label="Mobile Data Terminal")
    with Session(activities_web_engine) as db:
        system = db.get(InformationAsset, system_id)
        measure = SecurityMeasure(
            label="disk encryption", category=SecurityMeasureCategory.TECHNICAL
        )
        db.add(measure)
        db.flush()
        system.security_measures.append(measure)
        db.commit()
        measure_id = measure.id

    token = _token(activities_client)
    activities_client.post(
        f"/activities/{activity_id}/assets",
        data={"csrf_token": token, "item_id": system_id},
    )

    detail = activities_client.get(f"/activities/{activity_id}")
    assert "disk encryption" in detail.text
    assert "Inherited from assets" in detail.text

    manual_measure_id = _add_security_measure(activities_web_engine, label="clean desk policy")
    add_token = _token(activities_client)
    activities_client.post(
        f"/activities/{activity_id}/security",
        data={"csrf_token": add_token, "security_measure_id": manual_measure_id},
    )

    with Session(activities_web_engine) as db:
        inherited_link_id = (
            db.scalars(
                select(ActivitySecurity).where(
                    ActivitySecurity.activity_id == activity_id,
                    ActivitySecurity.security_measure_id == measure_id,
                )
            )
            .one()
            .id
        )

    remove_token = _token(activities_client)
    remove_inherited = activities_client.post(
        f"/activities/{activity_id}/security/{inherited_link_id}/remove",
        data={"csrf_token": remove_token},
    )
    assert remove_inherited.status_code == 422

    unlink_token = _token(activities_client)
    activities_client.post(
        f"/activities/{activity_id}/assets/{system_id}/remove",
        data={"csrf_token": unlink_token},
    )

    after_unlink = activities_client.get(f"/activities/{activity_id}")
    assert "Inherited from assets" not in after_unlink.text
    assert "clean desk policy" in after_unlink.text


def test_security_author_forbidden_for_contributor(activities_client, activities_web_engine):
    activity_id = _create_activity(
        activities_client, activities_web_engine, login_as="Cara Curator"
    )
    measure_id = _add_security_measure(activities_web_engine, label="clean desk policy")
    _login(activities_client, activities_web_engine, "Cody Contributor")
    token = _token(activities_client)
    response = activities_client.post(
        f"/activities/{activity_id}/security",
        data={"csrf_token": token, "security_measure_id": measure_id},
    )
    assert response.status_code == 403


def test_privacy_notice_junction_and_adm_transparency_ref(
    activities_client, activities_web_engine
):
    activity_id = _create_activity(
        activities_client,
        activities_web_engine,
        login_as="Cara Curator",
        external_data_use_mode="manual",
    )
    notice_id = _add_privacy_notice(activities_web_engine)
    token = _token(activities_client)
    link_notice = activities_client.post(
        f"/activities/{activity_id}/privacy-notices",
        data={"csrf_token": token, "item_id": notice_id},
    )
    assert link_notice.status_code == 302

    detail = activities_client.get(f"/activities/{activity_id}")
    assert 'id="privacy-notices-section"' in detail.text

    adm_form = activities_client.get(f"/activities/{activity_id}/adm/new")
    assert f'value="{notice_id}"' in adm_form.text


def test_trial_gate_blocks_curator_allows_approver(activities_client, activities_web_engine):
    activity_id = _create_activity(
        activities_client,
        activities_web_engine,
        login_as="Cara Curator",
        lifecycle_stage="trial",
        trial_start="2026-01-01",
        trial_end="2026-06-01",
    )

    edit_page = activities_client.get(f"/activities/{activity_id}/edit")
    assert "Only the DPO/approver may move a trial to live" in edit_page.text
    token = _extract_csrf(edit_page.text)

    with Session(activities_web_engine) as db:
        owner_id = db.scalars(select(User).where(User.display_name == "Cara Curator")).one().id
        business_function_id = business_function(db, "Prevention & Community Safety").id

    data = _minimal_create_data(
        token,
        business_function_id,
        owner_id,
        lifecycle_stage="live",
        trial_start="2026-01-01",
        trial_end="2026-06-01",
    )
    curator_attempt = activities_client.post(f"/activities/{activity_id}", data=data)
    assert curator_attempt.status_code == 403
    assert "Only the DPO/approver may move a trial to live" in curator_attempt.text

    with Session(activities_web_engine) as db:
        activity = db.get(ProcessingActivity, activity_id)
        assert activity.lifecycle_stage == LifecycleStage.TRIAL

    _login(activities_client, activities_web_engine, "Ada Approver")
    approver_edit = activities_client.get(f"/activities/{activity_id}/edit")
    approver_token = _extract_csrf(approver_edit.text)
    approver_data = _minimal_create_data(
        approver_token,
        business_function_id,
        owner_id,
        lifecycle_stage="live",
        trial_start="2026-01-01",
        trial_end="2026-06-01",
    )
    approver_attempt = activities_client.post(f"/activities/{activity_id}", data=approver_data)
    assert approver_attempt.status_code == 302

    with Session(activities_web_engine) as db:
        activity = db.get(ProcessingActivity, activity_id)
        assert activity.lifecycle_stage == LifecycleStage.LIVE
