import datetime
from typing import Dict, Any, List, Optional


def _parse_date(value: Any) -> Optional[datetime.date]:
    if not value or not isinstance(value, str):
        return None
    try:
        # Accept both date-only ("2018-09-21") and full datetime strings.
        return datetime.date.fromisoformat(value.replace("Z", "+00:00").split("T")[0])
    except ValueError:
        return None


def _milestone_due_date(milestone: Dict[str, Any]) -> Optional[datetime.date]:
    """Determine the date a milestone is due.

    Blue Ant only fills "endWished" when the user set an explicit date constraint;
    otherwise the scheduled date lives in "end". For a milestone "start" and "end"
    are the same instant, because a milestone is a point in time rather than a span
    - so "end" is the planned date, NOT a completion date.
    """
    return _parse_date(milestone.get("endWished")) or _parse_date(milestone.get("end"))


def summarize_milestones(milestones: List[Dict[str, Any]], today: Optional[datetime.date] = None) -> Dict[str, Any]:
    """Build a plan-vs-actual overview of a project's milestones.

    Completion is read from "progressActual" (0-100), which is the only reliable
    completion signal Blue Ant exposes for planning entries. A milestone counts as
    overdue when its due date has passed and it is not yet complete.
    """
    today = today or datetime.datetime.now(datetime.timezone.utc).date()

    entries = []
    overdue_count = 0
    completed_count = 0

    for m in milestones:
        name = m.get("description") or m.get("name") or "Unbenannter Meilenstein"
        due_date = _milestone_due_date(m)
        progress = float(m.get("progressActual", 0.0) or 0.0)
        is_completed = progress >= 100.0
        is_overdue = (not is_completed) and due_date is not None and due_date < today

        if is_completed:
            completed_count += 1
        if is_overdue:
            overdue_count += 1

        entries.append({
            "name": name,
            "due_date": due_date.isoformat() if due_date else None,
            "progress_percent": progress,
            "completed": is_completed,
            "overdue": is_overdue,
        })

    lines = []
    for e in entries:
        status = "erledigt" if e["completed"] else ("ÜBERFÄLLIG" if e["overdue"] else "offen")
        lines.append(
            f"- {e['name']}: geplant zum {e['due_date'] or 'N/A'}, Fortschritt {e['progress_percent']}% ({status})"
        )

    return {
        "milestones": entries,
        "total_count": len(entries),
        "completed_count": completed_count,
        "overdue_count": overdue_count,
        "summary_text": "\n".join(lines) if lines else "Keine Meilensteine hinterlegt.",
    }
