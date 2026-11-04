from datetime import date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from cairn.complaints import complaint_status
from cairn.models import ComplaintOutcome, ComplaintRecord, RecordVersion
from test_activities import _extract_csrf, _login, _user_id


def _token(client, path="/complaints/new") -> str:
    page = client.get(path)
    return _extract_csrf(page.text)


def _complaint(**overrides) -> ComplaintRecord:
    defaults = {
        "received_at": datetime.combine(date(2026, 1, 1), time.min),
        "acknowledged_at": None,
        "response_due": date(2026, 1, 31),
        "responded_at": None,
        "outcome": None,
        "ico_escalation_flagged": False,
    }
    defaults.update(overrides)
    return ComplaintRecord(**defaults)


def test_status_withdrawn():
    complaint = _complaint(outcome=ComplaintOutcome.WITHDRAWN)
    assert complaint_status(complaint, date(2026, 1, 5)) == ("Withdrawn", "grey")


def test_status_responded():
    complaint = _complaint(responded_at=datetime.combine(date(2026, 1, 10), time.min))
    assert complaint_status(complaint, date(2026, 1, 15)) == ("Responded", "green")


def test_status_acknowledgement_overdue():
    complaint = _complaint(received_at=datetime.combine(date(2026, 1, 1), time.min))
    today = date(2026, 1, 1) + timedelta(days=31)
    assert complaint_status(complaint, today) == ("Acknowledgement overdue", "red")


def test_status_acknowledgement_due_soon():
    complaint = _complaint(received_at=datetime.combine(date(2026, 1, 1), time.min))
    today = date(2026, 1, 1) + timedelta(days=23)
    assert complaint_status(complaint, today) == ("Acknowledgement due soon", "yellow")


def test_status_awaiting_acknowledgement():
    complaint = _complaint(received_at=datetime.combine(date(2026, 1, 1), time.min))
    today = date(2026, 1, 1) + timedelta(days=5)
    assert complaint_status(complaint, today) == ("Awaiting acknowledgement", "blue")


def test_status_response_overdue():
    complaint = _complaint(
        acknowledged_at=datetime.combine(date(2026, 1, 2), time.min),
        response_due=date(2026, 1, 10),
    )
    assert complaint_status(complaint, date(2026, 1, 11)) == ("Response overdue", "red")


def test_status_awaiting_response():
    complaint = _complaint(
        acknowledged_at=datetime.combine(date(2026, 1, 2), time.min),
        response_due=date(2026, 1, 10),
    )
    assert complaint_status(complaint, date(2026, 1, 5)) == ("Awaiting response", "blue")


def test_curator_creates_complaint(activities_client, activities_web_engine):
    _login(activities_client, activities_web_engine, "Cara Curator")
    token = _token(activities_client)
    response = activities_client.post(
        "/complaints",
        data={
            "csrf_token": token,
            "activity_id": "",
            "received_at": "2026-06-01",
            "acknowledged_at": "",
            "response_due": "",
            "responded_at": "",
            "outcome": "",
        },
    )
    assert response.status_code == 302, response.text
    with Session(activities_web_engine) as db:
        created = db.scalars(select(ComplaintRecord)).one()
        assert created.received_at == datetime.combine(date(2026, 6, 1), time.min)
        assert created.response_due == date(2026, 7, 1)
        assert created.activity_id is None


def test_approver_edits_with_change_note_records_version(activities_client, activities_web_engine):
    _login(activities_client, activities_web_engine, "Cara Curator")
    token = _token(activities_client)
    activities_client.post(
        "/complaints",
        data={
            "csrf_token": token,
            "activity_id": "",
            "received_at": "2026-06-01",
            "acknowledged_at": "",
            "response_due": "",
            "responded_at": "",
            "outcome": "",
        },
    )
    with Session(activities_web_engine) as db:
        complaint_id = db.scalars(select(ComplaintRecord)).one().id

    _login(activities_client, activities_web_engine, "Ada Approver")
    edit_page = activities_client.get(f"/complaints/{complaint_id}/edit")
    token = _extract_csrf(edit_page.text)
    response = activities_client.post(
        f"/complaints/{complaint_id}",
        data={
            "csrf_token": token,
            "activity_id": "",
            "received_at": "2026-06-01",
            "acknowledged_at": "2026-06-05",
            "response_due": "2026-07-01",
            "responded_at": "",
            "outcome": "",
            "change_note": "Acknowledged by phone",
        },
    )
    assert response.status_code == 302, response.text
    with Session(activities_web_engine) as db:
        updated = db.get(ComplaintRecord, complaint_id)
        assert updated.acknowledged_at == datetime.combine(date(2026, 6, 5), time.min)
        version = db.scalars(
            select(RecordVersion).where(
                RecordVersion.entity_type == "complaint_record",
                RecordVersion.entity_id == complaint_id,
            )
        ).one()
        assert version.version_change_note == "Acknowledged by phone"


def test_viewer_forbidden(activities_client, activities_web_engine):
    _login(activities_client, activities_web_engine, "Vic Viewer")
    assert activities_client.get("/complaints").status_code == 403
    assert activities_client.get("/complaints/new").status_code == 403


def test_contributor_forbidden(activities_client, activities_web_engine):
    _login(activities_client, activities_web_engine, "Cody Contributor")
    assert activities_client.get("/complaints").status_code == 403
    assert (
        activities_client.post(
            "/complaints", data={"csrf_token": "no-token"}
        ).status_code
        == 403
    )


def test_validation_acknowledged_before_received(activities_client, activities_web_engine):
    _login(activities_client, activities_web_engine, "Cara Curator")
    token = _token(activities_client)
    response = activities_client.post(
        "/complaints",
        data={
            "csrf_token": token,
            "activity_id": "",
            "received_at": "2026-06-10",
            "acknowledged_at": "2026-06-05",
            "response_due": "",
            "responded_at": "",
            "outcome": "",
        },
    )
    assert response.status_code == 422
    assert "cannot be before the date received" in response.text


def test_validation_outcome_without_responded_at(activities_client, activities_web_engine):
    _login(activities_client, activities_web_engine, "Cara Curator")
    token = _token(activities_client)
    response = activities_client.post(
        "/complaints",
        data={
            "csrf_token": token,
            "activity_id": "",
            "received_at": "2026-06-01",
            "acknowledged_at": "",
            "response_due": "",
            "responded_at": "",
            "outcome": "upheld",
        },
    )
    assert response.status_code == 422
    assert "Enter the date the response was sent" in response.text


def test_validation_invalid_date(activities_client, activities_web_engine):
    _login(activities_client, activities_web_engine, "Cara Curator")
    token = _token(activities_client)
    response = activities_client.post(
        "/complaints",
        data={
            "csrf_token": token,
            "activity_id": "",
            "received_at": "not-a-date",
            "acknowledged_at": "",
            "response_due": "",
            "responded_at": "",
            "outcome": "",
        },
    )
    assert response.status_code == 422


def test_late_acknowledgement_recordable(activities_client, activities_web_engine):
    _login(activities_client, activities_web_engine, "Cara Curator")
    received = date.today() - timedelta(days=40)
    token = _token(activities_client)
    activities_client.post(
        "/complaints",
        data={
            "csrf_token": token,
            "activity_id": "",
            "received_at": received.isoformat(),
            "acknowledged_at": "",
            "response_due": "",
            "responded_at": "",
            "outcome": "",
        },
    )
    with Session(activities_web_engine) as db:
        complaint_id = db.scalars(select(ComplaintRecord)).one().id

    edit_page = activities_client.get(f"/complaints/{complaint_id}/edit")
    token = _extract_csrf(edit_page.text)
    response = activities_client.post(
        f"/complaints/{complaint_id}",
        data={
            "csrf_token": token,
            "activity_id": "",
            "received_at": received.isoformat(),
            "acknowledged_at": date.today().isoformat(),
            "response_due": "",
            "responded_at": "",
            "outcome": "",
        },
    )
    assert response.status_code == 302, response.text
    with Session(activities_web_engine) as db:
        updated = db.get(ComplaintRecord, complaint_id)
        assert updated.acknowledged_at == datetime.combine(date.today(), time.min)


def test_dashboard_shows_open_complaints_needing_attention(
    activities_client, activities_web_engine
):
    approver_id = _user_id(activities_web_engine, "Ada Approver")
    with Session(activities_web_engine) as db:
        db.info["actor_id"] = approver_id
        overdue_ack = ComplaintRecord(
            received_at=datetime.combine(date.today() - timedelta(days=40), time.min),
            response_due=date.today() - timedelta(days=10),
        )
        overdue_response = ComplaintRecord(
            received_at=datetime.combine(date.today() - timedelta(days=20), time.min),
            acknowledged_at=datetime.combine(date.today() - timedelta(days=15), time.min),
            response_due=date.today() - timedelta(days=1),
        )
        responded = ComplaintRecord(
            received_at=datetime.combine(date.today() - timedelta(days=15), time.min),
            acknowledged_at=datetime.combine(date.today() - timedelta(days=10), time.min),
            response_due=date.today() - timedelta(days=1),
            responded_at=datetime.combine(date.today() - timedelta(days=1), time.min),
        )
        fresh = ComplaintRecord(
            received_at=datetime.combine(date.today(), time.min),
            response_due=date.today() + timedelta(days=30),
        )
        db.add_all([overdue_ack, overdue_response, responded, fresh])
        db.commit()

    _login(activities_client, activities_web_engine, "Ada Approver")
    home = activities_client.get("/")
    assert home.status_code == 200
    assert "3 open complaints" in home.text
    assert home.text.count("Acknowledgement overdue") == 1
    assert home.text.count("Response overdue") == 1


def _nav_html(html: str) -> str:
    start = html.index("<nav")
    end = html.index("</nav>", start)
    return html[start:end]


def test_nav_link_visible_for_curator_absent_for_viewer(
    activities_client, activities_web_engine
):
    # Complaints now lives under the site-wide "Review" section (Review is
    # role-gated the same way the old flat dashboard nav gated /complaints).
    _login(activities_client, activities_web_engine, "Cara Curator")
    home = activities_client.get("/")
    assert 'href="/review"' in _nav_html(home.text)

    _login(activities_client, activities_web_engine, "Vic Viewer")
    home = activities_client.get("/")
    assert 'href="/review"' not in _nav_html(home.text)


def _complaint_data(token, **overrides) -> dict:
    data = {
        "csrf_token": token,
        "activity_id": "",
        "received_at": "2026-06-01",
        "acknowledged_at": "",
        "response_due": "",
        "responded_at": "",
        "outcome": "",
    }
    return data | overrides


def test_complaint_evidence_fields_saved_and_shown_on_edit(
    activities_client, activities_web_engine
):
    _login(activities_client, activities_web_engine, "Cara Curator")
    token = _token(activities_client)
    response = activities_client.post(
        "/complaints",
        data=_complaint_data(
            token,
            responded_at="2026-06-20",
            outcome="upheld",
            outcome_communicated_at="2026-06-21",
            enquiries_note="Spoke to the station manager.",
            progress_updates="Updated complainant on 10 June.",
        ),
    )
    assert response.status_code == 302, response.text
    with Session(activities_web_engine) as db:
        created = db.scalars(select(ComplaintRecord)).one()
        assert created.enquiries_note == "Spoke to the station manager."
        assert created.progress_updates == "Updated complainant on 10 June."
        assert created.outcome_communicated_at == datetime.combine(date(2026, 6, 21), time.min)
        complaint_id = created.id
    edit = activities_client.get(f"/complaints/{complaint_id}/edit")
    assert "Spoke to the station manager." in edit.text
    assert 'value="2026-06-21"' in edit.text


def test_validation_outcome_without_communicated_date(activities_client, activities_web_engine):
    _login(activities_client, activities_web_engine, "Cara Curator")
    token = _token(activities_client)
    response = activities_client.post(
        "/complaints",
        data=_complaint_data(token, responded_at="2026-06-20", outcome="upheld"),
    )
    assert response.status_code == 422
    assert "Enter the date the outcome was communicated to the complainant" in response.text


def test_validation_invalid_outcome_communicated_date(activities_client, activities_web_engine):
    _login(activities_client, activities_web_engine, "Cara Curator")
    token = _token(activities_client)
    response = activities_client.post(
        "/complaints",
        data=_complaint_data(
            token,
            responded_at="2026-06-20",
            outcome="upheld",
            outcome_communicated_at="nope",
        ),
    )
    assert response.status_code == 422
