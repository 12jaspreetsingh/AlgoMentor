import logging
from typing import Literal

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/health", tags=["health"])


class LiveResponse(BaseModel):
    status: Literal["ok"] = "ok"


class ReadyResponse(BaseModel):
    status: Literal["ok", "not_ready"]
    database: Literal["reachable", "unavailable"]
    schema_status: Literal["current", "not_current", "unavailable"]


@router.get("/live", response_model=LiveResponse)
def live() -> LiveResponse:
    return LiveResponse()


@router.get("/ready", response_model=ReadyResponse, responses={503: {"model": ReadyResponse}})
def ready(request: Request, response: Response) -> ReadyResponse:
    database = "unavailable"
    try:
        with request.app.state.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            database = "reachable"
            revisions = set(
                connection.execute(text("SELECT version_num FROM alembic_version")).scalars()
            )
        if revisions == request.app.state.migration_heads:
            return ReadyResponse(status="ok", database="reachable", schema_status="current")
        schema_status = "not_current"
        logger.warning("Database migration revision does not match the application")
    except SQLAlchemyError as error:
        # Do not expose connection details or SQL parameters in logs/responses.
        logger.warning("Database readiness check failed (%s)", type(error).__name__)
        schema_status = "unavailable"
    response.status_code = 503
    return ReadyResponse(status="not_ready", database=database, schema_status=schema_status)
