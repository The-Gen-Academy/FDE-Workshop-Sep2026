"""Local customer chat UI for an in-process or Vertex-hosted claims agent."""

from pathlib import Path

from claims_core.config import load_environment
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .routers import router

load_environment()

app = FastAPI(title="Client Portal")
app.include_router(router)
app.mount(
    "/", StaticFiles(directory=Path(__file__).resolve().parent / "static", html=True), name="static"
)


@app.middleware("http")
async def no_store(request, call_next):
    """Keep chat state and local development assets fresh."""
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    return response
