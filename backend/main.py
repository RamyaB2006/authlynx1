import os
import cv2
import numpy as np
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from scipy.spatial.distance import cosine
from pydantic import BaseModel

import security  # type: ignore
from database import get_db, engine, Base  # type: ignore
from models import User, FaceEmbedding, VoiceProfile, BankAccount  # type: ignore
from ai_engine import AIEngine  # type: ignore

Base.metadata.create_all(bind=engine)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

ai_engine = AIEngine()

class TransferRequest(BaseModel):
    from_account: str
    to_account: str
    amount: float

@app.post("/register")
async def register(
    full_name: str = Form(...),
    customer_id: str = Form(...),
    mpin: str = Form(...),
    role: str = Form("Account Holder"),
    frame: UploadFile = File(...),
    audio: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    existing = db.query(User).filter(User.customer_id == customer_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="Customer ID already registered")

    frame_bytes = await frame.read()
    nparr = np.frombuffer(frame_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

    face_embedding = ai_engine.extract_face_embedding(img)
    if not face_embedding:
        raise HTTPException(status_code=400, detail="No face detected. Please ensure your face is clearly visible.")

    audio_bytes = await audio.read()
    voice_features = ai_engine.extract_voice_features(audio_bytes)

    user = User(
        full_name=full_name,
        customer_id=customer_id,
        mpin_hash=security.hash_mpin(mpin)
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    db.add(FaceEmbedding(user_id=user.id, embedding=face_embedding))
    db.add(VoiceProfile(user_id=user.id, feature_vector=voice_features))

    if role == "Account Holder":
        base_acct = f"31504000{user.id:04d}"
        accounts = [
            BankAccount(user_id=user.id, account_number=f"{base_acct}1", account_type="Savings Account", balance=254000.50),
            BankAccount(user_id=user.id, account_number=f"{base_acct}2", account_type="Current Account", balance=1120000.00),
            BankAccount(user_id=user.id, account_number=f"{base_acct}3", account_type="Home Loan", balance=-1500000.00),
        ]
        db.add_all(accounts)
    db.commit()

    return {"status": "success", "message": "User registered successfully"}


@app.post("/login")
async def login(
    customer_id: str = Form(...),
    mpin: str = Form(...),
    role: str = Form(...),
    frame: UploadFile = File(...),
    audio: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.customer_id == customer_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
        
    if not security.verify_mpin(mpin, str(user.mpin_hash)):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    frame_bytes = await frame.read()
    nparr = np.frombuffer(frame_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

    face_count = ai_engine.detect_faces(img)
    if face_count == 0:
        raise HTTPException(status_code=401, detail="Login Denied: No face detected. Please look at the camera.")
    elif face_count > 1:
        raise HTTPException(status_code=401, detail="Login Denied: Multiple faces detected. Shoulder-surfing risk.")

    live_face = ai_engine.extract_face_embedding(img)
    if not live_face:
        raise HTTPException(status_code=401, detail="No face detected in live feed.")

    db_face = db.query(FaceEmbedding).filter(FaceEmbedding.user_id == user.id).first()
    if not db_face or db_face.embedding is None:
        raise HTTPException(status_code=401, detail="Face biometric data not found.")

    face_similarity = 1 - cosine(live_face, list(db_face.embedding))  # type: ignore
    if face_similarity < 0.40:
        raise HTTPException(status_code=401, detail="Face verification failed.")

    audio_bytes = await audio.read()
    live_voice = ai_engine.extract_voice_features(audio_bytes)
    
    db_voice = db.query(VoiceProfile).filter(VoiceProfile.user_id == user.id).first()
    if not db_voice or db_voice.feature_vector is None:
        raise HTTPException(status_code=401, detail="Voice biometric data not found.")
    
    voice_similarity = 1 - cosine(live_voice, list(db_voice.feature_vector))  # type: ignore
    if voice_similarity < 0.70:
        raise HTTPException(status_code=401, detail="Voice mismatch. Identity unverified.")

    token = security.create_access_token(data={"sub": user.customer_id, "user_id": user.id, "role": role}) # type: ignore
    return {"access_token": token, "token_type": "bearer", "role": role}


@app.post("/verify-session")
async def verify_session(
    token: str = Form(...),
    frame: UploadFile = File(...),
    typing_speed: float = Form(...),
    hold_time: float = Form(...),
    latency: float = Form(...),
    rhythm: float = Form(...),
    error_rate: float = Form(...),
    movement_speed: float = Form(...),
    click_frequency: float = Form(...),
    scrolling_speed: float = Form(...)
):
    frame_bytes = await frame.read()
    nparr = np.frombuffer(frame_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

    face_count = ai_engine.detect_faces(img)

    # Initial trust score starting around 90
    tds = 91.5
    risk_level = "Low (Secure)"
    is_active = True

    if face_count == 0:
        # Critical risk: 10 - 30 range
        tds = 18.5
        risk_level = "Critical - No Face Detected"
        is_active = False
    elif face_count > 1:
        # Critical risk: 10 - 30 range
        tds = 22.0
        risk_level = "Critical - Multiple Faces Detected"
        is_active = False
    else:
        if float(error_rate) > 5.0 or float(latency) > 300.0:
            # High risk: 30 - 50 range
            tds = 42.0
            risk_level = "High - Unusual Typing Behavior"
            
    return {
        "trust_score": tds,
        "risk_level": risk_level,
        "is_active": is_active,
        "face_count": face_count
    }


@app.post("/simulate-attack")
async def simulate_attack(file: UploadFile = File(...), filename: str = Form(None)):
    file_bytes = await file.read()
    target_name = filename if filename else (file.filename if file.filename else "unknown")
    
    analysis = ai_engine.detect_deepfake(file_bytes, target_name)
    
    return {
        "status": "success",
        "classification": "fake" if analysis["is_fake"] else "real",
        "real_percentage": analysis["real_percentage"],
        "fake_percentage": analysis["fake_percentage"],
        "is_active": not analysis["is_fake"],
        "message": "Deepfake Artifacts Detected! Terminating session." if analysis["is_fake"] else "Media verified as authentic."
    }


@app.get("/accounts")
def get_accounts(user_id: int, db: Session = Depends(get_db)):
    accounts = db.query(BankAccount).filter(BankAccount.user_id == user_id).all()
    return accounts


@app.post("/transfer")
def transfer_funds(req: TransferRequest, db: Session = Depends(get_db)):
    from_acc = db.query(BankAccount).filter(BankAccount.account_number == req.from_account).first()
    to_acc = db.query(BankAccount).filter(BankAccount.account_number == req.to_account).first()
    
    if not from_acc:
        raise HTTPException(status_code=404, detail="Source account not found")
        
    if from_acc.balance < req.amount:  # type: ignore
        raise HTTPException(status_code=400, detail="Insufficient funds")
        
    from_acc.balance -= req.amount  # type: ignore
    
    if to_acc:
        to_acc.balance += req.amount  # type: ignore
        
    db.commit()
    return {"status": "success"}