import asyncio
import os
import cv2
import numpy as np
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool
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

FACE_VERIFICATION_WEIGHT = 0.30
DEEPFAKE_DETECTION_WEIGHT = 0.30
VOICE_SPOOF_WEIGHT = 0.20
BEHAVIORAL_WEIGHT = 0.20

# Hard ceiling on how long any single AI analysis call is allowed to run.
# Combined with the ai_engine speed fixes this should rarely (if ever) be
# hit, but it guarantees the endpoint always responds promptly instead of
# hanging on a pathological input file.
AI_CALL_TIMEOUT_SECONDS = 6.0


class TransferRequest(BaseModel):
    from_account: str
    to_account: str
    amount: float


async def _run_ai(fn, *args, timeout: float = AI_CALL_TIMEOUT_SECONDS, fallback: dict) -> dict:
    """
    Runs a blocking ai_engine call in FastAPI's threadpool instead of on the
    event loop directly. `fallback` is required (not optional) specifically
    so the return type is always `dict`, never `None` - this is what silences
    Pylance's reportOptionalSubscript false positive at the call sites below,
    since previously `fallback=None`'s default made Pylance infer an Optional
    return type even though every caller always passes a real fallback dict.
    """
    try:
        return await asyncio.wait_for(run_in_threadpool(fn, *args), timeout=timeout)
    except asyncio.TimeoutError:
        print(f"[WARN] AI call {getattr(fn, '__name__', fn)} timed out after {timeout}s")
        return fallback


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
    audio_bytes = await audio.read()
    nparr = np.frombuffer(frame_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

    # Face count check and voice-feature extraction don't depend on each
    # other - run them concurrently in the threadpool instead of one after
    # another, shaving real wall-clock time off login.
    face_count_task = run_in_threadpool(ai_engine.detect_faces, img)
    voice_task = run_in_threadpool(ai_engine.extract_voice_features, audio_bytes, _suffix_from_upload(audio))

    face_count = await face_count_task
    if face_count == 0:
        raise HTTPException(status_code=401, detail="Login Denied: No face detected. Please look at the camera.")
    elif face_count > 1:
        raise HTTPException(status_code=401, detail="Login Denied: Multiple faces detected. Shoulder-surfing risk.")

    live_face = await run_in_threadpool(ai_engine.extract_face_embedding, img)
    if not live_face:
        raise HTTPException(status_code=401, detail="No face detected in live feed.")

    db_face = db.query(FaceEmbedding).filter(FaceEmbedding.user_id == user.id).first()
    if not db_face or db_face.embedding is None:
        raise HTTPException(status_code=401, detail="Face biometric data not found.")

    face_similarity = 1 - cosine(live_face, list(db_face.embedding))  # type: ignore
    if face_similarity < 0.40:
        raise HTTPException(status_code=401, detail="Face verification failed.")

    live_voice = await voice_task

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

    # Kick off all independent AI work concurrently in the threadpool
    # instead of sequentially - this is what makes each 20s cycle actually
    # come back quickly instead of stacking up latency.
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

    return {
        "status": "success",
        "classification": "fake" if analysis["is_fake"] else "real",
        "real_percentage": analysis["real_percentage"],
        "fake_percentage": analysis["fake_percentage"],
        "is_active": not analysis["is_fake"],
        "message": "Deepfake Artifacts Detected! Terminating session." if analysis["is_fake"] else "Media verified as authentic.",
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

    if to_acc:
        to_acc.balance += req.amount  # type: ignore

    db.commit()
    return {"status": "success"}