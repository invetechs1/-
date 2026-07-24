"""دخول منصة اعتماد عبر نفاذ وحفظ الجلسة — يُشغَّل من جهازك (وليس من خادم سحابي).

الخطوات:
1. ضع رقم الهوية في إعدادات النظام (شاشة الإعدادات → حقل «رقم الهوية لدخول اعتماد»)
   أو مرره كمتغير بيئة: ETIMAD_NATIONAL_ID
2. ثبّت متطلب التشغيل مرة واحدة:  pip install playwright && playwright install chromium
3. شغّل:  python scripts/etimad_nafath_login.py
4. سيفتح متصفح على صفحة دخول اعتماد ويُدخل رقم الهوية، وسيظهر لك رقم نفاذ —
   افتح تطبيق نفاذ في جوالك واضغط الرقم المطابق.
5. بعد نجاح الدخول تُحفظ الجلسة في data/etimad_cookies.json ليستخدمها النظام
   في تنزيل كراسات الشروط ومتابعة منافساتك.

ملاحظة: جلسة اعتماد تنتهي صلاحيتها دورياً — أعد تشغيل السكربت عند انتهائها.
"""
import json
import os
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

LOGIN_URL = "https://sso.etimad.sa/Account/EtimadLogin"
COOKIES_FILE = BASE / "data" / "etimad_cookies.json"


def get_national_id() -> str:
    nid = os.environ.get("ETIMAD_NATIONAL_ID", "").strip()
    if not nid:
        try:
            from app.database import get_settings, init_db
            init_db()
            nid = get_settings().get("etimad_national_id", "").strip()
        except Exception:
            pass
    if not nid:
        nid = input("أدخل رقم الهوية الوطنية لدخول اعتماد: ").strip()
    return nid


def main():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("⚠️ ثبّت Playwright أولاً:  pip install playwright && playwright install chromium")
        sys.exit(1)

    national_id = get_national_id()
    if not national_id:
        print("⚠️ لم يُدخل رقم هوية.")
        sys.exit(1)

    print(f"🌐 فتح متصفح الدخول لاعتماد (الهوية: {national_id[:3]}*******)")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(locale="ar-SA")
        page = context.new_page()
        page.goto(LOGIN_URL, timeout=60_000)

        # محاولة تعبئة حقل الهوية تلقائياً (أسماء الحقول قد تتغير مع تحديثات المنصة)
        filled = False
        for selector in ("#IdentityNumber", "input[name='IdentityNumber']",
                         "input[name='username']", "input[type='text']"):
            try:
                page.fill(selector, national_id, timeout=4000)
                filled = True
                break
            except Exception:
                continue
        if filled:
            print("✍️ أُدخل رقم الهوية — اضغط زر الدخول في المتصفح إن لم يُضغط تلقائياً.")
        else:
            print("✍️ أدخل رقم الهوية يدوياً في المتصفح المفتوح.")

        print("📱 سيظهر رقم نفاذ في الصفحة — افتح تطبيق نفاذ بجوالك واضغط الرقم المطابق.")
        print("⏳ بانتظار اكتمال الدخول (حتى 5 دقائق)...")

        # ننتظر مغادرة نطاق sso (نجاح الدخول والعودة لاعتماد)
        try:
            page.wait_for_url(lambda url: "sso.etimad.sa" not in url, timeout=300_000)
        except Exception:
            print("⚠️ انتهت المهلة دون اكتمال الدخول. أعد المحاولة.")
            browser.close()
            sys.exit(1)

        COOKIES_FILE.parent.mkdir(parents=True, exist_ok=True)
        cookies = context.cookies()
        COOKIES_FILE.write_text(json.dumps(cookies, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"✅ تم الدخول وحُفظت الجلسة ({len(cookies)} كوكي) في: {COOKIES_FILE}")
        print("يمكنك الآن إغلاق المتصفح — النظام سيستخدم الجلسة لتنزيل كراسات الشروط.")
        browser.close()


if __name__ == "__main__":
    main()
