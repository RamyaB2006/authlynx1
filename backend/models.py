from datetime import datetime
from sqlalchemy import ForeignKey, DateTime
from sqlalchemy.types import ARRAY, Float
from sqlalchemy.orm import Mapped, mapped_column, relationship
from database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    full_name: Mapped[str] = mapped_column()
    customer_id: Mapped[str] = mapped_column(unique=True, index=True)
    mpin_hash: Mapped[str] = mapped_column()

    # Profile fields - all optional since existing users won't have them set
    email: Mapped[str | None] = mapped_column(nullable=True)
    phone: Mapped[str | None] = mapped_column(nullable=True)
    address: Mapped[str | None] = mapped_column(nullable=True)

    accounts: Mapped[list["BankAccount"]] = relationship(back_populates="owner")
    face_embedding: Mapped["FaceEmbedding"] = relationship(back_populates="owner", uselist=False)
    voice_profile: Mapped["VoiceProfile"] = relationship(back_populates="owner", uselist=False)
    beneficiaries: Mapped[list["Beneficiary"]] = relationship(back_populates="owner")
    cards: Mapped[list["Card"]] = relationship(back_populates="owner")
    deposits: Mapped[list["FixedDeposit"]] = relationship(back_populates="owner")


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
    transactions: Mapped[list["Transaction"]] = relationship(back_populates="account")
    cards: Mapped[list["Card"]] = relationship(back_populates="account")


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("bank_accounts.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    txn_type: Mapped[str] = mapped_column()  # "debit" | "credit"
    amount: Mapped[float] = mapped_column()
    balance_after: Mapped[float] = mapped_column()
    category: Mapped[str] = mapped_column(default="Transfer")  # Transfer, Bill Payment, Recharge, Deposit, ...
    description: Mapped[str] = mapped_column()
    counterparty: Mapped[str | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    account: Mapped["BankAccount"] = relationship(back_populates="transactions")


class Beneficiary(Base):
    __tablename__ = "beneficiaries"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    nickname: Mapped[str] = mapped_column()
    account_number: Mapped[str] = mapped_column()
    ifsc_code: Mapped[str] = mapped_column()
    bank_name: Mapped[str] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    owner: Mapped["User"] = relationship(back_populates="beneficiaries")


class Card(Base):
    __tablename__ = "cards"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    account_id: Mapped[int] = mapped_column(ForeignKey("bank_accounts.id"))
    card_number_last4: Mapped[str] = mapped_column()
    card_type: Mapped[str] = mapped_column()      # "Debit" | "Credit"
    card_network: Mapped[str] = mapped_column()   # "RuPay" | "Visa" | "Mastercard"
    expiry_month: Mapped[int] = mapped_column()
    expiry_year: Mapped[int] = mapped_column()
    status: Mapped[str] = mapped_column(default="Active")  # Active | Frozen | Blocked

    owner: Mapped["User"] = relationship(back_populates="cards")
    account: Mapped["BankAccount"] = relationship(back_populates="cards")


class FixedDeposit(Base):
    __tablename__ = "fixed_deposits"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    source_account_id: Mapped[int] = mapped_column(ForeignKey("bank_accounts.id"))
    deposit_type: Mapped[str] = mapped_column()  # "Fixed" | "Recurring"
    principal_amount: Mapped[float] = mapped_column()
    interest_rate: Mapped[float] = mapped_column()
    tenure_months: Mapped[int] = mapped_column()
    start_date: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    maturity_date: Mapped[datetime] = mapped_column(DateTime)
    maturity_amount: Mapped[float] = mapped_column()
    status: Mapped[str] = mapped_column(default="Active")  # Active | Matured | Closed

    owner: Mapped["User"] = relationship(back_populates="deposits")