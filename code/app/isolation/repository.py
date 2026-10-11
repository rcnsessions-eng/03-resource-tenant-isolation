import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager

from app.domain import Content, Learner, Principal, Progress
from app.errors import ServiceError
from app.repositories.memory import InMemoryLearningRepository


class SQLiteLearningRepository(InMemoryLearningRepository):
    def __init__(self) -> None:
        super().__init__()
        self.lock = threading.RLock()
        self.connection = sqlite3.connect(
            ":memory:", check_same_thread=False, isolation_level=None
        )
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript("""
            PRAGMA foreign_keys=ON;
            CREATE TABLE learners(tenant_id TEXT NOT NULL, id TEXT NOT NULL,
                active INTEGER NOT NULL, PRIMARY KEY(tenant_id,id));
            CREATE TABLE progress(tenant_id TEXT NOT NULL, learner_id TEXT NOT NULL,
                course_id TEXT NOT NULL, completion_percent REAL NOT NULL,
                PRIMARY KEY(tenant_id,learner_id),
                FOREIGN KEY(tenant_id,learner_id) REFERENCES learners(tenant_id,id));
            CREATE TABLE content(tenant_id TEXT NOT NULL, id TEXT NOT NULL,
                course_id TEXT NOT NULL,
                title TEXT NOT NULL, body TEXT NOT NULL, approved INTEGER NOT NULL,
                PRIMARY KEY(tenant_id,id));
            CREATE TABLE evidence(tenant_id TEXT NOT NULL, owner_id TEXT NOT NULL,
                event_id TEXT NOT NULL, value TEXT NOT NULL,
                PRIMARY KEY(tenant_id,owner_id,event_id),
                FOREIGN KEY(tenant_id,owner_id) REFERENCES learners(tenant_id,id));
        """)
        self.connection.executemany(
            "INSERT INTO learners VALUES(?,?,1)",
            [(learner.tenant_id, learner.id) for learner in self.learners],
        )
        self.connection.executemany(
            "INSERT INTO progress VALUES(?,?,?,?)",
            [
                (
                    record.tenant_id,
                    record.learner_id,
                    record.course_id,
                    record.completion_percent,
                )
                for record in self.progress
            ],
        )
        self.connection.executemany(
            "INSERT INTO content VALUES(?,?,?,?,?,?)",
            [
                (
                    record.tenant_id,
                    record.id,
                    record.course_id,
                    record.title,
                    record.body,
                    int(record.approved),
                )
                for record in self.content
            ],
        )

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self.lock:
            self.connection.execute("BEGIN IMMEDIATE")
            try:
                yield self.connection
                self.connection.execute("COMMIT")
            except Exception:
                self.connection.execute("ROLLBACK")
                raise

    @staticmethod
    def require_current_member(connection: sqlite3.Connection, principal: Principal) -> None:
        membership = connection.execute(
            "SELECT 1 FROM learners WHERE tenant_id=? AND id=? AND active=1",
            (principal.tenant_id, principal.subject),
        ).fetchone()
        if membership is None:
            raise ServiceError(404, "not_found", "Resource not found")

    def get_learner_metadata(self, tenant_id: str, learner_id: str) -> Learner | None:
        with self.lock:
            record = self.connection.execute(
                "SELECT tenant_id,id FROM learners WHERE tenant_id=? AND id=? AND active=1",
                (tenant_id, learner_id),
            ).fetchone()
        return Learner.model_validate(dict(record)) if record else None

    def list_approved_content(self, tenant_id: str, limit: int) -> tuple[Content, ...]:
        with self.lock:
            rows = self.connection.execute(
                "SELECT * FROM content WHERE tenant_id=? AND approved=1 ORDER BY id LIMIT ?",
                (tenant_id, max(0, min(limit, 20))),
            ).fetchall()
        return tuple(Content.model_validate(dict(row)) for row in rows)

    def get_progress(self, tenant_id: str, learner_id: str) -> Progress | None:
        with self.lock:
            row = self.connection.execute(
                """
                SELECT p.* FROM progress p JOIN learners l
                ON p.tenant_id=l.tenant_id AND p.learner_id=l.id
                WHERE p.tenant_id=? AND p.learner_id=? AND l.active=1
            """,
                (tenant_id, learner_id),
            ).fetchone()
        return Progress.model_validate(dict(row)) if row else None

    def read_progress_for(self, principal: Principal, learner_id: str) -> Progress:
        with self.transaction() as connection:
            self.require_current_member(connection, principal)
            if learner_id != principal.subject:
                raise ServiceError(404, "not_found", "Resource not found")
            record = self.get_progress(principal.tenant_id, learner_id)
            if record is None:
                raise ServiceError(404, "not_found", "Resource not found")
            return record

    def read_content_for(self, principal: Principal, limit: int) -> tuple[Content, ...]:
        with self.transaction() as connection:
            self.require_current_member(connection, principal)
            return self.list_approved_content(principal.tenant_id, limit)

    def record_evidence(
        self, principal: Principal, owner_id: str, event_id: str, value: str
    ) -> None:
        with self.transaction() as connection:
            self.require_current_member(connection, principal)
            if owner_id != principal.subject:
                raise ServiceError(404, "not_found", "Resource not found")
            connection.execute(
                "INSERT INTO evidence(tenant_id,owner_id,event_id,value) VALUES(?,?,?,?)",
                (principal.tenant_id, owner_id, event_id, value),
            )

    def revoke_membership(self, tenant_id: str, learner_id: str) -> None:
        with self.transaction() as connection:
            connection.execute(
                "UPDATE learners SET active=0 WHERE tenant_id=? AND id=?",
                (tenant_id, learner_id),
            )

    def delete_progress(self, tenant_id: str, learner_id: str) -> None:
        with self.transaction() as connection:
            connection.execute(
                "DELETE FROM progress WHERE tenant_id=? AND learner_id=?",
                (tenant_id, learner_id),
            )

    def evidence_count(self) -> int:
        with self.lock:
            row = self.connection.execute("SELECT COUNT(*) FROM evidence").fetchone()
        return int(row[0])

    def close(self) -> None:
        with self.lock:
            self.connection.close()
