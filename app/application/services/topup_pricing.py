"""Pay-as-you-go top-up pricing: amount paid -> credits added to an existing license.

Single source of truth for the gateway (checkout creation and webhook fulfilment). The hub shows the
same table, but the gateway always recomputes credits from the amount Stripe actually charged.
"""

from __future__ import annotations

TOPUP_CURRENCIES = ("eur", "usd")
TOPUP_MIN_CENTS = 500  # 5 EUR / 5 USD: below this the 0.25 fixed card fee eats >5 % of the sale
TOPUP_MAX_CENTS = 50_000  # 500 per payment: caps the damage of a stolen card
TOPUP_BASE_CREDITS_PER_UNIT = 20  # 1 EUR = 20 credits (0.05 EUR per credit)

# (minimum amount in cents, bonus percent), highest first.
TOPUP_BONUS_TIERS: tuple[tuple[int, int], ...] = (
    (10_000, 40),  # Enterprise: 100+   -> 28 cr per unit
    (5_000, 25),  # Business:   50-99  -> 25 cr per unit
    (2_000, 10),  # Pro:        20-49  -> 22 cr per unit
    (0, 0),  # Starter:    5-19   -> 20 cr per unit
)


def topup_bonus_percent(amount_cents: int) -> int:
    for floor, bonus in TOPUP_BONUS_TIERS:
        if amount_cents >= floor:
            return bonus
    return 0


def topup_credits(amount_cents: int) -> int:
    """Credits for a payment of amount_cents (integer maths, rounded down). 0 if below the minimum."""
    if not isinstance(amount_cents, int) or isinstance(amount_cents, bool) or amount_cents < TOPUP_MIN_CENTS:
        return 0
    bonus = topup_bonus_percent(amount_cents)
    return amount_cents * TOPUP_BASE_CREDITS_PER_UNIT * (100 + bonus) // 10_000


def validate_topup_amount(amount_cents: object, currency: object) -> tuple[int, str]:
    """Returns (amount_cents, currency) or raises ValueError with a user-facing reason."""
    cur = str(currency or "").strip().lower()
    if cur not in TOPUP_CURRENCIES:
        raise ValueError("Unsupported currency (use eur or usd).")
    if isinstance(amount_cents, bool) or not isinstance(amount_cents, int):
        raise ValueError("amount_cents must be an integer number of cents.")
    if amount_cents < TOPUP_MIN_CENTS or amount_cents > TOPUP_MAX_CENTS:
        raise ValueError(f"Amount must be between {TOPUP_MIN_CENTS // 100} and {TOPUP_MAX_CENTS // 100}.")
    if amount_cents % 100:
        raise ValueError("Amount must be a whole number (no cents).")
    return amount_cents, cur
