from fastapi import FastAPI, Request, Form, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, text
from datetime import datetime, date, time
from jose import jwt, JWTError
import os, shutil

from .db import Base, engine, SessionLocal
from . import models
from .security import hash_pw, verify_pw, make_token, SECRET, ALGO

# -----------------------------------------------------------------------------
# Setup
# -----------------------------------------------------------------------------
os.makedirs("uploads", exist_ok=True)
Base.metadata.create_all(bind=engine)

app = FastAPI(title="V-app (Voiceworx)")
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")
templates = Jinja2Templates(directory="app/templates")


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def get_db():
    d = SessionLocal()
    try:
        yield d
    finally:
        d.close()


def current_user(request: Request, d):
    token = request.cookies.get("t")
    if not token:
        return None
    try:
        email = jwt.decode(token, SECRET, algorithms=[ALGO]).get("sub")
    except JWTError:
        return None
    if not email:
        return None
    return d.execute(select(models.User).where(models.User.email == email)).scalar_one_or_none()


def require_user(request: Request):
    d = SessionLocal()
    try:
        u = current_user(request, d)
        if not u:
            raise HTTPException(status_code=302, headers={"Location": "/auth/login"})
        return u
    finally:
        d.close()


# -----------------------------------------------------------------------------
# Routes: Home / Auth
# -----------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse("home.html", {"request": request})


@app.get("/auth/register", response_class=HTMLResponse)
def reg_form(request: Request):
    return templates.TemplateResponse("register.html", {"request": request})


@app.post("/auth/register")
def reg(name: str = Form(...), email: str = Form(...), password: str = Form(...)):
    d = SessionLocal()
    try:
        existing = d.execute(select(models.User).where(models.User.email == email)).scalar_one_or_none()
        if existing:
            return RedirectResponse("/auth/login?e=exists", status_code=302)
        u = models.User(name=name, email=email, hashed_password=hash_pw(password))
        d.add(u)
        d.commit()
        return RedirectResponse("/auth/login?ok=1", status_code=302)
    finally:
        d.close()


@app.get("/auth/login", response_class=HTMLResponse)
def login_form(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@app.post("/auth/login")
def login(email: str = Form(...), password: str = Form(...)):
    d = SessionLocal()
    try:
        u = d.execute(select(models.User).where(models.User.email == email)).scalar_one_or_none()
        if not u or not verify_pw(password, u.hashed_password):
            return RedirectResponse("/auth/login?e=1", status_code=302)
        resp = RedirectResponse("/dashboard", status_code=302)
        resp.set_cookie("t", make_token(u.email), httponly=True, samesite="lax")
        return resp
    finally:
        d.close()


# -----------------------------------------------------------------------------
# Dashboard
# -----------------------------------------------------------------------------
@app.get("/dashboard", response_class=HTMLResponse)
def dash(request: Request):
    d = SessionLocal()
    try:
        u = current_user(request, d)
        if not u:
            return RedirectResponse("/auth/login", status_code=302)
        pts = d.execute(text("SELECT COALESCE(SUM(pts),0) FROM points WHERE user_id=:u"), {"u": u.id}).scalar()
        return templates.TemplateResponse("dashboard.html", {"request": request, "user": u, "points": int(pts or 0)})
    finally:
        d.close()


# -----------------------------------------------------------------------------
# Attendance
# -----------------------------------------------------------------------------
LATE_AFTER = time(10, 31)


def _month_late_and_paycut(d, user_id: int):
    late_count = d.execute(
        text(
            "SELECT COUNT(*) FROM attendance "
            "WHERE user_id=:u AND status='LATE' "
            "AND strftime('%Y-%m', date)=strftime('%Y-%m','now')"
        ),
        {"u": user_id},
    ).scalar()
    late_count = int(late_count or 0)
    return late_count, late_count // 4


def _serialize_row(row):
    if not row:
        return None
    m = row._mapping
    r = {
        "date": str(m.get("date")) if m.get("date") else None,
        "check_in_ts": str(m.get("cin_ts")) if m.get("cin_ts") else None,
        "check_out_ts": str(m.get("cout_ts")) if m.get("cout_ts") else None,
        "check_in_photo": f"/{m.get('cin_photo')}" if m.get("cin_photo") else None,
        "check_out_photo": f"/{m.get('cout_photo')}" if m.get("cout_photo") else None,
        "status": m.get("status"),
    }
    try:
        if r["check_in_ts"] and r["check_out_ts"]:
            t1 = datetime.fromisoformat(r["check_in_ts"])
            t2 = datetime.fromisoformat(r["check_out_ts"])
            r["working_hours"] = round((t2 - t1).total_seconds() / 3600, 2)
        else:
            r["working_hours"] = None
    except Exception:
        r["working_hours"] = None
    return r


@app.get("/attendance", response_class=HTMLResponse)
def attendance_page(request: Request):
    u = require_user(request)
    return templates.TemplateResponse("attendance.html", {"request": request, "user": u})


@app.get("/attendance/today")
def attendance_today(request: Request):
    u = require_user(request)
    d = SessionLocal()
    try:
        rec = d.execute(text("SELECT * FROM attendance WHERE user_id=:u AND date=:dt"), {"u": u.id, "dt": date.today()}).fetchone()
        record = _serialize_row(rec)
        late_count, paycut = _month_late_and_paycut(d, u.id)
        points_total = d.execute(text("SELECT COALESCE(SUM(pts),0) FROM points WHERE user_id=:u"), {"u": u.id}).scalar()
        return {
            "ok": True,
            "record": record,
            "late_count": late_count,
            "paycut_days": paycut,
            "points_total": float(points_total or 0),
        }
    finally:
        d.close()


@app.post("/attendance/checkin")
def checkin(request: Request, file: UploadFile = File(...), lat: float = Form(None), lng: float = Form(None)):
    u = require_user(request)
    os.makedirs("uploads/attendance", exist_ok=True)
    fn = f"uploads/attendance/{u.id}_{date.today().isoformat()}_in.jpg"
    with open(fn, "wb") as f:
        shutil.copyfileobj(file.file, f)
    now = datetime.now()
    status = "LATE" if now.time() >= LATE_AFTER and now.weekday() <= 5 else "PRESENT"
    d = SessionLocal()
    try:
        d.execute(
            text(
                "INSERT OR REPLACE INTO attendance (id,user_id,date,cin_ts,cin_lat,cin_lng,cin_photo,status) "
                "VALUES ((SELECT id FROM attendance WHERE user_id=:u AND date=:dt),:u,:dt,:ts,:lat,:lng,:ph,:st)"
            ),
            {"u": u.id, "dt": date.today(), "ts": now, "lat": lat, "lng": lng, "ph": fn, "st": status},
        )
        pts = -5 if status == "LATE" else 10
        d.execute(
            text("INSERT INTO points (user_id,category,descr,pts,created_at) VALUES (:u,:c,:d,:p,:t)"),
            {"u": u.id, "c": "ATTENDANCE", "d": "Check-in", "p": pts, "t": now},
        )
        d.commit()
        late_count, paycut = _month_late_and_paycut(d, u.id)
    finally:
        d.close()

    if "json" in (request.headers.get("accept") or "").lower():
        return {
            "ok": True,
            "status": status,
            "check_in_ts": now.isoformat(),
            "photo_url": f"/{fn}",
            "points_awarded": pts,
            "late_count": late_count,
            "paycut_days": paycut,
        }
    return RedirectResponse("/attendance?in=1", status_code=302)


@app.post("/attendance/checkout")
def checkout(request: Request, file: UploadFile = File(...), lat: float = Form(None), lng: float = Form(None)):
    u = require_user(request)
    os.makedirs("uploads/attendance", exist_ok=True)
    fn = f"uploads/attendance/{u.id}_{date.today().isoformat()}_out.jpg"
    with open(fn, "wb") as f:
        shutil.copyfileobj(file.file, f)
    now = datetime.now()
    d = SessionLocal()
    try:
        d.execute(
            text(
                "UPDATE attendance SET cout_ts=:ts, cout_lat=:lat, cout_lng=:lng, cout_photo=:ph "
                "WHERE user_id=:u AND date=:dt"
            ),
            {"ts": now, "lat": lat, "lng": lng, "ph": fn, "u": u.id, "dt": date.today()},
        )
        d.execute(
            text("INSERT INTO points (user_id,category,descr,pts,created_at) VALUES (:u,:c,:d,:p,:t)"),
            {"u": u.id, "c": "ATTENDANCE", "d": "Check-out", "p": 10, "t": now},
        )
        rec = d.execute(text("SELECT cin_ts, cout_ts FROM attendance WHERE user_id=:u AND date=:dt"), {"u": u.id, "dt": date.today()}).fetchone()
        hours = None
        if rec and rec._mapping.get("cin_ts") and rec._mapping.get("cout_ts"):
            t1 = rec._mapping["cin_ts"]
            t2 = rec._mapping["cout_ts"]
            diff = (t2 - t1).total_seconds()
            hours = round(diff / 3600, 2)
        d.commit()
        late_count, paycut = _month_late_and_paycut(d, u.id)
    finally:
        d.close()

    if "json" in (request.headers.get("accept") or "").lower():
        return {
            "ok": True,
            "check_out_ts": now.isoformat(),
            "photo_url": f"/{fn}",
            "working_hours": hours,
            "points_awarded": 10,
            "late_count": late_count,
            "paycut_days": paycut,
        }
    return RedirectResponse("/attendance?out=1", status_code=302)


# -----------------------------------------------------------------------------
# Reports
# -----------------------------------------------------------------------------
@app.get("/reports", response_class=HTMLResponse)
def reports_page(request: Request):
    u = require_user(request)
    d = SessionLocal()
    try:
        rows = d.execute(text("SELECT report_date, summary FROM reports WHERE user_id=:u ORDER BY report_date DESC"), {"u": u.id}).fetchall()
        return templates.TemplateResponse("reports.html", {"request": request, "user": u, "rows": rows})
    finally:
        d.close()


@app.post("/reports/new")
def report_new(request: Request, report_date: str = Form(...), summary: str = Form(...)):
    u = require_user(request)
    d = SessionLocal()
    try:
        d.execute(
            text("INSERT INTO reports (user_id, report_date, summary, created_at) VALUES (:u,:d,:s,:t)"),
            {"u": u.id, "d": report_date, "s": summary, "t": datetime.utcnow()},
        )
        d.execute(
            text("INSERT INTO points (user_id,category,descr,pts,created_at) VALUES (:u,:c,:d,:p,:t)"),
            {"u": u.id, "c": "REPORT", "d": "Daily report", "p": 10, "t": datetime.utcnow()},
        )
        d.commit()
    finally:
        d.close()
    return RedirectResponse("/reports?ok=1", status_code=302)


# -----------------------------------------------------------------------------
# Recce Uploads
# -----------------------------------------------------------------------------
@app.get("/recce", response_class=HTMLResponse)
def recce_page(request: Request):
    u = require_user(request)
    return templates.TemplateResponse("recce.html", {"request": request, "user": u})


@app.post("/recce/upload")
def recce_upload(request: Request, project: str = Form(None), notes: str = Form(None), file: UploadFile = File(...)):
    u = require_user(request)
    os.makedirs("uploads/recce", exist_ok=True)
    fn = f"uploads/recce/{u.id}_{int(datetime.utcnow().timestamp())}_{file.filename}"
    with open(fn, "wb") as f:
        shutil.copyfileobj(file.file, f)
    d = SessionLocal()
    try:
        d.execute(
            text("INSERT INTO recce (user_id, uploaded_at, project, notes, filename) VALUES (:u,:t,:p,:n,:f)"),
            {"u": u.id, "t": datetime.utcnow(), "p": project, "n": notes, "f": fn},
        )
        d.execute(
            text("INSERT INTO points (user_id,category,descr,pts,created_at) VALUES (:u,:c,:d,:p,:t)"),
            {"u": u.id, "c": "RECCE", "d": "Recce upload", "p": 15, "t": datetime.utcnow()},
        )
        d.commit()
    finally:
        d.close()
    return RedirectResponse("/recce?ok=1", status_code=302)


# -----------------------------------------------------------------------------
# Admin Leaderboard
# -----------------------------------------------------------------------------
@app.get("/admin", response_class=HTMLResponse)
def admin(request: Request):
    d = SessionLocal()
    try:
        u = current_user(request, d)
        if not u or u.role != "admin":
            raise HTTPException(status_code=403, detail="Admin only")
        users = d.execute(text("SELECT id,name FROM users ORDER BY name")).fetchall()
        lb = []
        for row in users:
            pts = d.execute(text("SELECT COALESCE(SUM(pts),0) FROM points WHERE user_id=:u"), {"u": row.id}).scalar()
            lb.append((row, int(pts or 0)))
        lb.sort(key=lambda x: x[1], reverse=True)
        return templates.TemplateResponse("admin.html", {"request": request, "user": u, "lb": lb})
    finally:
        d.close()

# -----------------------------------------------------------------------------
# Admin Attendance Dashboard
# -----------------------------------------------------------------------------
from fastapi.responses import FileResponse
import csv, io

@app.get("/admin/attendance", response_class=HTMLResponse)
def admin_attendance(request: Request, dt: str = None):
    u = require_user(request)
    if u.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")

    d = SessionLocal()
    try:
        if not dt:
            dt = date.today().isoformat()
        rows = d.execute(text("""
            SELECT a.date, u.name, u.email, 
                   a.cin_ts, a.cout_ts, a.status, 
                   a.cin_photo, a.cout_photo,
                   a.cin_lat, a.cin_lng, a.cout_lat, a.cout_lng
            FROM attendance a
            JOIN users u ON a.user_id = u.id
            WHERE a.date = :dt
            ORDER BY u.name
        """), {"dt": dt}).fetchall()

        data = []
        for r in rows:
            m = r._mapping
            hrs = None
            if m.get("cin_ts") and m.get("cout_ts"):
                t1, t2 = m["cin_ts"], m["cout_ts"]
                hrs = round((t2 - t1).total_seconds() / 3600, 2)
            data.append({
                "name": m["name"], "email": m["email"],
                "status": m["status"], "date": str(m["date"]),
                "cin": str(m["cin_ts"] or ""), "cout": str(m["cout_ts"] or ""),
                "hrs": hrs,
                "cin_photo": f"/{m['cin_photo']}" if m["cin_photo"] else None,
                "cout_photo": f"/{m['cout_photo']}" if m["cout_photo"] else None,
                "cin_lat": m["cin_lat"], "cin_lng": m["cin_lng"],
                "cout_lat": m["cout_lat"], "cout_lng": m["cout_lng"]
            })

        return templates.TemplateResponse("admin_attendance.html",
            {"request": request, "user": u, "date": dt, "rows": data})
    finally:
        d.close()


@app.get("/admin/attendance/export")
def admin_attendance_export(request: Request, dt: str = None):
    u = require_user(request)
    if u.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")

    if not dt:
        dt = date.today().isoformat()
    d = SessionLocal()
    try:
        rows = d.execute(text("""
            SELECT u.name, u.email, a.date, a.status, a.cin_ts, a.cout_ts,
                   a.cin_lat, a.cin_lng, a.cout_lat, a.cout_lng
            FROM attendance a
            JOIN users u ON a.user_id = u.id
            WHERE a.date = :dt
            ORDER BY u.name
        """), {"dt": dt}).fetchall()
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Name", "Email", "Date", "Status",
                         "Check-in Time", "Check-out Time",
                         "Check-in Lat", "Check-in Lng",
                         "Check-out Lat", "Check-out Lng"])
        for r in rows:
            m = r._mapping
            writer.writerow([
                m["name"], m["email"], m["date"], m["status"],
                m["cin_ts"], m["cout_ts"],
                m["cin_lat"], m["cin_lng"],
                m["cout_lat"], m["cout_lng"]
            ])
        output.seek(0)
        return FileResponse(io.BytesIO(output.getvalue().encode()),
                            media_type='text/csv',
                            filename=f"attendance_{dt}.csv")
    finally:
        d.close()

