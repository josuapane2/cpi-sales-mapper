"""RTG detection & forced categorization.

CRITICAL BUSINESS RULE (PRD 2.3 / 7.3):
Any product whose name contains "Ready To Go" or "RTG" MUST be categorized as
"Fiesta RTG" and treated as a RTG distributor row. It must NEVER be matched to a
non-RTG product, even if the name looks similar.
"""
import re

RTG_CATEGORY = "Fiesta RTG"
RTG_TYPE = "Dist. RTG"

# Match "RTG" as a standalone token or "Ready To Go" anywhere in the name.
_RTG_TOKEN = re.compile(r"\bRTG\b", re.IGNORECASE)
_READY_TO_GO = re.compile(r"ready\s*to\s*go", re.IGNORECASE)


def is_rtg(product_name: str) -> bool:
    """Return True when the product name indicates a Ready To Go product."""
    if not product_name:
        return False
    name = str(product_name)
    return bool(_RTG_TOKEN.search(name) or _READY_TO_GO.search(name))


def force_rtg_category(product_name: str) -> bool:
    """Convenience alias used by the engine for readability."""
    return is_rtg(product_name)
