import os
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal, TypeAlias

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session

from ci_analyzer.analyzer import MAX_LOG_BYTES, analyze_log, redact
from ci_analyzer.database import Base, Build, FailedTest, make_engine

STATIC = Path(__file__).parent / "static"
Status = Literal["passed", "failed", "unstable", "aborted", "unknown"]
Category = Literal["test", "compilation", "timeout", "infrastructure", "build", "unknown", "none"]


class BuildInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=120)
    project: str = Field(default="default", min_length=1, max_length=120)
    branch: str = Field(default="main", min_length=1, max_length=120)
    log: str = Field(min_length=1, max_length=MAX_LOG_BYTES)


def session_dependency(request: Request):
    with Session(request.app.state.engine) as session:
        yield session


Database: TypeAlias = Annotated[Session, Depends(session_dependency)]


def serialize_build(build: Build, detail: bool = True) -> dict:
    timestamp = build.created_at
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    result = {
        "id": build.id,
        "name": build.name,
        "project": build.project,
        "branch": build.branch,
        "created_at": timestamp.isoformat(),
        "status": build.status,
        "category": build.category,
        "failed_stage": build.failed_stage,
        "summary": build.summary,
        "line_count": build.line_count,
        "failed_tests": sorted(test.name for test in build.tests),
    }
    if detail:
        result["evidence"] = build.evidence
    return result


def save_build(payload: BuildInput, session: Session) -> Build:
    try:
        analysis = analyze_log(payload.log)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    values = asdict(analysis)
    names = values.pop("failed_tests")
    build = Build(
        name=redact(payload.name)[:120],
        project=redact(payload.project)[:120],
        branch=redact(payload.branch)[:120],
        created_at=datetime.now(UTC),
        tests=[FailedTest(name=name) for name in names],
        **values,
    )
    session.add(build)
    session.commit()
    session.refresh(build)
    return build


def create_app(database_url: str | None = None) -> FastAPI:
    url = database_url or os.getenv("DATABASE_URL", "sqlite:///./ci-analyzer.db")

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        engine = make_engine(url)
        Base.metadata.create_all(engine)
        application.state.engine = engine
        yield
        engine.dispose()

    application = FastAPI(
        title="CI Failure Analyzer",
        description="Rule-based CI log analysis and reliability metrics. Local/trusted use only.",
        version="0.1.0",
        lifespan=lifespan,
    )

    @application.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @application.get("/health", tags=["Operations"])
    def health(session: Database):
        session.execute(text("SELECT 1"))
        return {"status": "ok"}

    @application.post("/api/builds", status_code=201, tags=["Builds"])
    def ingest_build(payload: BuildInput, session: Database):
        return serialize_build(save_build(payload, session))

    @application.post("/api/builds/upload", status_code=201, tags=["Builds"])
    def upload_build(
        session: Database,
        file: Annotated[UploadFile, File()],
        name: Annotated[str, Form(min_length=1, max_length=120)],
        project: Annotated[str, Form(min_length=1, max_length=120)] = "default",
        branch: Annotated[str, Form(min_length=1, max_length=120)] = "main",
    ):
        try:
            content = file.file.read(MAX_LOG_BYTES + 1)
        finally:
            file.file.close()
        if len(content) > MAX_LOG_BYTES:
            raise HTTPException(413, "Logs must be at most 2 MiB.")
        try:
            log = content.decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise HTTPException(422, "Upload a UTF-8 text log.") from error
        if "\x00" in log:
            raise HTTPException(422, "Upload a text log, not a binary file.")
        if not all(value.strip() for value in (name, project, branch, log)):
            raise HTTPException(422, "Build name, project, branch and log must not be blank.")
        payload = BuildInput(name=name, project=project, branch=branch, log=log)
        return serialize_build(save_build(payload, session))

    @application.get("/api/builds", tags=["Builds"])
    def list_builds(
        session: Database,
        status: Status | None = None,
        category: Category | None = None,
        project: Annotated[str | None, Query(max_length=120)] = None,
        search: Annotated[str | None, Query(max_length=120)] = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
        offset: Annotated[int, Query(ge=0)] = 0,
    ):
        query = select(Build)
        if status:
            query = query.where(Build.status == status)
        if category:
            query = query.where(Build.category == category)
        if project:
            query = query.where(Build.project == project)
        if search:
            query = query.where(or_(
                Build.name.icontains(search, autoescape=True),
                Build.project.icontains(search, autoescape=True),
                Build.branch.icontains(search, autoescape=True),
            ))
        total = session.scalar(select(func.count()).select_from(query.subquery()))
        builds = session.scalars(query.order_by(Build.id.desc()).offset(offset).limit(limit))
        return {"total": total, "items": [serialize_build(build, False) for build in builds]}

    @application.get("/api/builds/{build_id}", tags=["Builds"])
    def get_build(build_id: int, session: Database):
        build = session.get(Build, build_id)
        if build is None:
            raise HTTPException(404, "Build not found.")
        return serialize_build(build)

    @application.delete("/api/builds/{build_id}", status_code=204, tags=["Builds"])
    def delete_build(build_id: int, session: Database):
        build = session.get(Build, build_id)
        if build is None:
            raise HTTPException(404, "Build not found.")
        session.delete(build)
        session.commit()

    @application.get("/api/metrics", tags=["Metrics"])
    def metrics(session: Database):
        statuses = dict(session.execute(
            select(Build.status, func.count()).group_by(Build.status)
        ).all())
        categories = dict(session.execute(
            select(Build.category, func.count()).where(Build.status != "passed")
            .group_by(Build.category)
        ).all())
        top_tests = session.execute(
            select(FailedTest.name, func.count().label("count"))
            .group_by(FailedTest.name).order_by(func.count().desc(), FailedTest.name).limit(8)
        )
        recent = list(session.scalars(select(Build).order_by(Build.id.desc()).limit(30)))
        total = sum(statuses.values())
        known = total - statuses.get("unknown", 0)
        return {
            "total": total,
            "statuses": statuses,
            "pass_rate": round(100 * statuses.get("passed", 0) / known, 1) if known else None,
            "categories": categories,
            "top_tests": [{"name": name, "count": count} for name, count in top_tests],
            "recent": [
                {"id": build.id, "name": build.name, "status": build.status}
                for build in reversed(recent)
            ],
            "projects": list(session.scalars(
                select(Build.project).distinct().order_by(Build.project)
            )),
        }

    @application.get("/", include_in_schema=False)
    def dashboard():
        return FileResponse(STATIC / "index.html")

    application.mount("/static", StaticFiles(directory=STATIC, check_dir=False), name="static")
    return application


app = create_app()