from sqlalchemy import Column, Integer, String, Float, DateTime, Date, ForeignKey
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String)
    email = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    role = Column(String, default="user")  # "user" or "admin"

class Attendance(Base):
    __tablename__ = "attendance"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    date = Column(Date)
    cin_ts = Column(DateTime)
    cout_ts = Column(DateTime)
    cin_lat = Column(Float)
    cin_lng = Column(Float)
    cout_lat = Column(Float)
    cout_lng = Column(Float)
    cin_photo = Column(String)
    cout_photo = Column(String)
    status = Column(String)  # PRESENT / LATE
    # NEW:
    cin_remark = Column(String)
    cout_remark = Column(String)

class Report(Base):
    __tablename__ = "reports"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    report_date = Column(Date)
    summary = Column(String)
    created_at = Column(DateTime)

class Recce(Base):
    __tablename__ = "recce"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    uploaded_at = Column(DateTime)
    project = Column(String)
    notes = Column(String)
    filename = Column(String)

class Points(Base):
    __tablename__ = "points"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    category = Column(String)   # ATTENDANCE / REPORT / RECCE / etc
    descr = Column(String)
    pts = Column(Integer)
    created_at = Column(DateTime)
