import logging
from contextlib import asynccontextmanager

from alembic.script import ScriptDirectory
from fastapi import FastAPI

from app.api.health import router as health_router
from app.config import BACKEND_DIR, Settings
from app.db import build_engine, build_session_factory


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logging.basicConfig(level=settings.log_level, format="%(levelname)s %(name)s: %(message)s")
        app.state.engine = build_engine(settings)
        app.state.session_factory = build_session_factory(app.state.engine)
        app.state.migration_heads = set(
            ScriptDirectory(str(BACKEND_DIR / "migrations")).get_heads()
        )
        try:
            yield
        finally:
            app.state.engine.dispose()

    app = FastAPI(
        title="AlgoMentor AI API",
        description="Phase 2: backend and PostgreSQL foundation. Local development only.",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.include_router(health_router, prefix="/api/v1")
    return app
