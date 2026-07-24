"""محلل فرصة الفوز — قرار تقدّم/لا تتقدّم مسبب قبل إعداد العرض.

يقرأ اسم المشروع ووثائقه (بما فيها اشتراطات التأهيل) ويقيّم خمسة عوامل:
1. الخبرة المماثلة   — أقرب عرض سابق في الأرشيف ودرجة تطابقه
2. تغطية التسعير     — نسبة مفردات نطاق المشروع المغطاة في قاعدة الأسعار والسوق
3. جاهزية الوثائق    — حالة الوثائق النظامية في الخزنة (منتهية/قريبة الانتهاء)
4. السجل مع العميل   — نسبة الفوز التاريخية لدى نفس الجهة إن وُجدت
5. اشتراطات التأهيل  — رصد اشتراطات عالية الخطورة في الوثائق (تصنيف، خبرة سنوات، غرامات...)
"""
import re

from .analytics import compute_analytics
from .database import list_company_docs, list_price_items, search_market_prices
from .similarity import find_similar, _tokens

# اشتراطات تأهيل تستدعي الانتباه إذا وردت في كراسة الشروط
_RISK_PATTERNS = [
    (r"تصنيف\s*(?:درجة|فئة)?\s*(?:أولى|ثانية|اولى|1|2)", "يشترط تصنيف مقاولين بدرجة متقدمة — تأكد من مطابقة تصنيف عزوم"),
    (r"خبرة\s*لا\s*تقل\s*عن\s*(\d+)", "يشترط سنوات خبرة محددة — جهّز شهادات الإنجاز المثبتة"),
    (r"مشاريع\s*مماثلة\s*(?:لا\s*تقل|بعدد)", "يشترط مشاريع مماثلة موثقة — أرفق عقود وشهادات إنجاز"),
    (r"غرامة|غرامات", "يتضمن غرامات تأخير — راجع قدرة الجدول الزمني على الالتزام"),
    (r"ضمان\s*(?:بنكي|ابتدائي)\s*(?:بنسبة)?\s*([2-9]|\d{2})\s*%", "ضمان ابتدائي أعلى من المعتاد (1%) — التزام مالي أكبر"),
    (r"محتوى\s*محلي\s*(?:لا\s*يقل|بنسبة)", "يشترط نسبة محتوى محلي محددة — راجع شهادة المحتوى المحلي"),
    (r"سيولة|قوائم\s*مالية|ملاءة", "يشترط إثبات ملاءة مالية — جهّز القوائم المالية المدققة"),
    (r"تحالف|ائتلاف", "يسمح/يشترط التحالف — قد يفتح مجالاً لتغطية نقص التأهيل"),
]


def analyze_opportunity(title: str, client: str, files_text: str) -> dict:
    factors = []
    query = f"{title}\n{files_text[:8000]}"

    # 1) الخبرة المماثلة (وزن 30)
    matches = find_similar(query, top_n=3)
    best = matches[0] if matches else None
    exp_score = min((best["score"] if best else 0), 100)
    factors.append({
        "name": "الخبرة المماثلة في الأرشيف",
        "weight": 30, "score": exp_score,
        "detail": f"أقرب عرض سابق: {best['title'][:60]} (تطابق {best['score']}%)" if best
                  else "لا يوجد عرض سابق مشابه — سيُبنى العرض من قاعدة الأسعار مباشرة",
    })

    # 2) تغطية التسعير (وزن 25)
    q_tokens = _tokens(query)
    catalog_tokens = set()
    for it in list_price_items():
        catalog_tokens |= _tokens(it["name"])
    covered = len(q_tokens & catalog_tokens)
    coverage = min(round(covered / max(min(len(q_tokens), 60), 1) * 130), 100)
    factors.append({
        "name": "تغطية قاعدة الأسعار لنطاق المشروع",
        "weight": 25, "score": coverage,
        "detail": f"{covered} مفردة من مفردات النطاق لها بنود مسعّرة في قاعدة عزوم/السوق",
    })

    # 3) جاهزية الوثائق النظامية (وزن 20)
    docs = list_company_docs()
    expired = [d["name"] for d in docs if d["status"] == "expired"]
    missing = [d["name"] for d in docs if d["status"] == "missing"]
    doc_score = max(0, 100 - len(expired) * 25 - len(missing) * 10)
    detail = []
    if expired: detail.append("منتهية: " + "، ".join(expired[:3]))
    if missing: detail.append(f"غير مُدخلة: {len(missing)} وثائق")
    factors.append({
        "name": "جاهزية وثائق التأهل",
        "weight": 20, "score": doc_score,
        "detail": " | ".join(detail) or "جميع الوثائق المسجلة سارية ✅",
    })

    # 4) السجل مع العميل (وزن 10)
    an = compute_analytics()
    client_rec = next((c for c in an["by_client"] if c["client"] and client and
                       (c["client"] in client or client in c["client"])), None)
    if client_rec and client_rec["win_rate"] is not None:
        cli_score = client_rec["win_rate"]
        cli_detail = f"سجلك مع {client_rec['client']}: فوز {client_rec['win_rate']}% من {client_rec['won'] + client_rec['lost']} عروض محسومة"
    else:
        cli_score = 50
        cli_detail = "لا يوجد سجل سابق مع هذا العميل — عامل محايد"
    factors.append({"name": "السجل التاريخي مع العميل", "weight": 10, "score": cli_score, "detail": cli_detail})

    # 5) اشتراطات التأهيل (وزن 15) — رصد المخاطر في نص الوثائق
    warnings = []
    for pattern, msg in _RISK_PATTERNS:
        if re.search(pattern, files_text):
            warnings.append(msg)
    risk_score = max(0, 100 - len(warnings) * 18)
    factors.append({
        "name": "اشتراطات التأهيل والمخاطر التعاقدية",
        "weight": 15, "score": risk_score,
        "detail": f"رُصد {len(warnings)} اشتراطاً يستدعي الانتباه" if warnings
                  else ("لم تُرصد اشتراطات عالية الخطورة" + ("" if files_text else " (لم تُرفق وثائق للفحص)")),
    })

    total = round(sum(f["score"] * f["weight"] for f in factors) / sum(f["weight"] for f in factors))
    if total >= 65:
        verdict, verdict_class = "تقدّم — فرصة فوز جيدة", "go"
    elif total >= 45:
        verdict, verdict_class = "تقدّم بحذر — عالج نقاط الضعف قبل التقديم", "caution"
    else:
        verdict, verdict_class = "لا يُنصح بالتقدم — الفجوات أكبر من الفرصة", "nogo"

    return {
        "score": total,
        "verdict": verdict,
        "verdict_class": verdict_class,
        "factors": factors,
        "qualification_warnings": warnings,
        "similar": matches,
    }
