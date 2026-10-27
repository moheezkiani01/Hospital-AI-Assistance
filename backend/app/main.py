from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.v1.api_router import api_router
from app.core.config import settings
from app.core.startup_checks import run_startup_checks
from app.db.base import Base
from app.db.database import engine
from app.services.audit_service import install_audit_listeners


install_audit_listeners()
Base.metadata.create_all(bind=engine)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Refuses to start in production if an admin still has a default password.
    run_startup_checks()
    yield


app = FastAPI(
    title="Hospital AI Assistant API",
    description="Backend API for multi-hospital AI assistant system",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api/v1")


@app.get("/")
def root():
    return {
        "message": "Hospital AI Assistant API is running",
        "database": "connected"
    }


@app.get("/health")
def health():
    """Liveness/readiness probe (used by Docker healthcheck). No secrets, no PHI."""
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception:
        raise HTTPException(status_code=503, detail="database unavailable")

    return {"status": "ok"}