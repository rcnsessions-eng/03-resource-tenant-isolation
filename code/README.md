# Resource and Tenant Isolation

This folder implements **only the resource and tenant isolation workshop**, extending the OPA authorization workshop's authorized services with a parameterized, tenant-aware SQLite repository. Earlier API and OPA code is reused through explicit image dependencies, not copied. Every numbered project retains its own Compose stack.

## Run and Verify

From this `code/` directory with the earlier project folders present:

```bash
bash scripts/check.sh
bash scripts/run.sh
LEARNING_BASE_URL=http://127.0.0.1:8222 python3 ../../01-foundation-learning-api/code/scripts/smoke.py
LEARNING_BASE_URL=http://127.0.0.1:8222 python3 ../../02-opa-authorization/code/scripts/outage_check.py
docker compose down
```

API UI: <http://127.0.0.1:8222/docs>. The default public demo credential is `demo-learner-red`; this is not production authentication. `LEARNING_PORT`, `LEARNING_SUBNET`, `LEARNING_BASE_URL` and `LEARNING_SMOKE_CREDENTIAL` support local overrides as in the preceding project. `.env.example` contains placeholders, not real secrets.

The check script builds and validates earlier dependencies first. This project's check image runs the inherited suites as well as its own isolation tests and policy mutation gate. Source and policy directories remain separate. Cleanup removes only this Compose project.

## Data Model and Enforcement

SQLite stores the same synthetic tenants/learners/progress/content plus an evidence table. Composite tenant/resource keys and foreign keys preserve scope. Every variable SQL value uses placeholders; no route directly queries SQL. Learner metadata is resolved with tenant and learner ID and current active membership. A bare ID does not grant access.

The service authorizes using authoritative metadata, then the repository checks current membership again inside `BEGIN IMMEDIATE` before reading protected data or mutating evidence. A process lock serializes transactions on the shared SQLite connection. A revocation committed before that transaction denies the operation. A revocation ordered after a completed transaction does not retroactively erase an authorized read/write; tests do not claim otherwise.

There are no instructor roles or cross-owner relationships. Same-tenant non-owner, cross-tenant, absent and deleted progress share a safe 404. The inherited demo credential identifies a fixture subject but cannot override current repository membership. Model output and raw tenant/user/role headers are not used to establish authority.

`record_evidence` is a service/repository test boundary, **not a new HTTP tool**. The inherited OPA policy still denies `evidence.record`; no public write authorization is implemented here. Repository-level tests demonstrate atomic membership/owner checks using trusted test principals and prove foreign/revoked writes create no records. Idempotency and approved write tool semantics belong to later workshops.

SQLite uses `:memory:` and resets on restart. Transactions demonstrate single-process state consistency, not distributed production persistence, multi-replica consistency or database row-level security. No extra database dependency is required. Existing API contracts remain unchanged.

## Isolation Matrix

| Operation | Allowed | Denied cases |
| --- | --- | --- |
| Approved content HTTP | Active learner, own tenant | Revoked membership, spoofed identity; foreign content absent |
| Progress HTTP | Active owner, own tenant | Same-tenant other, other tenant, missing/deleted progress, revoked during decision |
| Progress repository | Explicit tenant and current member | Omitted/wrong tenant, SQL-like ID substitution |
| Evidence service | None under inherited policy | Valid deny causes no write |
| Evidence repository | Trusted current owner in transaction | Foreign owner/tenant, revoked member, concurrent pre-transaction revocation |

Executed gates: 15 new isolation tests; combined 69 Python tests, 12 Rego tests and tenant-removal mutation passed; Ruff/format and strict mypy passed; real Compose HTTP smoke and scoped OPA outage/recovery passed. No hosted CI, mesh, real identity, SBOM or signing result is claimed.