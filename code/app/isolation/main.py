from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request

from app.api.routes import learning_service
from app.authz.client import OPAClient
from app.authz.main import PolicySettings
from app.authz.main import create_app as authorization_app
from app.isolation.repository import SQLiteLearningRepository
from app.isolation.service import IsolatedLearningService


def create_app(
    repository: SQLiteLearningRepository | None = None,
    transport: httpx.BaseTransport | None = None,
) -> FastAPI:
    import os

    records = repository if repository is not None else SQLiteLearningRepository()
    application = authorization_app(repository=records, transport=transport)
    settings = PolicySettings.model_validate(
        {
            "url": os.getenv("OPA_URL", "http://opa:8181"),
            "timeout": os.getenv("OPA_TIMEOUT_SECONDS", "0.5"),
        }
    )
    client = OPAClient(str(settings.url), settings.timeout, transport)

    def service_for_request(request: Request) -> IsolatedLearningService:
        return IsolatedLearningService(records, client, request.state.request_id)

    application.dependency_overrides[learning_service] = service_for_request
    previous_lifespan = application.router.lifespan_context

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        try:
            async with previous_lifespan(application):
                yield
        finally:
            client.close()
            records.close()

    application.router.lifespan_context = lifespan
    application.title = "PRD 03 Tenant-Isolated Learning API"
    return application
