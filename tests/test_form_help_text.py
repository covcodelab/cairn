import html
import re

import pytest
from sqlalchemy.orm import Session

from conftest import art6
from test_activities import _create_activity, _extract_csrf, _login


def _text(response) -> str:
    return html.unescape(response.text)


@pytest.fixture
def curator_activity(activities_client, activities_web_engine):
    activity_id = _create_activity(
        activities_client, activities_web_engine, login_as="Cara Curator"
    )
    return activities_client, activity_id


def test_art6_justification_says_it_is_required(curator_activity):
    client, activity_id = curator_activity
    page = _text(client.get(f"/activities/{activity_id}/basis/part2/edit"))
    assert "Why this basis applies" in page
    assert "Required when you choose an Art 6 basis" in page


def test_public_authority_basis_hint_is_accurate(activities_client, activities_web_engine):
    activity_id = _create_activity(
        activities_client,
        activities_web_engine,
        login_as="Cara Curator",
        is_statutory_task="true",
    )
    client = activities_client
    page = _text(client.get(f"/activities/{activity_id}/basis/part2/edit"))
    assert "recognised legitimate interest" in page
    assert "(f)/(ea)) will be flagged" not in page
    assert "outside its official tasks" in page


def test_lia_form_uses_plain_title_and_rli_hint(activities_client, activities_web_engine):
    activity_id = _create_activity(
        activities_client, activities_web_engine, login_as="Cara Curator"
    )
    client = activities_client
    with Session(activities_web_engine) as db:
        f_id = art6(db, "f").id
    token = _extract_csrf(client.get(f"/activities/{activity_id}/basis/part2/edit").text)
    client.post(
        f"/activities/{activity_id}/basis/part2",
        data={"csrf_token": token, "art6_basis_id": f_id, "art6_justification": "Interest."},
    )
    page = _text(client.get(f"/activities/{activity_id}/basis/part2/lia/new"))
    assert "Add legitimate interests assessment" in page
    assert "Required if the basis is recognised legitimate interest (ea)" in page
    assert "Required if the basis is legitimate interests (f)" in page


def test_complaint_form_reads_as_a_sequence(activities_client, activities_web_engine):
    _login(activities_client, activities_web_engine, "Cara Curator")
    page = _text(activities_client.get("/complaints/new"))
    positions = [
        page.index(label)
        for label in (
            "Date received",
            "Date acknowledged",
            "Enquiries made",
            "Progress updates given to the complainant",
            "Outcome",
            "Date outcome told to the complainant",
        )
    ]
    assert positions == sorted(positions)
    assert "within 30 days of receiving the complaint" in page
    assert "30 days after the date received" in page
    assert not re.search(r"\bICO\b", page)


def test_asset_import_page_describes_proposed_assets(activities_client, activities_web_engine):
    _login(activities_client, activities_web_engine, "Cara Curator")
    page = _text(activities_client.get("/imports/assets/new"))
    assert "each row becomes an approved information asset" not in page
    assert "created as proposed" in page
    assert "proposed as a new legal entity" in page


def test_asset_and_vocabulary_forms_show_field_hints(activities_client, activities_web_engine):
    _login(activities_client, activities_web_engine, "Cara Curator")
    asset_form = _text(activities_client.get("/assets/new"))
    assert "The senior person accountable for this asset" in asset_form
    vocab_form = _text(activities_client.get("/vocabularies/retention-rules/new"))
    assert "What starts the clock" in vocab_form
