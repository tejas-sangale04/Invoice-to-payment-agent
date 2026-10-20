from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import files, health, invoices, master_data, rules, tasks, users
from app.core.config import get_settings
from app.core.errors import register_error_handlers
from app.core.logging import configure_logging


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(title=settings.app_name, version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_error_handlers(app)
    app.include_router(health.router)
    app.include_router(users.router)
    app.include_router(master_data.router)
    app.include_router(rules.router)
    app.include_router(invoices.router)
    app.include_router(tasks.router)
    app.include_router(files.router)
    return app


app = create_app()
