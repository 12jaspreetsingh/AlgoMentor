from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from fastapi.testclient import TestClient
from sqlalchemy import func, inspect, select, text
from sqlalchemy.exc import IntegrityError, StatementError

from app.config import BACKEND_DIR
from app.main import create_app
from app.models import Base, IngestionRequest, Problem, ProblemTopic, Submission, Topic, User

pytestmark = pytest.mark.integration


@pytest.fixture
def records(db_session):
    user = User(tracking_started_on=date(2026, 11, 10))
    problem = Problem(slug="two-sum", title="Two Sum", difficulty="easy")
    db_session.add_all([user, problem])
    db_session.flush()
    return user, problem


def new_submission(user, problem, **overrides):
    values = {
        "user_id": user.id,
        "problem_id": problem.id,
        "status": "accepted",
        "record_key": uuid4().hex,
    }
    values.update(overrides)
    return Submission(**values)


def test_migrations_round_trip_and_match_models(migrated_engine):
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    with migrated_engine.begin() as connection:
        config.attributes["connection"] = connection
        assert set(inspect(connection).get_table_names()) == set(Base.metadata.tables) | {
            "alembic_version"
        }
        assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []
        command.upgrade(config, "head")  # Re-running a migration is safe.
        command.downgrade(config, "base")
        assert inspect(connection).get_table_names() == ["alembic_version"]
        command.upgrade(config, "head")
        assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []


def test_readiness_with_real_database(settings, migrated_engine, monkeypatch):
    monkeypatch.setattr("app.main.build_engine", lambda settings: migrated_engine)
    with TestClient(create_app(settings)) as client:
        response = client.get("/api/v1/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "reachable", "schema_status": "current"}


def test_readiness_requires_migrations(settings, postgres_engine, monkeypatch):
    monkeypatch.setattr("app.main.build_engine", lambda settings: postgres_engine)
    with TestClient(create_app(settings)) as client:
        response = client.get("/api/v1/health/ready")
    assert response.status_code == 503
    assert response.json()["database"] == "reachable"


def test_relationships_defaults_and_nullable_metadata(db_session, records):
    user, problem = records
    topic = Topic(slug="arrays", name="Arrays")
    problem.topics.append(topic)
    unknown = Problem(slug="unknown-problem", title="Unknown problem")
    submission = new_submission(user, problem)
    db_session.add_all([unknown, submission])
    db_session.commit()
    db_session.expire_all()
    assert problem.topics == [topic]
    assert topic.problems == [problem]
    assert submission.user == user and submission.problem == problem
    assert submission.submitted_at is None and unknown.difficulty is None
    assert user.timezone == "Asia/Kolkata" and user.history_complete is False
    assert submission.created_at.utcoffset() == timedelta(0)
    assert db_session.scalar(text("SHOW timezone")) == "UTC"


def test_repeated_acceptances_are_distinct_events(db_session, records):
    user, problem = records
    db_session.add_all([new_submission(user, problem), new_submission(user, problem)])
    db_session.commit()
    assert db_session.scalar(select(func.count()).select_from(Submission)) == 2
    assert db_session.scalar(select(func.count(func.distinct(Submission.problem_id)))) == 1


@pytest.mark.parametrize("duplicate_field", ["record_key", "external_submission_id"])
def test_duplicate_source_identity_rejected(db_session, records, duplicate_field):
    user, problem = records
    db_session.add(new_submission(user, problem, **{duplicate_field: "same-id"}))
    db_session.commit()
    db_session.add(new_submission(user, problem, **{duplicate_field: "same-id"}))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()
    assert db_session.scalar(select(func.count()).select_from(Submission)) == 1


def test_source_identity_scoped_per_user(db_session, records):
    user, problem = records
    other = User(tracking_started_on=date(2026, 11, 10))
    db_session.add(other)
    db_session.flush()
    for owner in (user, other):
        db_session.add(
            new_submission(owner, problem, record_key="same", external_submission_id="1")
        )
    db_session.commit()
    assert len(db_session.scalars(select(Submission)).all()) == 2


def test_problem_identity_is_unique(db_session, records):
    db_session.add(Problem(slug="two-sum", title="Same problem"))
    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.parametrize(
    "field,value", [("difficulty", "impossible"), ("title", " "), ("slug", "")]
)
def test_invalid_problem_values_rejected(db_session, field, value):
    values = {"slug": "sample", "title": "Sample", field: value}
    db_session.add(Problem(**values))
    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.parametrize(
    "field,value", [("status", "invented"), ("record_key", ""), ("source", " ")]
)
def test_invalid_submission_values_rejected(db_session, records, field, value):
    db_session.add(new_submission(*records, **{field: value}))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_foreign_key_rejects_orphan(db_session, records):
    db_session.add(new_submission(*records, user_id=uuid4()))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_problem_topic_link_cannot_repeat(db_session, records):
    _, problem = records
    topic = Topic(slug="arrays", name="Arrays")
    db_session.add(topic)
    db_session.flush()
    db_session.add(ProblemTopic(problem_id=problem.id, topic_id=topic.id))
    db_session.flush()
    db_session.add(ProblemTopic(problem_id=problem.id, topic_id=topic.id))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_event_time_round_trip_in_utc(db_session, records):
    instant = datetime(2026, 11, 10, 0, 15, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    submission = new_submission(*records, submitted_at=instant)
    db_session.add(submission)
    db_session.commit()
    db_session.refresh(submission)
    assert submission.submitted_at == datetime(2026, 11, 9, 18, 45, tzinfo=timezone.utc)
    assert submission.submitted_at.utcoffset() == timedelta(0)


def test_naive_event_timestamp_rejected(db_session, records):
    db_session.add(new_submission(*records, submitted_at=datetime(2026, 11, 10)))
    with pytest.raises(StatementError, match="timezone offset"):
        db_session.flush()


def test_request_key_unique_and_json_result_persists(db_session, records):
    user, _ = records
    saved = IngestionRequest(
        user_id=user.id,
        idempotency_key="request-1",
        payload_hash="a" * 64,
        result={"submission_id": str(uuid4())},
        completed_at=datetime.now(timezone.utc),
    )
    db_session.add(saved)
    db_session.commit()
    db_session.refresh(saved)
    assert "submission_id" in saved.result
    db_session.add(
        IngestionRequest(
            user_id=user.id,
            idempotency_key="request-1",
            payload_hash="b" * 64,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.parametrize(
    "overrides",
    [
        {"payload_hash": "invalid"},
        {"result": {"saved": True}},
        {"completed_at": datetime.now(timezone.utc)},
    ],
)
def test_invalid_request_state_rejected(db_session, records, overrides):
    user, _ = records
    values = {"user_id": user.id, "idempotency_key": "request", "payload_hash": "a" * 64}
    values.update(overrides)
    db_session.add(IngestionRequest(**values))
    with pytest.raises(IntegrityError):
        db_session.flush()
