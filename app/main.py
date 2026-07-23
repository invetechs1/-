"""نظام عزوم للعروض الفنية والمالية — خادم التطبيق."""
import csv
import io
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import database as db
from .ai_engine import ai_available, generate_proposal_ai
from .analytics import compute_analytics
from .config import EXPORTS_DIR
from .export_docx import export_proposal_docx
from .export_xlsx import export_boq_xlsx
from .file_extract import extract_text
from .proposal_builder import build_template_proposal, compute_financials, match_price_catalog
from .seed import seed_if_empty
from .similarity import find_similar, get_reference_content

app = FastAPI(title="نظام عزوم للعروض الفنية والمالية", version="1.0.0")

STATIC_DIR = Path(__file__).parent / "static"


@app.on_event("startup")
def startup():
    db.init_db()
    seed_if_empty()


@app.get("/", response_class=HTMLResponse)
def index():
    return (STATIC_DIR / "index.html").read_text(encoding="utf-8")


@app.get("/api/status")
def status():
    return {
        "ok": True,
        "ai_enabled": ai_available(),
        "engine": "claude" if ai_available() else "template",
        "proposals": len(db.list_proposals()),
        "price_items": len(db.list_price_items()),
    }


# ------------------------------ الإعدادات ------------------------------

@app.get("/api/settings")
def get_settings():
    return db.get_settings()


@app.put("/api/settings")
def put_settings(values: dict):
    db.update_settings(values)
    return db.get_settings()


# ---------------------------- قاعدة الأسعار ----------------------------

@app.get("/api/prices")
def get_prices(search: str = "", category: str = ""):
    return db.list_price_items(search, category)


@app.post("/api/prices")
def post_price(item: dict):
    required = {"code", "category", "name", "unit", "unit_price"}
    if not required.issubset(item):
        raise HTTPException(400, f"حقول مطلوبة: {', '.join(required)}")
    return db.upsert_price_item(item)


@app.delete("/api/prices/{item_id}")
def remove_price(item_id: int):
    db.delete_price_item(item_id)
    return {"ok": True}


@app.get("/api/prices/{item_id}/history")
def price_history(item_id: int):
    return db.get_price_history(item_id)


@app.get("/api/prices/export/csv")
def export_prices_csv():
    items = db.list_price_items()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["code", "category", "name", "unit", "unit_price", "notes"])
    for i in items:
        writer.writerow([i["code"], i["category"], i["name"], i["unit"], i["unit_price"], i["notes"]])
    data = "﻿" + buf.getvalue()  # BOM لدعم العربية في Excel
    return StreamingResponse(
        io.BytesIO(data.encode("utf-8")),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=azoom-prices.csv"},
    )


@app.post("/api/prices/import/csv")
async def import_prices_csv(file: UploadFile = File(...)):
    content = (await file.read()).decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(content))
    count = 0
    for row in reader:
        if not row.get("code") or not row.get("name"):
            continue
        db.upsert_price_item({
            "code": row["code"].strip(),
            "category": (row.get("category") or "غير مصنف").strip(),
            "name": row["name"].strip(),
            "unit": (row.get("unit") or "وحدة").strip(),
            "unit_price": float(row.get("unit_price") or 0),
            "notes": (row.get("notes") or "").strip(),
        })
        count += 1
    return {"imported": count}


# --------------------------- المكتبة الفنية ---------------------------

@app.get("/api/library")
def get_library(category: str = ""):
    return db.list_library(category)


@app.post("/api/library")
def post_library(entry: dict):
    if not entry.get("title") or not entry.get("body"):
        raise HTTPException(400, "العنوان والنص مطلوبان")
    entry.setdefault("category", "عام")
    return db.upsert_library(entry)


@app.delete("/api/library/{entry_id}")
def remove_library(entry_id: int):
    db.delete_library(entry_id)
    return {"ok": True}


# ------------------------- خزنة وثائق الشركة -------------------------

@app.get("/api/docs")
def get_docs():
    return db.list_company_docs()


@app.post("/api/docs")
def post_doc(doc: dict):
    if not doc.get("name"):
        raise HTTPException(400, "اسم الوثيقة مطلوب")
    return db.upsert_company_doc(doc)


@app.delete("/api/docs/{doc_id}")
def remove_doc(doc_id: int):
    db.delete_company_doc(doc_id)
    return {"ok": True}


# ----------------------------- التحليلات -----------------------------

@app.get("/api/analytics")
def get_analytics():
    return compute_analytics()


# ------------------------- توليد العروض وإدارتها -------------------------

@app.post("/api/proposals/generate")
async def generate_proposal(
    title: str = Form(...),
    client: str = Form(...),
    entity_type: str = Form("government"),
    files: list[UploadFile] = File(default=[]),
):
    texts = []
    for f in files:
        content = await f.read()
        extracted = extract_text(f.filename or "file", content)
        texts.append(f"===== الملف: {f.filename} =====\n{extracted}")
    files_text = "\n\n".join(texts)

    # البحث عن العروض السابقة الأشبه بنطاق المشروع — أساس بناء العرض الجديد
    matches = find_similar(f"{title}\n{files_text[:8000]}", top_n=3)
    similar_refs = get_reference_content([m["id"] for m in matches]) if matches else []
    # ترتيب المحتوى بنفس ترتيب درجات التطابق
    order = {m["id"]: i for i, m in enumerate(matches)}
    similar_refs.sort(key=lambda p: order.get(p["id"], 99))

    if ai_available():
        try:
            data = generate_proposal_ai(title, client, entity_type, files_text, similar_refs)
        except Exception as exc:
            # فشل الاتصال أو التوليد — ننتقل لمحرك القوالب مع إبلاغ المستخدم
            data = build_template_proposal(title, client, entity_type, files_text, similar_refs)
            data["engine_note"] = f"تعذر التوليد بالذكاء الاصطناعي ({exc}) — استُخدم محرك القوالب."
    else:
        data = build_template_proposal(title, client, entity_type, files_text, similar_refs)

    data["similar_refs"] = [
        {"id": m["id"], "ref_no": m["ref_no"], "title": m["title"], "score": m["score"]}
        for m in matches
    ]
    proposal = db.create_proposal(title, client, entity_type, data)
    return proposal


@app.get("/api/proposals/similar")
def similar_proposals(q: str):
    """البحث عن العروض السابقة المشابهة لنص مشروع (يُستخدم مباشرة في شاشة عرض جديد)."""
    return find_similar(q, top_n=5)


@app.get("/api/proposals")
def get_proposals():
    return db.list_proposals()


@app.get("/api/proposals/{pid}")
def get_proposal(pid: int):
    proposal = db.get_proposal(pid)
    if not proposal:
        raise HTTPException(404, "العرض غير موجود")
    return proposal


@app.put("/api/proposals/{pid}")
def put_proposal(pid: int, fields: dict):
    # عند تعديل جدول الكميات نعيد الحسابات المالية
    if "data" in fields and "boq" in fields["data"]:
        fields["data"]["boq"] = match_price_catalog(fields["data"]["boq"])
        fields["data"]["financial"] = compute_financials(fields["data"]["boq"])
    proposal = db.update_proposal(pid, fields)
    if not proposal:
        raise HTTPException(404, "العرض غير موجود")
    return proposal


@app.delete("/api/proposals/{pid}")
def remove_proposal(pid: int):
    db.delete_proposal(pid)
    return {"ok": True}


@app.get("/api/proposals/{pid}/export/docx")
def export_docx(pid: int):
    proposal = db.get_proposal(pid)
    if not proposal:
        raise HTTPException(404, "العرض غير موجود")
    path = EXPORTS_DIR / f"{proposal['ref_no']}.docx"
    export_proposal_docx(proposal, db.get_settings(), str(path))
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=f"{proposal['ref_no']}.docx",
    )


@app.get("/api/proposals/{pid}/export/xlsx")
def export_xlsx(pid: int):
    proposal = db.get_proposal(pid)
    if not proposal:
        raise HTTPException(404, "العرض غير موجود")
    path = EXPORTS_DIR / f"{proposal['ref_no']}-BOQ.xlsx"
    export_boq_xlsx(proposal, str(path))
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=f"{proposal['ref_no']}-BOQ.xlsx",
    )


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
