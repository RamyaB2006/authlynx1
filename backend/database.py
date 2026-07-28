from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# PostgreSQL connection string
# Update 'postgres' and 'password' with your actual PostgreSQL credentials
SQLALCHEMY_DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/authlynx1"

engine = create_engine(SQLALCHEMY_DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()