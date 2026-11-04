from datetime import date, datetime

from cairn.models import (
    DPIA,
    AgeCheckOutcome,
    APDScope,
    ConsentMethod,
    ConsentRecord,
    ContractDSA,
    ContractType,
    ControllerOrProcessor,
    LawfulBasisRecord,
    LegalEntity,
    LegalEntityRoleType,
    LIADecision,
    LIARLIRecord,
    ProcessingActivity,
    RegimeScope,
    RLICondition,
    ScreeningOutcome,
)
from cairn.rules import Severity, evaluate
from conftest import art6, art9, business_function, make_apd, schedule1


def make_activity(session, actor, **overrides):
    defaults = dict(
        name="Test Activity",
        business_function_id=business_function(session, "Prevention & Community Safety").id,
        purpose="Test purpose.",
        personal_data_source=["from_data_subject"],
        owner_id=actor.id,
        next_review_at=date(2026, 12, 1),
    )
    defaults.update(overrides)
    activity = ProcessingActivity(**defaults)
    session.add(activity)
    session.flush()
    return activity


def make_basis(session, activity, **overrides):
    defaults = dict(activity_id=activity.id, regime_scope=RegimeScope.PART2)
    defaults.update(overrides)
    basis = LawfulBasisRecord(**defaults)
    session.add(basis)
    session.flush()
    return basis


def make_dpia(session, activity, **overrides):
    defaults = dict(activity_id=activity.id, screening_outcome=ScreeningOutcome.NOT_REQUIRED)
    defaults.update(overrides)
    dpia = DPIA(**defaults)
    session.add(dpia)
    session.flush()
    return dpia


def test_rule2_fires_when_schedule1_missing(session, actor, frs_profile):
    activity = make_activity(session, actor)
    make_basis(session, activity, art6_basis=art6(session, "e"), art9_condition=art9(session, "g"))
    findings = evaluate(activity, frs_profile)
    assert [f.rule_id for f in findings] == ["2"]
    assert "Schedule 1" in findings[0].message


def test_rule2_no_apd_needed_for_para2(session, actor, frs_profile):
    activity = make_activity(session, actor)
    make_basis(
        session,
        activity,
        art6_basis=art6(session, "e"),
        art9_condition=art9(session, "h"),
        schedule1_condition=schedule1(session, 2),
    )
    assert evaluate(activity, frs_profile) == []


def test_rule2_apd_required_for_para18(session, actor, frs_profile):
    activity = make_activity(session, actor)
    make_basis(
        session,
        activity,
        art6_basis=art6(session, "e"),
        art9_condition=art9(session, "g"),
        schedule1_condition=schedule1(session, 18),
    )
    findings = evaluate(activity, frs_profile)
    assert [f.rule_id for f in findings] == ["2"]
    assert "Appropriate Policy Document" in findings[0].message


def test_rule2_clears_with_apd(session, actor, frs_profile):
    activity = make_activity(session, actor)
    apd = make_apd(
        session, title="APD — Safeguarding", scope=APDScope.SCHEDULE1, document_ref="apd_sg"
    )
    make_basis(
        session,
        activity,
        art6_basis=art6(session, "e"),
        art9_condition=art9(session, "g"),
        schedule1_condition=schedule1(session, 18),
        apd=apd,
    )
    assert evaluate(activity, frs_profile) == []


def test_rule2_not_applicable_when_condition_does_not_need_schedule1(session, actor, frs_profile):
    activity = make_activity(session, actor)
    make_basis(session, activity, art6_basis=art6(session, "e"), art9_condition=art9(session, "c"))
    assert evaluate(activity, frs_profile) == []


def test_rule5_fires_without_lia(session, actor, frs_profile):
    activity = make_activity(session, actor)
    make_basis(session, activity, art6_basis=art6(session, "f"))
    findings = evaluate(activity, frs_profile)
    assert [f.rule_id for f in findings] == ["5"]


def test_rule5_fires_when_balancing_test_empty(session, actor, frs_profile):
    activity = make_activity(session, actor)
    basis = make_basis(session, activity, art6_basis=art6(session, "f"))
    session.add(
        LIARLIRecord(
            lawful_basis_record_id=basis.id,
            interest_identified="Legitimate interest.",
            necessity_test="Necessary for the purpose.",
            balancing_test=None,
            decision=LIADecision.PROCEED,
            decision_date=date(2026, 6, 1),
        )
    )
    session.flush()
    findings = evaluate(activity, frs_profile)
    assert [f.rule_id for f in findings] == ["5"]


def test_rule5_clears_with_balancing_test(session, actor, frs_profile):
    activity = make_activity(session, actor)
    basis = make_basis(session, activity, art6_basis=art6(session, "f"))
    session.add(
        LIARLIRecord(
            lawful_basis_record_id=basis.id,
            interest_identified="Legitimate interest.",
            necessity_test="Necessary for the purpose.",
            balancing_test="Impact is minimal and proportionate.",
            decision=LIADecision.PROCEED,
            decision_date=date(2026, 6, 1),
        )
    )
    session.flush()
    assert evaluate(activity, frs_profile) == []


def test_rule5_silent_when_basis_is_e(session, actor, frs_profile):
    activity = make_activity(session, actor)
    make_basis(session, activity, art6_basis=art6(session, "e"))
    assert evaluate(activity, frs_profile) == []


def test_rule6_not_applicable_when_basis_is_not_a(session, actor, frs_profile):
    activity = make_activity(session, actor)
    make_basis(session, activity, art6_basis=art6(session, "e"))
    assert evaluate(activity, frs_profile) == []


def test_rule6_fires_without_consent(session, actor, frs_profile):
    activity = make_activity(session, actor)
    make_basis(session, activity, art6_basis=art6(session, "a"))
    findings = evaluate(activity, frs_profile)
    assert [f.rule_id for f in findings] == ["6"]


def test_rule6_clears_with_consent_when_not_children(session, actor, frs_profile):
    activity = make_activity(session, actor, children_flag=False)
    basis = make_basis(session, activity, art6_basis=art6(session, "a"))
    session.add(
        ConsentRecord(
            lawful_basis_record_id=basis.id,
            consented_to="Contact for fire safety advice.",
            wording_shown="We will use your details to contact you about fire safety.",
            consent_datetime=datetime(2026, 6, 1, 10, 0),
            consent_method=ConsentMethod.ONLINE_FORM,
        )
    )
    session.flush()
    assert evaluate(activity, frs_profile) == []


def test_rule6_children_matrix_fires_without_age_check(session, actor, frs_profile):
    activity = make_activity(session, actor, children_flag=True)
    make_dpia(session, activity)
    basis = make_basis(session, activity, art6_basis=art6(session, "a"))
    session.add(
        ConsentRecord(
            lawful_basis_record_id=basis.id,
            consented_to="Contact for fire safety advice.",
            wording_shown="We will use your details to contact you about fire safety.",
            consent_datetime=datetime(2026, 6, 1, 10, 0),
            consent_method=ConsentMethod.ONLINE_FORM,
        )
    )
    session.flush()
    findings = evaluate(activity, frs_profile)
    assert [f.rule_id for f in findings] == ["6"]
    assert "age-check" in findings[0].message


def test_rule6_children_matrix_fires_when_under13_without_parental_consent(
    session, actor, frs_profile
):
    activity = make_activity(session, actor, children_flag=True)
    make_dpia(session, activity)
    basis = make_basis(session, activity, art6_basis=art6(session, "a"))
    session.add(
        ConsentRecord(
            lawful_basis_record_id=basis.id,
            consented_to="Contact for fire safety advice.",
            wording_shown="We will use your details to contact you about fire safety.",
            consent_datetime=datetime(2026, 6, 1, 10, 0),
            consent_method=ConsentMethod.ONLINE_FORM,
            age_check_outcome=AgeCheckOutcome.CHILD_UNDER_13,
            parental_consent_captured=False,
        )
    )
    session.flush()
    findings = evaluate(activity, frs_profile)
    assert [f.rule_id for f in findings] == ["6"]
    assert "parental" in findings[0].message


def test_rule6_children_matrix_clears_when_complete(session, actor, frs_profile):
    activity = make_activity(session, actor, children_flag=True)
    make_dpia(session, activity)
    basis = make_basis(session, activity, art6_basis=art6(session, "a"))
    session.add(
        ConsentRecord(
            lawful_basis_record_id=basis.id,
            consented_to="Contact for fire safety advice.",
            wording_shown="We will use your details to contact you about fire safety.",
            consent_datetime=datetime(2026, 6, 1, 10, 0),
            consent_method=ConsentMethod.ONLINE_FORM,
            age_check_outcome=AgeCheckOutcome.CHILD_UNDER_13,
            parental_consent_captured=True,
        )
    )
    session.flush()
    assert evaluate(activity, frs_profile) == []


def _rule13_finding(findings):
    return next((f for f in findings if f.rule_id == "13"), None)


def test_rule13_not_applicable_for_controller(session, actor, frs_profile):
    activity = make_activity(
        session, actor, controller_or_processor=ControllerOrProcessor.CONTROLLER
    )
    make_basis(session, activity, art6_basis=art6(session, "e"))
    assert evaluate(activity, frs_profile) == []


def test_rule13_processor_fires_without_categories_or_controllers(session, actor, frs_profile):
    activity = make_activity(
        session, actor, controller_or_processor=ControllerOrProcessor.PROCESSOR
    )
    finding = _rule13_finding(evaluate(activity, frs_profile))
    assert finding is not None
    assert "categories_of_processing" in finding.message


def test_rule13_processor_fires_with_categories_but_no_controllers(session, actor, frs_profile):
    activity = make_activity(
        session,
        actor,
        controller_or_processor=ControllerOrProcessor.PROCESSOR,
        categories_of_processing="Call handling and incident logging.",
    )
    finding = _rule13_finding(evaluate(activity, frs_profile))
    assert finding is not None
    assert "controller" in finding.message


def test_rule13_processor_clears_when_satisfied(session, actor, frs_profile):
    neighbour = LegalEntity(
        label="Neighbouring Fire Authority", role_type=LegalEntityRoleType.PARTNER_AGENCY
    )
    session.add(neighbour)
    session.flush()
    activity = make_activity(
        session,
        actor,
        controller_or_processor=ControllerOrProcessor.PROCESSOR,
        categories_of_processing="Call handling and incident logging.",
    )
    activity.controllers.append(neighbour)
    session.flush()
    assert _rule13_finding(evaluate(activity, frs_profile)) is None


def test_rule13_joint_fires_without_joint_contract(session, actor, frs_profile):
    activity = make_activity(session, actor, controller_or_processor=ControllerOrProcessor.JOINT)
    finding = _rule13_finding(evaluate(activity, frs_profile))
    assert finding is not None
    assert "joint-controller" in finding.message


def test_rule13_joint_clears_with_joint_contract(session, actor, frs_profile):
    activity = make_activity(session, actor, controller_or_processor=ControllerOrProcessor.JOINT)
    activity.contracts.append(
        ContractDSA(
            type=ContractType.JOINT_CONTROLLER,
            start_date=date(2026, 4, 1),
            review_date=date(2027, 4, 1),
        )
    )
    session.flush()
    assert _rule13_finding(evaluate(activity, frs_profile)) is None


def test_rule5_and_rule6_severity_is_block(session, actor, frs_profile):
    activity = make_activity(session, actor)
    make_basis(session, activity, art6_basis=art6(session, "f"))
    findings = evaluate(activity, frs_profile)
    assert findings[0].severity == Severity.BLOCK


def test_rule12_silent_for_processor_without_basis(session, actor, frs_profile):
    activity = make_activity(
        session,
        actor,
        controller_or_processor=ControllerOrProcessor.PROCESSOR,
        categories_of_processing="Call handling on documented instructions.",
    )
    rule_ids = {f.rule_id for f in evaluate(activity, frs_profile)}
    assert "12" not in rule_ids


def test_rule12_fires_for_joint_without_basis(session, actor, frs_profile):
    activity = make_activity(
        session, actor, controller_or_processor=ControllerOrProcessor.JOINT
    )
    rule_ids = {f.rule_id for f in evaluate(activity, frs_profile)}
    assert "12" in rule_ids


def _rli_record(session, basis, **overrides):
    session.add(
        LIARLIRecord(
            lawful_basis_record_id=basis.id,
            interest_identified="Recognised interest.",
            necessity_test="Necessary for the purpose.",
            decision=LIADecision.PROCEED,
            decision_date=date(2026, 6, 1),
            **overrides,
        )
    )
    session.flush()


def test_rule5_fires_for_ea_without_rli_record(session, actor, frs_profile):
    activity = make_activity(session, actor)
    make_basis(session, activity, art6_basis=art6(session, "ea"))
    findings = evaluate(activity, frs_profile)
    assert [f.rule_id for f in findings] == ["5"]
    assert "recognised legitimate interest" in findings[0].message.lower()


def test_rule5_fires_for_ea_when_condition_missing(session, actor, frs_profile):
    activity = make_activity(session, actor)
    basis = make_basis(session, activity, art6_basis=art6(session, "ea"))
    _rli_record(session, basis)
    assert [f.rule_id for f in evaluate(activity, frs_profile)] == ["5"]


def test_rule5_clears_for_ea_with_condition(session, actor, frs_profile):
    activity = make_activity(session, actor)
    basis = make_basis(session, activity, art6_basis=art6(session, "ea"))
    _rli_record(session, basis, rli_condition=RLICondition.EMERGENCIES)
    assert evaluate(activity, frs_profile) == []
