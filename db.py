from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
engine=create_engine('sqlite:///./vapp.db', connect_args={'check_same_thread': False})
SessionLocal=sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base=declarative_base()
