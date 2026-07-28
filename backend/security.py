from passlib.context import CryptContext
import jwt
from datetime import datetime, timedelta

# Requires bcrypt<4.0.0
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
SECRET_KEY = "authlynx_super_secret_key"
ALGORITHM = "HS256"

def hash_mpin(mpin: str) -> str:
    return pwd_context.hash(mpin)

def verify_mpin(plain_mpin: str, hashed_mpin: str) -> bool:
    return pwd_context.verify(plain_mpin, hashed_mpin)

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=60)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt