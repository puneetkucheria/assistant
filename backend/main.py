"""FastAPI application entrypoint.

Mounts the API router under ``/api`` and serves the built React SPA from
``backend/static`` on all other paths. Designed to be run with:

    uvicorn backend.main:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import ipaddress
import os
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.api.chat import router as chat_router
from backend.api.health import router as health_router
from backend.config import get_settings

STATIC_DIR = Path(__file__).resolve().parent / "static"


class AllowedCIDRMiddleware:
    """Soft LAN gate: reject clients whose IP is outside the configured CIDR.

    Disabled when ``ALLOWED_CIDR`` is empty — the typical intranet case
    where the user trusts the network isolation. Enable it as cheap
    defence-in-depth when the server might be reachable from outside the
    intended network (e.g. via a firewall hole).
    """

    def __init__(self, app, cidr: str) -> None:
        self.app = app
        self.network = ipaddress.ip_network(cidr, strict=False)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        client_ip = scope.get("client")
        if client_ip:
            ip_str = client_ip[0]
            try:
                if ipaddress.ip_address(ip_str) not in self.network:
                    response = JSONResponse(
                        status_code=403,
                        content={"detail": "client IP not allowed"},
                    )
                    await response(scope, receive, send)
                    return
            except ValueError:
                pass
        await self.app(scope, receive, send)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, docs_url="/api/docs", openapi_url="/api/openapi.json")

    if settings.allowed_cidr:
        app.add_middleware(AllowedCIDRMiddleware, cidr=settings.allowed_cidr)

    if settings.cors_origin:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=[settings.cors_origin],
            allow_methods=["*"],
            allow_headers=["*"],
        )

    api_router = APIRouter()
    api_router.include_router(health_router)
    api_router.include_router(chat_router)
    app.include_router(api_router, prefix="/api")

    if STATIC_DIR.is_dir() and (STATIC_DIR / "index.html").exists():
        app.mount(
            "/assets",
            StaticFiles(directory=STATIC_DIR / "assets"),
            name="assets",
        )

        @app.get("/{full_path:path}")
        async def spa(full_path: str):
            # API docs / health are mounted under /api and handled above.
            if full_path.startswith("api"):
                return JSONResponse({"detail": "not found"}, status_code=404)
            candidate = STATIC_DIR / full_path
            if full_path and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(STATIC_DIR / "index.html")
    else:
        @app.get("/")
        async def root():
            return JSONResponse(
                {
                    "name": settings.app_name,
                    "message": (
                        "Frontend not built. Run: cd frontend && npm install && "
                        "npm run build, then restart the server. /api endpoints "
                        "are still available."
                    ),
                    "docs": "/api/docs",
                }
            )

    return app


# import here to avoid the circular issue with the APIRouter() alias above.
from fastapi import APIRouter  # noqa: E402

app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "backend.main:app",
        host=os.environ.get("HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", "8000")),
        reload=False,
    )
