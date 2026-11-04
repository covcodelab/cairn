from datetime import date, datetime

from sqlalchemy import Column, ForeignKey, Table, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cairn.models.activity import ProcessingActivity
from cairn.models.base import AuditedBase, Base
from cairn.models.enums import (
    ADMUseMode,
    AgeCheckOutcome,
    APDScope,
    ComplaintOutcome,
    ConsentMethod,
    ContractType,
    LIADecision,
    RegimeScope,
    ResidualRisk,
    RLICondition,
    ScreeningOutcome,
    SubProcessorAuthorisation,
    WithdrawalStatus,
)
from cairn.models.vocab import (
    ExternalDataSource,
    LawfulBasisGeneral,
    LawfulBasisLE,
    LegalEntity,
    Recipient,
    Schedule1Condition,
    Schedule8Condition,
    SpecialCategoryCondition,
    ThirdCountry,
    TransferMechanism,
)


class AppropriatePolicyDocument(AuditedBase):
    __tablename__ = "appropriate_policy_document"

    title: Mapped[str]
    scope: Mapped[APDScope]
    document_ref: Mapped[str]
    retain_until: Mapped[date]


class LawfulBasisRecord(AuditedBase):
    __tablename__ = "lawful_basis_record"
    __table_args__ = (UniqueConstraint("activity_id", "regime_scope"),)

    activity_id: Mapped[str] = mapped_column(ForeignKey("processing_activity.id"))
    regime_scope: Mapped[RegimeScope]
    art6_basis_id: Mapped[str | None] = mapped_column(ForeignKey("lawful_basis_general.id"))
    art6_justification: Mapped[str | None] = mapped_column(Text)
    art9_condition_id: Mapped[str | None] = mapped_column(
        ForeignKey("special_category_condition.id")
    )
    schedule1_condition_id: Mapped[str | None] = mapped_column(ForeignKey("schedule1_condition.id"))
    art10_basis: Mapped[str | None]
    s35_basis_id: Mapped[str | None] = mapped_column(ForeignKey("lawful_basis_le.id"))
    schedule8_condition_id: Mapped[str | None] = mapped_column(ForeignKey("schedule8_condition.id"))
    apd_id: Mapped[str | None] = mapped_column(ForeignKey("appropriate_policy_document.id"))

    activity: Mapped[ProcessingActivity] = relationship(back_populates="basis_records")
    art6_basis: Mapped[LawfulBasisGeneral | None] = relationship()
    art9_condition: Mapped[SpecialCategoryCondition | None] = relationship()
    schedule1_condition: Mapped[Schedule1Condition | None] = relationship()
    s35_basis: Mapped[LawfulBasisLE | None] = relationship()
    schedule8_condition: Mapped[Schedule8Condition | None] = relationship()
    apd: Mapped[AppropriatePolicyDocument | None] = relationship()
    consent_records: Mapped[list[ConsentRecord]] = relationship(
        back_populates="lawful_basis_record"
    )
    lia_rli_records: Mapped[list[LIARLIRecord]] = relationship(
        back_populates="lawful_basis_record"
    )


class ConsentRecord(AuditedBase):
    __tablename__ = "consent_record"

    lawful_basis_record_id: Mapped[str] = mapped_column(ForeignKey("lawful_basis_record.id"))
    consented_to: Mapped[str] = mapped_column(Text)
    wording_shown: Mapped[str] = mapped_column(Text)
    consent_datetime: Mapped[datetime]
    consent_method: Mapped[ConsentMethod]
    withdrawal_status: Mapped[WithdrawalStatus] = mapped_column(default=WithdrawalStatus.ACTIVE)
    withdrawal_datetime: Mapped[datetime | None]
    review_due: Mapped[date | None]
    age_check_outcome: Mapped[AgeCheckOutcome | None]
    parental_consent_captured: Mapped[bool | None]

    lawful_basis_record: Mapped[LawfulBasisRecord] = relationship(
        back_populates="consent_records"
    )


class LIARLIRecord(AuditedBase):
    __tablename__ = "lia_rli_record"

    lawful_basis_record_id: Mapped[str] = mapped_column(ForeignKey("lawful_basis_record.id"))
    interest_identified: Mapped[str] = mapped_column(Text)
    rli_condition: Mapped[RLICondition | None]
    necessity_test: Mapped[str] = mapped_column(Text)
    balancing_test: Mapped[str | None] = mapped_column(Text)
    safeguards: Mapped[str | None] = mapped_column(Text)
    decision: Mapped[LIADecision]
    decision_date: Mapped[date]

    lawful_basis_record: Mapped[LawfulBasisRecord] = relationship(
        back_populates="lia_rli_records"
    )


class Transfer(AuditedBase):
    __tablename__ = "transfer"

    activity_id: Mapped[str] = mapped_column(ForeignKey("processing_activity.id"))
    recipient_id: Mapped[str] = mapped_column(ForeignKey("recipient.id"))
    third_country_id: Mapped[str] = mapped_column(ForeignKey("third_country.id"))
    mechanism_id: Mapped[str] = mapped_column(ForeignKey("transfer_mechanism.id"))
    data_protection_test: Mapped[str | None] = mapped_column(Text)

    activity: Mapped[ProcessingActivity] = relationship(back_populates="transfers")
    mechanism: Mapped[TransferMechanism] = relationship()
    recipient: Mapped[Recipient] = relationship()
    third_country: Mapped[ThirdCountry] = relationship()


class DPIA(AuditedBase):
    __tablename__ = "dpia"

    activity_id: Mapped[str] = mapped_column(ForeignKey("processing_activity.id"))
    screening_outcome: Mapped[ScreeningOutcome]
    nature_scope_context_purposes: Mapped[str | None] = mapped_column(Text)
    necessity_proportionality: Mapped[str | None] = mapped_column(Text)
    risks_to_individuals: Mapped[str | None] = mapped_column(Text)
    mitigations: Mapped[str | None] = mapped_column(Text)
    residual_risk: Mapped[ResidualRisk | None]
    dpo_advice: Mapped[str | None] = mapped_column(Text)
    sign_off_by: Mapped[str | None] = mapped_column(ForeignKey("user.id"))
    review_date: Mapped[date | None]

    activity: Mapped[ProcessingActivity] = relationship(back_populates="dpias")


contract_party = Table(
    "contract_party",
    Base.metadata,
    Column("contract_id", ForeignKey("contract_dsa.id"), primary_key=True),
    Column("legal_entity_id", ForeignKey("legal_entity.id"), primary_key=True),
)


class ContractDSA(AuditedBase):
    __tablename__ = "contract_dsa"

    type: Mapped[ContractType]
    art28_checklist_complete: Mapped[bool | None]
    security_schedule: Mapped[str | None] = mapped_column(Text)
    sub_processor_authorisation: Mapped[SubProcessorAuthorisation | None]
    start_date: Mapped[date]
    review_date: Mapped[date]
    expiry_date: Mapped[date | None]

    parties: Mapped[list[LegalEntity]] = relationship(secondary=contract_party)


class PrivacyNotice(AuditedBase):
    __tablename__ = "privacy_notice"

    notice_version: Mapped[str]
    publish_date: Mapped[date]
    covers_art13: Mapped[bool]
    covers_art14: Mapped[bool]


class BreachRecord(AuditedBase):
    __tablename__ = "breach_record"

    activity_id: Mapped[str | None] = mapped_column(ForeignKey("processing_activity.id"))
    summary: Mapped[str] = mapped_column(Text)
    occurred_at: Mapped[datetime]
    detected_at: Mapped[datetime]
    reportable_to_ico: Mapped[bool]
    individuals_notified: Mapped[bool | None]


class ComplaintRecord(AuditedBase):
    __tablename__ = "complaint_record"

    activity_id: Mapped[str | None] = mapped_column(ForeignKey("processing_activity.id"))
    received_at: Mapped[datetime]
    acknowledged_at: Mapped[datetime | None]
    response_due: Mapped[date]
    responded_at: Mapped[datetime | None]
    outcome: Mapped[ComplaintOutcome | None]
    ico_escalation_flagged: Mapped[bool] = mapped_column(default=False)
    enquiries_note: Mapped[str | None] = mapped_column(Text)
    progress_updates: Mapped[str | None] = mapped_column(Text)
    outcome_communicated_at: Mapped[datetime | None]


adm_datasource = Table(
    "adm_datasource",
    Base.metadata,
    Column("adm_record_id", ForeignKey("decision_support_adm.id"), primary_key=True),
    Column("source_id", ForeignKey("external_data_source.id"), primary_key=True),
)


class DecisionSupportADM(AuditedBase):
    __tablename__ = "decision_support_adm"

    activity_id: Mapped[str] = mapped_column(ForeignKey("processing_activity.id"))
    use_mode: Mapped[ADMUseMode]
    technique: Mapped[str | None] = mapped_column(Text)
    solely_automated: Mapped[bool | None]
    significant_effects: Mapped[bool | None]
    accuracy_bias_checks: Mapped[str | None] = mapped_column(Text)
    human_review: Mapped[str | None] = mapped_column(Text)
    contestability: Mapped[str | None] = mapped_column(Text)
    transparency_ref: Mapped[str | None] = mapped_column(ForeignKey("privacy_notice.id"))

    activity: Mapped[ProcessingActivity] = relationship(back_populates="adm_records")
    data_sources: Mapped[list[ExternalDataSource]] = relationship(secondary=adm_datasource)
