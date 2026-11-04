from datetime import date
from html.parser import HTMLParser

import pytest
from sqlalchemy.orm import Session

from cairn.models import (
    ContractDSA,
    ContractType,
    ExternalDataSource,
    InformationAsset,
    PrivacyNotice,
)
from test_activities import _create_activity, _login
from test_assets import _create_asset
from test_registers_ui import (
    _add_legal_entity,
    _add_retention_rule,
    _add_security_measure,
)


class _SelectAudit(HTMLParser):
    def __init__(self):
        super().__init__()
        self.selects: list[dict] = []
        self.label_fors: set[str] = set()
        self.label_depth = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "label":
            self.label_depth += 1
            if "for" in attrs:
                self.label_fors.add(attrs["for"])
        if tag == "select":
            self.selects.append({**attrs, "wrapped": self.label_depth > 0})

    def handle_endtag(self, tag):
        if tag == "label":
            self.label_depth -= 1


JUNCTION_ADD_LABELS = [
    "Data subject to add",
    "Recipient to add",
    "Asset to link",
    "External data source to add",
    "Controller to add",
    "Privacy notice to add",
]


def unlabelled_selects(html: str) -> tuple[int, list[str]]:
    audit = _SelectAudit()
    audit.feed(html)
    ids = [s.get("id") for s in audit.selects]
    problems = [
        f"select name={s.get('name')!r} has no label"
        for s in audit.selects
        if not s["wrapped"] and (not s.get("id") or s["id"] not in audit.label_fors)
    ]
    duplicates = {i for i in ids if i and ids.count(i) > 1}
    problems += [f"duplicate select id {i!r}" for i in duplicates]
    return len(audit.selects), problems


def test_activity_detail_selects_are_labelled(activities_client, activities_web_engine):
    _add_security_measure(activities_web_engine, label="Encryption at rest")
    _add_retention_rule(activities_web_engine)
    _add_legal_entity(activities_web_engine)
    with Session(activities_web_engine) as db:
        db.add(
            ContractDSA(
                type=ContractType.CONTROLLER_PROCESSOR,
                start_date=date(2026, 1, 1),
                review_date=date(2027, 1, 1),
            )
        )
        db.add_all(
            [
                InformationAsset(label="Case system"),
                ExternalDataSource(name="Council housing feed"),
                PrivacyNotice(
                    notice_version="1.0",
                    publish_date=date(2026, 1, 1),
                    covers_art13=True,
                    covers_art14=True,
                ),
            ]
        )
        db.commit()
    _create_activity(activities_client, activities_web_engine, login_as="Cara Curator")
    activity_id = _create_activity(
        activities_client,
        activities_web_engine,
        login_as="Cara Curator",
        activity_type="analytics_modelling",
        controller_or_processor="processor",
        categories_of_processing="Hosting",
    )
    html = activities_client.get(f"/activities/{activity_id}").text
    count, problems = unlabelled_selects(html)
    for label in JUNCTION_ADD_LABELS:
        assert f">{label}</label>" in html
    assert count >= 13
    assert problems == []


def test_asset_detail_selects_are_labelled(activities_client, activities_web_engine):
    _add_security_measure(activities_web_engine, label="Encryption at rest")
    asset_id = _create_asset(activities_client, activities_web_engine, login_as="Cara Curator")
    html = activities_client.get(f"/assets/{asset_id}").text
    count, problems = unlabelled_selects(html)
    assert count >= 1
    assert problems == []


@pytest.mark.parametrize(
    "path",
    [
        "/activities",
        "/activities/new",
        "/assets",
        "/assets/new",
        "/intake/new",
        "/intake/assets/new",
    ],
)
def test_page_selects_are_labelled(activities_client, activities_web_engine, path):
    _login(activities_client, activities_web_engine, "Cara Curator")
    response = activities_client.get(path)
    assert response.status_code == 200
    _, problems = unlabelled_selects(response.text)
    assert problems == []
