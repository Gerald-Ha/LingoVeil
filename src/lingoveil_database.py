from __future__ import annotations
import hashlib
import json
import secrets

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator
from uuid import UUID
from pathlib import Path
import psycopg

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from psycopg.rows import dict_row
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id uuid PRIMARY KEY,
    username text NOT NULL,
    username_normalized text NOT NULL UNIQUE,
    email text NOT NULL,
    email_normalized text NOT NULL UNIQUE,
    password_hash text NOT NULL,
    role text NOT NULL CHECK (role IN ('admin', 'user')),
    is_active boolean NOT NULL DEFAULT true,
    email_verified_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()

);

CREATE TABLE IF NOT EXISTS user_sessions (
    token_hash text PRIMARY KEY,
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at timestamptz NOT NULL DEFAULT now(),
    last_seen_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL
);

CREATE INDEX IF NOT EXISTS user_sessions_user_id_idx ON user_sessions(user_id);

CREATE INDEX IF NOT EXISTS user_sessions_expires_at_idx ON user_sessions(expires_at);

CREATE TABLE IF NOT EXISTS password_reset_codes (
    user_id uuid PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    code_hash text NOT NULL,
    attempts integer NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS user_settings (
    user_id uuid PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    settings jsonb NOT NULL DEFAULT '{}'::jsonb,
    updated_at timestamptz NOT NULL DEFAULT now()

);

CREATE TABLE IF NOT EXISTS system_settings (
    key text PRIMARY KEY,
    value jsonb NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()

);

CREATE TABLE IF NOT EXISTS manga_bookmarks (
    id text NOT NULL,
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    url text NOT NULL,
    payload jsonb NOT NULL,
    active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, id),
    UNIQUE (user_id, url)

);

CREATE INDEX IF NOT EXISTS manga_bookmarks_active_idx
    ON manga_bookmarks(user_id, active);

CREATE TABLE IF NOT EXISTS user_history (
    id text NOT NULL,
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    payload jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, id)

);

CREATE TABLE IF NOT EXISTS translation_results (
    id uuid PRIMARY KEY,
    cache_key text NOT NULL UNIQUE,
    owner_user_id uuid REFERENCES users(id) ON DELETE SET NULL,
    private_scope boolean NOT NULL DEFAULT false,
    source_hash text NOT NULL,
    source_language text NOT NULL,
    target_language text NOT NULL,
    engine text NOT NULL,
    engine_version text NOT NULL DEFAULT '',
    ocr_result jsonb,
    translated_result jsonb,
    artifact_key text,
    created_at timestamptz NOT NULL DEFAULT now()

);

CREATE TABLE IF NOT EXISTS translation_jobs (
    id uuid PRIMARY KEY,
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    job_key text NOT NULL,
    payload jsonb NOT NULL,
    status text NOT NULL CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')),
    priority integer NOT NULL DEFAULT 0,
    attempts integer NOT NULL DEFAULT 0,
    result_id uuid REFERENCES translation_results(id) ON DELETE SET NULL,
    error text NOT NULL DEFAULT '',
    created_at timestamptz NOT NULL DEFAULT now(),
    started_at timestamptz,
    finished_at timestamptz,
    UNIQUE (user_id, job_key)

);

CREATE INDEX IF NOT EXISTS translation_jobs_queue_idx
    ON translation_jobs(status, priority DESC, created_at);

CREATE TABLE IF NOT EXISTS notification_deliveries (
    id uuid PRIMARY KEY,
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    bookmark_id text NOT NULL,
    chapter_url text NOT NULL,
    channel text NOT NULL DEFAULT 'email',
    payload jsonb NOT NULL,
    status text NOT NULL CHECK (status IN ('pending', 'sending', 'sent', 'failed')),
    attempts integer NOT NULL DEFAULT 0,
    last_error text NOT NULL DEFAULT '',
    created_at timestamptz NOT NULL DEFAULT now(),
    sent_at timestamptz,
    UNIQUE (user_id, bookmark_id, chapter_url, channel)

);

CREATE INDEX IF NOT EXISTS notification_deliveries_pending_idx
    ON notification_deliveries(status, created_at);

"""
class Database:
    def __init__(self, dsn: str) -> None:
        if not dsn.strip():
            raise RuntimeError("LINGOVEIL_DATABASE_URL ist nicht gesetzt")

        self.dsn = dsn
    @contextmanager
    def connection(self) -> Iterator[psycopg.Connection[dict[str, Any]]]:
        with psycopg.connect(self.dsn, row_factory=dict_row) as connection:
            yield connection
    def initialize(self) -> None:
        with self.connection() as connection:
            connection.execute(SCHEMA_SQL)

    def healthy(self) -> bool:
        try:
            with self.connection() as connection:
                connection.execute("SELECT 1").fetchone()

            return True
        except psycopg.Error:
            return False
class AuthService:
    pass
    def __init__(self, database: Database, *, session_hours: int = 72) -> None:
        self.database = database
        self.session_hours = max(1, session_hours)

        self.passwords = PasswordHasher()

    @staticmethod
    def _normalized(value: str) -> str:
        return value.strip().casefold()

    @staticmethod
    def _token_hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @staticmethod
    def public_user(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(row["id"]),
            "username": str(row["username"]),
            "email": str(row["email"]),
            "role": str(row["role"]),
            "is_admin": row["role"] == "admin",
        }

    def register(self, username: str, email: str, password: str) -> dict[str, Any]:
        username = username.strip()

        email = email.strip()

        if len(username) < 3 or len(username) > 64:
            raise ValueError("Benutzername muss 3 bis 64 Zeichen lang sein")

        if "@" not in email or len(email) > 320:
            raise ValueError("Ungültige E-Mail-Adresse")

        if len(password) < 8 or len(password) > 1024:
            raise ValueError("Passwort muss mindestens 8 Zeichen lang sein")

        user_id = secrets.token_hex(16)

        password_hash = self.passwords.hash(password)

        try:
            with self.database.connection() as connection:
                connection.execute("SELECT pg_advisory_xact_lock(74219031)")

                existing = connection.execute("SELECT EXISTS(SELECT 1 FROM users) AS value").fetchone()

                registration = connection.execute(
                    "SELECT value FROM system_settings WHERE key = 'registration_enabled'"
                ).fetchone()

                registration_enabled = bool(registration and registration["value"] is True)

                if existing and existing["value"] and not registration_enabled:
                    raise ValueError("Neue Registrierungen sind derzeit deaktiviert")

                role = "user" if existing and existing["value"] else "admin"
                row = connection.execute(
                    """
                    INSERT INTO users (
                        id, username, username_normalized, email, email_normalized,
                        password_hash, role
                    ) VALUES (%s::uuid, %s, %s, %s, %s, %s, %s)

                    RETURNING *
                    """,
                    (
                        user_id,
                        username,
                        self._normalized(username),
                        email,
                        self._normalized(email),
                        password_hash,
                        role,
                    ),
                ).fetchone()

        except psycopg.errors.UniqueViolation as exc:
            raise ValueError("Benutzername oder E-Mail-Adresse ist bereits vergeben") from exc
        assert row is not None
        return self.public_user(row)

    def login(self, username: str, password: str) -> tuple[str, dict[str, Any]]:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM users WHERE username_normalized = %s AND is_active = true",
                (self._normalized(username),),
            ).fetchone()

            if row is None:
                raise ValueError("Ungültiger Benutzername oder ungültiges Passwort")

            try:
                self.passwords.verify(str(row["password_hash"]), password)

            except (VerifyMismatchError, InvalidHashError) as exc:
                raise ValueError("Ungültiger Benutzername oder ungültiges Passwort") from exc
            if self.passwords.check_needs_rehash(str(row["password_hash"])):
                connection.execute(
                    "UPDATE users SET password_hash = %s WHERE id = %s",
                    (self.passwords.hash(password), row["id"]),
                )

            token = secrets.token_urlsafe(48)

            expires = datetime.now(timezone.utc) + timedelta(hours=self.session_hours)

            connection.execute(
                "INSERT INTO user_sessions (token_hash, user_id, expires_at) VALUES (%s, %s, %s)",
                (self._token_hash(token), row["id"], expires),
            )

        return token, self.public_user(row)

    def authenticate(self, token: str | None) -> dict[str, Any] | None:
        if not token:
            return None
        with self.database.connection() as connection:
            row = connection.execute(
                """
                SELECT u.* FROM user_sessions s
                JOIN users u ON u.id = s.user_id
                WHERE s.token_hash = %s AND s.expires_at > now() AND u.is_active = true
                """,
                (self._token_hash(token),),
            ).fetchone()

            if row is None:
                return None
            connection.execute(
                "UPDATE user_sessions SET last_seen_at = now() WHERE token_hash = %s",
                (self._token_hash(token),),
            )

        return self.public_user(row)

    def logout(self, token: str | None) -> None:
        if not token:
            return
        with self.database.connection() as connection:
            connection.execute(
                "DELETE FROM user_sessions WHERE token_hash = %s",
                (self._token_hash(token),),
            )

    def update_account(
        self,
        user_id: str,
        *,
        username: str,
        email: str,
        current_password: str,
        new_password: str = "",
        current_token: str | None = None,
    ) -> dict[str, Any]:
        pass
        username = username.strip()

        email = email.strip()

        if len(username) < 3 or len(username) > 64:
            raise ValueError("Benutzername muss 3 bis 64 Zeichen lang sein")

        if "@" not in email or len(email) > 320:
            raise ValueError("Ungültige E-Mail-Adresse")

        if not current_password:
            raise ValueError("Das aktuelle Passwort ist erforderlich")

        if new_password and (len(new_password) < 8 or len(new_password) > 1024):
            raise ValueError("Das neue Passwort muss mindestens 8 Zeichen lang sein")

        try:
            with self.database.connection() as connection:
                row = connection.execute(
                    "SELECT * FROM users WHERE id = %s::uuid AND is_active = true FOR UPDATE",
                    (user_id,),
                ).fetchone()

                if row is None:
                    raise ValueError("Benutzerkonto wurde nicht gefunden")

                try:
                    self.passwords.verify(str(row["password_hash"]), current_password)

                except (VerifyMismatchError, InvalidHashError) as exc:
                    raise ValueError("Das aktuelle Passwort ist falsch") from exc
                password_hash = (
                    self.passwords.hash(new_password)

                    if new_password
                    else str(row["password_hash"])

                )

                updated = connection.execute(
                    """
                    UPDATE users
                    SET username = %s, username_normalized = %s,
                        email = %s, email_normalized = %s, password_hash = %s
                    WHERE id = %s::uuid
                    RETURNING *
                    """,
                    (
                        username,
                        self._normalized(username),
                        email,
                        self._normalized(email),
                        password_hash,
                        user_id,
                    ),
                ).fetchone()

                if new_password:
                    if current_token:
                        connection.execute(
                            "DELETE FROM user_sessions WHERE user_id = %s::uuid AND token_hash <> %s",
                            (user_id, self._token_hash(current_token)),
                        )

                    else:
                        connection.execute(
                            "DELETE FROM user_sessions WHERE user_id = %s::uuid",
                            (user_id,),
                        )

        except psycopg.errors.UniqueViolation as exc:
            raise ValueError("Benutzername oder E-Mail-Adresse ist bereits vergeben") from exc
        assert updated is not None
        return self.public_user(updated)

    def cleanup_sessions(self) -> None:
        with self.database.connection() as connection:
            connection.execute("DELETE FROM user_sessions WHERE expires_at <= now()")

    def create_password_reset(self, email: str) -> dict[str, Any]:
        normalized = self._normalized(email)

        with self.database.connection() as connection:
            row = connection.execute(
                """
                SELECT u.*, COALESCE(s.settings->>'interface_language', 'en') AS language
                FROM users u LEFT JOIN user_settings s ON s.user_id = u.id
                WHERE u.email_normalized = %s AND u.is_active = true
                """,
                (normalized,),
            ).fetchone()

            if row is None:
                raise ValueError("Für diese E-Mail-Adresse wurde kein Konto gefunden")

            previous = connection.execute(
                "SELECT created_at > now() - interval '60 seconds' AS recent FROM password_reset_codes WHERE user_id = %s",
                (row["id"],),
            ).fetchone()

            if previous and previous["recent"]:
                raise ValueError("Bitte warte eine Minute, bevor du einen neuen Code anforderst")

            code = f"{secrets.randbelow(1_000_000):06d}"
            connection.execute(
                """
                INSERT INTO password_reset_codes (user_id, code_hash, expires_at)

                VALUES (%s, %s, now() + interval '15 minutes')

                ON CONFLICT (user_id) DO UPDATE SET
                    code_hash = EXCLUDED.code_hash, attempts = 0,
                    created_at = now(), expires_at = EXCLUDED.expires_at
                """,
                (row["id"], self.passwords.hash(code)),
            )

        return {
            "user_id": str(row["id"]), "email": str(row["email"]),
            "username": str(row["username"]), "language": str(row["language"]),
            "code": code,
        }

    def revoke_password_reset(self, user_id: str) -> None:
        with self.database.connection() as connection:
            connection.execute(
                "DELETE FROM password_reset_codes WHERE user_id = %s::uuid", (user_id,)

            )

    def reset_password(self, email: str, code: str, new_password: str) -> None:
        if len(new_password) < 8 or len(new_password) > 1024:
            raise ValueError("Passwort muss mindestens 8 Zeichen lang sein")

        if len(code.strip()) != 6 or not code.strip().isdigit():
            raise ValueError("Der Wiederherstellungscode muss aus 6 Ziffern bestehen")

        invalid_code = False
        with self.database.connection() as connection:
            row = connection.execute(
                """
                SELECT u.id, r.code_hash, r.attempts, r.expires_at
                FROM users u JOIN password_reset_codes r ON r.user_id = u.id
                WHERE u.email_normalized = %s AND u.is_active = true
                FOR UPDATE OF r
                """,
                (self._normalized(email),),
            ).fetchone()

            if row is None or row["expires_at"] <= datetime.now(timezone.utc):
                raise ValueError("Der Wiederherstellungscode ist ungültig oder abgelaufen")

            if int(row["attempts"]) >= 5:
                raise ValueError("Zu viele Fehlversuche; fordere bitte einen neuen Code an")

            try:
                self.passwords.verify(str(row["code_hash"]), code.strip())

            except (VerifyMismatchError, InvalidHashError):
                connection.execute(
                    "UPDATE password_reset_codes SET attempts = attempts + 1 WHERE user_id = %s",
                    (row["id"],),
                )

                invalid_code = True
            if not invalid_code:
                connection.execute(
                    "UPDATE users SET password_hash = %s WHERE id = %s",
                    (self.passwords.hash(new_password), row["id"]),
                )

                connection.execute("DELETE FROM user_sessions WHERE user_id = %s", (row["id"],))

                connection.execute("DELETE FROM password_reset_codes WHERE user_id = %s", (row["id"],))

        if invalid_code:
            raise ValueError("Der Wiederherstellungscode ist ungültig oder abgelaufen")

class UserDataStore:
    pass
    def __init__(self, database: Database) -> None:
        self.database = database
    def users(self) -> list[dict[str, Any]]:
        with self.database.connection() as connection:
            return list(connection.execute(
                "SELECT id::text AS id, username, email, role FROM users WHERE is_active = true"
            ).fetchall())

    def registration_config(self) -> dict[str, Any]:
        pass
        with self.database.connection() as connection:
            enabled_row = connection.execute(
                "SELECT value FROM system_settings WHERE key = 'registration_enabled'"
            ).fetchone()

            admin = connection.execute(
                """
                SELECT u.id::text AS id, COALESCE(s.settings->>'interface_language', 'en') AS language
                FROM users u
                LEFT JOIN user_settings s ON s.user_id = u.id
                WHERE u.role = 'admin' AND u.is_active = true
                ORDER BY u.created_at ASC
                LIMIT 1
                """
            ).fetchone()

        configured_enabled = bool(enabled_row and enabled_row["value"] is True)

        return {
            "registration_enabled": admin is None or configured_enabled,
            "registration_configured_enabled": configured_enabled,
            "bootstrap_required": admin is None,
            "interface_language": (
                "de" if admin and admin["language"] == "de" else "en"
            ),
        }

    def set_registration_enabled(self, enabled: bool) -> None:
        with self.database.connection() as connection:
            connection.execute(
                """
                INSERT INTO system_settings (key, value) VALUES ('registration_enabled', %s::jsonb)

                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()

                """,
                (json.dumps(bool(enabled)),),
            )

    def delete_user(self, user_id: str) -> dict[str, Any]:
        pass
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT id::text AS id, username, role FROM users WHERE id = %s::uuid FOR UPDATE",
                (user_id,),
            ).fetchone()

            if row is None:
                raise ValueError("Benutzerkonto wurde nicht gefunden")

            if row["role"] == "admin":
                raise ValueError("Das Administratorkonto kann nicht gelöscht werden")

            connection.execute("DELETE FROM users WHERE id = %s::uuid", (user_id,))

        return dict(row)

    def migrate_legacy_files(self, user_id: str, data_dir: Path) -> bool:
        pass
        with self.database.connection() as connection:
            marker = connection.execute(
                "SELECT value FROM system_settings WHERE key = 'legacy_json_migrated'"
            ).fetchone()

            if marker is not None:
                return False
            connection.execute("SELECT pg_advisory_xact_lock(74219032)")

            marker = connection.execute(
                "SELECT value FROM system_settings WHERE key = 'legacy_json_migrated'"
            ).fetchone()

            if marker is not None:
                return False
            role = connection.execute(
                "SELECT role FROM users WHERE id = %s::uuid", (user_id,)

            ).fetchone()

            if role is None or role["role"] != "admin":
                return False
            bookmarks: list[dict[str, Any]] = []
            history: list[dict[str, Any]] = []
            settings: dict[str, Any] = {}

            try:
                raw = json.loads((data_dir / "bookmarks.json").read_text(encoding="utf-8"))

                bookmarks = list(raw.get("bookmarks", []))

                bookmarks.extend(
                    {**item, "active": False}

                    for item in raw.get("removed", {}).values()

                )

            except (OSError, ValueError, json.JSONDecodeError):
                pass
            try:
                raw = json.loads((data_dir / "history.json").read_text(encoding="utf-8"))

                history = list(raw.get("entries", []))

            except (OSError, ValueError, json.JSONDecodeError):
                pass
            try:
                settings = dict(json.loads((data_dir / "settings.json").read_text(encoding="utf-8")))

            except (OSError, ValueError, json.JSONDecodeError):
                pass
            connection.execute(
                "INSERT INTO system_settings (key, value) VALUES ('legacy_json_migrated', %s::jsonb)",
                (json.dumps({"user_id": user_id, "at": datetime.now(timezone.utc).isoformat()}),),
            )

        if bookmarks:
            self.replace_bookmarks(user_id, bookmarks)

        if history:
            self.replace_history(user_id, history)

        if settings:
            personal_keys = {
                "theme", "interface_language", "chapter_email_notifications",
                "engine", "source_language", "target_language", "prefetch_count",
                "history_limit", "bookmark_chapter_cache_limit", "default_view",
                "show_overflow", "show_debug_areas",
            }

            self.save_settings(user_id, {key: settings[key] for key in personal_keys if key in settings})

        return bool(bookmarks or history or settings)

    def enqueue_chapter_notifications(
        self,
        user_id: str,
        discoveries: list[dict[str, Any]],
    ) -> int:
        created = 0
        with self.database.connection() as connection:
            for discovery in discoveries:
                bookmark_id = str(discovery.get("bookmark_id", ""))

                for chapter in discovery.get("chapters", []):
                    chapter_url = str(chapter.get("url", ""))

                    if not bookmark_id or not chapter_url:
                        continue
                    result = connection.execute(
                        """
                        INSERT INTO notification_deliveries (
                            id, user_id, bookmark_id, chapter_url, payload, status
                        ) VALUES (%s::uuid, %s::uuid, %s, %s, %s::jsonb, 'pending')

                        ON CONFLICT (user_id, bookmark_id, chapter_url, channel) DO NOTHING
                        """,
                        (
                            secrets.token_hex(16), user_id, bookmark_id, chapter_url,
                            json.dumps({**discovery, "chapter": chapter}),
                        ),
                    )

                    created += result.rowcount
        return created
    def load_settings(self, user_id: str) -> dict[str, Any]:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT settings FROM user_settings WHERE user_id = %s::uuid",
                (user_id,),
            ).fetchone()

        return dict(row["settings"]) if row else {}

    def save_settings(self, user_id: str, settings: dict[str, Any]) -> None:
        with self.database.connection() as connection:
            connection.execute(
                """
                INSERT INTO user_settings (user_id, settings) VALUES (%s::uuid, %s::jsonb)

                ON CONFLICT (user_id) DO UPDATE
                SET settings = EXCLUDED.settings, updated_at = now()

                """,
                (user_id, json.dumps(settings)),
            )

    def load_history(self, user_id: str) -> list[dict[str, Any]]:
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT payload FROM user_history WHERE user_id = %s::uuid ORDER BY updated_at DESC",
                (user_id,),
            ).fetchall()

        return [dict(row["payload"]) for row in rows]
    def replace_history(self, user_id: str, entries: list[dict[str, Any]]) -> None:
        with self.database.connection() as connection:
            connection.execute("DELETE FROM user_history WHERE user_id = %s::uuid", (user_id,))

            for item in entries:
                entry_id = str(item.get("id", "")).strip()

                if not entry_id:
                    continue
                connection.execute(
                    """
                    INSERT INTO user_history (id, user_id, payload, created_at, updated_at)

                    VALUES (%s, %s::uuid, %s::jsonb, COALESCE(%s::timestamptz, now()), COALESCE(%s::timestamptz, now()))

                    """,
                    (
                        entry_id,
                        user_id,
                        json.dumps(item),
                        item.get("created_at") or None,
                        item.get("updated_at") or None,
                    ),
                )

    def load_bookmarks(self, user_id: str, *, include_removed: bool = False) -> list[dict[str, Any]]:
        clause = "" if include_removed else "AND active = true"
        with self.database.connection() as connection:
            rows = connection.execute(
                f"SELECT payload, active FROM manga_bookmarks WHERE user_id = %s::uuid {clause}",
                (user_id,),
            ).fetchall()

        return [{**dict(row["payload"]), "active": bool(row["active"])} for row in rows]
    def replace_bookmarks(self, user_id: str, bookmarks: list[dict[str, Any]]) -> None:
        with self.database.connection() as connection:
            connection.execute("DELETE FROM manga_bookmarks WHERE user_id = %s::uuid", (user_id,))

            for item in bookmarks:
                url = str(item.get("url", "")).strip()

                if not url:
                    continue
                bookmark_id = str(item.get("id") or hashlib.sha256(url.encode()).hexdigest()[:20])

                connection.execute(
                    """
                    INSERT INTO manga_bookmarks (id, user_id, url, payload, active)

                    VALUES (%s, %s::uuid, %s, %s::jsonb, %s)

                    """,
                    (bookmark_id, user_id, url, json.dumps(item), bool(item.get("active", True))),
                )

    def upsert_bookmark(self, user_id: str, item: dict[str, Any], *, active: bool = True) -> None:
        with self.database.connection() as connection:
            connection.execute(
                """
                INSERT INTO manga_bookmarks (id, user_id, url, payload, active)

                VALUES (%s, %s::uuid, %s, %s::jsonb, %s)

                ON CONFLICT (user_id, url) DO UPDATE
                SET payload = EXCLUDED.payload, active = EXCLUDED.active, updated_at = now()

                """,
                (item["id"], user_id, item["url"], json.dumps(item), active),
            )

    def export_user(self, user_id: str) -> dict[str, Any]:
        return {
            "format": "lingoveil-user-progress",
            "version": 2,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "settings": self.load_settings(user_id),
            "bookmarks": self.load_bookmarks(user_id, include_removed=True),
            "history": self.load_history(user_id),
        }

    def restore_user(self, user_id: str, payload: dict[str, Any]) -> dict[str, int]:
        if payload.get("format") != "lingoveil-user-progress" or payload.get("version") != 2:
            raise ValueError("Nicht unterstütztes Benutzer-Backup")

        bookmarks = payload.get("bookmarks", [])

        history = payload.get("history", [])

        settings = payload.get("settings", {})

        if not isinstance(bookmarks, list) or not isinstance(history, list) or not isinstance(settings, dict):
            raise ValueError("Backup enthält ungültige Daten")

        if len(bookmarks) > 5000 or len(history) > 5000:
            raise ValueError("Backup enthält zu viele Einträge")

        portable_history = []
        for raw_entry in history:
            if not isinstance(raw_entry, dict):
                raise ValueError("Backup enthält einen ungültigen History-Eintrag")

            entry = json.loads(json.dumps(raw_entry))

            url = str(entry.get("url", "")).strip()

            if not url.startswith(("http://", "https://")):
                raise ValueError("Backup enthält eine ungültige History-URL")

            entry["needs_refresh"] = True
            for image in entry.get("images", []):
                if isinstance(image, dict):
                    image["translations"] = {}

                    image["original_file"] = ""
            portable_history.append(entry)

        self.replace_bookmarks(user_id, bookmarks)

        self.replace_history(user_id, portable_history)

        self.save_settings(user_id, settings)

        return {"bookmarks": len(bookmarks), "history_entries": len(history)}
