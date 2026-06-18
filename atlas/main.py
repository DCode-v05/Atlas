"""FastAPI application: lifespan builds the runtime, mounts the API + SSE, and
serves the built frontend (single container) when present.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from atlas.api import router as api_router
from atlas.config import get_settings
from atlas.runtime import build_runtime

WEB_DIST = Path(__file__).resolve().parent.parent / "web" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    rt = build_runtime(get_settings())
    app.state.runtime = rt
    await rt.registry.start_heartbeat()
    try:
        yield
    finally:
        await rt.registry.stop_heartbeat()
        await rt.cron.stop()


def create_app() -> FastAPI:
    app = FastAPI(title="Atlas — A2A Communication Platform", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(api_router)

    if WEB_DIST.exists():
        assets = WEB_DIST / "assets"
        if assets.exists():
            app.mount("/assets", StaticFiles(directory=str(assets)), name="assets")

        @app.get("/")
        async def index():
            return FileResponse(str(WEB_DIST / "index.html"))

        @app.get("/{path:path}")
        async def spa(path: str):
            target = WEB_DIST / path
            if target.is_file():
                return FileResponse(str(target))
            return FileResponse(str(WEB_DIST / "index.html"))
    else:

        @app.get("/")
        async def placeholder():
            return JSONResponse(
                {
                    "service": "Atlas A2A backend",
                    "status": "running",
                    "agents": 100,
                    "hint": "Build the frontend in web/ (npm run build) or run the Vite dev server. API is under /api.",
                    "api": ["/api/org", "/api/events (SSE)", "/api/prompt", "/api/cron", "/api/hitl", "/api/metrics"],
                }
            )

    return app


app = create_app()


def main() -> None:
    import uvicorn

    settings = get_settings()
    uvicorn.run("atlas.main:app", host=settings.host, port=settings.port, workers=1, reload=False)


if __name__ == "__main__":
    main()
