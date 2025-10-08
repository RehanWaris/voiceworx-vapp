from passlib.context import CryptContext
from datetime import datetime, timedelta
from jose import jwt
SECRET='CHANGE_ME'
ALGO='HS256'
EXP_MIN=60*24*7
pwd=CryptContext(schemes=['bcrypt'], deprecated='auto')
def hash_pw(p): return pwd.hash(p)
def verify_pw(p,h): return pwd.verify(p,h)
def make_token(email): return jwt.encode({'sub':email,'exp':datetime.utcnow()+timedelta(minutes=EXP_MIN)}, SECRET, algorithm=ALGO)
