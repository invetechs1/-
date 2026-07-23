"""محرك التشابه — يطابق المشروع الجديد مع العروض السابقة في الأرشيف.

يبني بصمة نصية لكل عرض مؤرشف (العنوان + الكلمات المفتاحية + النطاق + أسماء بنود
الكميات + الملخص) ويحسب درجة التطابق مع نص المشروع الجديد، فيُبنى العرض الجديد
على أقرب العروض السابقة لنطاقه — كلما كبر الأرشيف صار النظام أذكى.
"""
import re

from .database import list_proposals_full

# كلمات عامة لا تميز مجالاً عن آخر
_STOPWORDS = {
    "مشروع", "أعمال", "اعمال", "توريد", "وتركيب", "تركيب", "تنفيذ", "شامل",
    "شاملة", "وفق", "حسب", "جميع", "كافة", "لجميع", "عام", "عامة", "الأعمال",
    "with", "and", "the", "for", "works", "supply", "install",
}

_NORMALIZE = str.maketrans("أإآىة", "اااية")


def _tokens(text: str) -> set[str]:
    text = str(text or "").translate(_NORMALIZE).lower()
    raw = re.split(r"[^\w؀-ۿ]+", text)
    out = set()
    for t in raw:
        if len(t) < 3 or t in _STOPWORDS or t.isdigit():
            continue
        # إزالة "ال" التعريف لتوحيد الجذور
        if t.startswith("ال") and len(t) > 4:
            t = t[2:]
        out.add(t)
    return out


def _fingerprint(proposal: dict) -> tuple[set[str], set[str]]:
    """(كلمات عالية الأهمية، كلمات النطاق التفصيلي)"""
    d = proposal.get("data", {})
    high = _tokens(proposal.get("title", "")) | _tokens(d.get("keywords", "")) \
        | set().union(*[_tokens(s) for s in d.get("scope", [])] or [set()])
    detail = _tokens(d.get("summary", "")) \
        | set().union(*[_tokens(l.get("name", "")) for l in d.get("boq", [])] or [set()])
    return high, detail


def find_similar(query_text: str, top_n: int = 3, exclude_id: int | None = None) -> list[dict]:
    """أفضل العروض المؤرشفة المطابقة لنص المشروع الجديد، بدرجة 0-100."""
    q = _tokens(query_text)
    if not q:
        return []
    results = []
    for p in list_proposals_full():
        if exclude_id and p["id"] == exclude_id:
            continue
        high, detail = _fingerprint(p)
        if not high and not detail:
            continue
        # الكلمات عالية الأهمية بوزن مضاعف
        high_hits = q & high
        detail_hits = (q & detail) - high_hits
        score = len(high_hits) * 3 + len(detail_hits)
        denom = min(len(q), 40)
        pct = min(round(score / max(denom, 1) * 25), 100)
        if score >= 3:
            results.append({
                "id": p["id"], "ref_no": p["ref_no"], "title": p["title"],
                "client": p["client"], "status": p["status"],
                "score": pct,
                "matched_terms": sorted(high_hits | detail_hits)[:12],
                "boq_lines": len(p["data"].get("boq", [])),
                "is_reference": bool(p["data"].get("reference")),
            })
    results.sort(key=lambda r: -r["score"])
    return results[:top_n]


def get_reference_content(proposal_ids: list[int]) -> list[dict]:
    """محتوى العروض المرجعية المطابقة (للاستخدام في بناء العرض الجديد)."""
    wanted = set(proposal_ids)
    return [p for p in list_proposals_full() if p["id"] in wanted]
