"""تحليلات الفوز/الخسارة — معايرة التسعير من أرشيف العروض."""
from collections import defaultdict

from .database import list_proposals_full

STATUS_AR = {"draft": "مسودة", "submitted": "مُقدَّم", "won": "فائز", "lost": "غير فائز"}


def _value(p: dict) -> float:
    return float(p["data"].get("financial", {}).get("grand_total", 0) or 0)


def _profit_pct(p: dict) -> float | None:
    fin = p["data"].get("financial", {})
    return float(fin["profit_pct"]) if "profit_pct" in fin else None


def compute_analytics() -> dict:
    proposals = list_proposals_full()
    by_status = defaultdict(int)
    value_by_status = defaultdict(float)
    for p in proposals:
        by_status[p["status"]] += 1
        value_by_status[p["status"]] += _value(p)

    decided = by_status["won"] + by_status["lost"]
    win_rate = round(by_status["won"] / decided * 100, 1) if decided else None

    # متوسط هامش الربح في العروض الفائزة مقابل الخاسرة — مؤشر معايرة التسعير
    won_margins = [_profit_pct(p) for p in proposals if p["status"] == "won" and _profit_pct(p) is not None]
    lost_margins = [_profit_pct(p) for p in proposals if p["status"] == "lost" and _profit_pct(p) is not None]
    avg = lambda xs: round(sum(xs) / len(xs), 1) if xs else None

    # حسب نوع الجهة
    by_entity = {}
    for etype in ("government", "private"):
        subset = [p for p in proposals if p["entity_type"] == etype]
        e_decided = [p for p in subset if p["status"] in ("won", "lost")]
        e_won = [p for p in e_decided if p["status"] == "won"]
        by_entity[etype] = {
            "total": len(subset),
            "won": len(e_won),
            "decided": len(e_decided),
            "win_rate": round(len(e_won) / len(e_decided) * 100, 1) if e_decided else None,
            "won_value": round(sum(_value(p) for p in e_won), 2),
        }

    # حسب العميل
    clients = defaultdict(lambda: {"total": 0, "won": 0, "lost": 0, "won_value": 0.0})
    for p in proposals:
        c = clients[p["client"]]
        c["total"] += 1
        if p["status"] == "won":
            c["won"] += 1
            c["won_value"] = round(c["won_value"] + _value(p), 2)
        elif p["status"] == "lost":
            c["lost"] += 1
    by_client = [
        {"client": name, **stats,
         "win_rate": round(stats["won"] / (stats["won"] + stats["lost"]) * 100, 1)
         if (stats["won"] + stats["lost"]) else None}
        for name, stats in clients.items()
    ]
    by_client.sort(key=lambda c: (-(c["won_value"]), -c["total"]))

    return {
        "totals": {
            "proposals": len(proposals),
            "by_status": {s: by_status.get(s, 0) for s in STATUS_AR},
            "pipeline_value": round(sum(value_by_status[s] for s in ("draft", "submitted")), 2),
            "won_value": round(value_by_status["won"], 2),
            "win_rate": win_rate,
        },
        "margins": {
            "avg_won_margin": avg(won_margins),
            "avg_lost_margin": avg(lost_margins),
            "hint": _margin_hint(avg(won_margins), avg(lost_margins)),
        },
        "by_entity": by_entity,
        "by_client": by_client[:15],
    }


def _margin_hint(won: float | None, lost: float | None) -> str:
    if won is None or lost is None:
        return "سجّل حالات الفوز والخسارة في الأرشيف لتظهر مؤشرات معايرة التسعير."
    if lost > won:
        return ("متوسط هامش الربح في العروض الخاسرة أعلى منه في الفائزة — "
                "قد يشير إلى أن التسعير المرتفع سبب رئيسي للخسارة؛ ادرس خفض الهامش في المنافسات السعرية.")
    if won > lost:
        return ("هوامشك الرابحة أعلى من الخاسرة — تنافسيتك جيدة في مستوى الأسعار الحالي "
                "وقد يوجد مجال لرفع الهامش تدريجياً في الجهات التي تفوز لديها باستمرار.")
    return "الهوامش متقاربة بين الفوز والخسارة — العامل الحاسم غالباً فني وليس سعرياً."
