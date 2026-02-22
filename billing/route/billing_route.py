# billing/route/billing_route.py
import os
import hmac
import hashlib
import razorpay
from fastapi import APIRouter, Request, HTTPException, Depends
from sqlalchemy.orm import Session
from core.db_client import get_db
from billing.service.balance_service import BalanceService
from billing.pricing import BILLING_CURRENCY
from middleware import verify_access_token
from pydantic import BaseModel

RAZORPAY_KEY_ID     = os.getenv("RAZORPAY_KEY_ID")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET")

razorpay_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))

billing_router = APIRouter(prefix="/billing", tags=["billing"])


# ── Request schemas ───────────────────────────────────────────────────────────

class CreateOrderRequest(BaseModel):
    amount: float               # e.g. 100.00 (₹100)

class VerifyPaymentRequest(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str


# ── 1. Create Razorpay Order ─────────────────────────────────────────────────

@billing_router.post("/order")
def create_order(
    body: CreateOrderRequest,
    user_id: str = Depends(verify_access_token),
):
    """
    Creates a Razorpay Order. The frontend uses the returned order_id
    to open the Razorpay Checkout widget.

    POST /billing/order
    Body: {"amount": 100.00}
    Returns: {"order_id": "order_xxx", "amount_paise": 10000, "currency": "INR", "key_id": "rzp_..."}
    """
    if body.amount < 10:
        raise HTTPException(status_code=400, detail="Minimum top-up is ₹10")
    if body.amount > 50000:
        raise HTTPException(status_code=400, detail="Maximum single top-up is ₹50,000")

    amount_paise = int(body.amount * 100)

    order = razorpay_client.order.create({
        "amount":   amount_paise,
        "currency": BILLING_CURRENCY,
        "notes": {
            "user_id": user_id,
            "purpose": "ReadMyBook AI Credits",
        },
    })

    return {
        "order_id":     order["id"],
        "amount_paise": amount_paise,
        "amount":       body.amount,
        "currency":     BILLING_CURRENCY,
        "key_id":       RAZORPAY_KEY_ID,      # frontend needs this for Checkout
    }


# ── 2. Verify Payment & Credit Balance ───────────────────────────────────────

@billing_router.post("/verify")
def verify_payment(
    body: VerifyPaymentRequest,
    user_id: str = Depends(verify_access_token),
    db: Session = Depends(get_db),
):
    """
    Called by the frontend after Razorpay Checkout completes.
    Verifies the HMAC signature, then credits the user's balance.
    Idempotent — safe to call multiple times with the same payment_id.

    POST /billing/verify
    Body: {"razorpay_order_id": "...", "razorpay_payment_id": "...", "razorpay_signature": "..."}
    Returns: {"verified": true, "balance": 500.00, "credited": 100.00}
    """
    # ── Signature verification ────────────────────────────────────────────
    # Razorpay signs: order_id + "|" + payment_id with your key_secret
    expected_signature = hmac.new(
        RAZORPAY_KEY_SECRET.encode("utf-8"),
        f"{body.razorpay_order_id}|{body.razorpay_payment_id}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected_signature, body.razorpay_signature):
        raise HTTPException(status_code=400, detail="Invalid payment signature")

    # ── Fetch payment details from Razorpay ───────────────────────────────
    try:
        payment = razorpay_client.payment.fetch(body.razorpay_payment_id)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch payment: {e}")

    if payment.get("status") != "captured":
        raise HTTPException(status_code=400, detail=f"Payment not captured. Status: {payment.get('status')}")

    amount_paise = payment.get("amount", 0)
    currency     = payment.get("currency", BILLING_CURRENCY)
    amount       = amount_paise / 100

    # ── Verify user_id matches the order notes ────────────────────────────
    order = razorpay_client.order.fetch(body.razorpay_order_id)
    order_user_id = order.get("notes", {}).get("user_id")
    if order_user_id != user_id:
        raise HTTPException(status_code=403, detail="Payment does not belong to this user")

    # ── Credit balance (idempotent — safe on retries) ─────────────────────
    svc = BalanceService(db)
    new_balance = svc.credit(
        user_id=user_id,
        amount=amount,
        order_id=body.razorpay_order_id,
        payment_id=body.razorpay_payment_id,
        amount_paise=amount_paise,
        currency=currency,
    )

    return {
        "verified": True,
        "credited": amount,
        "currency": currency,
        "balance":  round(new_balance, 4),
    }


# ── 3. Razorpay Webhook (optional — for server-to-server confirmation) ───────

@billing_router.post("/webhook", include_in_schema=False)
async def razorpay_webhook(request: Request):
    """
    Optional: Razorpay can also send webhooks for payment.captured events.
    This is a safety net — the primary credit path is /billing/verify.

    Register in Razorpay Dashboard → Settings → Webhooks:
      URL: https://yourapp.com/billing/webhook
      Events: payment.captured
    """
    payload = await request.body()
    sig_header = request.headers.get("x-razorpay-signature", "")

    # Verify webhook signature
    webhook_secret = os.getenv("RAZORPAY_WEBHOOK_SECRET", RAZORPAY_KEY_SECRET)
    expected_sig = hmac.new(
        webhook_secret.encode("utf-8"),
        payload,
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected_sig, sig_header):
        raise HTTPException(status_code=400, detail="Invalid webhook signature")

    import json
    event = json.loads(payload)

    if event.get("event") == "payment.captured":
        payment_entity = event.get("payload", {}).get("payment", {}).get("entity", {})
        payment_id   = payment_entity.get("id")
        order_id     = payment_entity.get("order_id")
        amount_paise = payment_entity.get("amount", 0)
        currency     = payment_entity.get("currency", BILLING_CURRENCY)

        # Get user_id from the order notes
        try:
            order = razorpay_client.order.fetch(order_id)
            user_id = order.get("notes", {}).get("user_id")
        except Exception:
            user_id = None

        if user_id and payment_id:
            svc = BalanceService()
            try:
                svc.credit(
                    user_id=user_id,
                    amount=amount_paise / 100,
                    order_id=order_id,
                    payment_id=payment_id,
                    amount_paise=amount_paise,
                    currency=currency,
                )
            finally:
                svc.close()

    return {"status": "ok"}


# ── 4. Get Balance ────────────────────────────────────────────────────────────

@billing_router.get("/balance")
def get_balance(
    user_id: str = Depends(verify_access_token),
    db: Session = Depends(get_db),
):
    """
    Returns the user's current balance.
    Served from Redis (sub-millisecond) with DB fallback.
    """
    svc = BalanceService(db)
    balance = svc.get_balance(user_id)
    return {"balance": round(balance, 4), "currency": BILLING_CURRENCY}


# ── 5. Usage History ──────────────────────────────────────────────────────────

@billing_router.get("/history")
def get_usage_history(
    user_id: str = Depends(verify_access_token),
    db: Session = Depends(get_db),
    limit: int = 50,
    offset: int = 0,
):
    """Returns the user's debit (usage) transaction history."""
    from billing.data.model import UsageTransaction
    rows = (
        db.query(UsageTransaction)
        .filter(UsageTransaction.user_id == user_id)
        .order_by(UsageTransaction.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return {
        "transactions": [
            {
                "operation":     r.operation,
                "document_id":   r.document_id,
                "cost":          r.cost,
                "raw_llm_cost":  r.raw_llm_cost,
                "token_count":   r.token_count,
                "pages":         r.pages,
                "balance_after": r.balance_after,
                "currency":      r.currency,
                "created_at":    r.created_at.isoformat(),
            }
            for r in rows
        ]
    }


# ── 6. Top-Up History ────────────────────────────────────────────────────────

@billing_router.get("/topups")
def get_topup_history(
    user_id: str = Depends(verify_access_token),
    db: Session = Depends(get_db),
    limit: int = 20,
    offset: int = 0,
):
    """Returns the user's credit (top-up) history."""
    from billing.data.model import RazorpayTopUp
    rows = (
        db.query(RazorpayTopUp)
        .filter(RazorpayTopUp.user_id == user_id)
        .order_by(RazorpayTopUp.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return {
        "topups": [
            {
                "amount":        r.amount,
                "currency":      r.currency,
                "order_id":      r.razorpay_order_id,
                "payment_id":    r.razorpay_payment_id,
                "balance_after": r.balance_after,
                "created_at":    r.created_at.isoformat(),
            }
            for r in rows
        ]
    }
