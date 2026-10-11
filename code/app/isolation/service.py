from app.authz.client import OPAClient
from app.authz.contracts import ResourceContext
from app.authz.service import AuthorizedLearningService
from app.domain import ContentCollection, Principal, PublicContent, PublicProgress
from app.errors import ServiceError
from app.isolation.repository import SQLiteLearningRepository


class IsolatedLearningService(AuthorizedLearningService):
    def __init__(
        self, repository: SQLiteLearningRepository, policy: OPAClient, request_id: str
    ) -> None:
        super().__init__(repository, policy, request_id)
        self.scoped_repository = repository

    def read_progress(self, principal: Principal, learner_id: str) -> PublicProgress:
        if learner_id != principal.subject:
            raise ServiceError(404, "not_found", "Resource not found")
        learner = self.scoped_repository.get_learner_metadata(principal.tenant_id, learner_id)
        if learner is None:
            raise ServiceError(404, "not_found", "Resource not found")
        self.enforce(
            principal,
            "progress.read",
            ResourceContext(
                id="progress-" + learner.id,
                type="learner-progress",
                tenant_id=learner.tenant_id,
                owner_id=learner.id,
            ),
        )
        record = self.scoped_repository.read_progress_for(principal, learner_id)
        return PublicProgress(
            learner_id=record.learner_id,
            course_id=record.course_id,
            completion_percent=record.completion_percent,
        )

    def list_content(self, principal: Principal, limit: int) -> ContentCollection:
        learner = self.scoped_repository.get_learner_metadata(
            principal.tenant_id, principal.subject
        )
        if learner is None:
            raise ServiceError(404, "not_found", "Resource not found")
        self.enforce(
            principal,
            "content.search",
            ResourceContext(
                id="approved-" + learner.tenant_id,
                type="approved-content-collection",
                tenant_id=learner.tenant_id,
            ),
        )
        records = self.scoped_repository.read_content_for(principal, limit)
        return ContentCollection(
            items=[
                PublicContent(
                    id=record.id,
                    course_id=record.course_id,
                    title=record.title,
                    body=record.body,
                )
                for record in records
            ]
        )

    def record_evidence(
        self, principal: Principal, owner_id: str, event_id: str, value: str
    ) -> None:
        if owner_id != principal.subject:
            raise ServiceError(404, "not_found", "Resource not found")
        learner = self.scoped_repository.get_learner_metadata(principal.tenant_id, owner_id)
        if learner is None:
            raise ServiceError(404, "not_found", "Resource not found")
        self.enforce(
            principal,
            "evidence.record",
            ResourceContext(
                id="progress-" + learner.id,
                type="learner-progress",
                tenant_id=learner.tenant_id,
                owner_id=learner.id,
            ),
        )
        self.scoped_repository.record_evidence(principal, owner_id, event_id, value)
