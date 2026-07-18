"""إعدادات نظام عزوم للعروض الفنية والمالية."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
UPLOADS_DIR = DATA_DIR / "uploads"
EXPORTS_DIR = DATA_DIR / "exports"
DB_PATH = DATA_DIR / "azoom.db"

for d in (DATA_DIR, UPLOADS_DIR, EXPORTS_DIR):
    d.mkdir(parents=True, exist_ok=True)

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
CLAUDE_MODEL = "claude-opus-4-8"

# الهوية البصرية لشركة عزوم
BRAND = {
    "name_ar": "شركة عزوم",
    "name_en": "AZOOM",
    "primary": "10263F",   # كحلي عميق
    "accent": "C79A3C",    # ذهبي
    "light": "F5F1E8",     # رملي فاتح
}

# القيم الافتراضية المالية (قابلة للتعديل من شاشة الإعدادات)
DEFAULT_SETTINGS = {
    "company_name": "شركة عزوم",
    "company_cr": "",            # السجل التجاري
    "company_vat_no": "",        # الرقم الضريبي
    "company_address": "المملكة العربية السعودية",
    "company_phone": "",
    "company_email": "",
    "vat_rate": "15",            # ضريبة القيمة المضافة %
    "overhead_pct": "12",        # المصاريف الإدارية والعمومية %
    "risk_pct": "3",             # احتياطي المخاطر %
    "profit_pct": "15",          # هامش الربح %
    "validity_days": "90",       # مدة سريان العرض (المتعارف عليه في المنافسات الحكومية)
    "bid_bond_pct": "1",         # الضمان الابتدائي % (نظام المنافسات: لا يقل عن 1%)
    "payment_terms": "دفعة مقدمة 10% مقابل ضمان بنكي، ودفعات شهرية حسب نسب الإنجاز الفعلية المعتمدة، مع محتجز ضمان 10% يُصرف بعد الاستلام النهائي.",
}
