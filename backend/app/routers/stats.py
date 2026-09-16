from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, extract
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Record

router = APIRouter(prefix="/api")


def _period_filter(q, year, month):
    if year:
        q = q.filter(extract("year", Record.trade_date) == year)
        if month:
            q = q.filter(extract("month", Record.trade_date) == month)
    return q


@router.get("/stats/summary")
def summary(
    year: int = Query(None),
    month: int = Query(None),
    db: Session = Depends(get_db),
):
    rows = _period_filter(
        db.query(Record.category, func.count(Record.id), func.sum(Record.amount)),
        year, month,
    ).group_by(Record.category).all()
    total = sum(float(r[2] or 0) for r in rows)
    max_rec = _period_filter(db.query(Record), year, month).order_by(Record.amount.desc()).first()
    return {
        "total": round(total, 2),
        "by_category": [
            {"category": r[0], "count": r[1], "amount": round(float(r[2] or 0), 2)}
            for r in rows
        ],
        "max_record": {
            "title": max_rec.title,
            "amount": round(float(max_rec.amount), 2),
            "trade_date": max_rec.trade_date.isoformat(),
        } if max_rec else None,
    }


@router.get("/stats/monthly")
def monthly(db: Session = Depends(get_db)):
    rows = (
        db.query(
            extract("year", Record.trade_date).label("y"),
            extract("month", Record.trade_date).label("m"),
            func.sum(Record.amount),
        )
        .group_by("y", "m")
        .order_by("y", "m")
        .all()
    )
    return [
        {"month": f"{int(r[0])}-{int(r[1]):02d}", "amount": round(float(r[2] or 0), 2)}
        for r in rows
    ]
