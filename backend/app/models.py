from datetime import datetime, date

from sqlalchemy import String, Text, Numeric, DateTime, Date, ForeignKey, JSON, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class Receipt(Base):
    __tablename__ = "receipts"

    id: Mapped[int] = mapped_column(primary_key=True)
    image_path: Mapped[str] = mapped_column(String(255))
    ocr_text: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    records: Mapped[list["Record"]] = relationship(back_populates="receipt", cascade="all, delete-orphan")


class Record(Base):
    __tablename__ = "records"

    id: Mapped[int] = mapped_column(primary_key=True)
    receipt_id: Mapped[int | None] = mapped_column(ForeignKey("receipts.id"))
    category: Mapped[str] = mapped_column(String(50), default="未分类")
    title: Mapped[str] = mapped_column(String(255), default="")
    amount: Mapped[float] = mapped_column(Numeric(12, 2))
    trade_date: Mapped[date] = mapped_column(Date)
    extra: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    receipt: Mapped[Receipt | None] = relationship(back_populates="records")
