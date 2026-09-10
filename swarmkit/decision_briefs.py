"""Reader-facing decision contracts, separate from exact authorization values."""

from .core import SwarmError, atomic_write, json_load
from .storage import add_event, mission


def brief_mode(conn):
    row = conn.execute("SELECT value FROM meta WHERE key='decision_briefs'").fetchone()
    return row[0] if row else "legacy"


@atomic_write
def configure_briefs(conn, mode, actor):
    if mode not in {"legacy", "required"}:
        raise SwarmError("Decision brief mode must be legacy or required")
    conn.execute("INSERT OR REPLACE INTO meta VALUES('decision_briefs',?)", (mode,))
    add_event(
        conn,
        mission(conn)["id"],
        "mission",
        mission(conn)["id"],
        "DECISION_BRIEF_MODE_SET",
        actor,
        {"mode": mode},
    )
    return {"decision_briefs": mode}


def validate_brief(brief, options):
    fields = {
        "schema_version",
        "background",
        "human_reason",
        "option_details",
        "recommended_option",
        "recommendation_rationale",
        "blocked_outcome",
        "evidence",
        "response_required",
    }
    if (
        not isinstance(brief, dict)
        or set(brief) != fields
        or type(brief["schema_version"]) is not int
        or brief["schema_version"] != 1
    ):
        raise SwarmError(
            "Decision brief requires schema_version 1 and fields: " + ", ".join(sorted(fields))
        )
    for field in ("background", "human_reason", "recommendation_rationale", "blocked_outcome"):
        if not isinstance(brief[field], str) or not brief[field].strip():
            raise SwarmError("Decision brief requires nonempty " + field)
    if (
        not isinstance(options, list)
        or any(not isinstance(o, str) or not o.strip() for o in options)
        or len(set(options)) != len(options)
    ):
        raise SwarmError("Structured decision options must be unique nonempty strings")
    details = brief["option_details"]
    if not isinstance(details, list) or len(details) != len(options):
        raise SwarmError("Provide exactly one detail per option")
    values = []
    for option in details:
        if not isinstance(option, dict) or set(option) != {"value", "label", "consequence", "risk"}:
            raise SwarmError("Option details require value, label, consequence and risk")
        if any(not isinstance(x, str) or not x.strip() for x in option.values()):
            raise SwarmError("Option details must contain nonempty strings")
        values.append(option["value"])
    if sorted(values) != sorted(options):
        raise SwarmError("Option details must exactly match authorization options")
    if brief["recommended_option"] is not None and brief["recommended_option"] not in options:
        raise SwarmError("Recommendation must name an exact option or be null")
    response = brief["response_required"]
    if options:
        if response is not None:
            raise SwarmError("Fixed options require response_required null")
    elif not isinstance(response, str) or not response.strip():
        raise SwarmError("Free response requires response_required explaining the needed answer")
    if not isinstance(brief["evidence"], list):
        raise SwarmError("Evidence must be a list of references and summaries")
    for evidence in brief["evidence"]:
        if (
            not isinstance(evidence, dict)
            or set(evidence) != {"reference", "summary"}
            or any(not isinstance(v, str) or not v.strip() for v in evidence.values())
        ):
            raise SwarmError("Each evidence item requires nonempty reference and summary")
    return brief


def get_brief(conn, decision_id):
    row = conn.execute(
        "SELECT brief_json FROM decision_briefs WHERE decision_id=?", (decision_id,)
    ).fetchone()
    return json_load(row[0]) if row else None


def render_decision(decision):
    lines = ["### `%s`" % decision["id"], "", decision["question"], ""]
    brief = decision.get("brief")
    if brief:
        lines += [
            "**Background:** " + brief["background"],
            "",
            "**Why you:** " + brief["human_reason"],
            "",
        ]
        for option in brief["option_details"]:
            lines += [
                "- `%s` — %s: %s Risk/uncertainty: %s"
                % (option["value"], option["label"], option["consequence"], option["risk"])
            ]
        if brief["response_required"]:
            lines += ["**Answer needed:** " + brief["response_required"]]
        lines += [
            "",
            "**Recommendation:** %s. %s"
            % (
                brief["recommended_option"] or "No fixed recommendation",
                brief["recommendation_rationale"],
            ),
            "",
            "**Waiting:** " + brief["blocked_outcome"],
        ]
    else:
        lines += [
            "- Recommendation: " + (decision["recommendation"] or "None recorded"),
            "- Options: " + ("; ".join(decision["options"]) or "Free response (legacy)"),
        ]
    lines += ["- Affected tasks: " + ", ".join(decision["blocks"]), ""]
    if brief:
        lines += ["#### Evidence and details", ""]
        lines += ["- %s — %s" % (e["reference"], e["summary"]) for e in brief["evidence"]]
        if not brief["evidence"]:
            lines += ["No supporting references supplied."]
        lines += [""]
    return lines
