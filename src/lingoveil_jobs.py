from __future__ import annotations
import hashlib
import json
import threading
import time

from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable
from uuid import uuid4
from lingoveil_database import Database
@dataclass
class _Work:
    job_id: str
    user_id: str
    task: Callable[[], Any]
    done: threading.Event = field(default_factory=threading.Event)

    result: Any = None
    error: BaseException | None = None
    owned: bool = True
class FairTranslationQueue:
    pass
    def __init__(self, database: Database) -> None:
        self.database = database
        self._condition = threading.Condition()

        self._queues: dict[str, deque[_Work]] = {}

        self._users: deque[str] = deque()

        self._stopping = False
        with self.database.connection() as connection:
            connection.execute(
                """
                UPDATE translation_jobs
                SET status = 'failed', error = 'Server während Ausführung beendet',
                    finished_at = now()

                WHERE status IN ('queued', 'running')

                """
            )

        self._thread = threading.Thread(
            target=self._run, name="lingoveil-fair-translation-queue", daemon=True
        )

        self._thread.start()

    def submit(
        self,
        user_id: str,
        job_key: str,
        payload: dict[str, Any],
        task: Callable[[], Any],
    ) -> Any:
        work = self.enqueue(user_id, job_key, payload, task)

        if not work.owned:
            while True:
                current = self.status(user_id, work.job_id)

                if current is None:
                    raise RuntimeError("Übersetzungsauftrag wurde nicht gefunden")

                if current["status"] == "succeeded":
                    return current["result"]
                if current["status"] in {"failed", "cancelled"}:
                    raise RuntimeError(current["error"] or "Übersetzungsauftrag fehlgeschlagen")

                time.sleep(0.25)

        work.done.wait()

        if work.error is not None:
            raise work.error
        return work.result
    def enqueue(
        self,
        user_id: str,
        job_key: str,
        payload: dict[str, Any],
        task: Callable[[], Any],
    ) -> _Work:
        pass
        job_id = str(uuid4())

        durable_key = hashlib.sha256(f"{user_id}:{job_key}".encode()).hexdigest()

        with self.database.connection() as connection:
            existing = connection.execute(
                """
                SELECT id::text AS id FROM translation_jobs
                WHERE user_id = %s::uuid AND job_key = %s
                  AND status IN ('queued', 'running')

                """,
                (user_id, durable_key),
            ).fetchone()

            if existing:
                return _Work(
                    job_id=str(existing["id"]), user_id=user_id, task=task, owned=False
                )

            row = connection.execute(
                """
                INSERT INTO translation_jobs (id, user_id, job_key, payload, status)

                VALUES (%s::uuid, %s::uuid, %s, %s::jsonb, 'queued')

                ON CONFLICT (user_id, job_key) DO UPDATE
                SET id = EXCLUDED.id, payload = EXCLUDED.payload, status = 'queued',
                    attempts = 0, result_id = NULL, error = '', created_at = now(),
                    started_at = NULL, finished_at = NULL
                RETURNING id::text AS id
                """,
                (job_id, user_id, durable_key, json.dumps(payload)),
            ).fetchone()

        work = _Work(job_id=str(row["id"]), user_id=user_id, task=task)

        with self._condition:
            queue = self._queues.setdefault(user_id, deque())

            queue.append(work)

            if user_id not in self._users:
                self._users.append(user_id)

            self._condition.notify()

        return work
    def status(self, user_id: str, job_id: str) -> dict[str, Any] | None:
        with self.database.connection() as connection:
            row = connection.execute(
                """
                SELECT j.id::text AS id, j.status, j.error, j.payload,
                       r.translated_result
                FROM translation_jobs j
                LEFT JOIN translation_results r ON r.id = j.result_id
                WHERE j.id = %s::uuid AND j.user_id = %s::uuid
                """,
                (job_id, user_id),
            ).fetchone()

        if not row:
            return None
        return {
            "job_id": row["id"],
            "status": row["status"],
            "error": row["error"],
            "payload": dict(row["payload"] or {}),
            "result": row["translated_result"],
        }

    def active_for_image_ids(
        self,
        user_id: str,
        image_ids: list[str],
    ) -> dict[str, dict[str, str]]:
        if not image_ids:
            return {}
        with self.database.connection() as connection:
            rows = connection.execute(
                """
                SELECT id::text AS id, status, payload->>'image_id' AS image_id
                FROM translation_jobs
                WHERE user_id = %s::uuid
                  AND status IN ('queued', 'running')
                  AND payload->>'image_id' = ANY(%s)
                """,
                (user_id, image_ids),
            ).fetchall()
        return {
            str(row["image_id"]): {
                "job_id": str(row["id"]),
                "status": str(row["status"]),
            }
            for row in rows
            if row.get("image_id")
        }

    def statuses(self, user_id: str, job_ids: list[str]) -> dict[str, str]:
        if not job_ids:
            return {}
        with self.database.connection() as connection:
            rows = connection.execute(
                """
                SELECT id::text AS id, status
                FROM translation_jobs
                WHERE user_id = %s::uuid AND id = ANY(%s::uuid[])
                """,
                (user_id, job_ids),
            ).fetchall()
        return {str(row["id"]): str(row["status"]) for row in rows}

    def _next(self) -> _Work | None:
        with self._condition:
            while not self._stopping and not self._users:
                self._condition.wait()

            if self._stopping:
                return None
            user_id = self._users.popleft()

            queue = self._queues[user_id]
            work = queue.popleft()

            if queue:
                self._users.append(user_id)

            else:
                del self._queues[user_id]
            return work
    def _run(self) -> None:
        while True:
            work = self._next()

            if work is None:
                return
            try:
                with self.database.connection() as connection:
                    connection.execute(
                        "UPDATE translation_jobs SET status = 'running', attempts = attempts + 1, started_at = now() WHERE id = %s::uuid",
                        (work.job_id,),
                    )

                work.result = work.task()

                result_id = str(uuid4())

                with self.database.connection() as connection:
                    job = connection.execute(
                        "SELECT job_key, payload FROM translation_jobs WHERE id = %s::uuid",
                        (work.job_id,),
                    ).fetchone()

                    payload = dict(job["payload"])

                    connection.execute(
                        """
                        INSERT INTO translation_results (
                            id, cache_key, owner_user_id, private_scope, source_hash,
                            source_language, target_language, engine, translated_result
                        ) VALUES (%s::uuid, %s, %s::uuid, true, %s, %s, %s, %s, %s::jsonb)

                        ON CONFLICT (cache_key) DO UPDATE
                        SET translated_result = EXCLUDED.translated_result, created_at = now()

                        """,
                        (
                            result_id, job["job_key"], work.user_id,
                            hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest(),
                            str(payload.get("source_language", "eng")),
                            str(payload.get("target_language", "deu")),
                            str(payload.get("engine", "")),
                            json.dumps(work.result),
                        ),
                    )

                    result_row = connection.execute(
                        "SELECT id FROM translation_results WHERE cache_key = %s",
                        (job["job_key"],),
                    ).fetchone()

                    connection.execute(
                        "UPDATE translation_jobs SET status = 'succeeded', result_id = %s, finished_at = now() WHERE id = %s::uuid",
                        (result_row["id"], work.job_id),
                    )

            except BaseException as exc:
                work.error = exc
                with self.database.connection() as connection:
                    connection.execute(
                        "UPDATE translation_jobs SET status = 'failed', error = %s, finished_at = now() WHERE id = %s::uuid",
                        (str(exc)[:2000], work.job_id),
                    )

            finally:
                work.done.set()

    def stop(self) -> None:
        with self._condition:
            self._stopping = True
            self._condition.notify_all()

        self._thread.join(timeout=5)
