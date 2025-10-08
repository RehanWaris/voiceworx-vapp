from sqlalchemy import Column,Integer,String,Date,DateTime,Float,Text,ForeignKey
from datetime import datetime
from .db import Base
class User(Base):
    __tablename__='users'
    id=Column(Integer, primary_key=True); name=Column(String); email=Column(String, unique=True); hashed_password=Column(String); role=Column(String, default='employee')
class Points(Base):
    __tablename__='points'
    id=Column(Integer, primary_key=True); user_id=Column(Integer); category=Column(String); descr=Column(Text); pts=Column(Float); created_at=Column(DateTime, default=datetime.utcnow)
class Attendance(Base):
    __tablename__='attendance'
    id=Column(Integer, primary_key=True); user_id=Column(Integer); date=Column(Date); cin_ts=Column(DateTime); cin_lat=Column(Float); cin_lng=Column(Float); cin_photo=Column(String); cout_ts=Column(DateTime); cout_lat=Column(Float); cout_lng=Column(Float); cout_photo=Column(String); status=Column(String)
class Report(Base):
    __tablename__='reports'
    id=Column(Integer, primary_key=True); user_id=Column(Integer); report_date=Column(Date); summary=Column(Text); created_at=Column(DateTime, default=datetime.utcnow)
class Recce(Base):
    __tablename__='recce'
    id=Column(Integer, primary_key=True); user_id=Column(Integer); uploaded_at=Column(DateTime, default=datetime.utcnow); project=Column(String); notes=Column(Text); filename=Column(String)
