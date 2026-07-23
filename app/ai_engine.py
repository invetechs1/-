"""محرك التوليد الذكي — يحلل وثائق المشروع ويولّد العرض الفني والمالي عبر Claude API.

عند غياب مفتاح ANTHROPIC_API_KEY يتولى محرك القوالب (proposal_builder) المهمة.
"""
import json

from .config import ANTHROPIC_API_KEY, CLAUDE_MODEL
from .database import get_settings, list_price_items, list_library
from .proposal_builder import compute_financials, match_price_catalog

PROPOSAL_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "description": "ملخص تنفيذي موجز للعرض"},
        "scope": {"type": "array", "items": {"type": "string"}, "description": "بنود نطاق العمل المستخلصة من الوثائق"},
        "technical_sections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "body": {"type": "string"},
                },
                "required": ["title", "body"],
                "additionalProperties": False,
            },
        },
        "compliance_matrix": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "requirement": {"type": "string", "description": "متطلب من كراسة الشروط"},
                    "response": {"type": "string", "description": "ملتزمون / ملتزمون مع توضيح / غير منطبق"},
                    "reference": {"type": "string", "description": "القسم الذي يغطي المتطلب في العرض"},
                },
                "required": ["requirement", "response", "reference"],
                "additionalProperties": False,
            },
        },
        "boq": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "كود البند من قاعدة الأسعار إن وُجد، وإلا فارغ"},
                    "name": {"type": "string"},
                    "unit": {"type": "string"},
                    "qty": {"type": "number"},
                    "unit_price": {"type": "number", "description": "من قاعدة الأسعار، أو تقدير مبرر إن لم يوجد البند"},
                },
                "required": ["code", "name", "unit", "qty", "unit_price"],
                "additionalProperties": False,
            },
        },
        "plan": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "phase": {"type": "string"},
                    "description": {"type": "string"},
                    "duration_weeks": {"type": "number"},
                    "deliverables": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["phase", "description", "duration_weeks", "deliverables"],
                "additionalProperties": False,
            },
        },
        "duration_weeks": {"type": "number"},
        "assumptions": {"type": "array", "items": {"type": "string"}},
        "team": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "role": {"type": "string"},
                    "count": {"type": "number"},
                },
                "required": ["role", "count"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["summary", "scope", "technical_sections", "compliance_matrix",
                 "boq", "plan", "duration_weeks", "assumptions", "team"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """أنت خبير إعداد العروض الفنية والمالية في شركة عزوم السعودية، متمكن من نظام المنافسات
والمشتريات الحكومية السعودي ومتطلبات منصة اعتماد، وتكتب بعربية فصيحة مهنية تليق بالجهات الحكومية.

مهمتك: تحليل وثائق المشروع المرفقة وإنتاج عرض فني ومالي وخطة تنفيذية متكاملة باسم شركة عزوم.

قواعد إلزامية:
1. الأقسام الفنية تتبع الهيكل المعتمد في المنافسات الحكومية: الملخص التنفيذي، التعريف بالشركة،
   فهم نطاق العمل (مفصّل ومستخلص فعلياً من الوثائق وبمصطلحات صاحب العمل)، منهجية التنفيذ،
   الهيكل التنظيمي وفريق العمل، الخبرات المماثلة، خطة الجودة، خطة السلامة، إدارة المخاطر،
   خطة المحتوى المحلي والسعودة، الضمانات والالتزامات.
2. جدول الكميات: استخدم بنود قاعدة أسعار عزوم المرفقة (بالكود والسعر) كلما وُجد بند مطابق،
   وقدّر الكميات من الوثائق. للبنود غير الموجودة في القاعدة اترك الكود فارغاً وقدّر سعراً سوقياً
   واقعياً بالريال السعودي.
3. مصفوفة الالتزام: استخلص المتطلبات الجوهرية من كراسة الشروط وحدد موضع تغطيتها في العرض.
4. الخطة التنفيذية: مراحل واقعية بمدد أسبوعية ومخرجات محددة قابلة للقياس.
5. استخدم نصوص المكتبة الفنية المرفقة كأساس للأقسام العامة مع تكييفها لسياق المشروع.
6. لا تختلق أرقام تراخيص أو أسماء مشاريع سابقة أو بيانات غير موجودة في المدخلات."""


def ai_available() -> bool:
    return bool(ANTHROPIC_API_KEY)


def _format_similar_refs(similar_refs: list[dict] | None) -> str:
    if not similar_refs:
        return "(لا توجد عروض سابقة مشابهة في الأرشيف)"
    parts = []
    for ref in similar_refs[:2]:
        d = ref.get("data", {})
        boq_sample = "\n".join(
            f"  - {l['name']} | {l.get('unit','')} | سعر الوحدة: {l.get('unit_price',0)} ريال"
            for l in d.get("boq", []) if l.get("unit_price")
        )[:6000]
        parts.append(
            f"### عرض سابق مشابه: {ref['title']} — {ref['client']}\n"
            f"الملخص: {d.get('summary','')}\n"
            f"نطاقه: {'، '.join(d.get('scope', [])[:15])}\n"
            f"بنوده المسعّرة (استرشد بها في التسعير والصياغة):\n{boq_sample}"
        )
    return "\n\n".join(parts)


def generate_proposal_ai(title: str, client_name: str, entity_type: str, files_text: str,
                         similar_refs: list[dict] | None = None) -> dict:
    import anthropic

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    settings = get_settings()
    catalog = list_price_items()
    library = list_library()

    catalog_txt = "\n".join(
        f"{i['code']} | {i['category']} | {i['name']} | {i['unit']} | {i['unit_price']} ريال"
        for i in catalog
    )
    library_txt = "\n\n".join(f"### {e['title']}\n{e['body']}" for e in library)
    entity_label = "جهة حكومية (منافسة عبر منصة اعتماد)" if entity_type == "government" else "قطاع خاص"

    user_content = f"""## بيانات المشروع
- اسم المشروع: {title}
- العميل: {client_name}
- نوع الجهة: {entity_label}
- بيانات الشركة: {settings.get('company_name')} — {settings.get('company_address')}

## قاعدة أسعار عزوم المعتمدة (كود | تصنيف | البند | الوحدة | سعر الوحدة)
{catalog_txt}

## المكتبة الفنية (نصوص عزوم المعتمدة)
{library_txt}

## عروض عزوم السابقة المشابهة لنطاق هذا المشروع (خبرة الشركة الفعلية — ابنِ عليها)
{_format_similar_refs(similar_refs)}

## وثائق المشروع المرفوعة
{files_text or '(لم تُرفق وثائق — ابنِ العرض على اسم المشروع ونوع الجهة والعروض المشابهة)'}

أنتج العرض الكامل الآن وفق المخطط المطلوب، مستفيداً من بنود وأسعار العروض السابقة
المشابهة كلما طابقت نطاق المشروع الجديد."""

    with client.messages.stream(
        model=CLAUDE_MODEL,
        max_tokens=64000,
        thinking={"type": "adaptive"},
        system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        output_config={"format": {"type": "json_schema", "schema": PROPOSAL_SCHEMA}},
        messages=[{"role": "user", "content": user_content}],
    ) as stream:
        message = stream.get_final_message()

    if message.stop_reason == "refusal":
        raise RuntimeError("تعذر توليد العرض — تم رفض الطلب من مرشحات الأمان. جرّب تعديل صياغة الوثائق.")

    text = next(b.text for b in message.content if b.type == "text")
    data = json.loads(text)

    # مطابقة البنود مع قاعدة الأسعار ثم الحسابات المالية بمحرك التسعير المحلي (لا نثق بحسابات النموذج)
    data["boq"] = match_price_catalog(data.get("boq", []))
    data["financial"] = compute_financials(data["boq"], settings)
    data["engine"] = "claude"
    return data
