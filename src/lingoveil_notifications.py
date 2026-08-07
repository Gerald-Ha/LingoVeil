from __future__ import annotations
import html
import os
import smtplib
import ssl

from collections import OrderedDict
from email.message import EmailMessage
from email.utils import formataddr, parseaddr
from typing import Any
from urllib.parse import urlparse
from lingoveil_database import Database
class ChapterNotificationMailer:
    def __init__(self, database: Database) -> None:
        self.database = database
        self.host = os.environ.get("LINGOVEIL_SMTP_HOST", "").strip()

        self.port = int(os.environ.get("LINGOVEIL_SMTP_PORT", "587"))

        self.use_tls = os.environ.get("LINGOVEIL_SMTP_USE_TLS", "true").strip().lower() in {
            "1", "true", "yes", "on"
        }

        self.username = os.environ.get("LINGOVEIL_SMTP_USERNAME", "").strip()

        self.password = os.environ.get("LINGOVEIL_SMTP_PASSWORD", "")

        self.sender = os.environ.get("LINGOVEIL_SMTP_FROM", "").strip()

        self.sender_name = os.environ.get(
            "LINGOVEIL_SMTP_FROM_NAME", "LingoVeil Manga Updates"
        ).strip() or "LingoVeil Manga Updates"
        public_url = os.environ.get("LINGOVEIL_PUBLIC_URL", "").strip().rstrip("/")

        hostname = (urlparse(public_url).hostname or "").lower()

        self.public_url = "" if hostname in {"localhost", "127.0.0.1", "::1"} else public_url
    @property
    def configured(self) -> bool:
        return bool(self.host and self.sender)

    def _send(self, message: EmailMessage) -> None:
        smtp = (
            smtplib.SMTP(self.host, self.port, timeout=30)

            if self.use_tls
            else smtplib.SMTP_SSL(
                self.host, self.port, timeout=30, context=ssl.create_default_context()

            )

        )

        with smtp:
            if self.use_tls:
                smtp.starttls(context=ssl.create_default_context())

            if self.username:
                smtp.login(self.username, self.password)

            smtp.send_message(message)

    def send_password_reset(self, *, email: str, username: str, code: str, language: str) -> None:
        if not self.configured:
            raise RuntimeError("SMTP wurde vom Administrator noch nicht konfiguriert")

        english = language == "en"
        message = EmailMessage()

        sender_address = parseaddr(self.sender)[1] or self.sender
        message["From"] = formataddr(("LingoVeil", sender_address))

        message["To"] = email
        message["Subject"] = "LingoVeil password reset" if english else "LingoVeil Passwort zurücksetzen"
        intro = (
            f"Hello {username}, use this code to reset your LingoVeil password:"
            if english else
            f"Hallo {username}, verwende diesen Code, um dein LingoVeil-Passwort zurückzusetzen:"
        )

        expiry = (
            "The code is valid for 15 minutes. If you did not request it, you can ignore this email."
            if english else
            "Der Code ist 15 Minuten gültig. Falls du ihn nicht angefordert hast, kannst du diese E-Mail ignorieren."
        )

        message.set_content(f"{intro}\n\n{code}\n\n{expiry}\n")

        message.add_alternative(
            '<!doctype html><html><body style="background:#0f121a;color:#edf1ff;'
            'font-family:Arial,sans-serif;margin:0;padding:24px"><main style="max-width:560px;margin:auto">'
            '<h1 style="font-size:24px">LingoVeil</h1>'
            f'<p style="color:#b8c0d9">{html.escape(intro)}</p>'
            f'<div style="font-size:32px;letter-spacing:8px;font-weight:700;color:#8aa4ff;'
            f'background:#171b26;border:1px solid #30384d;border-radius:12px;padding:18px;text-align:center">{code}</div>'
            f'<p style="color:#b8c0d9">{html.escape(expiry)}</p></main></body></html>',
            subtype="html",
        )

        self._send(message)

    def _claim_batch(self, limit: int) -> dict[str, Any] | None:
        pass
        with self.database.connection() as connection:
            user_row = connection.execute(
                """
                SELECT n.user_id, u.email,
                       COALESCE(s.settings->>'interface_language', 'de') AS language
                FROM notification_deliveries n
                JOIN users u ON u.id = n.user_id
                JOIN user_settings s ON s.user_id = n.user_id
                WHERE n.status IN ('pending', 'failed') AND n.attempts < 5
                  AND COALESCE((s.settings->>'chapter_email_notifications')::boolean, false)

                ORDER BY n.created_at
                FOR UPDATE OF n SKIP LOCKED
                LIMIT 1
                """
            ).fetchone()

            if user_row is None:
                return None
            rows = connection.execute(
                """
                SELECT id, payload
                FROM notification_deliveries
                WHERE user_id = %s::uuid
                  AND status IN ('pending', 'failed') AND attempts < 5
                ORDER BY created_at
                FOR UPDATE SKIP LOCKED
                LIMIT %s
                """,
                (user_row["user_id"], max(1, limit)),
            ).fetchall()

            ids = [row["id"] for row in rows]
            if not ids:
                return None
            connection.execute(
                """
                UPDATE notification_deliveries
                SET status = 'sending', attempts = attempts + 1
                WHERE id = ANY(%s)

                """,
                (ids,),
            )

            return {
                "ids": ids,
                "email": str(user_row["email"]),
                "language": str(user_row["language"]),
                "payloads": [dict(row["payload"]) for row in rows],
            }

    def _finish(self, notification_ids: list[Any], error: str = "") -> None:
        with self.database.connection() as connection:
            connection.execute(
                """
                UPDATE notification_deliveries
                SET status = %s, last_error = %s,
                    sent_at = CASE WHEN %s = '' THEN now() ELSE sent_at END
                WHERE id = ANY(%s)

                """,
                (
                    "failed" if error else "sent",
                    error[:2000],
                    error,
                    notification_ids,
                ),
            )

    @staticmethod
    def _group(payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
        grouped: OrderedDict[str, dict[str, Any]] = OrderedDict()

        for payload in payloads:
            title = str(payload.get("title") or payload.get("manga_url") or "Manga")

            item = grouped.setdefault(title, {"title": title, "chapters": []})

            chapter = dict(payload.get("chapter", {}))

            label = str(chapter.get("label") or chapter.get("chapter") or chapter.get("url") or "Chapter")

            if label not in item["chapters"]:
                item["chapters"].append(label)

        return list(grouped.values())

    def _message(self, batch: dict[str, Any]) -> EmailMessage:
        english = batch["language"] == "en"
        grouped = self._group(batch["payloads"])

        chapter_count = sum(len(item["chapters"]) for item in grouped)

        message = EmailMessage()

        sender_address = parseaddr(self.sender)[1] or self.sender
        message["From"] = formataddr((self.sender_name, sender_address))

        message["To"] = batch["email"]
        if english:
            message["Subject"] = f"{chapter_count} new manga chapter update(s)"
            intro = "LingoVeil found new chapters for your bookmarks:"
            closing = "Open LingoVeil to continue reading."
            button = "Open LingoVeil"
        else:
            message["Subject"] = f"{chapter_count} neue Manga-Chapter"
            intro = "LingoVeil hat neue Chapter für deine Bookmarks gefunden:"
            closing = "Öffne LingoVeil, um weiterzulesen."
            button = "LingoVeil öffnen"
        text_lines = [intro, ""]
        cards = []
        for item in grouped:
            text_lines.append(item["title"])

            text_lines.extend(f"  • {chapter}" for chapter in item["chapters"])

            text_lines.append("")

            chapter_html = "".join(
                f'<li style="color:#33d17a;font-weight:700;margin:6px 0">{html.escape(chapter)}</li>'
                for chapter in item["chapters"]
            )

            cards.append(
                '<section style="background:#171b26;border:1px solid #30384d;'
                'border-radius:12px;padding:16px 18px;margin:14px 0">'
                f'<h2 style="color:#8aa4ff;font-size:18px;margin:0 0 8px">{html.escape(item["title"])}</h2>'
                f'<ul style="margin:0;padding-left:22px">{chapter_html}</ul></section>'
            )

        if self.public_url:
            text_lines.extend([f"{button}: {self.public_url}", ""])

            action_html = (
                f'<a href="{html.escape(self.public_url, quote=True)}" style="display:inline-block;'
                'background:#6f8cff;color:#fff;text-decoration:none;border-radius:8px;'
                f'padding:11px 18px;font-weight:700">{html.escape(button)}</a>'
            )

        else:
            text_lines.extend([closing, ""])

            action_html = f'<p style="color:#b8c0d9">{html.escape(closing)}</p>'
        message.set_content("\n".join(text_lines))

        message.add_alternative(
            '<!doctype html><html><body style="background:#0f121a;color:#edf1ff;'
            'font-family:Arial,sans-serif;margin:0;padding:24px">'
            '<main style="max-width:640px;margin:auto">'
            '<h1 style="color:#edf1ff;font-size:24px">LingoVeil</h1>'
            f'<p style="color:#b8c0d9">{html.escape(intro)}</p>'
            f'{"".join(cards)}{action_html}</main></body></html>',
            subtype="html",
        )

        return message
    def deliver_pending(self, *, limit: int = 100) -> dict[str, int]:
        if not self.configured:
            return {"sent": 0, "failed": 0}

        sent = failed = processed = 0
        while processed < max(1, limit):
            batch = self._claim_batch(max(1, limit - processed))

            if batch is None:
                break
            try:
                message = self._message(batch)

                self._send(message)

                self._finish(batch["ids"])

                sent += 1
            except Exception as exc:
                self._finish(batch["ids"], str(exc))

                failed += 1
            processed += len(batch["ids"])

        return {"sent": sent, "failed": failed}
