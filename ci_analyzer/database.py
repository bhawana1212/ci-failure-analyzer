from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Build(Base):
    __tablename__ = "builds"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    project: Mapped[str] = mapped_column(String(120), index=True)
    branch: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(20), index=True)
    category: Mapped[str] = mapped_column(String(30), index=True)
    failed_stage: Mapped[str | None] = mapped_column(String(200))
    summary: Mapped[str] = mapped_column(Text)
    line_count: Mapped[int] = mapped_column(Integer)
    evidence: Mapped[list[dict]] = mapped_column(JSON)
    tests: Mapped[list["FailedTest"]] = relationship(
        cascade="all, delete-orphan", back_populates="build", lazy="selectin"
    )


class FailedTest(Base):
    __tablename__ = "failed_tests"

    build_id: Mapped[int] = mapped_column(ForeignKey("builds.id"), primary_key=True)
    name: Mapped[str] = mapped_column(String(500), primary_key=True)
    build: Mapped[Build] = relationship(back_populates="tests")


def make_engine(url: str):
    options = {"check_same_thread": False, "timeout": 30} if url.startswith("sqlite") else {}
    engine = create_engine(url, connect_args=options, pool_pre_ping=True)
    if engine.dialect.name == "sqlite":
        @event.listens_for(engine, "connect")
        def enable_foreign_keys(connection, _record):
            connection.execute("PRAGMA foreign_keys=ON")
    return engine