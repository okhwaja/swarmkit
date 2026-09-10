"""Replay durable events into the existing immutable delivery outbox."""

import re

from .core import SwarmError, json_dump, json_load, transaction
from .storage import add_event, mission


def validate_subscriptions(specifications):
    if not isinstance(specifications, list):
        raise SwarmError("notifications must be a list")
    seen = set()
    for spec in specifications:
        if not isinstance(spec, dict) or set(spec) - {
            "id",
            "version",
            "extension",
            "channel",
            "recipients",
            "events",
            "after_seq",
        }:
            raise SwarmError("Invalid notification subscription fields")
        if not isinstance(spec.get("id"), str) or not re.fullmatch(r"[a-z0-9_-]+", spec["id"]):
            raise SwarmError(
                "Notification id must contain lowercase letters, digits, underscores or hyphens"
            )
        if spec["id"] in seen:
            raise SwarmError("Notification ids must be unique")
        seen.add(spec["id"])
        for field, minimum in (("version", 1), ("after_seq", 0)):
            value = spec.get(field, minimum)
            if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
                raise SwarmError("Notification %s must be an integer >= %s" % (field, minimum))
        for field in ("extension", "channel"):
            if not isinstance(spec.get(field), str) or not spec[field].strip():
                raise SwarmError("Notification %s is required" % field)
        for field in ("recipients", "events"):
            if (
                not isinstance(spec.get(field), list)
                or not spec[field]
                or not all(isinstance(x, str) and x.strip() for x in spec[field])
            ):
                raise SwarmError("Notification %s must be a nonempty list of strings" % field)
        if any(
            event.startswith("DELIVERY_") or event.startswith("NOTIFICATION_")
            for event in spec["events"]
        ):
            raise SwarmError("Delivery and notification events cannot trigger notification loops")
    return specifications


def enqueue_notifications(root, conn, specifications, limit=100):
    """Cursor advancement and enqueue commit together; provider dispatch happens later."""
    from .delivery import enqueue_delivery, validate_recipients

    validate_subscriptions(specifications)
    with transaction(conn):
        active = {
            (row["id"], row["version"])
            for row in conn.execute(
                "SELECT id,version FROM notification_subscriptions WHERE active=1"
            )
        }
        selected = {(spec["id"], spec.get("version", 1)) for spec in specifications}
        for identifier, version in active - selected:
            conn.execute(
                "UPDATE notification_subscriptions SET active=0 WHERE id=? AND version=?",
                (identifier, version),
            )
            add_event(
                conn,
                mission(conn)["id"],
                "notification",
                identifier,
                "NOTIFICATION_DISABLED",
                "configuration",
                {"version": version},
            )
        for spec in specifications:
            identifier, version = spec["id"], spec.get("version", 1)
            encoded = json_dump(spec)
            extension = conn.execute(
                "SELECT manifest_json FROM extensions WHERE id=?", (spec["extension"],)
            ).fetchone()
            if not extension:
                raise SwarmError("Unknown notification extension: " + spec["extension"])
            manifest = json_load(extension[0], {})
            if spec["channel"] not in manifest["handles"]:
                raise SwarmError(
                    "Notification extension does not handle channel " + spec["channel"]
                )
            validate_recipients(manifest, spec["recipients"])
            previous = conn.execute(
                "SELECT * FROM notification_subscriptions WHERE id=? AND version=?",
                (identifier, version),
            ).fetchone()
            if previous and previous["specification_json"] != encoded:
                raise SwarmError("Changed notification subscription requires a new version")
            conn.execute(
                "INSERT INTO notification_subscriptions VALUES(?,?,?,?,1) ON CONFLICT(id,version) DO UPDATE SET active=1",
                (identifier, version, encoded, spec.get("after_seq", 0)),
            )
            if (identifier, version) not in active:
                add_event(
                    conn,
                    mission(conn)["id"],
                    "notification",
                    identifier,
                    "NOTIFICATION_ENABLED",
                    "configuration",
                    {"version": version, "specification": spec},
                )
            cursor = previous["cursor"] if previous else spec.get("after_seq", 0)
            events = conn.execute(
                "SELECT * FROM events WHERE seq>? ORDER BY seq LIMIT ?", (cursor, limit)
            ).fetchall()
            for event in events:
                if event["event_type"] in spec["events"]:
                    # Payload is solely a function of this immutable event, not current ages/state.
                    text = json_dump(dict(event)) + "\n"
                    directory = root / "notifications" / identifier / str(version)
                    directory.mkdir(parents=True, exist_ok=True)
                    path = directory / (str(event["seq"]) + ".json")
                    if path.exists() and path.read_text(encoding="utf-8") != text:
                        raise SwarmError("Notification event snapshot changed")
                    path.write_text(text, encoding="utf-8")
                    key = "notification:%s:%s:%s:%s" % (
                        event["mission_id"],
                        event["seq"],
                        identifier,
                        version,
                    )
                    delivery = enqueue_delivery(
                        root,
                        conn,
                        spec["extension"],
                        spec["channel"],
                        event["event_type"],
                        spec["recipients"],
                        path,
                        [],
                        key,
                        "notifications",
                    )
                    conn.execute(
                        "INSERT OR IGNORE INTO notification_deliveries VALUES(?,?,?,?)",
                        (identifier, version, event["seq"], delivery["id"]),
                    )
                cursor = event["seq"]
            conn.execute(
                "UPDATE notification_subscriptions SET cursor=? WHERE id=? AND version=?",
                (cursor, identifier, version),
            )

        return bool(
            conn.execute(
                "SELECT 1 FROM notification_subscriptions s WHERE active=1 AND EXISTS (SELECT 1 FROM events e WHERE e.seq>s.cursor) LIMIT 1"
            ).fetchone()
        )


def pending_notifications(conn, limit):
    return [
        row[0]
        for row in conn.execute(
            "SELECT d.id FROM deliveries d JOIN notification_deliveries n ON n.delivery_id=d.id "
            "JOIN notification_subscriptions s ON s.id=n.subscription_id AND s.version=n.subscription_version "
            "WHERE d.status='PENDING' AND s.active=1 ORDER BY d.created_at,d.id LIMIT ?",
            (limit,),
        )
    ]
