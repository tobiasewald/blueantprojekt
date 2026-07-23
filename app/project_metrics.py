import datetime
from typing import Dict, Any, List, Optional

# Effort overrun (in percent) above which a project counts as critical.
VARIANCE_CRITICAL_THRESHOLD = 15.0
# How far the reported progress may lag behind the elapsed schedule time
# (in percentage points) before the project counts as critical.
PROGRESS_LAG_CRITICAL_THRESHOLD = 20.0


def parse_datetime_utc(value: Optional[str]) -> Optional[datetime.datetime]:
    """Parse either a date-only string ("2018-09-21") or a full ISO datetime into a
    timezone-aware UTC datetime. Blue Ant's project start/end fields are date-only,
    which would otherwise produce a naive datetime that cannot be compared to "now"."""
    if not value or not isinstance(value, str):
        return None
    try:
        date_part = value.replace("Z", "+00:00").split("T")[0]
        d = datetime.date.fromisoformat(date_part)
        return datetime.datetime(d.year, d.month, d.day, tzinfo=datetime.timezone.utc)
    except ValueError:
        return None


def compute_elapsed_time_percent(
    start_date: Optional[str],
    end_date: Optional[str],
    now: Optional[datetime.datetime] = None,
) -> Optional[float]:
    """How much of the planned project duration has elapsed at the reporting date.

    Returns None when the dates are missing or unusable, so callers can render an
    honest "N/A" instead of a misleading 0%.
    """
    now = now or datetime.datetime.now(datetime.timezone.utc)
    start_dt = parse_datetime_utc(start_date)
    end_dt = parse_datetime_utc(end_date)
    if not start_dt or not end_dt or end_dt <= start_dt:
        return None
    total_dur = (end_dt - start_dt).total_seconds()
    elapsed_dur = (now - start_dt).total_seconds()
    return round(max(0.0, min(100.0, (elapsed_dur / total_dur) * 100.0)), 2)


def compute_effort_forecast(
    planned_hours: float,
    actual_hours: float,
    progress_percent: float,
) -> Dict[str, float]:
    """Linear extrapolation of the remaining and total effort.

    If a project reports X% progress for Y hours booked, the projected total is
    Y / (X/100). Without a usable progress figure we fall back to the plan.
    """
    if progress_percent > 0:
        forecasted_total = actual_hours / (progress_percent / 100.0)
        estimated_remaining = max(0.0, forecasted_total - actual_hours)
    else:
        estimated_remaining = max(0.0, planned_hours - actual_hours)
        forecasted_total = actual_hours + estimated_remaining

    return {
        "estimated_remaining_hours": round(estimated_remaining, 2),
        "forecasted_total_hours": round(actual_hours + estimated_remaining, 2),
    }


def compute_forecast_completion_date(
    start_date: Optional[str],
    end_date: Optional[str],
    progress_percent: float,
    now: Optional[datetime.datetime] = None,
) -> Optional[str]:
    """Project the completion date from the observed progress rate.

    Uses the same linear model as the effort forecast: if X% took the time elapsed
    so far, 100% takes proportionally longer. Returns None when there is no usable
    basis, so the dashboard can show an honest "N/A" instead of a guessed date.
    """
    now = now or datetime.datetime.now(datetime.timezone.utc)
    start_dt = parse_datetime_utc(start_date)
    if not start_dt:
        return None

    if progress_percent >= 100.0:
        end_dt = parse_datetime_utc(end_date)
        return (end_dt or now).date().isoformat()

    if progress_percent <= 0:
        return None

    elapsed_days = (now - start_dt).days
    if elapsed_days <= 0:
        return None

    total_days = elapsed_days / (progress_percent / 100.0)
    try:
        return (start_dt + datetime.timedelta(days=total_days)).date().isoformat()
    except (OverflowError, ValueError):
        return None


def resolve_statusampel_color(project: Dict[str, Any]) -> str:
    """Read the resolved traffic-light colour off a project record."""
    risk = project.get("overallRisk")
    if isinstance(risk, dict):
        return (risk.get("color") or risk.get("name") or "unbekannt").lower()
    if isinstance(risk, str):
        return risk.lower()
    return "unbekannt"


def evaluate_criticality(
    statusampel: str,
    variance_percent: float,
    progress_percent: float,
    elapsed_time_percent: Optional[float],
    overdue_milestones: int,
) -> Dict[str, Any]:
    """Decide deterministically whether a project is critical, and why.

    This is computed in code rather than left to the LLM so that the criticality
    flag, the criticality level and the dashboard's "critical projects" counter can
    never contradict each other, and so repeated runs on unchanged data give the
    same answer (the client's "KI soll gleiche Daten liefern" requirement).
    """
    reasons: List[str] = []

    colour = (statusampel or "").lower()
    if colour == "red":
        reasons.append("Statusampel steht auf Rot.")
    elif colour == "yellow":
        reasons.append("Statusampel steht auf Gelb.")

    if variance_percent > VARIANCE_CRITICAL_THRESHOLD:
        reasons.append(
            f"Aufwandsabweichung von {variance_percent}% überschreitet die Schwelle von {VARIANCE_CRITICAL_THRESHOLD}%."
        )

    if elapsed_time_percent is not None:
        lag = elapsed_time_percent - progress_percent
        if lag > PROGRESS_LAG_CRITICAL_THRESHOLD:
            reasons.append(
                f"Fortschritt liegt {round(lag, 2)} Prozentpunkte hinter der verstrichenen Zeit zurück."
            )

    if overdue_milestones > 0:
        reasons.append(f"{overdue_milestones} Meilenstein(e) überfällig.")

    is_critical = len(reasons) > 0
    if not is_critical:
        level = "low"
    elif colour == "red" or len(reasons) >= 2:
        level = "high"
    else:
        level = "medium"

    return {
        "is_critical": is_critical,
        "criticality_level": level,
        "criticality_reasons": reasons,
    }
