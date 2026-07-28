from pydantic import BaseModel
from typing import List

class RegisterRequest(BaseModel):
    full_name: str
    customer_id: str
    mpin: str
    face_embedding: List[float]
    voice_feature_vector: List[float]

class TransferRequest(BaseModel):
    from_account: str
    to_account: str
    amount: float