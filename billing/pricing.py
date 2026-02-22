# billing/pricing.py
"""
Central pricing config. All costs are in INR unless you change BILLING_CURRENCY.

MARKUP is applied on top of the raw OpenAI cost (converted to INR):
  - 2.0 = 100% margin on top of raw LLM cost

USD_TO_INR: approximate exchange rate. Update periodically or pull from an API.
"""
import os

MARKUP = 1.5
PDF_CONVERT_COST_PER_PAGE = 1.50        # ₹1.50 per page
MIN_BALANCE = 0.10                       # minimum ₹0.10 to proceed
BILLING_CURRENCY = os.getenv("BILLING_CURRENCY", "INR")

# Exchange rate: used to convert OpenAI's USD cost to INR for billing.
# Update this periodically or fetch from an exchange rate API.
USD_TO_INR = 85.0


def llm_cost(raw_openai_cost_usd: float) -> float:
    """Convert raw OpenAI USD cost to INR with markup."""
    return round(raw_openai_cost_usd * USD_TO_INR * MARKUP, 4)


def pdf_cost(pages: int) -> float:
    """Cost for converting `pages` pages of PDF to Markdown."""
    return round(pages * PDF_CONVERT_COST_PER_PAGE, 4)
