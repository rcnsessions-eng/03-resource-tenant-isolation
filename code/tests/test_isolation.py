import json
import threading
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from fastapi.testclient import TestClient

from app.authz.client import OPAClient
from app.domain import Principal
from app.errors import ServiceError
from app.isolation.main import create_app
from app.isolation.repository import SQLiteLearningRepository
from app.isolation.service import IsolatedLearningService


def test_tenant_aware_repository() -> None:
    repository = SQLiteLearningRepository()
    assert repository.get_progress("tenant-red", "learner-red-1") is not None
    assert repository.get_progress("tenant-red", "learner-blue-1") is None
    assert repository.get_progress("tenant-blue", "learner-red-1") is None
    assert repository.get_progress("tenant-red", "learner-red-1' OR 1=1 --") is None
    assert len(repository.list_approved_content("tenant-red", 20)) == 1
    repository.close()


def test_revoked_membership_blocks_atomic_evidence_write() -> None:
    repository = SQLiteLearningRepository()
    principal = Principal(subject="learner-red-1", tenant_id="tenant-red")
    repository.revoke_membership(principal.tenant_id, principal.subject)
    with pytest.raises(ServiceError):
        repository.record_evidence(
            principal, principal.subject, "event-1", "synthetic evidence"
        )
    assert repository.evidence_count() == 0
    repository.close()


def allowed_response(request: httpx.Request) -> httpx.Response:
    action = json.loads(request.content)["input"]["action"]
    reason = (
        "OWNER_AND_TENANT_MATCH" if action == "progress.read" else "TENANT_APPROVED_CONTENT"
    )
    return httpx.Response(
        200, json={"result": {"allow": True, "reason_code": reason, "policy_version": "1.0.0"}}
    )


@pytest.mark.parametrize(
    "path",
    [
        "/v1/content",
        "/v1/learners/learner-red-1/progress",
    ],
)
def test_every_protected_endpoint_checks_current_membership(path: str) -> None:
    repository = SQLiteLearningRepository()
    repository.revoke_membership("tenant-red", "learner-red-1")
    with TestClient(create_app(repository, httpx.MockTransport(allowed_response))) as client:
        response = client.get(path, headers={"Authorization": "Bearer demo-learner-red"})
    assert response.status_code == 404
    assert "completion_percent" not in response.text and "items" not in response.text


@pytest.mark.parametrize("learner_id", ["learner-red-2", "learner-blue-1", "learner-missing"])
def test_id_substitution_and_claim_spoofing(learner_id: str) -> None:
    with TestClient(create_app(transport=httpx.MockTransport(allowed_response))) as client:
        response = client.get(
            f"/v1/learners/{learner_id}/progress",
            headers={
                "Authorization": "Bearer demo-learner-red",
                "X-Tenant-ID": "tenant-blue",
                "X-User-ID": "learner-blue-1",
                "X-Role": "instructor",
            },
        )
    assert response.status_code == 404
    assert learner_id not in response.text


def test_deleted_progress_and_unknown_look_identical() -> None:
    repository = SQLiteLearningRepository()
    repository.delete_progress("tenant-red", "learner-red-1")
    with TestClient(create_app(repository, httpx.MockTransport(allowed_response))) as client:
        headers = {"Authorization": "Bearer demo-learner-red", "X-Request-ID": "missing-check"}
        deleted = client.get("/v1/learners/learner-red-1/progress", headers=headers)
        missing = client.get("/v1/learners/learner-missing/progress", headers=headers)
    assert deleted.status_code == missing.status_code == 404
    assert deleted.json() == missing.json()


@pytest.mark.parametrize("path", ["/v1/content", "/v1/learners/learner-red-1/progress"])
def test_revocation_during_policy_decision_prevents_read(path: str) -> None:
    repository = SQLiteLearningRepository()

    def reply(request: httpx.Request) -> httpx.Response:
        repository.revoke_membership("tenant-red", "learner-red-1")
        return allowed_response(request)

    with TestClient(create_app(repository, httpx.MockTransport(reply))) as client:
        response = client.get(path, headers={"Authorization": "Bearer demo-learner-red"})
    assert response.status_code == 404
    assert "completion_percent" not in response.text and "items" not in response.text


def test_cross_tenant_and_non_owner_writes_have_no_effect() -> None:
    repository = SQLiteLearningRepository()
    principal = Principal(subject="learner-red-1", tenant_id="tenant-red")
    for owner in ["learner-red-2", "learner-blue-1"]:
        with pytest.raises(ServiceError):
            repository.record_evidence(principal, owner, "event-1", "synthetic denied evidence")
    forged = Principal(subject="learner-red-1", tenant_id="tenant-blue")
    with pytest.raises(ServiceError):
        repository.record_evidence(
            forged, forged.subject, "event-2", "synthetic denied evidence"
        )
    assert repository.evidence_count() == 0
    repository.close()


def test_current_member_repository_write_is_atomic() -> None:
    repository = SQLiteLearningRepository()
    principal = Principal(subject="learner-red-1", tenant_id="tenant-red")
    repository.record_evidence(principal, principal.subject, "event-1", "synthetic evidence")
    assert repository.evidence_count() == 1
    repository.close()


def test_policy_denied_evidence_has_no_side_effect() -> None:
    repository = SQLiteLearningRepository()
    policy = OPAClient(
        "http://policy",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "result": {
                        "allow": False,
                        "reason_code": "ACCESS_DENIED",
                        "policy_version": "1.0.0",
                    }
                },
            )
        ),
    )
    service = IsolatedLearningService(repository, policy, "evidence-denied")
    principal = Principal(subject="learner-red-1", tenant_id="tenant-red")
    with pytest.raises(ServiceError):
        service.record_evidence(
            principal, principal.subject, "event-1", "synthetic denied evidence"
        )
    assert repository.evidence_count() == 0
    policy.close()
    repository.close()


def test_concurrent_revocation_before_transaction_blocks_write() -> None:
    repository = SQLiteLearningRepository()
    principal = Principal(subject="learner-red-1", tenant_id="tenant-red")
    ready = threading.Event()
    revoked = threading.Event()

    def writer() -> None:
        assert (
            repository.get_learner_metadata(principal.tenant_id, principal.subject) is not None
        )
        ready.set()
        assert revoked.wait(timeout=2)
        with pytest.raises(ServiceError):
            repository.record_evidence(
                principal, principal.subject, "event-race", "synthetic denied evidence"
            )

    def revoker() -> None:
        assert ready.wait(timeout=2)
        repository.revoke_membership(principal.tenant_id, principal.subject)
        revoked.set()

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(writer)
        second = executor.submit(revoker)
        first.result(timeout=5)
        second.result(timeout=5)
    assert repository.evidence_count() == 0
    repository.close()


def test_no_route_can_omit_tenant_scope() -> None:
    repository = SQLiteLearningRepository()
    with pytest.raises(TypeError):
        repository.get_progress(learner_id="learner-red-1")
    assert repository.get_learner_metadata("", "learner-red-1") is None
    repository.close()
