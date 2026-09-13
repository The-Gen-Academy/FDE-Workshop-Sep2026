"""Local claim review and policy administration UI."""

from pathlib import Path

from claims_core.config import load_environment
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .routers import router

load_environment()

app = FastAPI(title="Adjuster Portal")
app.include_router(router)
app.mount(
    "/", StaticFiles(directory=Path(__file__).resolve().parent / "static", html=True), name="static"
)


@app.middleware("http")
async def no_store(request, call_next):
    """Keep claim state and local development assets fresh."""
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    return response
