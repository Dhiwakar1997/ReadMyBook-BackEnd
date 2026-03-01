# billing/pricing.py
"""
Central pricing config. All costs are in INR unless you change BILLING_CURRENCY.

MARKUP is applied on top of the raw OpenAI cost (converted to INR):
  - 2.0 = 100% margin on top of raw LLM cost

USD_TO_INR: approximate exchange rate. Update periodically or pull from an API.
"""
import os

MARKUP = 1.5
PDF_CONVERSION_MARKUP = 1.0
PDF_CONVERT_COST_PER_PAGE = 1.50        # ₹1.50 per page
MIN_BALANCE = 0.10                       # minimum ₹0.10 to proceed
BILLING_CURRENCY = os.getenv("BILLING_CURRENCY", "INR")

# Exchange rate: used to convert OpenAI's USD cost to INR for billing.
# Update this periodically or fetch from an exchange rate API.
USD_TO_INR = 85.0

# Mathpix conversion costs (USD)
MATHPIX_COST_PER_PAGE_USD = 0.0035      # $0.0035 per page
MATHPIX_COST_PER_IMAGE_USD = 0.0015     # $0.0015 per image


def llm_cost(raw_openai_cost_usd: float) -> float:
    """Convert raw OpenAI USD cost to INR with markup."""
    return round(raw_openai_cost_usd * USD_TO_INR * MARKUP, 4)


def pdf_cost(pages: int) -> float:
    """Cost for converting `pages` pages of PDF to Markdown."""
    return round(pages * PDF_CONVERT_COST_PER_PAGE, 4)


PDF_CONVERT_COST_PER_SECOND = 0.0110152  # ₹0.0110152 per second of conversion time
NODE_START_TIME = 30                      # 30 seconds added for node cold start


def conversion_time_cost(total_seconds: float) -> float:
    """Cost based on total conversion time in seconds (includes node start time)."""
    return round((total_seconds + NODE_START_TIME) * PDF_CONVERT_COST_PER_SECOND, 4)


def mathpix_cost(pages: int, images: int = 0) -> float:
    """Cost for Mathpix conversion: per-page + per-image + node start time, converted to INR (no markup)."""
    raw_usd = (pages * MATHPIX_COST_PER_PAGE_USD) + (images * MATHPIX_COST_PER_IMAGE_USD)
    node_start_cost = NODE_START_TIME * PDF_CONVERT_COST_PER_SECOND
    return round((raw_usd * USD_TO_INR) + node_start_cost, 4)
