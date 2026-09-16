import base64
import io
import json
import re

import httpx
from PIL import Image

from ..config import OLLAMA_BASE_URL, OLLAMA_MODEL, OLLAMA_NUM_CTX


class LLMError(Exception):
    """识别服务调用失败，message 为面向用户的中文原因。"""


# 图片最长边超过此值先等比缩小：视觉 token 数与像素数成正比，
# 手机长截图不缩小会撑爆模型上下文，且识别更慢、精度几乎无损。
MAX_IMAGE_EDGE = 1600

PROMPT = """请仔细观察这张账单/支付截图图片，提取全部消费记录。

提取步骤：
1. 逐块扫描整张图片（长截图、拼图都要完整扫描），找出所有独立的订单/支付区块；每个含“实付款”“支付成功”“合计”“应付”字样的区块算一份订单。
2. 每份订单输出一条记录，有几份订单就输出几条，不能只输出第一条。
3. 同一份订单内的商品明细合并为该订单一笔总消费。

对每份订单分别抄写以下数字（都必须从图片中明确出现的数字里抄，找不到就填null）：
- paid_amount: “实付款”或“实际支付”行的数字
- total_amount: “合计”或“应付”行的数字

只输出如下格式的JSON对象，不要输出解释或其他文字：
{{
  "orders": [
    {{
      "title": "商户名称或消费描述",
      "paid_amount": 0.00,
      "total_amount": 0.00,
      "trade_date": "YYYY-MM-DD",
      "category": "餐饮/购物/交通/日用/娱乐/医疗/其他",
      "amount_candidates": [
        {{"value": 0.00, "context": "金额上下文", "type": "actual_paid/product_price/discount/coupon/points/balance/advertisement/noise"}}
      ]
    }}
  ]
}}

规则：
1. 数字只能抄写，不要计算。
2. 忽略商品单价、优惠、积分、余额、广告金额；订单号、时间、数量、百分比不是金额。
3. title优先商户名；没有商户名用商品或消费描述；都不清楚填“图片账单”。
4. category只能从餐饮、购物、交通、日用、娱乐、医疗、其他中选择，无法判断填“其他”。
5. trade_date图片中没有就用今天日期{today}。
6. amount_candidates列出该订单中所有出现的金额，一个都不能漏。"""


def _pick_amount(item: dict):
    """实付款优先，其次合计，再次模型直接给出的amount。"""
    for key, context in (("paid_amount", "实付款"), ("total_amount", "合计"), ("amount", "当前金额")):
        value = item.get(key)
        if isinstance(value, (int, float)) and value > 0:
            candidates = item.get("amount_candidates")
            if not isinstance(candidates, list):
                candidates = item["amount_candidates"] = []
            if not any(isinstance(c, dict) and isinstance(c.get("value"), (int, float)) and c["value"] == value for c in candidates):
                candidates.append({"value": value, "context": context, "type": "actual_paid"})
            return value
    return None


def _prepare_image_b64(image_bytes: bytes) -> str:
    """缩小过大的图片并统一转成 JPEG，控制视觉 token 数和请求体积。"""
    img = Image.open(io.BytesIO(image_bytes))
    if max(img.size) > MAX_IMAGE_EDGE:
        ratio = MAX_IMAGE_EDGE / max(img.size)
        img = img.resize((max(1, round(img.width * ratio)), max(1, round(img.height * ratio))))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=90)
    return base64.b64encode(buf.getvalue()).decode()


async def extract_records(
    image_bytes: bytes, today: str, categories: list[str] | None = None
) -> tuple[list[dict], str]:
    """Send the receipt image straight to the vision model.

    Returns (records, raw_response) — raw_response is kept for debugging.
    """
    categories = categories or ["餐饮", "购物", "交通", "日用", "娱乐", "医疗", "其他"]
    category_text = "、".join(categories)
    try:
        image_b64 = _prepare_image_b64(image_bytes)
    except Exception as e:
        raise LLMError(f"图片文件无法解析（可能已损坏）：{e}") from e
    try:
        async with httpx.AsyncClient(timeout=600) as client:
            resp = await client.post(
                f"{OLLAMA_BASE_URL}/api/chat",
                json={
                    "model": OLLAMA_MODEL,
                    "messages": [
                        {
                            "role": "user",
                            "content": PROMPT.format(today=today).replace(
                                "餐饮、购物、交通、日用、娱乐、医疗、其他", category_text
                            ),
                            "images": [image_b64],
                        }
                    ],
                    "stream": False,
                    "format": "json",
                    "options": {"temperature": 0, "num_ctx": OLLAMA_NUM_CTX},
                },
            )
            resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        try:
            detail = e.response.json().get("error") or e.response.text[:200]
        except Exception:
            detail = e.response.text[:200]
        if "context size" in detail:
            detail += "（图片过大，请裁剪后再试）"
        raise LLMError(f"识别服务返回错误（HTTP {e.response.status_code}）：{detail}") from e
    except httpx.RequestError as e:
        raise LLMError(f"无法连接识别服务：{e}") from e
    raw = resp.json()["message"]["content"]

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = None
    items = []
    if isinstance(data, dict):
        items = data.get("orders") or []
    elif isinstance(data, list):
        # Tolerate models that return a bare array despite the schema.
        items = data

    records = []
    for item in items:
        if not isinstance(item, dict):
            continue
        amount = _pick_amount(item)
        if amount is None:
            continue
        records.append({
            "title": item.get("title") or "图片账单",
            "amount": amount,
            "trade_date": item.get("trade_date") or today,
            "category": item.get("category") or "其他",
            "amount_candidates": item.get("amount_candidates") or [],
        })
    if records:
        return records, raw

    # Fallback when the small model returns an empty/malformed response.
    # Prefer the largest decimal amount mentioned in its answer, which is
    # usually the actual paid total rather than an ad/coupon amount.
    amounts = []
    for match in re.finditer(r"(?<!\d)(\d{1,8}[.]\d{2})(?!\d)", raw):
        value = float(match.group(1))
        if 0 < value <= 1_000_000:
            amounts.append(value)
    amount = max(amounts) if amounts else 0.0
    return [{
        "title": "图片账单",
        "amount": amount,
        "trade_date": today,
        "category": "其他",
        "amount_candidates": [
            {"value": value, "context": "", "type": "actual_paid" if value == amount else "noise"}
            for value in amounts
        ],
    }], raw
