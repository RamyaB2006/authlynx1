from sqlalchemy import ForeignKey
from sqlalchemy.types import ARRAY, Float
from sqlalchemy.orm import Mapped, mapped_column, relationship
from database import Base

class User(Base):
    __tablename__ = "users"
    
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    full_name: Mapped[str] = mapped_column()
    customer_id: Mapped[str] = mapped_column(unique=True, index=True)
    mpin_hash: Mapped[str] = mapped_column()
    
    accounts: Mapped[list["BankAccount"]] = relationship(back_populates="owner")
    face_embedding: Mapped["FaceEmbedding"] = relationship(back_populates="owner", uselist=False)
    voice_profile: Mapped["VoiceProfile"] = relationship(back_populates="owner", uselist=False)

class FaceEmbedding(Base):
    __tablename__ = "face_embeddings"
    
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    embedding: Mapped[list[float]] = mapped_column(ARRAY(Float))
    
    owner: Mapped["User"] = relationship(back_populates="face_embedding")

class VoiceProfile(Base):
    __tablename__ = "voice_profiles"
    
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    feature_vector: Mapped[list[float]] = mapped_column(ARRAY(Float))
    
    owner: Mapped["User"] = relationship(back_populates="voice_profile")

class BankAccount(Base):
    __tablename__ = "bank_accounts"
    
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    account_number: Mapped[str] = mapped_column(unique=True, index=True)
    account_type: Mapped[str] = mapped_column()
    balance: Mapped[float] = mapped_column()
    
    owner: Mapped["User"] = relationship(back_populates="accounts")