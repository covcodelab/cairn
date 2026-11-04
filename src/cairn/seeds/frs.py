"""Draft — verify against latest revised legislation before production seeding (Spec §11)."""

from sqlalchemy.orm import Session

from cairn.models import (
    BusinessFunction,
    DataSubjectCategory,
    PersonalDataCategory,
    Recipient,
    RecipientType,
    SecurityMeasure,
    SecurityMeasureCategory,
)

BUSINESS_FUNCTIONS = [
    "Response / Operations",
    "Prevention & Community Safety",
    "Protection (Fire Safety Regulation & Enforcement)",
    "Fire Investigation",
    "Youth & Early Intervention",
    "Emergency Medical Response",
    "Control / Mobilising",
    "Corporate Services",
    "HR",
    "Occupational Health",
    "Finance & Procurement",
    "Legal & Governance",
    "ICT",
    "Communications & Engagement",
    "Data & Performance",
    "Estates & Fleet",
]

DATA_SUBJECT_CATEGORIES = [
    "members of the public",
    "casualties / persons involved in incidents",
    "vulnerable persons (HFSV / Safe & Well)",
    "responsible persons / duty holders (fire safety)",
    "business owners & occupiers",
    "employees (current)",
    "former employees",
    "applicants / prospective employees",
    "on-call / retained firefighters",
    "volunteers",
    "cadets & young people",
    "parents / guardians",
    "partner-agency staff",
    "emergency-service contacts",
    "complainants",
    "FOI / SAR requesters",
    "contractors & suppliers",
    "witnesses",
    "next of kin / emergency contacts",
]

PERSONAL_DATA_CATEGORIES = [
    ("contact details", False, False),
    ("identifiers (reference numbers)", False, False),
    ("household & premises data", False, False),
    ("employment / HR data", False, False),
    ("financial data", False, False),
    ("CCTV / imagery", False, False),
    ("location / telemetry", False, False),
    ("health data (casualty, OH, EMR)", True, False),
    ("safeguarding concerns", True, False),
    ("racial or ethnic origin (PSED)", True, False),
    ("religious or philosophical beliefs (PSED)", True, False),
    ("sexual orientation (PSED)", True, False),
    ("biometric data", True, False),
    ("genetic data", True, False),
    ("trade union membership", True, False),
    ("criminal offence data (fire investigation / arson, employee vetting / DBS)", False, True),
]

RECIPIENTS = [
    ("police", RecipientType.PUBLIC_BODY),
    ("ambulance / NHS trusts", RecipientType.PUBLIC_BODY),
    ("local authorities", RecipientType.PUBLIC_BODY),
    ("adult social care", RecipientType.PUBLIC_BODY),
    ("children's social care", RecipientType.PUBLIC_BODY),
    ("other fire & rescue services", RecipientType.PUBLIC_BODY),
    ("coroner", RecipientType.PUBLIC_BODY),
    ("courts & tribunals", RecipientType.PUBLIC_BODY),
    ("Information Commission", RecipientType.PUBLIC_BODY),
    ("Home Office / central government", RecipientType.PUBLIC_BODY),
    ("National Fire Chiefs Council", RecipientType.OTHER),
    ("insurers", RecipientType.OTHER),
    ("IT / cloud processors", RecipientType.PROCESSOR),
    ("auditors", RecipientType.OTHER),
    ("legal advisors", RecipientType.OTHER),
    ("utility companies", RecipientType.OTHER),
    ("contractors", RecipientType.OTHER),
]

SECURITY_MEASURES = [
    ("encryption at rest", SecurityMeasureCategory.TECHNICAL),
    ("encryption in transit", SecurityMeasureCategory.TECHNICAL),
    ("role-based access control", SecurityMeasureCategory.TECHNICAL),
    ("multi-factor authentication", SecurityMeasureCategory.TECHNICAL),
    ("mobile device management", SecurityMeasureCategory.TECHNICAL),
    ("appliance / MDT controls", SecurityMeasureCategory.TECHNICAL),
    ("pseudonymisation", SecurityMeasureCategory.TECHNICAL),
    ("network firewalls", SecurityMeasureCategory.TECHNICAL),
    ("anti-malware", SecurityMeasureCategory.TECHNICAL),
    ("audit logging", SecurityMeasureCategory.TECHNICAL),
    ("backup & recovery", SecurityMeasureCategory.TECHNICAL),
    ("vulnerability & patch management", SecurityMeasureCategory.TECHNICAL),
    ("secure disposal", SecurityMeasureCategory.TECHNICAL),
    ("physical security & access", SecurityMeasureCategory.ORGANISATIONAL),
    ("staff training & awareness", SecurityMeasureCategory.ORGANISATIONAL),
    ("clear desk / clear screen", SecurityMeasureCategory.ORGANISATIONAL),
    ("access reviews", SecurityMeasureCategory.ORGANISATIONAL),
    ("supplier due diligence", SecurityMeasureCategory.ORGANISATIONAL),
]


def seed_frs_pack(session: Session) -> None:
    from cairn.seeds.intake import seed_activity_questions, seed_asset_questions

    for label in BUSINESS_FUNCTIONS:
        session.add(BusinessFunction(label=label))
    for label in DATA_SUBJECT_CATEGORIES:
        session.add(DataSubjectCategory(label=label))
    for label, special, criminal in PERSONAL_DATA_CATEGORIES:
        session.add(
            PersonalDataCategory(
                label=label, is_special_category=special, is_criminal_offence=criminal
            )
        )
    for label, type_ in RECIPIENTS:
        session.add(Recipient(label=label, type=type_))
    for label, category in SECURITY_MEASURES:
        session.add(SecurityMeasure(label=label, category=category))
    seed_activity_questions(session)
    seed_asset_questions(session)
    session.flush()
