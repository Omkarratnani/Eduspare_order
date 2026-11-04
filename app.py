import os, sqlite3, uuid, secrets, smtplib, threading
from datetime import datetime
from decimal import Decimal, InvalidOperation
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from functools import wraps
from io import BytesIO
from flask import (Flask, render_template, request, redirect, url_for,
                   flash, session, send_from_directory, abort, make_response, Response)
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
from urllib.parse import quote as urlquote
import requests as http_requests

try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib import colors as rlc
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                    Table, TableStyle, HRFlowable)
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    REPORTLAB = True
except ImportError:
    REPORTLAB = False

BASE   = os.path.dirname(__file__)
IS_VERCEL = os.environ.get("VERCEL", "") == "1"
UPLOAD_DIR = os.path.join("/tmp", "uploads") if IS_VERCEL else os.path.join(BASE, "uploads")
app    = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(32))
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024
DB     = os.environ.get("DATABASE_PATH", "/tmp/eduspare.db" if IS_VERCEL else os.path.join(BASE, "eduspare.db"))
os.makedirs(UPLOAD_DIR, exist_ok=True)
UPI    = "computerbaazi@axl"
ADMIN_WA = "918839445039"
STATUSES = ["Requested","Payment Received","In Progress","Testing","Ready","Delivered","Cancelled"]
SITE_NAME = "EduSpare"

SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")
MAIL_FROM = os.environ.get("MAIL_FROM", SMTP_USER)
NEXTJS_URL = os.environ.get("NEXTJS_URL", "http://127.0.0.1:3000")

# ── Email helpers ─────────────────────────────────────────────────────────────
def send_email_async(to, subject, html):
    if not SMTP_USER or not SMTP_PASS:
        app.logger.warning("SMTP not configured - skipping email to %s", to)
        return
    def _send():
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = f"{SITE_NAME} <{MAIL_FROM}>"
            msg["To"] = to
            msg.attach(MIMEText(html, "html"))
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
                s.starttls()
                s.login(SMTP_USER, SMTP_PASS)
                s.sendmail(MAIL_FROM, [to], msg.as_string())
            app.logger.info("Email sent to %s", to)
        except Exception as e:
            app.logger.error("Email error: %s", e)
    if IS_VERCEL:
        _send()  # Vercel kills threads after response — must run synchronously
    else:
        threading.Thread(target=_send, daemon=True).start()

def _wrap_email(body_html, oid=""):
    footer = f"Order ID: <b>{oid}</b> &nbsp;|&nbsp; UPI: {UPI} &nbsp;|&nbsp; WhatsApp: +{ADMIN_WA}" if oid else ""
    return f"""<div style="font-family:sans-serif;max-width:600px;margin:auto;background:#0f0f1a;border-radius:12px;overflow:hidden">
  <div style="background:#1a0533;padding:24px;text-align:center;border-bottom:2px solid #7c3aed">
    <h1 style="color:#a78bfa;margin:0;font-size:1.5rem">EduSpare</h1>
    <p style="color:#64748b;margin:4px 0 0;font-size:.8rem">Project Studio</p>
  </div>
  <div style="padding:32px">{body_html}</div>
  <div style="background:#0a0a14;padding:16px;text-align:center;font-size:.78rem;color:#334155">{footer}</div>
</div>"""

def mail_order_confirmed(o, tracking_url):
    total, advance, balance = amounts(o)
    body = f"""<h2 style="color:#e2e8f0;margin:0 0 8px">Order Confirmed! &#127881;</h2>
<p style="color:#94a3b8">Hi <b style="color:#e2e8f0">{o["name"]}</b>, your project request has been received and your advance payment screenshot is under review.</p>
<div style="background:#1a1a2e;border-radius:8px;padding:18px;margin:18px 0;border:1px solid rgba(124,58,237,.25)">
  <p style="margin:4px 0;color:#94a3b8"><b style="color:#a78bfa">Project ID:</b> <span style="font-family:monospace;color:#fff;font-size:1.1em">{o["id"]}</span></p>
  <p style="margin:4px 0;color:#94a3b8"><b style="color:#a78bfa">Title:</b> {o["title"]}</p>
  <p style="margin:4px 0;color:#94a3b8"><b style="color:#a78bfa">Total Amount:</b> {money(total)}</p>
  <p style="margin:4px 0;color:#94a3b8"><b style="color:#a78bfa">50% Advance Paid:</b> {money(advance)}</p>
  <p style="margin:4px 0;color:#94a3b8"><b style="color:#a78bfa">Balance on Delivery:</b> {money(balance)}</p>
</div>
<p style="color:#94a3b8">You can download your project bill from the tracking page.</p>
<a href="{tracking_url}" style="display:inline-block;background:#7c3aed;color:#fff;padding:12px 28px;border-radius:8px;text-decoration:none;font-weight:600">Track &amp; Download Bill &#8594;</a>"""
    send_email_async(o["email"], f"[{SITE_NAME}] Order Confirmed - {o['id']}", _wrap_email(body, o["id"]))

def mail_status_update(o, new_status, admin_notes, tracking_url):
    note_row = f"<p style='margin:8px 0 0;color:#94a3b8'><b style='color:#a78bfa'>Update:</b> {admin_notes}</p>" if admin_notes else ""
    body = f"""<h2 style="color:#e2e8f0;margin:0 0 8px">Order Status Updated &#128276;</h2>
<p style="color:#94a3b8">Hi <b style="color:#e2e8f0">{o["name"]}</b>, your order has a new update.</p>
<div style="background:#1a1a2e;border-radius:8px;padding:18px;margin:18px 0;border:1px solid rgba(124,58,237,.25)">
  <p style="margin:0;color:#94a3b8"><b style="color:#a78bfa">New Status:</b> <span style="color:#fff;font-weight:700">{new_status}</span></p>
  {note_row}
</div>
<a href="{tracking_url}" style="display:inline-block;background:#7c3aed;color:#fff;padding:12px 28px;border-radius:8px;text-decoration:none;font-weight:600">View Timeline &amp; Download Bill &#8594;</a>"""
    send_email_async(o["email"], f"[{SITE_NAME}] Status Update: {new_status} - {o['id']}", _wrap_email(body, o["id"]))

# ── DB ────────────────────────────────────────────────────────────────────────
def db():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c

def init():
    with db() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS orders (
            id TEXT PRIMARY KEY, created TEXT, name TEXT, phone TEXT, email TEXT,
            category TEXT, title TEXT, description TEXT, delivery_type TEXT,
            deadline TEXT, urgent INTEGER DEFAULT 0, status TEXT, base_price INTEGER,
            advance_verified INTEGER DEFAULT 0, final_verified INTEGER DEFAULT 0,
            payment_ref TEXT, payment_file TEXT, quote_accepted INTEGER DEFAULT 0,
            admin_notes TEXT, order_payment_ref TEXT, order_payment_file TEXT
        )""")
        for col, defn in [("order_payment_ref","TEXT"),("order_payment_file","TEXT"),("urgent","INTEGER DEFAULT 0")]:
            try: c.execute(f"ALTER TABLE orders ADD COLUMN {col} {defn}")
            except: pass
        c.execute("""CREATE TABLE IF NOT EXISTS status_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id TEXT NOT NULL, status TEXT NOT NULL, note TEXT, ts TEXT NOT NULL
        )""")
        c.execute("CREATE TABLE IF NOT EXISTS admins (username TEXT PRIMARY KEY, password_hash TEXT NOT NULL)")
        if os.environ.get("ADMIN_PASSWORD") and not c.execute("SELECT 1 FROM admins").fetchone():
            c.execute("INSERT INTO admins VALUES (?,?)",(os.environ.get("ADMIN_USER","admin"),generate_password_hash(os.environ["ADMIN_PASSWORD"])))

# ── Helpers ───────────────────────────────────────────────────────────────────
def csrf():
    if "csrf" not in session: session["csrf"] = secrets.token_hex(24)
    return session["csrf"]
app.jinja_env.globals["csrf_token"] = csrf

@app.before_request
def protect():
    if request.method == "POST" and not secrets.compare_digest(request.form.get("csrf_token",""),csrf()): abort(400)

def admin_only(fn):
    @wraps(fn)
    def inner(*a,**kw):
        if not session.get("admin"): return redirect(url_for("login"))
        return fn(*a,**kw)
    return inner

def get_order(oid):
    with db() as c: return c.execute("SELECT * FROM orders WHERE id=?",(oid,)).fetchone()

def get_status_log(oid):
    with db() as c: return c.execute("SELECT * FROM status_log WHERE order_id=? ORDER BY ts ASC",(oid,)).fetchall()

def log_status(c, oid, status, note=""):
    c.execute("INSERT INTO status_log (order_id,status,note,ts) VALUES (?,?,?,?)",(oid,status,note,datetime.now().isoformat(timespec="minutes")))

def amounts(o):
    total = o["base_price"] or 0
    return total, total//2, total - total//2

def money(p): return f"Rs.{p/100:,.2f}"

ALLOWED_EXT = {".png",".jpg",".jpeg",".webp",".pdf"}
def save_upload(file):
    ext = os.path.splitext(secure_filename(file.filename))[1].lower()
    if ext not in ALLOWED_EXT: return None, "Unsupported file type (PNG/JPG/WEBP/PDF)."
    fn = uuid.uuid4().hex + ext
    file.save(os.path.join(UPLOAD_DIR, fn))
    return fn, None

# ── PDF Bill ──────────────────────────────────────────────────────────────────
def generate_bill_pdf(o):
    if not REPORTLAB: return None
    buf = BytesIO()
    total, advance, balance = amounts(o)
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            rightMargin=18*mm, leftMargin=18*mm,
                            topMargin=18*mm, bottomMargin=18*mm)
    st = getSampleStyleSheet()
    def sty(name, **kw):
        return ParagraphStyle(name, parent=st["Normal"], **kw)

    purple = rlc.HexColor("#a78bfa")
    dpurple = rlc.HexColor("#7c3aed")
    dark   = rlc.HexColor("#0f0f1a")
    dark2  = rlc.HexColor("#1a1a2e")
    slate  = rlc.HexColor("#94a3b8")
    white  = rlc.HexColor("#e2e8f0")
    line   = rlc.HexColor("#2d2d4e")
    amber  = rlc.HexColor("#f59e0b")

    elems = []

    # Brand header
    elems.append(Paragraph("EduSpare", sty("brand", fontSize=26, textColor=purple, fontName="Helvetica-Bold")))
    elems.append(Paragraph("Project Studio  |  Custom Electronics & Software", sty("sub", fontSize=9, textColor=slate)))
    elems.append(Spacer(1, 3*mm))
    elems.append(HRFlowable(width="100%", thickness=1.5, color=dpurple))
    elems.append(Spacer(1, 6*mm))

    # Invoice + date row
    row = [[
        Paragraph("PROJECT INVOICE", sty("inv", fontSize=16, fontName="Helvetica-Bold", textColor=white)),
        Paragraph(f"<b>Order ID:</b> {o['id']}<br/><b>Date:</b> {o['created'][:10]}<br/><b>Status:</b> {o['status']}",
                  sty("meta", fontSize=9, textColor=slate, alignment=2))
    ]]
    t = Table(row, colWidths=[95*mm, 80*mm])
    t.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"TOP")]))
    elems.append(t)
    elems.append(Spacer(1, 7*mm))

    # Bill to
    elems.append(Paragraph("BILL TO", sty("sec", fontSize=7, fontName="Helvetica-Bold", textColor=dpurple, spaceAfter=2)))
    elems.append(Paragraph(o["name"], sty("cname", fontSize=13, fontName="Helvetica-Bold", textColor=white)))
    elems.append(Paragraph(o["email"], sty("cmeta", fontSize=9, textColor=slate)))
    elems.append(Paragraph(o["phone"], sty("cmeta2", fontSize=9, textColor=slate)))
    elems.append(Spacer(1, 7*mm))

    # Project details table
    elems.append(Paragraph("PROJECT DETAILS", sty("sec2", fontSize=7, fontName="Helvetica-Bold", textColor=dpurple, spaceAfter=2)))
    desc_short = o["description"][:250] + ("..." if len(o["description"]) > 250 else "")
    pdata = [
        ["Title", o["title"]],
        ["Category", o["category"]],
        ["Delivery", o["delivery_type"]],
        ["Deadline", o["deadline"]],
        ["Description", desc_short],
    ]
    def cell(txt, bold=False):
        return Paragraph(txt, sty("c", fontSize=9, textColor=(purple if bold else slate), fontName=("Helvetica-Bold" if bold else "Helvetica")))
    prows = [[cell(r[0], True), cell(r[1])] for r in pdata]
    pt = Table(prows, colWidths=[38*mm, 137*mm])
    pt.setStyle(TableStyle([
        ("ROWBACKGROUNDS",(0,0),(-1,-1),[dark2, dark]),
        ("GRID",(0,0),(-1,-1),0.4,line),
        ("PADDING",(0,0),(-1,-1),5),
        ("VALIGN",(0,0),(-1,-1),"TOP"),
    ]))
    elems.append(pt)
    elems.append(Spacer(1, 7*mm))

    # Payment summary
    elems.append(Paragraph("PAYMENT SUMMARY", sty("sec3", fontSize=7, fontName="Helvetica-Bold", textColor=dpurple, spaceAfter=2)))
    pydata = [
        [Paragraph("<b>Description</b>", sty("ph", fontSize=9, textColor=purple, fontName="Helvetica-Bold")),
         Paragraph("<b>Amount</b>", sty("ph2", fontSize=9, textColor=purple, fontName="Helvetica-Bold", alignment=2))],
        [cell("Total Project Amount"), Paragraph(money(total), sty("am", fontSize=9, textColor=white, alignment=2))],
        [cell("50% Advance Paid"),     Paragraph(money(advance), sty("am2", fontSize=9, textColor=rlc.HexColor("#10b981"), alignment=2))],
        [Paragraph("<b>Balance Due on Delivery</b>", sty("bal", fontSize=9, fontName="Helvetica-Bold", textColor=amber)),
         Paragraph(f"<b>{money(balance)}</b>", sty("bal2", fontSize=9, fontName="Helvetica-Bold", textColor=amber, alignment=2))],
    ]
    pyt = Table(pydata, colWidths=[130*mm, 45*mm])
    pyt.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,0),rlc.HexColor("#1a0533")),
        ("ROWBACKGROUNDS",(0,1),(-1,-1),[dark2, dark]),
        ("GRID",(0,0),(-1,-1),0.4,line),
        ("PADDING",(0,0),(-1,-1),6),
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
    ]))
    elems.append(pyt)
    elems.append(Spacer(1, 6*mm))

    # Payment reference
    if o["order_payment_ref"]:
        elems.append(Paragraph("ADVANCE PAYMENT RECORD", sty("sec4", fontSize=7, fontName="Helvetica-Bold", textColor=dpurple, spaceAfter=2)))
        rdata = [
            [cell("UPI Reference", True), cell(o["order_payment_ref"] or "N/A")],
            [cell("Amount Paid", True), cell(money(advance))],
            [cell("Proof", True), cell("Screenshot uploaded at submission")],
        ]
        rt = Table(rdata, colWidths=[45*mm, 130*mm])
        rt.setStyle(TableStyle([
            ("ROWBACKGROUNDS",(0,0),(-1,-1),[dark2, dark]),
            ("GRID",(0,0),(-1,-1),0.4,line),
            ("PADDING",(0,0),(-1,-1),5),
        ]))
        elems.append(rt)

    elems.append(Spacer(1, 10*mm))
    elems.append(HRFlowable(width="100%", thickness=0.5, color=line))
    elems.append(Spacer(1, 4*mm))
    foot = sty("foot", fontSize=8, textColor=rlc.HexColor("#475569"), alignment=1)
    elems.append(Paragraph(f"Thank you for choosing EduSpare!  |  UPI: {UPI}  |  WhatsApp: +{ADMIN_WA}", foot))
    elems.append(Paragraph("This is a computer-generated document. No signature required.", foot))

    doc.build(elems)
    buf.seek(0)
    return buf

# ── Globals ───────────────────────────────────────────────────────────────────
app.jinja_env.globals.update(money=money, amounts=amounts, upi=UPI, statuses=STATUSES, admin_wa=ADMIN_WA)

# ── Routes ────────────────────────────────────────────────────────────────────
@app.get("/")
def home(): return render_template("home.html")

# ── Solutions proxy ───────────────────────────────────────────────────────────
@app.route("/solutions", defaults={"path": ""})
@app.route("/solutions/<path:path>")
def solutions_proxy(path):
    """Reverse-proxy requests under /solutions/* to the Next.js dev server."""
    target = f"{NEXTJS_URL}/{path}"
    if request.query_string:
        target = f"{target}?{request.query_string.decode()}"
    try:
        resp = http_requests.request(
            method=request.method,
            url=target,
            headers={k: v for k, v in request.headers if k.lower() != "host"},
            data=request.get_data(),
            cookies=request.cookies,
            allow_redirects=True,
            stream=True,
            timeout=15,
        )
        excluded = {"content-encoding", "content-length", "transfer-encoding", "connection"}
        headers = [(name, value) for name, value in resp.raw.headers.items()
                   if name.lower() not in excluded]
        return Response(resp.content, resp.status_code, headers)
    except http_requests.exceptions.ConnectionError:
        return Response(
            "<h1>Solutions site is starting up...</h1>"
            "<p>The Next.js server is not running yet. Please start it with <code>npm run dev</code> "
            "inside the eduspare-solutions folder, then refresh.</p>",
            503, {"Content-Type": "text/html"})

@app.route("/order", methods=["GET","POST"])
def order():
    if request.method == "POST":
        fields = {k: request.form.get(k,"").strip()
                  for k in ["name","phone","email","category","title","description","delivery_type","deadline"]}
        if not all(fields.values()) or len(fields["description"]) > 5000:
            flash("Please complete all fields (description max 5000 chars).")
            return redirect(url_for("order"))
        # Discussed amount
        try:
            discussed = Decimal(request.form.get("discussed_amount","0").replace(",",""))
            if not discussed.is_finite() or discussed <= 0: raise InvalidOperation()
            base_price_paise = int(discussed * 100)
        except (InvalidOperation, ValueError):
            flash("Please enter the amount discussed with our team (must be > 0).")
            return redirect(url_for("order"))
        # Payment proof
        proof_file = request.files.get("order_proof")
        ref = request.form.get("order_ref","").strip()
        if not ref or not proof_file or not proof_file.filename:
            flash("UPI reference and payment screenshot are required to submit.")
            return redirect(url_for("order"))
        filename, err = save_upload(proof_file)
        if err:
            flash(err); return redirect(url_for("order"))
        oid = "EDU-" + datetime.now().strftime("%y%m") + "-" + uuid.uuid4().hex[:7].upper()
        with db() as c:
            c.execute("""INSERT INTO orders
                (id,created,name,phone,email,category,title,description,
                 delivery_type,deadline,urgent,status,base_price,
                 order_payment_ref,order_payment_file)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (oid, datetime.now().isoformat(timespec="minutes"),
                 *fields.values(), 0, "Requested", base_price_paise, ref, filename))
            log_status(c, oid, "Requested", "Order submitted with advance payment screenshot.")
        session["customer_"+oid] = True
        mail_order_confirmed(get_order(oid), url_for("track",oid=oid,_external=True))
        flash(f"Order placed! Your Project ID is {oid}. Confirmation email sent.")
        return redirect(url_for("track", oid=oid, new="1"))
    return render_template("order.html")

@app.route("/track/<oid>", methods=["GET","POST"])
def track(oid):
    o = get_order(oid)
    if not o: abort(404)
    if not session.get("admin") and not session.get("customer_"+oid):
        if request.method != "POST" or request.form.get("phone","").strip() != o["phone"]:
            return render_template("verify.html", oid=oid, error=request.method=="POST")
        session["customer_"+oid] = True
    if request.method == "POST":
        action = request.form.get("action")
        if action == "accept" and o["status"] == "Quoted":
            with db() as c:
                c.execute("UPDATE orders SET quote_accepted=1,status='Awaiting Advance' WHERE id=?",(oid,))
                log_status(c, oid, "Awaiting Advance", "Customer accepted the quotation.")
        elif action == "payment" and o["quote_accepted"] and o["status"] in ["Awaiting Advance","Payment Review"]:
            file = request.files.get("proof")
            ref  = request.form.get("reference","").strip()
            if not ref or not file or not file.filename:
                flash("Reference and screenshot required."); return redirect(url_for("track",oid=oid))
            filename, err = save_upload(file)
            if err:
                flash(err); return redirect(url_for("track",oid=oid))
            with db() as c:
                c.execute("UPDATE orders SET payment_ref=?,payment_file=?,status='Payment Review' WHERE id=?",(ref,filename,oid))
                log_status(c, oid, "Payment Review", "Advance payment proof submitted.")
        return redirect(url_for("track",oid=oid))
    o = get_order(oid)
    log_entries = get_status_log(oid)
    total, advance, balance = amounts(o)
    wa_admin_msg = urlquote(
        f"New EduSpare Order!\nOrder ID: {o['id']}\nCustomer: {o['name']}\nProject: {o['title']}\n"
        f"Amount: {money(total)}  |  Advance: {money(advance)}\n"
        f"Track: {url_for('track',oid=oid,_external=True)}"
    )
    wa_msg = urlquote(f"Hello EduSpare, regarding my order {oid} - {o['title']}.")
    new_order = request.args.get("new") == "1"
    return render_template("track.html", o=o, log=log_entries,
                           total=total, advance=advance, balance=balance,
                           wa=f"https://wa.me/{ADMIN_WA}?text={wa_msg}",
                           wa_admin=f"https://wa.me/{ADMIN_WA}?text={wa_admin_msg}",
                           new_order=new_order,
                           has_bill=bool(o["base_price"]))

@app.get("/bill/<oid>")
def bill(oid):
    o = get_order(oid)
    if not o: abort(404)
    if not session.get("admin") and not session.get("customer_"+oid): abort(403)
    if not REPORTLAB:
        flash("PDF generation unavailable (reportlab not installed).")
        return redirect(url_for("track",oid=oid))
    buf = generate_bill_pdf(o)
    if not buf:
        flash("Error generating bill."); return redirect(url_for("track",oid=oid))
    resp = make_response(buf.read())
    resp.headers["Content-Type"] = "application/pdf"
    resp.headers["Content-Disposition"] = f"attachment; filename=EduSpare-{oid}.pdf"
    return resp

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        with db() as c: a = c.execute("SELECT * FROM admins WHERE username=?",(request.form.get("username"),)).fetchone()
        if a and check_password_hash(a["password_hash"],request.form.get("password","")):
            session["admin"] = True; return redirect(url_for("admin"))
        flash("Invalid credentials")
    return render_template("login.html")

@app.get("/logout")
def logout(): session.clear(); return redirect(url_for("home"))

@app.get("/admin")
@admin_only
def admin():
    with db() as c: orders = c.execute("SELECT * FROM orders ORDER BY created DESC").fetchall()
    return render_template("admin.html", orders=orders)

@app.route("/admin/<oid>", methods=["GET","POST"])
@admin_only
def manage(oid):
    o = get_order(oid)
    if not o: abort(404)
    if request.method == "POST":
        status = request.form.get("status")
        if status not in STATUSES: abort(400)
        try:
            price = Decimal(request.form.get("base_price","0"))
            if not price.is_finite() or price < 0 or price > 10000000: raise InvalidOperation()
            paise = int(price * 100)
        except (InvalidOperation, ValueError):
            flash("Invalid price"); return redirect(url_for("manage",oid=oid))
        verified = int(request.form.get("advance_verified") == "yes")
        final    = int(request.form.get("final_verified") == "yes")
        if status in ["In Progress","Testing","Ready","Delivered"] and not verified:
            flash("Verify advance before starting."); return redirect(url_for("manage",oid=oid))
        if status == "Delivered" and not final:
            flash("Verify final payment before marking Delivered."); return redirect(url_for("manage",oid=oid))
        notes = request.form.get("admin_notes","")[:2000]
        old_status = o["status"]
        with db() as c:
            c.execute("UPDATE orders SET status=?,base_price=?,advance_verified=?,final_verified=?,admin_notes=? WHERE id=?",(status,paise,verified,final,notes,oid))
            if status != old_status: log_status(c, oid, status, notes)
        if status != old_status:
            mail_status_update(get_order(oid), status, notes, url_for("track",oid=oid,_external=True))
        flash("Order updated — customer notified by email."); return redirect(url_for("manage",oid=oid))
    return render_template("manage.html", o=o, log=get_status_log(oid))

@app.get("/admin/proof/<oid>")
@admin_only
def proof(oid):
    o = get_order(oid)
    if not o or not o["payment_file"]: abort(404)
    return send_from_directory(UPLOAD_DIR, o["payment_file"], as_attachment=True)

@app.get("/admin/order-proof/<oid>")
@admin_only
def order_proof(oid):
    o = get_order(oid)
    if not o or not o["order_payment_file"]: abort(404)
    return send_from_directory(UPLOAD_DIR, o["order_payment_file"], as_attachment=True)

init()
if __name__ == "__main__": app.run(debug=os.environ.get("FLASK_DEBUG")=="1")
