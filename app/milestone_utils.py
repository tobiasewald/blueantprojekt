import datetime
from typing import Dict, Any, List


def _parse_date(value: Any) -> "datetime.date | None":
    if not value or not isinstance(value, str):
        return None
    try:
        # Accept both date-only ("2018-09-21") and full datetime strings.
        return datetime.date.fromisoformat(value.replace("Z", "+00:00").split("T")[0])
    except ValueError:
        return None


def summarize_milestones(milestones: List[Dict[str, Any]], today: "datetime.date | None" = None) -> Dict[str, Any]:
    """Build a plan-vs-actual overview of a project's milestones.

    Blue Ant exposes milestones as planning entries with entryType "milestone".
    - startWished/endWished: planned dates
    - start/end: actual dates (set once the milestone has actually started/finished)
    - progressActual: 0-100
    A milestone counts as overdue if its planned end date has passed and it has
    not been completed (no actual end date / progress below 100).
    """
    today = today or datetime.datetime.now(datetime.timezone.utc).date()

    entries = []
    overdue_count = 0
    completed_count = 0

    for m in milestones:
        name = m.get("description") or m.get("name") or "Unbenannter Meilenstein"
        planned_end = _parse_date(m.get("endWished"))
        actual_end = _parse_date(m.get("end"))
        progress = float(m.get("progressActual", 0.0) or 0.0)
        is_completed = progress >= 100.0 or actual_end is not None
        is_overdue = (not is_completed) and planned_end is not None and planned_end < today

        if is_completed:
            completed_count += 1
        if is_overdue:
            overdue_count += 1

        entries.append({
            "name": name,
            "planned_end": m.get("endWished"),
            "actual_end": m.get("end"),
            "progress_percent": progress,
            "completed": is_completed,
            "overdue": is_overdue,
        })

    lines = []
    for e in entries:
        status = "erledigt" if e["completed"] else ("ÜBERFÄLLIG" if e["overdue"] else "offen")
        lines.append(
            f"- {e['name']}: geplant bis {e['planned_end'] or 'N/A'}, Fortschritt {e['progress_percent']}% ({status})"
        )

    return {
        "milestones": entries,
        "total_count": len(entries),
        "completed_count": completed_count,
        "overdue_count": overdue_count,
        "summary_text": "\n".join(lines) if lines else "Keine Meilensteine hinterlegt.",
    }
