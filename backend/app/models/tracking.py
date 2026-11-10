from datetime import date, datetime
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.models.base import Base, EntityMixin, UTCDateTime


class User(EntityMixin, Base):
    __tablename__ = "users"

    leetcode_username: Mapped[str | None] = mapped_column(String(100))
    timezone: Mapped[str] = mapped_column(
        String(100), default="Asia/Kolkata", server_default="Asia/Kolkata"
    )
    tracking_started_on: Mapped[date] = mapped_column(Date)
    history_complete: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )

    submissions: Mapped[list["Submission"]] = relationship(back_populates="user")
    ingestion_requests: Mapped[list["IngestionRequest"]] = relationship(back_populates="user")

    @validates("timezone")
    def validate_timezone(self, key: str, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Timezone must be a valid IANA timezone") from None
        return value


class Problem(EntityMixin, Base):
    __tablename__ = "problems"
    __table_args__ = (
        UniqueConstraint("platform", "slug", name="uq_problems_platform_slug"),
        CheckConstraint("difficulty IN ('easy', 'medium', 'hard')", name="difficulty"),
        CheckConstraint("length(trim(slug)) > 0", name="slug_nonempty"),
        CheckConstraint("length(trim(title)) > 0", name="title_nonempty"),
        CheckConstraint("length(trim(platform)) > 0", name="platform_nonempty"),
    )

    platform: Mapped[str] = mapped_column(String(50), default="leetcode", server_default="leetcode")
    slug: Mapped[str] = mapped_column(String(200))
    title: Mapped[str] = mapped_column(String(300))
    difficulty: Mapped[str | None] = mapped_column(String(10))
    metadata_source: Mapped[str] = mapped_column(
        String(50), default="manual", server_default="manual"
    )

    topics: Mapped[list["Topic"]] = relationship(
        secondary="problem_topics", back_populates="problems"
    )
    submissions: Mapped[list["Submission"]] = relationship(back_populates="problem")


class Topic(EntityMixin, Base):
    __tablename__ = "topics"
    __table_args__ = (
        CheckConstraint("length(trim(slug)) > 0", name="slug_nonempty"),
        CheckConstraint("length(trim(name)) > 0", name="name_nonempty"),
    )

    slug: Mapped[str] = mapped_column(String(100), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    problems: Mapped[list[Problem]] = relationship(
        secondary="problem_topics", back_populates="topics"
    )


class ProblemTopic(Base):
    __tablename__ = "problem_topics"

    problem_id: Mapped[UUID] = mapped_column(ForeignKey("problems.id"), primary_key=True)
    topic_id: Mapped[UUID] = mapped_column(ForeignKey("topics.id"), primary_key=True)


class Submission(EntityMixin, Base):
    __tablename__ = "submissions"
    __table_args__ = (
        UniqueConstraint("user_id", "source", "record_key", name="uq_submissions_record"),
        Index(
            "uq_submissions_external",
            "user_id",
            "source",
            "external_submission_id",
            unique=True,
            postgresql_where=text("external_submission_id IS NOT NULL"),
        ),
        Index("ix_submissions_user_time", "user_id", "submitted_at"),
        Index("ix_submissions_user_problem", "user_id", "problem_id"),
        CheckConstraint(
            "status IN ('accepted', 'wrong_answer', 'time_limit_exceeded', "
            "'memory_limit_exceeded', 'runtime_error', 'compile_error', "
            "'output_limit_exceeded', 'internal_error', 'unknown')",
            name="status",
        ),
        CheckConstraint("length(trim(source)) > 0", name="source_nonempty"),
        CheckConstraint("length(trim(record_key)) > 0", name="record_key_nonempty"),
        CheckConstraint(
            "external_submission_id IS NULL OR length(trim(external_submission_id)) > 0",
            name="external_id_nonempty",
        ),
    )

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    problem_id: Mapped[UUID] = mapped_column(ForeignKey("problems.id"))
    status: Mapped[str] = mapped_column(String(30))
    submitted_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    source: Mapped[str] = mapped_column(String(50), default="manual", server_default="manual")
    external_submission_id: Mapped[str | None] = mapped_column(String(200))
    record_key: Mapped[str] = mapped_column(String(200))

    user: Mapped[User] = relationship(back_populates="submissions")
    problem: Mapped[Problem] = relationship(back_populates="submissions")


class IngestionRequest(EntityMixin, Base):
    __tablename__ = "ingestion_requests"
    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key", name="uq_ingestion_requests_user_key"),
        CheckConstraint("length(trim(idempotency_key)) > 0", name="key_nonempty"),
        CheckConstraint("payload_hash ~ '^[0-9a-f]{64}$'", name="sha256_hash"),
        CheckConstraint(
            "(completed_at IS NULL AND result IS NULL) OR "
            "(completed_at IS NOT NULL AND result IS NOT NULL)",
            name="completion_pair",
        ),
    )

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    idempotency_key: Mapped[str] = mapped_column(String(200))
    payload_hash: Mapped[str] = mapped_column(String(64))
    result: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    user: Mapped[User] = relationship(back_populates="ingestion_requests")
