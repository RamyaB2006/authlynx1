import asyncio
import os
import random
from datetime import datetime, timedelta

import cv2
import numpy as np
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool
from sqlalchemy.orm import Session
from sqlalchemy import desc
from scipy.spatial.distance import cosine
from pydantic import BaseModel

import security  # type: ignore
from database import get_db, engine, Base  # type: ignore
from models import (  # type: ignore
    User, FaceEmbedding, VoiceProfile, BankAccount,
    Transaction, Beneficiary, Card, FixedDeposit,
)
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

FACE_VERIFICATION_WEIGHT = 0.30
DEEPFAKE_DETECTION_WEIGHT = 0.30
VOICE_SPOOF_WEIGHT = 0.20
BEHAVIORAL_WEIGHT = 0.20

AI_CALL_TIMEOUT_SECONDS = 6.0

FD_INTEREST_RATE = 6.75   # % p.a., flat rate for demo purposes
RD_INTEREST_RATE = 6.25   # % p.a.

BILLERS = {
    "Electricity": ["TANGEDCO", "BESCOM", "MSEB", "Adani Electricity"],
    "Mobile Recharge": ["Airtel", "Jio", "Vi", "BSNL"],
    "DTH": ["Tata Play", "Dish TV", "Airtel Digital TV"],
    "Broadband": ["ACT Fibernet", "BSNL Broadband", "Jio Fiber"],
    "Water": ["Municipal Water Board"],
    "Gas": ["Indane", "HP Gas", "Bharat Gas"],
    "Credit Card": ["IOB Credit Card"],
}


class TransferRequest(BaseModel):
    from_account: str
    to_account: str
    amount: float


class BeneficiaryRequest(BaseModel):
    user_id: int
    nickname: str
    account_number: str
    ifsc_code: str
    bank_name: str


class BillPayRequest(BaseModel):
    user_id: int
    from_account: str
    biller_category: str
    biller_name: str
    consumer_number: str
    amount: float


class FixedDepositRequest(BaseModel):
    user_id: int
    source_account: str
    deposit_type: str  # "Fixed" | "Recurring"
    principal_amount: float
    tenure_months: int


class ProfileUpdateRequest(BaseModel):
    user_id: int
    email: str | None = None
    phone: str | None = None
    address: str | None = None


class CardActionRequest(BaseModel):
    user_id: int
    card_id: int
    action: str  # "freeze" | "unfreeze" | "block"


async def _run_ai(fn, *args, timeout: float = AI_CALL_TIMEOUT_SECONDS, fallback: dict) -> dict:
    try:
        return await asyncio.wait_for(run_in_threadpool(fn, *args), timeout=timeout)
    except asyncio.TimeoutError:
        print(f"[WARN] AI call {getattr(fn, '__name__', fn)} timed out after {timeout}s")
        return fallback


def _record_transaction(db: Session, account: BankAccount, txn_type: str, amount: float,
                         category: str, description: str, counterparty: str | None = None):
    txn = Transaction(
        account_id=account.id,
        user_id=account.user_id,
        txn_type=txn_type,
        amount=amount,
        balance_after=account.balance,
        category=category,
        description=description,
        counterparty=counterparty,
    )
    db.add(txn)
    return txn


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

    face_embedding = await run_in_threadpool(ai_engine.extract_face_embedding, img)
    if not face_embedding:
        raise HTTPException(status_code=400, detail="No face detected. Please ensure your face is clearly visible.")

    audio_bytes = await audio.read()
    voice_features = await run_in_threadpool(
        ai_engine.extract_voice_features, audio_bytes, _suffix_from_upload(audio)
    )

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
        savings = BankAccount(user_id=user.id, account_number=f"{base_acct}1", account_type="Savings Account", balance=254000.50)
        current = BankAccount(user_id=user.id, account_number=f"{base_acct}2", account_type="Current Account", balance=1120000.00)
        loan = BankAccount(user_id=user.id, account_number=f"{base_acct}3", account_type="Home Loan", balance=-1500000.00)
        db.add_all([savings, current, loan])
        db.flush()  # so savings.id is available for the card FK below

        # Auto-issue a debit card against the new Savings account, same as
        # a real bank would at account opening.
        card = Card(
            user_id=user.id,
            account_id=savings.id,
            card_number_last4=f"{random.randint(0, 9999):04d}",
            card_type="Debit",
            card_network="RuPay",
            expiry_month=datetime.utcnow().month,
            expiry_year=datetime.utcnow().year + 5,
            status="Active",
        )
        db.add(card)

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
    audio_bytes = await audio.read()
    nparr = np.frombuffer(frame_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

    # Kick off ALL AI work at once instead of sequentially
    face_count_task = run_in_threadpool(ai_engine.detect_faces, img)
    face_embed_task = run_in_threadpool(ai_engine.extract_face_embedding, img)
    voice_task = run_in_threadpool(
        ai_engine.extract_voice_features, audio_bytes, _suffix_from_upload(audio)
    )

    face_count, live_face, live_voice = await asyncio.gather(
        face_count_task, face_embed_task, voice_task
    )

    if face_count == 0:
        raise HTTPException(status_code=401, detail="Login Denied: No face detected. Please look at the camera.")
    elif face_count > 1:
        raise HTTPException(status_code=401, detail="Login Denied: Multiple faces detected. Shoulder-surfing risk.")

    if not live_face:
        raise HTTPException(status_code=401, detail="No face detected in live feed.")

    db_face = db.query(FaceEmbedding).filter(FaceEmbedding.user_id == user.id).first()
    if not db_face or db_face.embedding is None:
        raise HTTPException(status_code=401, detail="Face biometric data not found.")

    face_similarity = 1 - cosine(live_face, list(db_face.embedding))  # type: ignore
    if face_similarity < 0.55:
        raise HTTPException(status_code=401, detail="Face verification failed.")

    db_voice = db.query(VoiceProfile).filter(VoiceProfile.user_id == user.id).first()
    if not db_voice or db_voice.feature_vector is None:
        raise HTTPException(status_code=401, detail="Voice biometric data not found.")

    voice_similarity = 1 - cosine(live_voice, list(db_voice.feature_vector))  # type: ignore
    if voice_similarity < 0.70:
        raise HTTPException(status_code=401, detail="Voice mismatch. Identity unverified.")

    token = security.create_access_token(data={"sub": user.customer_id, "user_id": user.id, "role": role})  # type: ignore
    return {"access_token": token, "token_type": "bearer", "role": role}

def _suffix_from_upload(upload: UploadFile) -> str:
    name = (upload.filename or "").lower()
    for ext in (".webm", ".wav", ".mp3", ".flac", ".m4a", ".ogg"):
        if name.endswith(ext):
            return ext
    return ".webm"


def _decode_and_verify_token(token: str, expected_user_id: int):
    try:
        import jwt as pyjwt
        payload = pyjwt.decode(token, security.SECRET_KEY, algorithms=[security.ALGORITHM])  # type: ignore
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired session token")

    token_user_id = payload.get("user_id")
    if token_user_id is None or int(token_user_id) != int(expected_user_id):
        raise HTTPException(status_code=401, detail="Token does not match user")

    return payload


@app.post("/quick-face-check")
async def quick_face_check(
    token: str = Form(...),
    user_id: int = Form(...),
    frame: UploadFile = File(...),
):
    _decode_and_verify_token(token, user_id)

    frame_bytes = await frame.read()
    nparr = np.frombuffer(frame_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

    face_count = await run_in_threadpool(ai_engine.detect_faces, img) if img is not None else 0

    violation = face_count != 1
    reason = None
    if img is None or face_count == 0:
        reason = "No face detected"
    elif face_count > 1:
        reason = "Multiple faces detected - shoulder-surfing risk"

    return {"face_count": face_count, "violation": violation, "reason": reason}


@app.post("/verify-session")
async def verify_session(
    token: str = Form(...),
    user_id: int = Form(...),
    frame: UploadFile = File(...),
    audio: UploadFile = File(...),
    typing_speed: float = Form(...),
    hold_time: float = Form(...),
    latency: float = Form(...),
    rhythm: float = Form(...),
    error_rate: float = Form(...),
    db: Session = Depends(get_db)
):
    _decode_and_verify_token(token, user_id)

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    frame_bytes = await frame.read()
    audio_bytes = await audio.read()

    nparr = np.frombuffer(frame_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

    face_count_task = run_in_threadpool(ai_engine.detect_faces, img) if img is not None else None
    face_embed_task = run_in_threadpool(ai_engine.extract_face_embedding, img) if img is not None else None
    deepfake_task = _run_ai(
        ai_engine.detect_deepfake, frame_bytes, "live_frame.jpg",
        fallback={"is_fake": False, "real_percentage": 50.0, "fake_percentage": 50.0},
    )
    voice_spoof_task = _run_ai(
        ai_engine.detect_deepfake, audio_bytes, f"live_audio{_suffix_from_upload(audio)}",
        fallback={"is_fake": False, "real_percentage": 50.0, "fake_percentage": 50.0},
    )

    face_count = await face_count_task if face_count_task else 0
    live_face = await face_embed_task if face_embed_task else None
    deepfake_result = await deepfake_task
    voice_spoof_result = await voice_spoof_task

    no_face_detected = img is None or face_count == 0
    multiple_faces_detected = face_count > 1

    face_score = 0.0
    if live_face:
        db_face = db.query(FaceEmbedding).filter(FaceEmbedding.user_id == user.id).first()
        if db_face and db_face.embedding is not None:
            similarity = 1 - cosine(live_face, list(db_face.embedding))  # type: ignore
            face_score = float(np.clip(similarity, 0.0, 1.0) * 100)

    deepfake_score = deepfake_result["real_percentage"]
    frame_is_fake = deepfake_result["is_fake"]

    voice_spoof_score = voice_spoof_result["real_percentage"]
    audio_is_fake = voice_spoof_result["is_fake"]

    behavioral_score = ai_engine.compute_behavioral_score(
        typing_speed, hold_time, latency, rhythm, error_rate
    )

    trust_score = round(float(
        FACE_VERIFICATION_WEIGHT * face_score +
        DEEPFAKE_DETECTION_WEIGHT * deepfake_score +
        VOICE_SPOOF_WEIGHT * voice_spoof_score +
        BEHAVIORAL_WEIGHT * behavioral_score
    ), 1)

    deepfake_detected = bool(frame_is_fake or audio_is_fake)
    security_violation = deepfake_detected or no_face_detected or multiple_faces_detected

    if deepfake_detected:
        risk_level = "Critical (Deepfake Detected)"
        violation_reason = "Deepfake or spoofed media detected"
    elif no_face_detected:
        risk_level = "Critical (No Face Detected)"
        violation_reason = "No face detected in camera frame"
    elif multiple_faces_detected:
        risk_level = "Critical (Multiple Faces Detected)"
        violation_reason = "Multiple faces detected - shoulder-surfing risk"
    elif trust_score > 75:
        risk_level = "Low (Secure)"
        violation_reason = None
    elif trust_score >= 30:
        risk_level = "Medium (Monitor)"
        violation_reason = None
    else:
        risk_level = "High (Critical)"
        violation_reason = None

    is_active = (not security_violation) and trust_score > 30

    return {
        "trust_score": trust_score,
        "face_match": round(face_score, 1),
        "deepfake_score": round(deepfake_score, 1),
        "voice_match": round(voice_spoof_score, 1),
        "behavioral_score": round(behavioral_score, 1),
        "risk_level": risk_level,
        "is_active": is_active,
        "deepfake_detected": deepfake_detected,
        "face_count": face_count,
        "violation_reason": violation_reason,
    }


@app.post("/simulate-attack")
async def simulate_attack(file: UploadFile = File(...), filename: str = Form(None)):
    file_bytes = await file.read()
    target_name = filename if filename else (file.filename if file.filename else "unknown")

    analysis = await _run_ai(
        ai_engine.detect_deepfake, file_bytes, target_name,
        fallback={"is_fake": False, "real_percentage": 50.0, "fake_percentage": 50.0,
                  "debug_signals": {"note": "analysis_timed_out"}},
    )

    debug_note = analysis.get("debug_signals", {}).get("note")
    inconclusive_notes = {
        "no_face_detected", "image_decode_failed", "audio_decode_failed",
        "analysis_timed_out", "unrecognized_file_type",
    }
    is_inconclusive = debug_note in inconclusive_notes or (
        debug_note is not None and debug_note.startswith("analysis_error")
    )

    if is_inconclusive:
        classification = "inconclusive"
        message = f"Could not confidently analyze this media ({debug_note}). Try a clearer frontal-face sample."
    else:
        classification = "fake" if analysis["is_fake"] else "real"
        message = "Deepfake Artifacts Detected! Terminating session." if analysis["is_fake"] else "Media verified as authentic."

    return {
        "status": "success",
        "classification": classification,
        "real_percentage": analysis["real_percentage"],
        "fake_percentage": analysis["fake_percentage"],
        "is_active": not (analysis["is_fake"]),  # inconclusive doesn't force logout
        "message": message,
        "debug_signals": analysis.get("debug_signals", {}),
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
    _record_transaction(
        db, from_acc, "debit", req.amount, "Transfer",
        f"Transfer to {req.to_account}", counterparty=req.to_account,
    )

    if to_acc:
        to_acc.balance += req.amount  # type: ignore
        _record_transaction(
            db, to_acc, "credit", req.amount, "Transfer",
            f"Transfer from {req.from_account}", counterparty=req.from_account,
        )

    db.commit()
    return {"status": "success"}


# ----------------------------------------------------------------------
# Transaction history
# ----------------------------------------------------------------------
@app.get("/transactions")
def get_transactions(user_id: int, account_number: str | None = None, limit: int = 50,
                      db: Session = Depends(get_db)):
    query = db.query(Transaction).filter(Transaction.user_id == user_id)
    if account_number:
        acc = db.query(BankAccount).filter(BankAccount.account_number == account_number).first()
        if not acc:
            raise HTTPException(status_code=404, detail="Account not found")
        query = query.filter(Transaction.account_id == acc.id)

    txns = query.order_by(desc(Transaction.created_at)).limit(limit).all()

    results = []
    for t in txns:
        acc = db.query(BankAccount).filter(BankAccount.id == t.account_id).first()
        results.append({
            "id": t.id,
            "account_number": acc.account_number if acc else None,
            "txn_type": t.txn_type,
            "amount": t.amount,
            "balance_after": t.balance_after,
            "category": t.category,
            "description": t.description,
            "counterparty": t.counterparty,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        })
    return results


# ----------------------------------------------------------------------
# Beneficiaries
# ----------------------------------------------------------------------
@app.get("/beneficiaries")
def list_beneficiaries(user_id: int, db: Session = Depends(get_db)):
    return db.query(Beneficiary).filter(Beneficiary.user_id == user_id).order_by(desc(Beneficiary.created_at)).all()


@app.post("/beneficiaries")
def add_beneficiary(req: BeneficiaryRequest, db: Session = Depends(get_db)):
    existing = db.query(Beneficiary).filter(
        Beneficiary.user_id == req.user_id,
        Beneficiary.account_number == req.account_number,
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="This beneficiary is already saved")

    beneficiary = Beneficiary(
        user_id=req.user_id,
        nickname=req.nickname,
        account_number=req.account_number,
        ifsc_code=req.ifsc_code,
        bank_name=req.bank_name,
    )
    db.add(beneficiary)
    db.commit()
    db.refresh(beneficiary)
    return beneficiary


@app.delete("/beneficiaries/{beneficiary_id}")
def delete_beneficiary(beneficiary_id: int, user_id: int, db: Session = Depends(get_db)):
    beneficiary = db.query(Beneficiary).filter(
        Beneficiary.id == beneficiary_id, Beneficiary.user_id == user_id
    ).first()
    if not beneficiary:
        raise HTTPException(status_code=404, detail="Beneficiary not found")
    db.delete(beneficiary)
    db.commit()
    return {"status": "success"}


# ----------------------------------------------------------------------
# Bill payments & recharge
# ----------------------------------------------------------------------
@app.get("/billers")
def get_billers():
    return BILLERS


@app.post("/bills/pay")
def pay_bill(req: BillPayRequest, db: Session = Depends(get_db)):
    if req.amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be greater than zero")

    from_acc = db.query(BankAccount).filter(BankAccount.account_number == req.from_account).first()
    if not from_acc:
        raise HTTPException(status_code=404, detail="Source account not found")
    if from_acc.balance < req.amount:  # type: ignore
        raise HTTPException(status_code=400, detail="Insufficient funds")

    from_acc.balance -= req.amount  # type: ignore
    category = "Recharge" if req.biller_category == "Mobile Recharge" else "Bill Payment"
    _record_transaction(
        db, from_acc, "debit", req.amount, category,
        f"{req.biller_category} - {req.biller_name} ({req.consumer_number})",
        counterparty=req.biller_name,
    )
    db.commit()
    return {"status": "success", "message": f"₹{req.amount:.2f} paid to {req.biller_name} successfully"}


# ----------------------------------------------------------------------
# Fixed / Recurring deposits
# ----------------------------------------------------------------------
@app.get("/deposits")
def list_deposits(user_id: int, db: Session = Depends(get_db)):
    return db.query(FixedDeposit).filter(FixedDeposit.user_id == user_id).order_by(desc(FixedDeposit.start_date)).all()


@app.post("/deposits")
def create_deposit(req: FixedDepositRequest, db: Session = Depends(get_db)):
    if req.principal_amount <= 0:
        raise HTTPException(status_code=400, detail="Principal amount must be greater than zero")
    if req.tenure_months <= 0:
        raise HTTPException(status_code=400, detail="Tenure must be at least 1 month")

    source_acc = db.query(BankAccount).filter(BankAccount.account_number == req.source_account).first()
    if not source_acc:
        raise HTTPException(status_code=404, detail="Source account not found")
    if source_acc.balance < req.principal_amount:  # type: ignore
        raise HTTPException(status_code=400, detail="Insufficient funds")

    rate = RD_INTEREST_RATE if req.deposit_type == "Recurring" else FD_INTEREST_RATE
    maturity_amount = req.principal_amount * (1 + (rate / 100) * (req.tenure_months / 12))
    start = datetime.utcnow()
    maturity_date = start + timedelta(days=30 * req.tenure_months)

    source_acc.balance -= req.principal_amount  # type: ignore
    _record_transaction(
        db, source_acc, "debit", req.principal_amount, "Deposit",
        f"{req.deposit_type} Deposit opened ({req.tenure_months} months)",
    )

    deposit = FixedDeposit(
        user_id=req.user_id,
        source_account_id=source_acc.id,
        deposit_type=req.deposit_type,
        principal_amount=req.principal_amount,
        interest_rate=rate,
        tenure_months=req.tenure_months,
        start_date=start,
        maturity_date=maturity_date,
        maturity_amount=round(maturity_amount, 2),
        status="Active",
    )
    db.add(deposit)
    db.commit()
    db.refresh(deposit)
    return deposit


# ----------------------------------------------------------------------
# Cards
# ----------------------------------------------------------------------
@app.get("/cards")
def list_cards(user_id: int, db: Session = Depends(get_db)):
    cards = db.query(Card).filter(Card.user_id == user_id).all()
    results = []
    for c in cards:
        acc = db.query(BankAccount).filter(BankAccount.id == c.account_id).first()
        results.append({
            "id": c.id,
            "card_number_last4": c.card_number_last4,
            "card_type": c.card_type,
            "card_network": c.card_network,
            "expiry_month": c.expiry_month,
            "expiry_year": c.expiry_year,
            "status": c.status,
            "linked_account_number": acc.account_number if acc else None,
        })
    return results


@app.post("/cards/action")
def card_action(req: CardActionRequest, db: Session = Depends(get_db)):
    card = db.query(Card).filter(Card.id == req.card_id, Card.user_id == req.user_id).first()
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")

    if req.action == "freeze":
        card.status = "Frozen"  # type: ignore
    elif req.action == "unfreeze":
        card.status = "Active"  # type: ignore
    elif req.action == "block":
        card.status = "Blocked"  # type: ignore
    else:
        raise HTTPException(status_code=400, detail="Invalid action. Use freeze, unfreeze, or block.")

    db.commit()
    return {"status": "success", "card_status": card.status}


# ----------------------------------------------------------------------
# Profile
# ----------------------------------------------------------------------
@app.get("/profile")
def get_profile(user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {
        "user_id": user.id,
        "full_name": user.full_name,
        "customer_id": user.customer_id,
        "email": user.email,
        "phone": user.phone,
        "address": user.address,
    }


@app.put("/profile")
def update_profile(req: ProfileUpdateRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == req.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if req.email is not None:
        user.email = req.email  # type: ignore
    if req.phone is not None:
        user.phone = req.phone  # type: ignore
    if req.address is not None:
        user.address = req.address  # type: ignore

    db.commit()
    return {"status": "success"}