/* نظام عزوم — منطق الواجهة */
const $ = (s) => document.querySelector(s);
const $$ = (s) => document.querySelectorAll(s);

const STATUS_AR = { draft: "مسودة", submitted: "مُقدَّم", won: "فائز", lost: "غير فائز" };
const fmt = (n) => Number(n || 0).toLocaleString("ar-SA", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

let currentProposal = null;
let pendingFiles = [];

/* ---------- تنقّل ---------- */
function go(page) {
  $$(".page").forEach((p) => p.classList.remove("active"));
  $(`#page-${page}`).classList.add("active");
  $$(".nav-btn").forEach((b) => b.classList.toggle("active", b.dataset.page === page));
  if (page === "dashboard") loadDashboard();
  if (page === "proposals") loadProposals();
  if (page === "prices") loadPrices();
  if (page === "library") loadLibrary();
  if (page === "docs") loadDocs();
  if (page === "analytics") loadAnalytics();
  if (page === "settings") loadSettings();
}
$$(".nav-btn").forEach((b) => b.addEventListener("click", () => go(b.dataset.page)));

function toast(msg, isErr = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "toast show" + (isErr ? " err" : "");
  setTimeout(() => t.classList.remove("show"), 3500);
}

async function api(url, opts = {}) {
  if (opts.json) {
    opts.body = JSON.stringify(opts.json);
    opts.headers = { "Content-Type": "application/json" };
    delete opts.json;
  }
  const res = await fetch(url, opts);
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch {}
    throw new Error(detail);
  }
  return res.json();
}

/* ---------- لوحة التحكم ---------- */
async function loadDashboard() {
  const [status, proposals] = await Promise.all([api("/api/status"), api("/api/proposals")]);
  $("#engineBadge").innerHTML = status.ai_enabled
    ? "🤖 محرك التوليد: Claude AI"
    : "📋 محرك التوليد: القوالب الذكية<br>أضف ANTHROPIC_API_KEY لتفعيل الذكاء الاصطناعي";
  $("#engineHint").textContent = status.ai_enabled
    ? "سيُولَّد العرض بالذكاء الاصطناعي (Claude) استناداً لوثائق المشروع وقاعدة أسعار عزوم"
    : "التوليد بمحرك القوالب الذكية — أضف مفتاح API في ملف ‎.env لتفعيل Claude";

  const won = proposals.filter((p) => p.status === "won").length;
  const submitted = proposals.filter((p) => p.status === "submitted").length;
  $("#statCards").innerHTML = `
    <div class="card gold"><div class="num">${proposals.length}</div><div class="lbl">إجمالي العروض</div></div>
    <div class="card"><div class="num">${submitted}</div><div class="lbl">عروض مُقدَّمة</div></div>
    <div class="card"><div class="num">${won}</div><div class="lbl">عروض فائزة</div></div>
    <div class="card"><div class="num">${status.price_items}</div><div class="lbl">بند في قاعدة الأسعار</div></div>`;

  $("#recentTable tbody").innerHTML = proposals.slice(0, 8).map(rowHtml).join("") ||
    `<tr><td colspan="7" class="muted">لا توجد عروض بعد — ابدأ بإنشاء عرض جديد</td></tr>`;

  // تنبيهات صلاحية وثائق الشركة
  const docs = await api("/api/docs");
  const expired = docs.filter((d) => d.status === "expired");
  const expiring = docs.filter((d) => d.status === "expiring");
  if (expired.length || expiring.length) {
    const parts = [];
    if (expired.length) parts.push(`⛔ وثائق منتهية: ${expired.map((d) => d.name).join("، ")}`);
    if (expiring.length) parts.push(`⚠️ تنتهي خلال 30 يوماً: ${expiring.map((d) => `${d.name} (${d.days_left} يوماً)`).join("، ")}`);
    $("#docsAlert").innerHTML = `<div class="panel" style="border-right:4px solid var(--warn)">
      <b>تنبيه الوثائق النظامية</b>
      <p class="muted mt" style="line-height:1.9">${parts.join("<br>")}</p>
      <button class="btn sm ghost mt" onclick="go('docs')">فتح وثائق الشركة</button></div>`;
  } else {
    $("#docsAlert").innerHTML = "";
  }
}

function rowHtml(p) {
  return `<tr>
    <td>${p.ref_no}</td><td>${p.title}</td><td>${p.client}</td>
    <td><span class="tag ${p.entity_type === "government" ? "gov" : "private"}">${p.entity_type === "government" ? "حكومي" : "خاص"}</span></td>
    <td><span class="tag ${p.status}">${STATUS_AR[p.status] || p.status}</span></td>
    <td class="num-cell">${p.created_at.slice(0, 10)}</td>
    <td><button class="btn sm" onclick="openProposal(${p.id})">فتح</button>
        <button class="btn sm danger" onclick="removeProposal(${p.id})">حذف</button></td>
  </tr>`;
}

/* ---------- عرض جديد ---------- */
const dropzone = $("#dropzone");
const fileInput = $("#fileInput");
dropzone.addEventListener("click", () => fileInput.click());
dropzone.addEventListener("dragover", (e) => { e.preventDefault(); dropzone.classList.add("drag"); });
dropzone.addEventListener("dragleave", () => dropzone.classList.remove("drag"));
dropzone.addEventListener("drop", (e) => {
  e.preventDefault();
  dropzone.classList.remove("drag");
  addFiles(e.dataTransfer.files);
});
fileInput.addEventListener("change", () => addFiles(fileInput.files));

function addFiles(list) {
  for (const f of list) pendingFiles.push(f);
  renderFileList();
}
function renderFileList() {
  $("#fileList").innerHTML = pendingFiles.map((f, i) =>
    `<span class="file-chip">${f.name}<button onclick="pendingFiles.splice(${i},1);renderFileList()">✕</button></span>`
  ).join("");
}

/* اقتراح العروض المشابهة أثناء كتابة اسم المشروع */
let similarTimer;
function suggestSimilar() {
  clearTimeout(similarTimer);
  similarTimer = setTimeout(async () => {
    const q = $("#npTitle").value.trim();
    if (q.length < 5) { $("#similarBox").innerHTML = ""; return; }
    try {
      const matches = await api(`/api/proposals/similar?q=${encodeURIComponent(q)}`);
      if (!matches.length) { $("#similarBox").innerHTML = ""; return; }
      $("#similarBox").innerHTML = `
        <div class="mt" style="border:1px solid var(--accent);border-radius:10px;padding:12px 14px;background:#fdf9f0">
          <b style="color:var(--primary)">🧠 عروض سابقة مشابهة في الأرشيف — سيُبنى العرض الجديد عليها:</b>
          ${matches.map((m) => `
            <div class="row mt" style="justify-content:space-between;font-size:13px">
              <span>${m.title} <span class="muted">(${m.client})</span></span>
              <span class="tag gov">تطابق ${m.score}% • ${m.boq_lines} بنداً</span>
            </div>`).join("")}
        </div>`;
    } catch { /* تجاهل أخطاء الاقتراح */ }
  }, 400);
}

$("#generateBtn").addEventListener("click", async () => {
  const title = $("#npTitle").value.trim();
  const client = $("#npClient").value.trim();
  if (!title || !client) return toast("أدخل اسم المشروع والعميل", true);

  const form = new FormData();
  form.append("title", title);
  form.append("client", client);
  form.append("entity_type", $("#npEntity").value);
  for (const f of pendingFiles) form.append("files", f);

  $("#generateBtn").disabled = true;
  $("#genSpinner").classList.add("on");
  try {
    const proposal = await api("/api/proposals/generate", { method: "POST", body: form });
    pendingFiles = [];
    renderFileList();
    $("#npTitle").value = ""; $("#npClient").value = "";
    if (proposal.data.engine_note) toast(proposal.data.engine_note, true);
    else toast(`تم إنشاء العرض ${proposal.ref_no} بنجاح ✅`);
    viewProposal(proposal);
  } catch (err) {
    toast("فشل التوليد: " + err.message, true);
  } finally {
    $("#generateBtn").disabled = false;
    $("#genSpinner").classList.remove("on");
  }
});

/* ---------- أرشيف العروض ---------- */
async function loadProposals() {
  const proposals = await api("/api/proposals");
  $("#proposalsTable tbody").innerHTML = proposals.map(rowHtml).join("") ||
    `<tr><td colspan="7" class="muted">لا توجد عروض بعد</td></tr>`;
}

async function removeProposal(id) {
  if (!confirm("حذف هذا العرض نهائياً؟")) return;
  await api(`/api/proposals/${id}`, { method: "DELETE" });
  toast("تم حذف العرض");
  loadProposals(); loadDashboard();
}

async function openProposal(id) {
  viewProposal(await api(`/api/proposals/${id}`));
}

/* ---------- عارض العرض ---------- */
$$(".tab-btn").forEach((b) => b.addEventListener("click", () => {
  $$(".tab-btn").forEach((x) => x.classList.toggle("active", x === b));
  $$(".tab-pane").forEach((p) => p.classList.toggle("active", p.id === `tab-${b.dataset.tab}`));
}));

function viewProposal(p) {
  currentProposal = p;
  go("viewer");
  $$(".nav-btn").forEach((b) => b.classList.remove("active"));
  $("#vTitle").textContent = `${p.ref_no} — ${p.title}`;
  const engine = p.data.engine === "claude" ? "🤖 توليد Claude AI"
    : p.data.reference ? "🗄️ عرض مرجعي (محلل من عرض فعلي)" : "📋 محرك القوالب";
  let meta = `${p.client} • ${p.entity_type === "government" ? "جهة حكومية" : "قطاع خاص"} • ${engine}`;
  if (p.data.similar_refs?.length) {
    meta += ` • مبني على: ${p.data.similar_refs.map((r) => `${r.title.slice(0, 30)}… (${r.score}%)`).join("، ")}`;
  }
  $("#vMeta").textContent = meta;
  $("#vStatus").value = p.status;
  renderTech(p.data);
  renderFin(p.data);
  renderPlan(p.data);
}

function renderTech(d) {
  let html = (d.technical_sections || []).map((s) =>
    `<div class="panel section-block"><h4>${s.title}</h4><p>${s.body}</p></div>`).join("");

  if (d.team?.length) {
    html += `<div class="panel section-block"><h4>فريق العمل المقترح</h4>
      <div class="t-wrap"><table><thead><tr><th>الدور</th><th>العدد</th></tr></thead><tbody>
      ${d.team.map((t) => `<tr><td>${t.role}</td><td>${t.count}</td></tr>`).join("")}
      </tbody></table></div></div>`;
  }
  if (d.compliance_matrix?.length) {
    html += `<div class="panel section-block"><h4>مصفوفة الالتزام بالمتطلبات</h4>
      <div class="t-wrap"><table><thead><tr><th>المتطلب</th><th>الالتزام</th><th>الموضع في العرض</th></tr></thead><tbody>
      ${d.compliance_matrix.map((m) => `<tr><td>${m.requirement}</td><td>${m.response}</td><td>${m.reference}</td></tr>`).join("")}
      </tbody></table></div></div>`;
  }
  $("#tab-tech").innerHTML = html;
}

function renderFin(d) {
  const boq = d.boq || [];
  const f = d.financial || {};
  $("#tab-fin").innerHTML = `
    <div class="panel">
      <h3>جدول الكميات والأسعار <span class="muted">(عدّل الكميات والأسعار — يُعاد الحساب تلقائياً)</span></h3>
      <div class="t-wrap"><table>
        <thead><tr><th>م</th><th>الكود</th><th>البند</th><th>الوحدة</th><th>الكمية</th><th>سعر الوحدة</th><th>الإجمالي</th><th>المصدر</th><th></th></tr></thead>
        <tbody>${boq.map((l, i) => `
          <tr>
            <td>${i + 1}</td>
            <td class="num-cell">${l.code || "—"}</td>
            <td>${l.name}</td>
            <td>${l.unit}</td>
            <td style="width:90px"><input type="number" value="${l.qty}" step="0.01" onchange="editBoq(${i},'qty',this.value)"></td>
            <td style="width:120px"><input type="number" value="${l.unit_price}" step="0.01" onchange="editBoq(${i},'unit_price',this.value)"></td>
            <td class="num-cell">${fmt(l.total)}</td>
            <td><span class="tag ${l.source === "قاعدة الأسعار" ? "src" : "est"}">${l.source || "تقدير"}</span></td>
            <td><button class="btn sm danger" onclick="removeBoqLine(${i})">✕</button></td>
          </tr>`).join("")}
        </tbody>
      </table></div>
      <div class="mt"><button class="btn ghost sm" onclick="addBoqLine()">+ إضافة بند</button></div>
    </div>
    <div class="panel fin-summary">
      <h3>ملخص القيمة الإجمالية</h3>
      <div class="fin-row"><span>التكلفة المباشرة</span><span class="num-cell">${fmt(f.direct_cost)} ر.س</span></div>
      <div class="fin-row"><span>المصاريف الإدارية والعمومية (${f.overhead_pct ?? 0}%)</span><span class="num-cell">${fmt(f.overhead)} ر.س</span></div>
      <div class="fin-row"><span>احتياطي المخاطر (${f.risk_pct ?? 0}%)</span><span class="num-cell">${fmt(f.risk)} ر.س</span></div>
      <div class="fin-row"><span>هامش الربح (${f.profit_pct ?? 0}%)</span><span class="num-cell">${fmt(f.profit)} ر.س</span></div>
      <div class="fin-row"><span>الإجمالي قبل الضريبة</span><span class="num-cell">${fmt(f.subtotal)} ر.س</span></div>
      <div class="fin-row"><span>ضريبة القيمة المضافة (${f.vat_rate ?? 15}%)</span><span class="num-cell">${fmt(f.vat)} ر.س</span></div>
      <div class="fin-row total"><span>الإجمالي النهائي</span><span class="v num-cell">${fmt(f.grand_total)} ر.س</span></div>
      <p class="muted mt">الضمان الابتدائي المطلوب (${f.bid_bond_pct ?? 1}%): <b>${fmt(f.bid_bond)} ر.س</b></p>
    </div>
    ${(d.assumptions || []).length ? `<div class="panel"><h3>الافتراضات والاستثناءات</h3>${d.assumptions.map((a) => `<p class="muted">• ${a}</p>`).join("")}</div>` : ""}`;
}

function renderPlan(d) {
  const plan = d.plan || [];
  const totalWeeks = plan.reduce((s, p) => s + Number(p.duration_weeks || 0), 0) || 1;
  let start = 0;
  const gantt = plan.map((p) => {
    const width = (p.duration_weeks / totalWeeks) * 100;
    const bar = `<div class="gantt-row">
      <div class="gantt-label">${p.phase}</div>
      <div class="gantt-track"><div class="gantt-bar" style="right:${(start / totalWeeks) * 100}%;width:${width}%"></div></div>
    </div>`;
    start += Number(p.duration_weeks || 0);
    return bar;
  }).join("");

  $("#tab-plan").innerHTML = `
    <div class="panel">
      <h3>الخطة التنفيذية — المدة الإجمالية ${d.duration_weeks || totalWeeks} أسبوعاً</h3>
      ${plan.map((p, i) => `
        <div class="phase">
          <h4>المرحلة ${i + 1}: ${p.phase} <span class="dur">(${p.duration_weeks} أسابيع)</span></h4>
          <p>${p.description}</p>
          <ul>${(p.deliverables || []).map((x) => `<li>${x}</li>`).join("")}</ul>
        </div>`).join("")}
      <h3 class="mt">المخطط الزمني</h3>
      <div class="gantt">${gantt}</div>
    </div>`;
}

async function saveBoqChanges() {
  currentProposal = await api(`/api/proposals/${currentProposal.id}`, {
    method: "PUT",
    json: { data: currentProposal.data },
  });
  renderFin(currentProposal.data);
}

function editBoq(i, field, value) {
  currentProposal.data.boq[i][field] = Number(value);
  if (field === "unit_price") currentProposal.data.boq[i].source = "معدّل يدوياً";
  saveBoqChanges();
}
function removeBoqLine(i) {
  currentProposal.data.boq.splice(i, 1);
  saveBoqChanges();
}
function addBoqLine() {
  const name = prompt("اسم البند الجديد:");
  if (!name) return;
  currentProposal.data.boq.push({ code: "", name, unit: "وحدة", qty: 1, unit_price: 0, source: "يدوي" });
  saveBoqChanges();
}

async function changeStatus() {
  currentProposal = await api(`/api/proposals/${currentProposal.id}`, {
    method: "PUT", json: { status: $("#vStatus").value },
  });
  toast("تم تحديث حالة العرض");
}

function exportDocx() { window.location = `/api/proposals/${currentProposal.id}/export/docx`; }
function exportXlsx() { window.location = `/api/proposals/${currentProposal.id}/export/xlsx`; }

/* ---------- قاعدة الأسعار ---------- */
async function loadPrices() {
  const search = $("#prSearch").value || "";
  const cat = $("#prFilterCat").value || "";
  const items = await api(`/api/prices?search=${encodeURIComponent(search)}&category=${encodeURIComponent(cat)}`);

  const cats = [...new Set((await api("/api/prices")).map((i) => i.category))];
  $("#catList").innerHTML = cats.map((c) => `<option value="${c}">`).join("");
  const filterSel = $("#prFilterCat");
  if (filterSel.options.length <= 1) {
    filterSel.innerHTML = `<option value="">كل التصنيفات</option>` + cats.map((c) => `<option>${c}</option>`).join("");
  }

  $("#pricesTable tbody").innerHTML = items.map((i) => `
    <tr>
      <td class="num-cell">${i.code}</td><td>${i.category}</td><td>${i.name}</td><td>${i.unit}</td>
      <td class="num-cell"><b>${fmt(i.unit_price)}</b></td>
      <td class="num-cell muted">${i.updated_at.slice(0, 10)}</td>
      <td>
        <button class="btn sm ghost" onclick='fillPriceForm(${JSON.stringify(i).replace(/'/g, "&#39;")})'>تعديل</button>
        <button class="btn sm danger" onclick="removePrice(${i.id})">حذف</button>
      </td>
    </tr>`).join("");
}

function fillPriceForm(i) {
  $("#prCode").value = i.code; $("#prCat").value = i.category;
  $("#prName").value = i.name; $("#prUnit").value = i.unit;
  $("#prPrice").value = i.unit_price;
  window.scrollTo({ top: 0, behavior: "smooth" });
}

async function savePrice() {
  const item = {
    code: $("#prCode").value.trim(), category: $("#prCat").value.trim(),
    name: $("#prName").value.trim(), unit: $("#prUnit").value.trim(),
    unit_price: Number($("#prPrice").value),
  };
  if (!item.code || !item.name || !item.category || !item.unit) return toast("أكمل الحقول المطلوبة", true);
  await api("/api/prices", { method: "POST", json: item });
  toast("تم حفظ البند ✅");
  ["prCode", "prCat", "prName", "prUnit", "prPrice"].forEach((id) => $("#" + id).value = "");
  loadPrices();
}

async function removePrice(id) {
  if (!confirm("حذف هذا البند من قاعدة الأسعار؟")) return;
  await api(`/api/prices/${id}`, { method: "DELETE" });
  loadPrices();
}

$("#csvImport").addEventListener("change", async (e) => {
  const file = e.target.files[0];
  if (!file) return;
  const form = new FormData();
  form.append("file", file);
  const res = await api("/api/prices/import/csv", { method: "POST", body: form });
  toast(`تم استيراد ${res.imported} بنداً`);
  loadPrices();
});

/* ---------- المكتبة الفنية ---------- */
async function loadLibrary() {
  const entries = await api("/api/library");
  $("#libraryList").innerHTML = entries.map((e) => `
    <div class="panel">
      <div class="row" style="justify-content:space-between">
        <div><b style="color:var(--primary)">${e.title}</b> <span class="tag gov">${e.category}</span></div>
        <div>
          <button class="btn sm ghost" onclick='fillLibraryForm(${JSON.stringify(e).replace(/'/g, "&#39;")})'>تعديل</button>
          <button class="btn sm danger" onclick="removeLibrary(${e.id})">حذف</button>
        </div>
      </div>
      <p class="muted mt" style="line-height:1.8">${e.body}</p>
    </div>`).join("");
}

function fillLibraryForm(e) {
  $("#libId").value = e.id; $("#libCat").value = e.category;
  $("#libTitle").value = e.title; $("#libBody").value = e.body;
  window.scrollTo({ top: 0, behavior: "smooth" });
}
function clearLibraryForm() {
  ["libId", "libCat", "libTitle", "libBody"].forEach((id) => $("#" + id).value = "");
}

async function saveLibrary() {
  const entry = {
    id: $("#libId").value ? Number($("#libId").value) : undefined,
    category: $("#libCat").value.trim() || "عام",
    title: $("#libTitle").value.trim(),
    body: $("#libBody").value.trim(),
  };
  if (!entry.title || !entry.body) return toast("العنوان والنص مطلوبان", true);
  await api("/api/library", { method: "POST", json: entry });
  toast("تم الحفظ ✅");
  clearLibraryForm();
  loadLibrary();
}

async function removeLibrary(id) {
  if (!confirm("حذف هذا النص من المكتبة؟")) return;
  await api(`/api/library/${id}`, { method: "DELETE" });
  loadLibrary();
}

/* ---------- وثائق الشركة ---------- */
const DOC_STATUS = {
  expired: ["منتهية ⛔", "lost"],
  expiring: ["تنتهي قريباً ⚠️", "est"],
  valid: ["سارية ✅", "src"],
  missing: ["غير مُدخلة", "draft"],
};

async function loadDocs() {
  const docs = await api("/api/docs");
  $("#docsTable tbody").innerHTML = docs.map((d) => {
    const [label, cls] = DOC_STATUS[d.status] || DOC_STATUS.missing;
    const days = d.status === "expiring" ? ` (${d.days_left} يوماً)` : "";
    return `<tr>
      <td><b>${d.name}</b></td><td class="num-cell">${d.number || "—"}</td><td>${d.issuer || "—"}</td>
      <td class="num-cell">${d.expiry_date || "—"}</td>
      <td><span class="tag ${cls}">${label}${days}</span></td>
      <td>
        <button class="btn sm ghost" onclick='fillDocForm(${JSON.stringify(d).replace(/'/g, "&#39;")})'>تعديل</button>
        <button class="btn sm danger" onclick="removeDoc(${d.id})">حذف</button>
      </td></tr>`;
  }).join("");
}

function fillDocForm(d) {
  $("#docId").value = d.id; $("#docName").value = d.name;
  $("#docNumber").value = d.number || ""; $("#docIssuer").value = d.issuer || "";
  $("#docIssue").value = d.issue_date || ""; $("#docExpiry").value = d.expiry_date || "";
  $("#docNotes").value = d.notes || "";
  window.scrollTo({ top: 0, behavior: "smooth" });
}
function clearDocForm() {
  ["docId", "docName", "docNumber", "docIssuer", "docIssue", "docExpiry", "docNotes"]
    .forEach((id) => $("#" + id).value = "");
}

async function saveDoc() {
  const doc = {
    id: $("#docId").value ? Number($("#docId").value) : undefined,
    name: $("#docName").value.trim(),
    number: $("#docNumber").value.trim(),
    issuer: $("#docIssuer").value.trim(),
    issue_date: $("#docIssue").value,
    expiry_date: $("#docExpiry").value,
    notes: $("#docNotes").value.trim(),
  };
  if (!doc.name) return toast("اسم الوثيقة مطلوب", true);
  await api("/api/docs", { method: "POST", json: doc });
  toast("تم حفظ الوثيقة ✅");
  clearDocForm();
  loadDocs();
}

async function removeDoc(id) {
  if (!confirm("حذف هذه الوثيقة؟")) return;
  await api(`/api/docs/${id}`, { method: "DELETE" });
  loadDocs();
}

/* ---------- التحليلات ---------- */
async function loadAnalytics() {
  const a = await api("/api/analytics");
  const t = a.totals;
  $("#anCards").innerHTML = `
    <div class="card gold"><div class="num">${t.win_rate !== null ? t.win_rate + "%" : "—"}</div><div class="lbl">نسبة الفوز (من العروض المحسومة)</div></div>
    <div class="card"><div class="num">${fmt(t.won_value)}</div><div class="lbl">قيمة العروض الفائزة (ر.س)</div></div>
    <div class="card"><div class="num">${fmt(t.pipeline_value)}</div><div class="lbl">قيمة العروض قيد الانتظار (ر.س)</div></div>
    <div class="card"><div class="num">${t.by_status.won} / ${t.by_status.won + t.by_status.lost}</div><div class="lbl">فائز / محسوم</div></div>`;

  const m = a.margins;
  $("#anMargins").innerHTML = `
    <h3>مؤشر معايرة التسعير</h3>
    <div class="row" style="gap:26px">
      <div>متوسط هامش الربح في العروض <b style="color:var(--ok)">الفائزة</b>: <b>${m.avg_won_margin !== null ? m.avg_won_margin + "%" : "—"}</b></div>
      <div>متوسط هامش الربح في العروض <b style="color:#a33">الخاسرة</b>: <b>${m.avg_lost_margin !== null ? m.avg_lost_margin + "%" : "—"}</b></div>
    </div>
    <p class="muted mt" style="line-height:1.9">💡 ${m.hint}</p>`;

  const ENTITY_AR = { government: "جهات حكومية", private: "قطاع خاص" };
  $("#anEntityTable tbody").innerHTML = Object.entries(a.by_entity).map(([k, e]) => `
    <tr><td><b>${ENTITY_AR[k]}</b></td><td>${e.total}</td><td>${e.won}</td>
    <td>${e.win_rate !== null ? e.win_rate + "%" : "—"}</td>
    <td class="num-cell">${fmt(e.won_value)}</td></tr>`).join("");

  $("#anClientTable tbody").innerHTML = a.by_client.map((c) => `
    <tr><td>${c.client}</td><td>${c.total}</td><td>${c.won}</td><td>${c.lost}</td>
    <td>${c.win_rate !== null ? c.win_rate + "%" : "—"}</td>
    <td class="num-cell">${fmt(c.won_value)}</td></tr>`).join("") ||
    `<tr><td colspan="6" class="muted">لا توجد بيانات بعد</td></tr>`;
}

/* ---------- الإعدادات ---------- */
async function loadSettings() {
  const s = await api("/api/settings");
  $$("[data-key]").forEach((el) => { el.value = s[el.dataset.key] ?? ""; });
}

async function saveSettings() {
  const values = {};
  $$("[data-key]").forEach((el) => { values[el.dataset.key] = el.value; });
  await api("/api/settings", { method: "PUT", json: values });
  toast("تم حفظ الإعدادات ✅");
}

/* ---------- بدء التشغيل ---------- */
loadDashboard();
