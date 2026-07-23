"""بناء العرض الفني والمالي — الحسابات المالية ومحرك القوالب الاحتياطي.

نموذج التسعير (يتوافق مع الممارسات المتبعة في المنافسات الحكومية):
  التكلفة المباشرة (جدول الكميات)
+ المصاريف الإدارية والعمومية (نسبة من التكلفة المباشرة)
+ احتياطي المخاطر (نسبة من التكلفة المباشرة)
+ هامش الربح (نسبة من مجموع ما سبق)
= الإجمالي قبل الضريبة
+ ضريبة القيمة المضافة 15% (تُعرض في بند مستقل وفق الممارسة السعودية)
= الإجمالي النهائي
"""
import re

from .database import get_settings, list_price_items, list_library


def compute_financials(boq: list[dict], settings: dict | None = None) -> dict:
    s = settings or get_settings()
    overhead_pct = float(s.get("overhead_pct", 12))
    risk_pct = float(s.get("risk_pct", 3))
    profit_pct = float(s.get("profit_pct", 15))
    vat_rate = float(s.get("vat_rate", 15))
    bid_bond_pct = float(s.get("bid_bond_pct", 1))

    for line in boq:
        line["qty"] = float(line.get("qty", 1) or 1)
        line["unit_price"] = float(line.get("unit_price", 0) or 0)
        line["total"] = round(line["qty"] * line["unit_price"], 2)

    direct_cost = round(sum(l["total"] for l in boq), 2)
    overhead = round(direct_cost * overhead_pct / 100, 2)
    risk = round(direct_cost * risk_pct / 100, 2)
    profit = round((direct_cost + overhead + risk) * profit_pct / 100, 2)
    subtotal = round(direct_cost + overhead + risk + profit, 2)
    vat = round(subtotal * vat_rate / 100, 2)
    grand_total = round(subtotal + vat, 2)

    return {
        "direct_cost": direct_cost,
        "overhead_pct": overhead_pct, "overhead": overhead,
        "risk_pct": risk_pct, "risk": risk,
        "profit_pct": profit_pct, "profit": profit,
        "subtotal": subtotal,
        "vat_rate": vat_rate, "vat": vat,
        "grand_total": grand_total,
        "bid_bond_pct": bid_bond_pct,
        "bid_bond": round(grand_total * bid_bond_pct / 100, 2),
    }


def match_price_catalog(boq: list[dict]) -> list[dict]:
    """مطابقة بنود جدول الكميات مع قاعدة الأسعار (بالكود ثم بتشابه الاسم)."""
    catalog = list_price_items()
    by_code = {item["code"]: item for item in catalog}
    for line in boq:
        matched = by_code.get(line.get("code", ""))
        if not matched:
            matched = _best_name_match(line.get("name", ""), catalog)
        if matched:
            line["code"] = matched["code"]
            line["unit"] = line.get("unit") or matched["unit"]
            if not line.get("unit_price"):
                line["unit_price"] = matched["unit_price"]
            line["source"] = "قاعدة الأسعار"
        else:
            line["source"] = line.get("source", "تقدير")
    return boq


def _tokens(text: str) -> set[str]:
    return {t for t in re.split(r"[\s،,/|()-]+", text) if len(t) > 2}


def _best_name_match(name: str, catalog: list[dict]) -> dict | None:
    target = _tokens(name)
    if not target:
        return None
    best, best_score = None, 0.0
    for item in catalog:
        overlap = len(target & _tokens(item["name"]))
        score = overlap / max(len(target), 1)
        if overlap >= 2 and score > best_score:
            best, best_score = item, score
    return best


# ---------------------------------------------------------------------------
# محرك القوالب — يعمل بدون مفتاح API ويُنتج عرضاً كاملاً قابلاً للتحرير
# ---------------------------------------------------------------------------

_KEYWORD_MAP = [
    (["نظام", "برمج", "تطبيق", "بوابة", "إلكترون", "رقمن", "منصة"],
     ["IT-001", "IT-003", "IT-004", "IT-006", "IT-007", "HR-010", "HR-011", "HR-012", "HR-001"]),
    (["إنشاء", "مبنى", "خرسان", "بناء", "تشييد", "مبان"],
     ["GN-001", "CV-001", "CV-002", "CV-003", "CV-004", "CV-005", "CV-006", "CV-007",
      "EM-001", "EM-002", "EM-003", "EM-006", "HR-001", "HR-002", "HR-005", "GN-003", "GN-004", "GN-005"]),
    (["طرق", "أسفلت", "رصف", "سفلت"],
     ["GN-001", "CV-001", "CV-008", "CV-009", "EM-004", "EQ-001", "HR-002", "HR-007", "GN-003", "GN-005"]),
    (["صيانة", "تشغيل", "نظافة"],
     ["OM-001", "OM-002", "OM-003", "OM-004", "HR-001", "HR-007", "GN-003"]),
    (["كهرباء", "إنارة", "تيار"],
     ["EM-001", "EM-002", "EM-003", "EM-004", "HR-003", "HR-007"]),
    (["كاميرا", "أمن", "مراقبة", "إنذار"],
     ["EM-008", "EM-009", "IT-005", "HR-003", "IT-007"]),
]

_DEFAULT_CODES = ["GN-001", "HR-001", "HR-002", "HR-007", "GN-003", "GN-004", "GN-005"]


def build_template_proposal(title: str, client: str, entity_type: str, files_text: str,
                            similar_refs: list[dict] | None = None) -> dict:
    """توليد عرض متكامل بمحرك القوالب (بديل عند غياب مفتاح Claude API).

    عند وجود عروض سابقة مشابهة (similar_refs) يُبنى جدول الكميات من بنود
    أقرب عرض مطابق بدلاً من المطابقة بالكلمات المفتاحية فقط.
    """
    text = f"{title}\n{files_text}"
    boq: list[dict] = []
    matched_ref_note = ""

    # أولاً: البناء من أقرب عرض سابق مشابه إن وُجد تطابق قوي
    if similar_refs:
        best = similar_refs[0]
        ref_boq = best.get("data", {}).get("boq", [])
        if ref_boq:
            matched_ref_note = f"{best['title']} ({best['ref_no']})"
            for l in ref_boq:
                boq.append({
                    "code": l.get("code", ""), "name": l["name"], "unit": l.get("unit", "وحدة"),
                    "qty": l.get("qty", 1), "unit_price": l.get("unit_price", 0),
                    "source": l.get("source") or ("قاعدة الأسعار" if l.get("code") else "من عرض سابق"),
                })

    # ثانياً: المطابقة بالكلمات المفتاحية عند غياب مرجع مشابه
    if not boq:
        codes: list[str] = []
        for keywords, item_codes in _KEYWORD_MAP:
            if any(k in text for k in keywords):
                for c in item_codes:
                    if c not in codes:
                        codes.append(c)
        if not codes:
            codes = _DEFAULT_CODES
        catalog = {i["code"]: i for i in list_price_items()}
        for code in codes:
            item = catalog.get(code)
            if item:
                boq.append({
                    "code": item["code"], "name": item["name"], "unit": item["unit"],
                    "qty": 1, "unit_price": item["unit_price"], "source": "قاعدة الأسعار",
                })

    library = {e["title"]: e["body"] for e in list_library()}
    # الهيكل المعتمد للعرض الفني في المنافسات الحكومية السعودية (منصة اعتماد)
    sections = [
        {"title": "الملخص التنفيذي", "body": library.get("الملخص التنفيذي القياسي", "")},
        {"title": "التعريف بالشركة والتراخيص والشهادات", "body": library.get("نبذة عن شركة عزوم", "")},
        {"title": "فهم نطاق العمل",
         "body": f"اطلعت شركة عزوم على وثائق مشروع «{title}» الخاص بـ{client}، وقامت بتحليل متطلباته "
                 "وحصر نطاق أعماله. ويغطي هذا العرض كامل نطاق العمل الوارد في الوثائق المرجعية، ويُعد "
                 "جدول الكميات المرفق ترجمة تفصيلية لهذا النطاق. (حرّر هذا القسم لإضافة تفاصيل النطاق "
                 "المستخلصة من كراسة الشروط.)"},
        {"title": "منهجية التنفيذ وإدارة المشروع", "body": library.get("منهجية إدارة المشروع", "")},
        {"title": "الهيكل التنظيمي وفريق العمل", "body":
            "يُشكَّل فريق مشروع متكامل بقيادة مدير مشروع معتمد PMP يمثل نقطة الاتصال الوحيدة مع "
            "صاحب العمل، وتُرفق السير الذاتية للكوادر الأساسية ضمن الملاحق. (راجع جدول فريق العمل.)"},
        {"title": "الخبرات والمشاريع المماثلة",
         "body": (f"نفذت شركة عزوم وقدمت عروضاً لمشاريع مماثلة مباشرة لنطاق هذا المشروع، "
                  f"أقربها: {matched_ref_note}، وقد بُني جدول الكميات في هذا العرض على خبرة "
                  f"التسعير الفعلية لذلك المشروع. "
                  + library.get("الخبرات والمشاريع المماثلة", ""))
         if matched_ref_note else library.get("الخبرات والمشاريع المماثلة", "")},
        {"title": "خطة ضمان الجودة", "body": library.get("خطة ضمان الجودة", "")},
        {"title": "خطة السلامة والصحة المهنية", "body": library.get("خطة السلامة والصحة المهنية", "")},
        {"title": "إدارة المخاطر", "body": library.get("منهجية إدارة المخاطر", "")},
        {"title": "خطة المحتوى المحلي والسعودة والتدريب", "body": library.get("خطة المحتوى المحلي والسعودة والتدريب", "")},
        {"title": "الضمانات والالتزامات", "body": library.get("الضمانات والالتزامات", "")},
    ]

    compliance_matrix = [
        {"requirement": "تغطية كامل نطاق العمل الوارد في كراسة الشروط", "response": "ملتزمون", "reference": "قسم فهم نطاق العمل + جدول الكميات"},
        {"requirement": "الالتزام بالجدول الزمني المحدد", "response": "ملتزمون", "reference": "الخطة التنفيذية"},
        {"requirement": "تقديم الضمان الابتدائي والنهائي وفق النظام", "response": "ملتزمون", "reference": "قسم الضمانات"},
        {"requirement": "متطلبات المحتوى المحلي والتوطين", "response": "ملتزمون", "reference": "خطة المحتوى المحلي"},
    ]

    plan = [
        {"phase": "مرحلة التجهيز والتعبئة", "duration_weeks": 2,
         "description": "استلام الموقع/المتطلبات، تجهيز فريق العمل، اعتماد الخطة الزمنية التفصيلية وخطط الجودة والسلامة.",
         "deliverables": ["خطة زمنية معتمدة", "خطة جودة وسلامة", "تشكيل فريق المشروع"]},
        {"phase": "مرحلة التنفيذ الأساسية", "duration_weeks": 12,
         "description": "تنفيذ بنود نطاق العمل وفق جدول الكميات مع تقارير إنجاز أسبوعية وشهرية.",
         "deliverables": ["تقارير إنجاز دورية", "محاضر فحص واعتماد", "نسب إنجاز موثقة"]},
        {"phase": "مرحلة الفحص والتسليم الابتدائي", "duration_weeks": 3,
         "description": "الفحوصات النهائية، معالجة الملاحظات، التسليم الابتدائي.",
         "deliverables": ["محضر استلام ابتدائي", "إغلاق الملاحظات"]},
        {"phase": "مرحلة الإغلاق والتسليم النهائي", "duration_weeks": 2,
         "description": "تسليم الوثائق النهائية والمخططات كما نُفذت ونقل المعرفة والإغلاق المالي والإداري.",
         "deliverables": ["وثائق As-Built", "محضر استلام نهائي", "تقرير إغلاق المشروع"]},
    ]

    settings = get_settings()
    return {
        "summary": f"عرض فني ومالي مقدم من شركة عزوم لتنفيذ مشروع «{title}» لصالح {client}.",
        "scope": ["راجع قسم فهم نطاق العمل وجدول الكميات."],
        "technical_sections": sections,
        "compliance_matrix": compliance_matrix,
        "boq": boq,
        "financial": compute_financials(boq, settings),
        "plan": plan,
        "duration_weeks": sum(p["duration_weeks"] for p in plan),
        "assumptions": [
            "الأسعار بالريال السعودي وتشمل كافة الالتزامات ما لم يُذكر خلاف ذلك.",
            f"سريان العرض {settings.get('validity_days', '90')} يوماً من تاريخ تقديمه.",
            "الكميات في جدول الكميات تقديرية وتُحاسب على الكميات الفعلية المنفذة (حرّرها حسب كراسة الشروط).",
        ],
        "team": [{"role": "مدير مشروع PMP", "count": 1}, {"role": "مهندس موقع", "count": 1},
                 {"role": "مهندس جودة وسلامة", "count": 1}],
        "engine": "template",
    }
