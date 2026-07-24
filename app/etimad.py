"""وحدة الربط مع منصة اعتماد.

المسار الأول (يعمل فوراً بدون تسجيل دخول): جلب المنافسات المطروحة من واجهة
الزوار العامة في tenders.etimad.sa وتخزينها محلياً مع درجة ملاءمة لنشاط عزوم
محسوبة من الذاكرة المرجعية.

المسار الثاني (يتطلب دخول نفاذ من جهازك): تنزيل كراسات الشروط — راجع
scripts/etimad_nafath_login.py لحفظ جلسة الدخول.

ملاحظة: يعمل الجلب من جهازك مباشرة؛ بعض البيئات السحابية تحجب نطاق اعتماد.
"""
import json
import ssl
import urllib.parse
import urllib.request
from pathlib import Path

from .config import DATA_DIR
from .database import get_db, now_iso

VISITOR_API = "https://tenders.etimad.sa/Tender/AllSupplierTendersForVisitorAsync"
VISITOR_API_FALLBACK = "https://tenders.etimad.sa/Tender/AllTendersForVisitorAsync"
DETAILS_URL = "https://tenders.etimad.sa/Tender/DetailsForVisitor?STenderId={}"
COOKIES_FILE = DATA_DIR / "etimad_cookies.json"

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://tenders.etimad.sa/Tender/AllTendersForVisitor",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS etimad_tenders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tender_key TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    agency TEXT DEFAULT '',
    activity TEXT DEFAULT '',
    tender_type TEXT DEFAULT '',
    deadline TEXT DEFAULT '',
    booklet_price TEXT DEFAULT '',
    details_url TEXT DEFAULT '',
    relevance INTEGER DEFAULT 0,
    matched_ref TEXT DEFAULT '',
    status TEXT DEFAULT 'جديدة',
    raw TEXT DEFAULT '{}',
    fetched_at TEXT NOT NULL
);
"""


def init_etimad_table():
    with get_db() as db:
        db.executescript(SCHEMA)


def _pick(d: dict, *keys, default=""):
    """قراءة مرنة لأسماء الحقول — واجهة اعتماد قد تغيّر التسمية بين الإصدارات."""
    for k in keys:
        for variant in (k, k[0].upper() + k[1:], k.lower()):
            if variant in d and d[variant] not in (None, ""):
                return d[variant]
    return default


def _http_get(url: str, timeout: int = 30) -> dict:
    req = urllib.request.Request(url, headers=_HEADERS)
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_tenders(pages: int = 3, page_size: int = 50) -> dict:
    """جلب المنافسات المطروحة من واجهة الزوار وتخزين الجديد منها مع درجة الملاءمة."""
    from .similarity import find_similar

    init_etimad_table()
    added, scanned, errors = 0, 0, []
    for page in range(1, pages + 1):
        params = urllib.parse.urlencode({"PageSize": page_size, "PageNumber": page})
        data = None
        for api in (VISITOR_API, VISITOR_API_FALLBACK):
            try:
                data = _http_get(f"{api}?{params}")
                break
            except Exception as exc:
                errors.append(f"{api.rsplit('/', 1)[-1]}: {exc}")
        if data is None:
            return {
                "ok": False, "added": added, "scanned": scanned,
                "error": "تعذر الوصول لمنصة اعتماد من هذا الجهاز. شغّل النظام من جهاز "
                         "غير محجوب عنه نطاق tenders.etimad.sa ثم أعد المحاولة. "
                         f"التفاصيل: {errors[-1] if errors else ''}",
            }
        rows = data.get("data") or data.get("Data") or []
        if not rows:
            break
        for t in rows:
            scanned += 1
            key = str(_pick(t, "tenderIdString", "tenderId", "id", default=""))
            name = str(_pick(t, "tenderName", "name"))
            if not key or not name:
                continue
            agency = str(_pick(t, "agencyName", "agency"))
            matches = find_similar(f"{name} {agency}", top_n=1)
            relevance = matches[0]["score"] if matches else 0
            matched_ref = matches[0]["title"][:80] if matches else ""
            with get_db() as db:
                cur = db.execute(
                    "INSERT OR IGNORE INTO etimad_tenders "
                    "(tender_key, name, agency, activity, tender_type, deadline, booklet_price, "
                    " details_url, relevance, matched_ref, raw, fetched_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (key, name, agency,
                     str(_pick(t, "tenderActivityName", "activityName")),
                     str(_pick(t, "tenderTypeName", "tenderType")),
                     str(_pick(t, "lastOfferPresentationDate", "offersDeadline", "submitionDate"))[:16],
                     str(_pick(t, "condetionalBookletPrice", "bookletPrice", "financialFees")),
                     DETAILS_URL.format(urllib.parse.quote(key)),
                     relevance, matched_ref,
                     json.dumps(t, ensure_ascii=False)[:8000], now_iso()),
                )
                if cur.rowcount:
                    added += 1
    return {"ok": True, "added": added, "scanned": scanned}


def list_tenders(status: str = "", q: str = "", min_relevance: int = 0) -> list[dict]:
    init_etimad_table()
    query = ("SELECT id, tender_key, name, agency, activity, tender_type, deadline, "
             "booklet_price, details_url, relevance, matched_ref, status, fetched_at "
             "FROM etimad_tenders WHERE relevance >= ?")
    params: list = [min_relevance]
    if status:
        query += " AND status = ?"
        params.append(status)
    if q:
        query += " AND (name LIKE ? OR agency LIKE ?)"
        params += [f"%{q}%", f"%{q}%"]
    query += " ORDER BY relevance DESC, id DESC LIMIT 300"
    with get_db() as db:
        rows = db.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def update_tender_status(tid: int, status: str):
    with get_db() as db:
        db.execute("UPDATE etimad_tenders SET status = ? WHERE id = ?", (status, tid))


def has_session() -> bool:
    return COOKIES_FILE.exists()
