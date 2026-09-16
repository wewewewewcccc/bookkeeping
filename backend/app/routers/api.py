import hashlib
import re
from datetime import date, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..config import IMAGE_DIR
from ..database import get_db
from ..models import Receipt, Record
from ..services import llm

router = APIRouter(prefix="/api")

ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp", "image/bmp"}


class RecordOut(BaseModel):
    id: int
    receipt_id: int | None
    category: str
    title: str
    amount: float
    trade_date: date
    extra: dict | None

    model_config = {"from_attributes": True}


class ReceiptOut(BaseModel):
    id: int
    image_path: str
    ocr_text: str | None
    created_at: datetime
    records: list[RecordOut]

    model_config = {"from_attributes": True}


@router.post("/receipts", response_model=list[ReceiptOut])
async def upload_receipts(
    files: list[UploadFile] = File(...),
    categories: str = Form("餐饮,购物,交通,日用,娱乐,医疗,其他"),
    trade_month: str = Form(""),
    db: Session = Depends(get_db),
):
    for f in files:
        if f.content_type not in ALLOWED_TYPES:
            raise HTTPException(400, f"仅支持 jpg/png/webp/bmp 图片：{f.filename}")
    category_list = [x.strip() for x in categories.split(",") if x.strip()][:50]
    receipts = []
    for f in files:
        try:
            receipts.append(await _create_receipt(f, category_list, db, trade_month))
        except llm.LLMError as e:
            raise HTTPException(502, f"{f.filename}：{e}")
    return receipts


async def _create_receipt(file: UploadFile, category_list: list[str], db: Session, trade_month: str = "") -> Receipt:
    content = await file.read()
    digest = hashlib.sha256(content).hexdigest()[:16]
    ext = Path(file.filename or "img.jpg").suffix or ".jpg"
    image_dir = Path(IMAGE_DIR)
    image_dir.mkdir(parents=True, exist_ok=True)
    image_path = image_dir / f"{date.today():%Y%m%d}_{digest}{ext}"

    try:
        image_path.write_bytes(content)
        fallback_date = trade_month + "-01" if re.fullmatch(r"\d{4}-\d{2}", trade_month) else date.today().isoformat()
        extracted, raw = await llm.extract_records(content, fallback_date, category_list)
    except Exception:
        # 识别失败时不留孤儿图片
        image_path.unlink(missing_ok=True)
        raise

    receipt = Receipt(image_path=image_path.name, ocr_text=raw)
    for item in extracted:
        receipt.records.append(Record(
            title=str(item.get("title", ""))[:255],
            amount=round(float(item["amount"]), 2),
            trade_date=_parse_date(item.get("trade_date"), trade_month),
            category=str(item.get("category", "其他"))[:50],
            extra={"amount_candidates": item.get("amount_candidates", [])},
        ))
    db.add(receipt)
    db.commit()
    db.refresh(receipt)
    return receipt


def _parse_date(value, trade_month: str = "") -> date:
    today = date.today()
    fallback = date(today.year, today.month, 1)
    if re.fullmatch(r"\d{4}-\d{2}", trade_month):
        y, m = map(int, trade_month.split("-"))
        fallback = date(y, m, 1)
        if y == today.year and m == today.month:
            fallback = today
    if isinstance(value, str):
        m = re.match(r"(\d{4})[-/.年](\d{1,2})[-/.月](\d{1,2})", value)
        if m:
            try:
                parsed = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                return parsed if parsed <= today else fallback
            except ValueError:
                return fallback
        m = re.search(r"(\d{1,2})\s*[月/-]\s*(\d{1,2})\s*日?", value)
        if m:
            try:
                parsed = date(today.year, int(m.group(1)), int(m.group(2)))
                return parsed if parsed <= today else fallback
            except ValueError:
                return fallback
    try:
        parsed = date.fromisoformat(str(value))
        return parsed if parsed <= today else fallback
    except ValueError:
        return fallback


@router.get("/receipts", response_model=list[ReceiptOut])
def list_receipts(db: Session = Depends(get_db)):
    return db.query(Receipt).order_by(Receipt.id.desc()).limit(100).all()


@router.get("/receipts/{receipt_id}/image")
def get_image(receipt_id: int, db: Session = Depends(get_db)):
    receipt = db.get(Receipt, receipt_id)
    if not receipt:
        raise HTTPException(404, "not found")
    return {"url": f"/images/{receipt.image_path}"}


@router.delete("/receipts/{receipt_id}")
def delete_receipt(receipt_id: int, db: Session = Depends(get_db)):
    receipt = db.get(Receipt, receipt_id)
    if not receipt:
        raise HTTPException(404, "not found")
    image_path = Path(IMAGE_DIR) / receipt.image_path
    db.delete(receipt)
    db.commit()
    if image_path.exists():
        image_path.unlink()
    return {"ok": True}


class RecordUpdate(BaseModel):
    category: str | None = None
    title: str | None = None
    amount: float | None = Field(gt=0)
    trade_date: date | None = None


@router.patch("/records/{record_id}", response_model=RecordOut)
def update_record(record_id: int, body: RecordUpdate, db: Session = Depends(get_db)):
    record = db.get(Record, record_id)
    if not record:
        raise HTTPException(404, "not found")
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(record, k, v)
    db.commit()
    db.refresh(record)
    return record


@router.delete("/records/{record_id}")
def delete_record(record_id: int, db: Session = Depends(get_db)):
    record = db.get(Record, record_id)
    if not record:
        raise HTTPException(404, "not found")
    db.delete(record)
    db.commit()
    return {"ok": True}
