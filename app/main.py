from fastapi import FastAPI, Request, Form, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, text
from datetime import datetime, date, time
import os, shutil
from jose import jwt, JWTError
from .db import Base, engine, SessionLocal
from . import models
from .security import hash_pw, verify_pw, make_token, SECRET, ALGO

# Ensure uploads folder exists
os.makedirs("uploads", exist_ok=True)

Base.metadata.create_all(bind=engine)
app = FastAPI(title='V-app (Voiceworx)')
app.mount('/uploads', StaticFiles(directory='uploads'), name='uploads')
templates = Jinja2Templates(directory='app/templates')

def get_db():
    d = SessionLocal()
    try:
        yield d
    finally:
        d.close()

def current_user(request: Request, d):
    token = request.cookies.get('t')
    if not token:
        return None
    try:
        email = jwt.decode(token, SECRET, algorithms=[ALGO]).get('sub')
    except JWTError:
        return None
    if not email:
        return None
    return d.execute(select(models.User).where(models.User.email == email)).scalar_one_or_none()

@app.get('/', response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse('home.html', {'request': request})

@app.get('/auth/register', response_class=HTMLResponse)
def reg_form(request: Request):
    return templates.TemplateResponse('register.html', {'request': request})

@app.post('/auth/register')
def reg(name: str = Form(...), email: str = Form(...), password: str = Form(...)):
    d = SessionLocal()
    try:
        # FIXED: do NOT wrap select() in text()
        existing = d.execute(select(models.User).where(models.User.email == email)).scalar_one_or_none()
        if existing:
            return RedirectResponse('/auth/login?e=exists', status_code=302)
        u = models.User(name=name, email=email, hashed_password=hash_pw(password))
        d.add(u)
        d.commit()
        return RedirectResponse('/auth/login?ok=1', status_code=302)
    finally:
        d.close()

@app.get('/auth/login', response_class=HTMLResponse)
def login_form(request: Request):
    return templates.TemplateResponse('login.html', {'request': request})

@app.post('/auth/login')
def login(email: str = Form(...), password: str = Form(...)):
    d = SessionLocal()
    try:
        u = d.execute(select(models.User).where(models.User.email == email)).scalar_one_or_none()
        if not u or not verify_pw(password, u.hashed_password):
            return RedirectResponse('/auth/login?e=1', status_code=302)
        resp = RedirectResponse('/dashboard', status_code=302)
        resp.set_cookie('t', make_token(u.email), httponly=True, samesite='lax')
        return resp
    finally:
        d.close()

def require_user(request: Request):
    d = SessionLocal()
    try:
        u = current_user(request, d)
        if not u:
            raise HTTPException(status_code=302, headers={'Location': '/auth/login'})
        return u
    finally:
        d.close()

@app.get('/dashboard', response_class=HTMLResponse)
def dash(request: Request):
    d = SessionLocal()
    try:
        u = current_user(request, d)
        if not u:
            return RedirectResponse('/auth/login', status_code=302)
        pts = d.execute(text('SELECT COALESCE(SUM(pts),0) FROM points WHERE user_id=:u'), {'u': u.id}).scalar()
        return templates.TemplateResponse('dashboard.html', {'request': request, 'user': u, 'points': int(pts or 0)})
    finally:
        d.close()

# Attendance
LATE_AFTER = time(10, 31)

def _month_late_and_paycut(d, user_id: int):
    late_count = d.execute(text(
        "SELECT COUNT(*) FROM attendance "
        "WHERE user_id=:u AND status='LATE' "
        "AND strftime('%Y-%m', date)=strftime('%Y-%m','now')"
    ), {'u': user_id}).scalar()
    late_count = int(late_count or 0)
    return late_count, late_count // 4

def _serialize_row(row):
    if not row: return None
    m = row._mapping
    r = {
        'date': str(m.get('date')) if m.get('date') else None,
        'check_in_ts': str(m.get('cin_ts')) if m.get('cin_ts') else None,
        'check_out_ts': str(m.get('cout_ts')) if m.get('cout_ts') else None,
        'check_in_photo': f"/{m.get('cin_photo')}" if m.get('cin_photo') else None,
        'check_out_photo': f"/{m.get('cout_photo')}" if m.get('cout_photo') else None,
        'status': m.get('status'),
    }
    # compute hours if both times present
    try:
        if r['check_in_ts'] and r['check_out_ts']:
            t1 = datetime.fromisoformat(r['check_in_ts'])
            t2 = datetime.fromisoformat(r['check_out_ts'])
            r['working_hours'] = round((t2 - t1).total_seconds() / 3600, 2)
        else:
            r['working_hours'] = None
    except Exception:
        r['working_hours'] = None
    return r

@app.get('/attendance/today')
def attendance_today(request: Request):
    u = require_user(request)
    d = SessionLocal()
    try:
        rec = d.execute(text('SELECT * FROM attendance WHERE user_id=:u AND date=:dt'),
                        {'u': u.id, 'dt': date.today()}).fetchone()
        record = _serialize_row(rec)
        late_count, paycut = _month_late_and_paycut(d, u.id)
        points_total = d.execute(text('SELECT COALESCE(SUM(pts),0) FROM points WHERE user_id=:u'),
                                 {'u': u.id}).scalar()
        return {'ok': True, 'record': record, 'late_count': late_count,
                'paycut_days': paycut, 'points_total': float(points_total or 0)}
    finally:
        d.close()


@app.get('/attendance', response_class=HTMLResponse)
def attendance_page(request: Request):
    u = require_user(request)
    return templates.TemplateResponse('attendance.html', {'request': request, 'user': u})

    try:
        rec = d.execute(text('SELECT * FROM attendance WHERE user_id=:u AND date=:dt'), {'u': u.id, 'dt': date.today()}).fetchone()
        late_count = d.execute(text("SELECT COUNT(*) FROM attendance WHERE user_id=:u AND status='LATE' AND strftime('%Y-%m', date)=strftime('%Y-%m','now')"), {'u': u.id}).scalar()
        paycut = late_count // 4
        return templates.TemplateResponse('attendance.html', {'request': request, 'user': u, 'rec': rec, 'late': late_count, 'paycut': paycut})
    finally:
        d.close()

@app.post('/attendance/checkin')
def checkin(request: Request, file: UploadFile = File(...), lat: float = Form(None), lng: float = Form(None)):
    u = require_user(request)
    os.makedirs('uploads/attendance', exist_ok=True)
    fn = f"uploads/attendance/{u.id}_{date.today().isoformat()}_in.jpg"
    with open(fn, 'wb') as f:
        shutil.copyfileobj(file.file, f)
    now = datetime.now()
    status = 'LATE' if now.time() >= LATE_AFTER and now.weekday() <= 5 else 'PRESENT'
    d = SessionLocal()
    try:
        d.execute(text(
            'INSERT OR REPLACE INTO attendance (id,user_id,date,cin_ts,cin_lat,cin_lng,cin_photo,status) '
            'VALUES ((SELECT id FROM attendance WHERE user_id=:u AND date=:dt),:u,:dt,:ts,:lat,:lng,:ph,:st)'
        ), {'u': u.id, 'dt': date.today(), 'ts': now, 'lat': lat, 'lng': lng, 'ph': fn, 'st': status})
        pts = -5 if status == 'LATE' else 10
        d.execute(text('INSERT INTO points (user_id,category,descr,pts,created_at) VALUES (:u,:c,:d,:p,:t)'),
                  {'u': u.id, 'c': 'ATTENDANCE', 'd': 'Check-in', 'p': pts, 't': now})
        d.commit()
        late_count, paycut = _month_late_and_paycut(d, u.id)
    finally:
        d.close()

    # If Accept: application/json present, return JSON for the JS UI
    if 'json' in (request.headers.get('accept') or '').lower():
        return {'ok': True, 'status': status, 'check_in_ts': now.isoformat(),
                'photo_url': f'/{fn}', 'points_awarded': pts,
                'late_count': late_count, 'paycut_days': paycut}
    # Fallback to redirect if someone posts from a plain form
    return RedirectResponse('/attendance?in=1', status_code=302)

@app.post('/attendance/checkout')
def checkout(request: Request, file: UploadFile = File(...), lat: float = Form(None), lng: float = Form(None)):
    u = require_user(request)
    os.makedirs('uploads/attendance', exist_ok=True)
    fn = f"uploads/attendance/{u.id}_{date.today().isoformat()}_out.jpg"
    with open(fn, 'wb') as f:
        shutil.copyfileobj(file.file, f)
    now = datetime.now()
    d = SessionLocal()
    try:
        d.execute(text(
            'UPDATE attendance SET cout_ts=:ts, cout_lat=:lat, cout_lng=:lng, cout_photo=:ph '
            'WHERE user_id=:u AND date=:dt'
        ), {'ts': now, 'lat': lat, 'lng': lng, 'ph': fn, 'u': u.id, 'dt': date.today()})
        d.execute(text('INSERT INTO points (user_id,category,descr,pts,created_at) VALUES (:u,:c,:d,:p,:t)'),
                  {'u': u.id, 'c': 'ATTENDANCE', 'd': 'Check-out', 'p': 10, 't': now})
        # compute hours
        rec = d.execute(text('SELECT cin_ts, cout_ts FROM attendance WHERE user_id=:u AND date=:dt'),
                        {'u': u.id, 'dt': date.today()}).fetchone()
        hours = None
        if rec and rec._mapping.get('cin_ts') and rec._mapping.get('cout_ts'):
            t1 = rec._mapping['cin_ts']; t2 = rec._mapping['cout_ts']
            # they come back as datetime objects from SQLite driver
            diff = (t2 - t1).total_seconds()
            hours = round(diff / 3600, 2)
        d.commit()
        late_count, paycut = _month_late_and_paycut(d, u.id)
    finally:
        d.close()

    if 'json' in (request.headers.get('accept') or '').lower():
        return {'ok': True, 'check_out_ts': now.isoformat(), 'photo_url': f'/{fn}',
                'working_hours': hours, 'points_awarded': 10,
                'late_count': late_count, 'paycut_days': paycut}
    return RedirectResponse('/attendance?out=1', status_code=302)




# Reports
@app.get('/reports', response_class=HTMLResponse)
def reports_page(request: Request):
    u = require_user(request)
    d = SessionLocal()
    try:
        rows = d.execute(text('SELECT report_date, summary FROM reports WHERE user_id=:u ORDER BY report_date DESC'), {'u': u.id}).fetchall()
        return templates.TemplateResponse('reports.html', {'request': request, 'user': u, 'rows': rows})
    finally:
        d.close()

@app.post('/reports/new')
def report_new(request: Request, report_date: str = Form(...), summary: str = Form(...)):
    u = require_user(request)
    d = SessionLocal()
    try:
        d.execute(text('INSERT INTO reports (user_id, report_date, summary, created_at) VALUES (:u,:d,:s,:t)'), {'u': u.id, 'd': report_date, 's': summary, 't': datetime.utcnow()})
        d.execute(text('INSERT INTO points (user_id,category,descr,pts,created_at) VALUES (:u,:c,:d,:p,:t)'), {'u': u.id, 'c': 'REPORT', 'd': 'Daily report', 'p': 10, 't': datetime.utcnow()})
        d.commit()
    finally:
        d.close()
    return RedirectResponse('/reports?ok=1', status_code=302)

# Recce
@app.get('/recce', response_class=HTMLResponse)
def recce_page(request: Request):
    u = require_user(request)
    return templates.TemplateResponse('recce.html', {'request': request, 'user': u})

@app.post('/recce/upload')
def recce_upload(request: Request, project: str = Form(None), notes: str = Form(None), file: UploadFile = File(...)):
    u = require_user(request)
    os.makedirs('uploads/recce', exist_ok=True)
    fn = f"uploads/recce/{u.id}_{int(datetime.utcnow().timestamp())}_{file.filename}"
    with open(fn, 'wb') as f:
        shutil.copyfileobj(file.file, f)
    d = SessionLocal()
    try:
        d.execute(text('INSERT INTO recce (user_id, uploaded_at, project, notes, filename) VALUES (:u,:t,:p,:n,:f)'), {'u': u.id, 't': datetime.utcnow(), 'p': project, 'n': notes, 'f': fn})
        d.execute(text('INSERT INTO points (user_id,category,descr,pts,created_at) VALUES (:u,:c,:d,:p,:t)'), {'u': u.id, 'c': 'RECCE', 'd': 'Recce upload', 'p': 15, 't': datetime.utcnow()})
        d.commit()
    finally:
        d.close()
    return RedirectResponse('/recce?ok=1', status_code=302)

# Admin leaderboard
@app.get('/admin', response_class=HTMLResponse)
def admin(request: Request):
    d = SessionLocal()
    try:
        u = current_user(request, d)
        if not u or u.role != 'admin':
            raise HTTPException(status_code=403, detail='Admin only')
        users = d.execute(text('SELECT id,name FROM users ORDER BY name')).fetchall()
        lb = []
        for row in users:
            pts = d.execute(text('SELECT COALESCE(SUM(pts),0) FROM points WHERE user_id=:u'), {'u': row.id}).scalar()
            lb.append((row, int(pts or 0)))
        lb.sort(key=lambda x: x[1], reverse=True)
        return templates.TemplateResponse('admin.html', {'request': request, 'user': u, 'lb': lb})
    finally:
        d.close()
