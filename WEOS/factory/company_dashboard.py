"""Logged-in company dashboard: growth, collection, follow-up queue."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Mapping

from WEOS.factory.company_index import all_project_rows
from WEOS.factory.fy import current_fy, fy_bounds, fy_label, fy_start_year
from WEOS.factory.ledger_store import status_counts_toward_turnover
from WEOS.factory.project_store import load_project, save_project

REJECTED_STATUSES = frozenset({"rejected", "cancelled", "canceled", "archived"})


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        dt = value
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _month_start(year: int, month: int) -> datetime:
    return datetime(year, month, 1, tzinfo=timezone.utc)


def _shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    idx = year * 12 + (month - 1) + delta
    return idx // 12, idx % 12 + 1


def _in_range(dt: datetime | None, start: datetime, end: datetime) -> bool:
    return bool(dt and start <= dt < end)


def _money(n: Any) -> float:
    try:
        return round(float(n or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def _delta(current: float, previous: float) -> dict[str, Any]:
    cur = round(float(current or 0), 2)
    prev = round(float(previous or 0), 2)
    diff = round(cur - prev, 2)
    if abs(prev) < 0.005:
        pct = 100.0 if cur > 0 else (0.0 if cur == 0 else -100.0)
    else:
        pct = round((diff / prev) * 100.0, 1)
    return {
        "current": cur,
        "previous": prev,
        "amount": diff,
        "change": diff,
        "percent": pct,
        "growth": diff > 0.005,
        "less": diff < -0.005,
        "flat": abs(diff) <= 0.005,
    }


def _period(count: int, amount: float, previous_amount: float) -> dict[str, Any]:
    d = _delta(amount, previous_amount)
    return {
        "count": int(count or 0),
        "amount": round(float(amount or 0), 2),
        "previous": d["previous"],
        "change": d["change"],
        "percent": d["percent"],
        "growth": d["growth"],
        "less": d["less"],
        "flat": d["flat"],
    }


def _phone_digits(raw: Any) -> str:
    return re.sub(r"\D", "", str(raw or ""))


def wa_link(phone: Any) -> str | None:
    d = _phone_digits(phone)
    if len(d) == 10:
        d = "91" + d
    if len(d) < 10:
        return None
    if len(d) > 12:
        d = d[-12:]
    return f"https://wa.me/{d}"


def tel_link(phone: Any) -> str | None:
    d = _phone_digits(phone)
    if len(d) == 10:
        d = "+91" + d
    elif d and not d.startswith("+"):
        d = "+" + d
    return f"tel:{d}" if d else None


def _is_order(status: Any) -> bool:
    return status_counts_toward_turnover(status)


def _counts_as_order(row: Mapping[str, Any], paid: float = 0.0) -> bool:
    """Approved/confirmed statuses, or any job that already took an advance."""
    if _is_order(row.get("status")):
        return True
    return float(paid or 0) > 0.5


def _project_value(row: Mapping[str, Any]) -> float:
    return _money(row.get("totalGrand") if row.get("totalGrand") is not None else row.get("grandTotal"))


def _order_stamp(row: Mapping[str, Any], *, paid_at: datetime | None = None) -> datetime | None:
    """Prefer quote/order date; fall back to first advance date for advance-backed jobs."""
    for key in ("orderDate", "quoteDate", "approvedAt", "createdAt", "updatedAt"):
        dt = _parse_dt(row.get(key))
        if dt:
            return dt
    return paid_at


def _fy_month_keys(fy: str) -> list[tuple[int, int, str]]:
    """Apr…Mar buckets for an Indian FY label like 2026-27."""
    try:
        start = int(str(fy).split("-", 1)[0])
    except (TypeError, ValueError):
        start = _now().year if _now().month >= 4 else _now().year - 1
    out: list[tuple[int, int, str]] = []
    labels = ("Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec", "Jan", "Feb", "Mar")
    for i, lab in enumerate(labels):
        if i < 9:
            y, m = start, i + 4
        else:
            y, m = start + 1, i - 8
        out.append((y, m, f"{lab} {str(y)[2:]}"))
    return out


def _tenure_series(
    projects: list[Mapping[str, Any]],
    advances: list[Mapping[str, Any]],
    *,
    fy: str,
    adv_by_pid: Mapping[str, float],
    first_adv: Mapping[str, datetime],
) -> list[dict[str, Any]]:
    buckets = _fy_month_keys(fy)
    orders = { (y, m): {"count": 0, "amount": 0.0} for y, m, _ in buckets }
    collect = { (y, m): {"count": 0, "amount": 0.0} for y, m, _ in buckets }
    for p in projects:
        pid = str(p.get("projectId") or "")
        paid = float(adv_by_pid.get(pid, 0.0) or 0)
        if not _counts_as_order(p, paid):
            continue
        stamp = _order_stamp(p, paid_at=first_adv.get(pid))
        if not stamp:
            continue
        key = (stamp.year, stamp.month)
        if key not in orders:
            continue
        orders[key]["count"] += 1
        orders[key]["amount"] = round(orders[key]["amount"] + _project_value(p), 2)
    for a in advances:
        val = _money(a.get("amount"))
        if val <= 0:
            continue
        stamp = _parse_dt(a.get("paidAt") or a.get("createdAt"))
        if not stamp:
            continue
        key = (stamp.year, stamp.month)
        if key not in collect:
            continue
        collect[key]["count"] += 1
        collect[key]["amount"] = round(collect[key]["amount"] + val, 2)
    series = []
    for y, m, label in buckets:
        o = orders[(y, m)]
        c = collect[(y, m)]
        series.append(
            {
                "year": y,
                "month": m,
                "label": label,
                "ordersCount": o["count"],
                "ordersAmount": o["amount"],
                "collectionCount": c["count"],
                "collectionAmount": c["amount"],
            }
        )
    return series


def _approved_list(
    projects: list[Mapping[str, Any]],
    *,
    adv_by_pid: Mapping[str, float],
    first_adv: Mapping[str, datetime],
    limit: int = 40,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for p in projects:
        pid = str(p.get("projectId") or "")
        paid = float(adv_by_pid.get(pid, 0.0) or 0)
        status_ok = _is_order(p.get("status"))
        if not status_ok and paid <= 0.5:
            continue
        stamp = _order_stamp(p, paid_at=first_adv.get(pid))
        reason = "approved" if status_ok else "advance"
        if status_ok and paid > 0.5:
            reason = "approved+advance"
        rows.append(
            {
                "projectId": p.get("projectId"),
                "quotationId": p.get("quotationId"),
                "name": p.get("name"),
                "customer": p.get("customer"),
                "customerMobile": p.get("customerMobile"),
                "status": p.get("status") or ("approved" if paid > 0.5 else "draft"),
                "effectiveStatus": "approved" if _counts_as_order(p, paid) else (p.get("status") or "draft"),
                "reason": reason,
                "amount": _project_value(p),
                "advance": round(paid, 2),
                "orderDate": stamp.date().isoformat() if stamp else None,
                "fy": p.get("fy") or (fy_of(stamp) if stamp else ""),
                "updatedAt": p.get("updatedAt"),
            }
        )
    rows.sort(key=lambda r: str(r.get("orderDate") or r.get("updatedAt") or ""), reverse=True)
    return rows[:limit]


def company_dashboard(company_gst: str) -> dict[str, Any]:
    gst = str(company_gst or "").strip().upper()
    projects = [p for p in all_project_rows(gst) if str(p.get("companyGst") or gst).upper() == gst]
    now = _now()
    ty, tm = now.year, now.month
    ly, lm = _shift_month(ty, tm, -1)
    this_m0, next_m0 = _month_start(ty, tm), _month_start(*_shift_month(ty, tm, 1))
    last_m0, last_m1 = _month_start(ly, lm), this_m0
    this_fy = current_fy()
    last_fy = fy_label((fy_start_year(this_fy) or ty) - 1)
    year0, year1 = fy_bounds(this_fy) or (datetime(ty, 4, 1, tzinfo=timezone.utc), datetime(ty + 1, 4, 1, tzinfo=timezone.utc))
    prev_year0, prev_year1 = fy_bounds(last_fy) or (datetime(ty - 1, 4, 1, tzinfo=timezone.utc), year0)

    pids = [str(p.get("projectId") or "") for p in projects if p.get("projectId")]
    advances: list[dict[str, Any]] = []
    try:
        from WEOS.factory.ledger_store import list_advances_for_projects

        advances = list_advances_for_projects(pids)
    except Exception:
        advances = []

    adv_by_pid: dict[str, float] = {}
    last_adv: dict[str, datetime] = {}
    first_adv: dict[str, datetime] = {}
    for a in advances:
        if _money(a.get("amount")) <= 0:
            continue
        pid = str(a.get("projectId") or "")
        adv_by_pid[pid] = round(adv_by_pid.get(pid, 0) + _money(a.get("amount")), 2)
        dt = _parse_dt(a.get("paidAt") or a.get("createdAt"))
        if pid and dt:
            if pid not in last_adv or dt > last_adv[pid]:
                last_adv[pid] = dt
            if pid not in first_adv or dt < first_adv[pid]:
                first_adv[pid] = dt

    def _orders(start: datetime, end: datetime) -> tuple[int, float]:
        n, amt = 0, 0.0
        for p in projects:
            pid = str(p.get("projectId") or "")
            paid = float(adv_by_pid.get(pid, 0.0) or 0)
            if not _counts_as_order(p, paid):
                continue
            stamp = _order_stamp(p, paid_at=first_adv.get(pid))
            if _in_range(stamp, start, end):
                n += 1
                amt += _project_value(p)
        return n, round(amt, 2)

    def _collect(start: datetime, end: datetime) -> tuple[int, float]:
        n, amt = 0, 0.0
        for a in advances:
            val = _money(a.get("amount"))
            if val <= 0:
                continue
            if _in_range(_parse_dt(a.get("paidAt") or a.get("createdAt")), start, end):
                n += 1
                amt += val
        return n, round(amt, 2)

    def _cleared(start: datetime, end: datetime) -> tuple[int, float]:
        n, amt = 0, 0.0
        for p in projects:
            pid = str(p.get("projectId") or "")
            value = _project_value(p)
            paid = adv_by_pid.get(pid, 0.0)
            if value <= 0 or paid + 0.5 < value:
                continue
            stamp = last_adv.get(pid) or _order_stamp(p)
            if _in_range(stamp, start, end):
                n += 1
                amt += value
        return n, round(amt, 2)

    om_n, om_a = _orders(this_m0, next_m0)
    olm_n, olm_a = _orders(last_m0, last_m1)
    oy_n, oy_a = _orders(year0, year1)
    oly_n, oly_a = _orders(prev_year0, year0)

    cm_n, cm_a = _collect(this_m0, next_m0)
    clm_n, clm_a = _collect(last_m0, last_m1)
    cy_n, cy_a = _collect(year0, year1)
    cly_n, cly_a = _collect(prev_year0, year0)

    xm_n, xm_a = _cleared(this_m0, next_m0)
    xlm_n, xlm_a = _cleared(last_m0, last_m1)
    xy_n, xy_a = _cleared(year0, year1)
    xly_n, xly_a = _cleared(prev_year0, year0)

    hot = [p for p in projects if str(p.get("fy") or "") == this_fy and str(p.get("status") or "") != "archived"]
    followups = _followup_queue(
        [
            p
            for p in hot
            if float(adv_by_pid.get(str(p.get("projectId") or ""), 0.0) or 0) <= 0.5
        ],
        now,
    )
    today = now.date().isoformat()
    todays_orders = sum(
        1
        for p in hot
        if _counts_as_order(p, float(adv_by_pid.get(str(p.get("projectId") or ""), 0.0) or 0))
        and str((_order_stamp(p, paid_at=first_adv.get(str(p.get("projectId") or ""))) or now).date()) == today
    )
    active = sum(1 for p in hot if str(p.get("status") or "active") == "active")
    drafts = sum(1 for p in hot if str(p.get("status") or "") == "draft")

    recent = sorted(hot, key=lambda p: str(p.get("updatedAt") or ""), reverse=True)[:8]
    tenure = _tenure_series(hot, advances, fy=this_fy, adv_by_pid=adv_by_pid, first_adv=first_adv)
    approved = _approved_list(hot, adv_by_pid=adv_by_pid, first_adv=first_adv, limit=40)

    return {
        "ok": True,
        "loggedIn": True,
        "gstNo": gst,
        "activeProjects": active,
        "draftQuotations": drafts,
        "todaysOrders": todays_orders,
        "projectCount": len(projects),
        "orders": {
            "month": _period(om_n, om_a, olm_a),
            "year": _period(oy_n, oy_a, oly_a),
        },
        "collection": {
            "month": _period(cm_n, cm_a, clm_a),
            "year": _period(cy_n, cy_a, cly_a),
        },
        "orderClear": {
            "month": _period(xm_n, xm_a, xlm_a),
            "year": _period(xy_n, xy_a, xly_a),
        },
        "tenure": {
            "fy": this_fy,
            "months": tenure,
            "note": "Month buckets follow Indian FY (Apr–Mar). Quotes with advances count as approved orders even if status was still draft.",
        },
        "approved": {
            "count": len(approved),
            "items": approved,
            "note": "Approved list = status approved/confirmed/… OR any advance already received on that job.",
        },
        "followUps": followups,
        "recentProjects": recent,
        "year": ty,
        "month": tm,
        "fy": this_fy,
        "lastFy": last_fy,
        "fyNote": "Dashboard loads this financial year only (1 Apr–31 Mar). Closed years stay in the database — open them from Company hub when needed.",
    }


def _followup_queue(projects: list[Mapping[str, Any]], now: datetime) -> dict[str, Any]:
    high: list[dict[str, Any]] = []
    medium: list[dict[str, Any]] = []
    later: list[dict[str, Any]] = []
    for p in projects:
        st = str(p.get("status") or "draft").strip().lower()
        if st in REJECTED_STATUSES or _is_order(st):
            continue
        created = _parse_dt(p.get("createdAt") or p.get("updatedAt")) or now
        age = max(0, int((now - created).total_seconds() // 86400))
        last = _parse_dt(p.get("lastFollowUpAt"))
        phone = p.get("customerMobile") or ""
        row = {
            "projectId": p.get("projectId"),
            "quotationId": p.get("quotationId"),
            "name": p.get("name"),
            "customer": p.get("customer"),
            "customerMobile": phone,
            "status": st or "draft",
            "amount": _project_value(p),
            "ageDays": age,
            "createdAt": p.get("createdAt"),
            "lastFollowUpAt": p.get("lastFollowUpAt"),
            "lastFollowUpAgo": (max(0, int((now - last).total_seconds() // 86400)) if last else None),
            "whatsappUrl": wa_link(phone),
            "callUrl": tel_link(phone),
        }
        if age >= 10:
            row["priority"] = "high"
            high.append(row)
        elif age >= 5:
            row["priority"] = "medium"
            medium.append(row)
        else:
            row["priority"] = "later"
            later.append(row)
    high.sort(key=lambda r: (-int(r.get("ageDays") or 0), str(r.get("createdAt") or "")))
    medium.sort(key=lambda r: (-int(r.get("ageDays") or 0), str(r.get("createdAt") or "")))
    later.sort(key=lambda r: str(r.get("createdAt") or ""))
    return {
        "high": high[:40],
        "medium": medium[:40],
        "later": later[:40],
        "highCount": len(high),
        "mediumCount": len(medium),
        "laterCount": len(later),
    }


def record_follow_up(
    project_id: str,
    *,
    channel: str,
    company_gst: str,
) -> dict[str, Any]:
    ch = str(channel or "").strip().lower()
    if ch not in {"whatsapp", "call"}:
        raise ValueError("Follow-up must be WhatsApp or call")
    pid = str(project_id or "").strip()
    doc = load_project(pid)
    from WEOS.factory.project_store import _belongs_to_company, _norm_company_gst

    gst = _norm_company_gst(company_gst)
    if gst and not _belongs_to_company(doc, gst, include_unscoped=False):
        raise PermissionError("This quote is not in the logged-in company")
    now = _now().isoformat()
    log = list(doc.get("followUps") or [])
    log.append({"at": now, "channel": ch})
    doc["followUps"] = log[-40:]
    doc["lastFollowUpAt"] = now
    saved = save_project(doc, bump_version=False, action="follow_up")
    return {
        "ok": True,
        "projectId": saved.get("projectId"),
        "channel": ch,
        "at": now,
        "followUps": saved.get("followUps") or [],
        "lastFollowUpAt": now,
    }
