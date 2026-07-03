from typing import Dict, Any, List

# Priority tier per matched KPI id. Higher tier always wins over a lower one,
# and a candidate may re-confirm its own tier (see git history: "fix: resolve
# KPI overwriting bug by introducing prioritized matching").
PLANNED_KPI_TIERS = {
    "WorkTotalPlan": 3,
    "ProjectBudgetWorkPlan": 2,
    "BudgetPlanWork": 1,
}
ACTUAL_KPI_TIERS = {
    "WorkTotalActual": 3,
    "ProjectBudgetWorkActual": 2,
    "BudgetIsWork": 1,
}


def _is_generic_effort_match(name_lower: str, direction_keyword: str) -> bool:
    """True if a KPI name looks like a top-level plan/actual effort KPI (not a sub-budget one)."""
    if direction_keyword not in name_lower:
        return False
    if not ("aufwand" in name_lower or "arbeit" in name_lower or "effort" in name_lower):
        return False
    if "teilprojekt" in name_lower or "ticket" in name_lower or "mehrarbeit" in name_lower:
        return False
    return True


def extract_effort_kpis(kpis: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Extract planned/actual effort hours and reported progress from a project's KPI list.

    Converts PT (Personentage) to hours (1 PT = 8h) and returns a formatted
    kpi_lines summary alongside the derived planned/actual/progress values.
    """
    planned_hours = 0.0
    actual_hours = 0.0
    progress_percent = 0.0
    planned_strength = 0
    actual_strength = 0
    kpi_lines = []

    for k in kpis:
        if k.get("period", "TOTAL") != "TOTAL":
            continue

        k_id = k.get("id", "")
        name = k.get("name", "") or ""
        name_lower = name.lower()
        val = float(k.get("value", 0.0) or 0.0)
        unit = k.get("unit", "") or ""

        if unit == "PT":
            val = val * 8.0
            unit = "h"

        kpi_lines.append(f"- {name}: {val} {unit}".strip())

        if k_id == "SubjectiveProgress":
            progress_percent = val
        elif "fortschritt" in name_lower or "progress" in name_lower or "fertigstellung" in name_lower:
            if k_id == "SubjectiveProgress" or progress_percent == 0.0:
                progress_percent = val

        planned_tier = PLANNED_KPI_TIERS.get(k_id)
        if planned_tier is not None:
            if planned_tier >= planned_strength:
                planned_hours = val
                planned_strength = planned_tier
        elif _is_generic_effort_match(name_lower, "plan") or _is_generic_effort_match(name_lower, "basisplan"):
            if planned_strength == 0:
                planned_hours = val

        actual_tier = ACTUAL_KPI_TIERS.get(k_id)
        if actual_tier is not None:
            if actual_tier >= actual_strength:
                actual_hours = val
                actual_strength = actual_tier
        elif _is_generic_effort_match(name_lower, "ist") or _is_generic_effort_match(name_lower, "actual"):
            if actual_strength == 0:
                actual_hours = val

    kpis_summary = "\n".join(kpi_lines) if kpi_lines else "No KPIs available."
    variance_hours = actual_hours - planned_hours
    variance_percent = (variance_hours / planned_hours * 100.0) if planned_hours > 0 else 0.0

    return {
        "planned_hours": planned_hours,
        "actual_hours": actual_hours,
        "progress_percent": progress_percent,
        "variance_hours": variance_hours,
        "variance_percent": round(variance_percent, 2),
        "kpis_summary": kpis_summary,
    }
