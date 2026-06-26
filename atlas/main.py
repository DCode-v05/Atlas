"""FastAPI application: lifespan builds the runtime, mounts the API + SSE, and
serves the built frontend (single container) when present.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from atlas.api import router as api_router, wellknown_router
from atlas.config import get_settings
from atlas.runtime import Runtime, build_runtime

WEB_DIST = Path(__file__).resolve().parent.parent / "web" / "dist"


def _client_key(request: Request) -> Optional[str]:
    """The API key a caller presented: an X-API-Key header, a Bearer token, or
    (for the SSE stream, which can't set headers) a ?key= query param."""
    k = request.headers.get("x-api-key")
    if k:
        return k
    authz = request.headers.get("authorization", "")
    if authz[:7].lower() == "bearer ":
        return authz[7:].strip()
    return request.query_params.get("key")


def _serve_index(request: Request):
    """Serve the SPA shell, injecting the edge API key for the bundled operator
    console when auth is enabled (so the first-party UI can authenticate). The key
    is exposed only to the same-origin console; a hardened deployment would front
    Atlas with an auth proxy rather than handing the key to the browser."""
    rt = getattr(request.app.state, "runtime", None)
    key = rt.settings.api_key if rt is not None else get_settings().api_key
    if not key:
        return FileResponse(str(WEB_DIST / "index.html"))
    html = (WEB_DIST / "index.html").read_text(encoding="utf-8")
    tag = f"<script>window.__ATLAS_API_KEY__={json.dumps(key)}</script>"
    return HTMLResponse(html.replace("</head>", tag + "</head>", 1))


@asynccontextmanager
async def lifespan(app: FastAPI):
    # tests inject a pre-built (sqlite + fake-LLM) runtime so the REAL boot path runs offline
    rt = getattr(app.state, "preset_runtime", None) or build_runtime(get_settings())
    app.state.runtime = rt
    if rt.db is not None:
        from atlas.db import seed_org

        await rt.db.create_all()
        await seed_org(rt.db, rt.snapshot)  # mirror the org into the DB on first boot (idempotent)
        if rt.network is not None:
            await rt.network.init()  # load/create the signing key + re-hydrate live sessions
        if rt.dbwriter is not None:
            await rt.dbwriter.start(rt.broker)  # durable write-through worker + telemetry tap
    await rt.registry.start_heartbeat()
    await rt.push.start()
    try:
        yield
    finally:
        await rt.registry.stop_heartbeat()
        await rt.cron.stop()
        await rt.push.stop()
        if rt.dbwriter is not None:
            await rt.dbwriter.stop()
        if rt.db is not None:
            await rt.db.dispose()


def create_app(runtime: Optional[Runtime] = None) -> FastAPI:
    app = FastAPI(title="Atlas — A2A Communication Platform", version="0.1.0", lifespan=lifespan)
    if runtime is not None:
        app.state.preset_runtime = runtime  # the lifespan uses this instead of building one
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def _enforce_edge_auth(request: Request, call_next):
        # Opt-in edge auth: only when ATLAS_API_KEY is set. The static UI and
        # /api/healthz stay open; every other /api/* request must present the key.
        path = request.url.path
        if request.method != "OPTIONS" and path.startswith("/api/") and path != "/api/healthz":
            rt = getattr(request.app.state, "runtime", None)
            key = rt.settings.api_key if rt is not None else get_settings().api_key
            if key:
                presented = _client_key(request)
                if not presented:
                    return JSONResponse(
                        {"error": "authentication required"},
                        status_code=401,
                        headers={"WWW-Authenticate": "Bearer"},
                    )
                if presented != key:
                    return JSONResponse({"error": "forbidden"}, status_code=403)
        return await call_next(request)

    app.include_router(api_router)
    # Root-level A2A discovery (/.well-known/...). Registered before the SPA
    # catch-all so it isn't swallowed by the static-file fallback, and outside
    # /api so the edge-auth middleware leaves public discovery open.
    app.include_router(wellknown_router)

    if WEB_DIST.exists():
        assets = WEB_DIST / "assets"
        if assets.exists():
            app.mount("/assets", StaticFiles(directory=str(assets)), name="assets")

        @app.get("/")
        async def index(request: Request):
            return _serve_index(request)

        @app.get("/{path:path}")
        async def spa(path: str, request: Request):
            target = WEB_DIST / path
            if target.is_file():
                return FileResponse(str(target))
            return _serve_index(request)
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
