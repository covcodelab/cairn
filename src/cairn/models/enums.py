from enum import StrEnum


class Regime(StrEnum):
    GENERAL = "general"
    LAW_ENFORCEMENT = "law_enforcement"


class RegimeScope(StrEnum):
    PART2 = "part2"
    PART3 = "part3"


ACTIVE_SCOPE = {Regime.GENERAL: RegimeScope.PART2, Regime.LAW_ENFORCEMENT: RegimeScope.PART3}


class RegimeSource(StrEnum):
    POLICY = "policy"
    MANUAL_OVERRIDE = "manual_override"


class ActivityDomain(StrEnum):
    FIRE_SAFETY_ENFORCEMENT = "fire_safety_enforcement"
    FIRE_INVESTIGATION = "fire_investigation"
    FIRESETTER_INTERVENTION = "firesetter_intervention"
    OTHER = "other"


class ActivityType(StrEnum):
    OPERATIONAL = "operational"
    ANALYTICS_MODELLING = "analytics_modelling"


class ControllerOrProcessor(StrEnum):
    CONTROLLER = "controller"
    PROCESSOR = "processor"
    JOINT = "joint"


class RecordStatus(StrEnum):
    DRAFT = "draft"
    IN_REVIEW = "in_review"
    ACTIVE = "active"
    RETIRED = "retired"


class LifecycleStage(StrEnum):
    TRIAL = "trial"
    LIVE = "live"
    RETIRED = "retired"


class ExternalDataUseMode(StrEnum):
    NONE = "none"
    MANUAL = "manual"
    AUTOMATED = "automated"


class OrgType(StrEnum):
    PUBLIC_AUTHORITY = "public_authority"
    PRIVATE_BODY = "private_body"
    MIXED = "mixed"


class LegalEntityTopology(StrEnum):
    SINGLE = "single"
    GROUP = "group"
    JOINT = "joint"


class Role(StrEnum):
    CONTRIBUTOR = "contributor"
    CURATOR = "curator"
    APPROVER_DPO = "approver_dpo"
    VIEWER = "viewer"


class SourceSpecialCategory(StrEnum):
    NONE = "none"
    INFERRED = "inferred"
    DIRECT = "direct"


class PersonalDataSource(StrEnum):
    FROM_DATA_SUBJECT = "from_data_subject"
    FROM_THIRD_PARTY = "from_third_party"
    PUBLIC_SOURCE = "public_source"


class LineageGranularity(StrEnum):
    ACTIVITY = "activity"
    RECORD = "record"


class LEClassification(StrEnum):
    SUSPECT = "suspect"
    CONVICTED = "convicted"
    VICTIM = "victim"
    WITNESS = "witness"
    OTHER = "other"
    NONE = "none"


class LegalEntityRoleType(StrEnum):
    OWN_ORG = "own_org"
    JOINT_CONTROLLER = "joint_controller"
    REPRESENTATIVE = "representative"
    DPO = "dpo"
    PROCESSOR = "processor"
    SUB_PROCESSOR = "sub_processor"
    DATA_SUPPLIER = "data_supplier"
    PARTNER_AGENCY = "partner_agency"


class RecipientType(StrEnum):
    INTERNAL = "internal"
    PROCESSOR = "processor"
    JOINT_CONTROLLER = "joint_controller"
    PUBLIC_BODY = "public_body"
    OTHER = "other"


class SecurityMeasureCategory(StrEnum):
    TECHNICAL = "technical"
    ORGANISATIONAL = "organisational"


class AdequacyStatus(StrEnum):
    ADEQUATE = "adequate"
    NOT_ADEQUATE = "not_adequate"
    UNDER_REVIEW = "under_review"


class SupplierRole(StrEnum):
    PROCESSOR = "processor"
    SEPARATE_CONTROLLER = "separate_controller"


class ConsentMethod(StrEnum):
    ONLINE_FORM = "online_form"
    PAPER = "paper"
    VERBAL_LOGGED = "verbal_logged"
    OTHER = "other"


class WithdrawalStatus(StrEnum):
    ACTIVE = "active"
    WITHDRAWN = "withdrawn"


class AgeCheckOutcome(StrEnum):
    ADULT = "adult"
    CHILD_OVER_13 = "child_over_13"
    CHILD_UNDER_13 = "child_under_13"
    UNKNOWN = "unknown"


class APDScope(StrEnum):
    SCHEDULE1 = "schedule1"
    S42_PART3 = "s42_part3"


class ScreeningOutcome(StrEnum):
    REQUIRED = "required"
    NOT_REQUIRED = "not_required"
    DOCUMENTED_NOT_REQUIRED = "documented_not_required"


class ResidualRisk(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ContractType(StrEnum):
    CONTROLLER_PROCESSOR = "controller_processor"
    JOINT_CONTROLLER = "joint_controller"
    DATA_SHARING = "data_sharing"


class SubProcessorAuthorisation(StrEnum):
    NONE = "none"
    GENERAL = "general"
    SPECIFIC = "specific"


class ComplaintOutcome(StrEnum):
    UPHELD = "upheld"
    PARTLY_UPHELD = "partly_upheld"
    NOT_UPHELD = "not_upheld"
    WITHDRAWN = "withdrawn"


class ADMUseMode(StrEnum):
    MANUAL = "manual"
    AUTOMATED = "automated"


class LIADecision(StrEnum):
    PROCEED = "proceed"
    DO_NOT_PROCEED = "do_not_proceed"


class RLICondition(StrEnum):
    NATIONAL_SECURITY_DEFENCE = "national_security_defence"
    EMERGENCIES = "emergencies"
    CRIME = "crime"
    SAFEGUARDING_VULNERABLE = "safeguarding_vulnerable"
    PUBLIC_INTEREST_DISCLOSURE_REQUEST = "public_interest_disclosure_request"


class EntryStatus(StrEnum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    REJECTED = "rejected"


class ImportBatchStatus(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"


class IntakeAnswerKind(StrEnum):
    TEXT = "text"
    TEXTAREA = "textarea"
    YES_NO = "yes_no"
    DATE = "date"
    SINGLE_CHOICE = "single_choice"
    MULTI_CHOICE = "multi_choice"
    VOCAB_MULTI = "vocab_multi"


class IntakeStatus(StrEnum):
    IN_PROGRESS = "in_progress"
    SUBMITTED = "submitted"
    CANCELLED = "cancelled"


class IntakeQuestionSet(StrEnum):
    ACTIVITY = "activity"
    ASSET = "asset"


class AssetType(StrEnum):
    SYSTEM = "system"
    DATABASE = "database"
    SOFTWARE = "software"
    PAPER = "paper"
    PHYSICAL = "physical"


class AssetStatus(StrEnum):
    IN_USE = "in_use"
    RETIRING = "retiring"
    DISPOSED = "disposed"


class SecurityClassification(StrEnum):
    NOT_CLASSIFIED = "not_classified"
    OFFICIAL = "official"
    OFFICIAL_SENSITIVE = "official_sensitive"
