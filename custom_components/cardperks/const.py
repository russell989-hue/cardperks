"""Constants for the CardPerks integration."""

from __future__ import annotations

from enum import StrEnum

DOMAIN = "cardperks"

STORAGE_KEY = f"{DOMAIN}.state"
STORAGE_VERSION = 1
STORAGE_MINOR_VERSION = 1

SUBENTRY_OWNER = "owner"
SUBENTRY_CARD = "held_card"
SUBENTRY_IMPORT = "import"
SUBENTRY_STATEMENT = "statement"
SUBENTRY_STATUS = "status"

OVERRIDE_DIR = DOMAIN  # /config/cardperks/catalog/

CONF_HOUSEHOLD_NAME = "household_name"
CONF_FIRST_OWNER = "first_owner"
CONF_NAME = "name"
CONF_OWNER_ID = "owner_id"
CONF_ISSUER = "issuer"
CONF_PRODUCT_ID = "product_id"
CONF_ROLE = "role"
CONF_PARENT_CARD_ID = "parent_card_id"
CONF_OPEN_DATE = "open_date"
CONF_FEE_MONTH = "fee_month"
CONF_LAST4 = "last4"
CONF_NICKNAME = "nickname"
CONF_CLOSE_DATE = "close_date"
CONF_NOTES = "notes"
CONF_ANNUAL_FEE = "annual_fee"
CONF_ENABLED_CONDITIONAL = "enabled_conditional"
CONF_PREVIOUS_LAST4 = "previous_last4"
CONF_NOT_APPLICABLE = "not_applicable"
CONF_COLOR = "color"
CONF_PROGRAM = "program"
CONF_PROGRAM_ID = "program_id"
CONF_TIER_ID = "tier_id"
CONF_TIER = "tier"
CONF_VALID_THROUGH = "valid_through"
CONF_SOURCE = "source"

# Home Assistant's tile-card palette, so a card's colour works anywhere in Lovelace.
CARD_COLORS: tuple[str, ...] = (
    "red",
    "pink",
    "purple",
    "deep-purple",
    "indigo",
    "blue",
    "light-blue",
    "cyan",
    "teal",
    "green",
    "light-green",
    "lime",
    "yellow",
    "amber",
    "orange",
    "deep-orange",
    "brown",
    "light-grey",
    "grey",
    "dark-grey",
    "blue-grey",
)

ATTR_AMOUNT = "amount"
ATTR_AMOUNT_USED = "amount_used"
ATTR_DATE = "date"
ATTR_NOTE = "note"
ATTR_BENEFIT_ID = "benefit_id"
ATTR_VALUE = "value"
ATTR_CATEGORY = "category"
ATTR_QUARTER = "quarter"
ATTR_DEVICE_ID = "device_id"

SERVICE_MARK_USED = "mark_used"
SERVICE_RESET_BENEFIT = "reset_benefit"
SERVICE_ADD_SUB_SPEND = "add_sub_spend"
SERVICE_SET_PERK_VALUE = "set_perk_value"
SERVICE_ACTIVATE_ROTATING_CATEGORY = "activate_rotating_category"
SERVICE_IMPORT_CARDS = "import_cards"
ATTR_CSV = "csv"
ATTR_FILE = "file"
ATTR_CARD = "card"
ATTR_APPLY_FEE = "apply_fee"
ATTR_ADOPT_LAST4 = "adopt_last4"
ATTR_PATH = "path"
ATTR_PATTERN = "pattern"
SERVICE_IMPORT_STATEMENT = "import_statement"
SERVICE_ADD_STATEMENT_MATCH = "add_statement_match"
DATA_IMPORTING = "importing"

STALE_CATALOG_DAYS = 183
FEE_WARNING_DAYS = 45
STATUS_WARNING_DAYS = 45  # elite status about to lapse
REVIEW_DAYS_BEFORE_FEE = 30  # calendar reminder to review a card before its fee posts
BIG_TICKET_MIN = 50  # dollars still unused that make a credit worth chasing
# A statement for last month may not exist yet; one more month of slack before nagging.
STATEMENT_GRACE_MONTHS = 1
HISTORY_RETENTION_DAYS = 5 * 365
ROLLOVER_HOUR = 0
ROLLOVER_MINUTE = 5


class BenefitStatus(StrEnum):
    """Status of a benefit instance in its current period."""

    UNUSED = "unused"
    PARTIAL = "partial"
    USED = "used"
    NA = "n_a"


class BenefitType(StrEnum):
    STATEMENT_CREDIT = "statement_credit"
    PERK = "perk"
    REBATE = "rebate"  # a share of spend returned as a credit, with no cap
    INSURANCE = "insurance"
    EARNING = "earning"


class Cadence(StrEnum):
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    SEMIANNUAL = "semiannual"
    ANNUAL = "annual"
    ONE_TIME = "one_time"
    PER_ANNIVERSARY = "per_anniversary"
    EVERY_FOUR_YEARS = "every_four_years"  # Global Entry: one credit per four-year block


class SpendCategory(StrEnum):
    """Where a purchase happens, for the best-card lookup. Issuers each draw their own
    lines; these are the buckets a shopper actually thinks in. The issuer's exact
    wording (caps, exclusions, portal-only) rides along in the rate's notes."""

    DINING = "dining"
    GROCERIES = "groceries"
    GAS = "gas"
    FLIGHTS = "flights"  # booked directly with the airline
    HOTELS = "hotels"  # booked directly with the hotel
    CAR_RENTAL = "car_rental"
    TRAVEL = "travel"  # the issuer's general travel category
    ISSUER_TRAVEL_PORTAL = "issuer_travel_portal"  # Chase Travel, Amex Travel, Capital One Travel
    BRAND_AIRLINE = "brand_airline"  # purchases with the co-brand airline itself
    TRANSIT = "transit"  # trains, taxis, rideshare, tolls, parking
    STREAMING = "streaming"
    WIRELESS = "wireless"
    INTERNET_CABLE_PHONE = "internet_cable_phone"
    SHIPPING = "shipping"
    ADVERTISING = "advertising"
    ELECTRONICS_SOFTWARE = "electronics_software"
    ENTERTAINMENT = "entertainment"
    LARGE_PURCHASE = "large_purchase"
    OTHER = "other"


class ResetRule(StrEnum):
    CALENDAR = "calendar"
    CARDMEMBER_YEAR = "cardmember_year"


class AppliesTo(StrEnum):
    PRIMARY = "primary"
    PRIMARY_AND_AU = "primary_and_au"
    AU_OWN_ALLOTMENT = "au_own_allotment"


class LedgerWindow(StrEnum):
    """How far back a ledger view looks."""

    YTD = "year_to_date"
    PRIOR_YEAR = "prior_year"
    T12 = "trailing_12_months"
    ALL = "all"


class CardStatus(StrEnum):
    """Whether a card is being tracked.

    Frozen keeps the card and its history but stops opening periods and drops it from
    every total; cancelled does the same and hides it from dashboards.
    """

    ACTIVE = "active"
    FROZEN = "frozen"
    CANCELLED = "cancelled"


class Role(StrEnum):
    PRIMARY = "primary"
    AUTHORIZED_USER = "authorized_user"


PERIODS_PER_YEAR: dict[Cadence, float] = {
    Cadence.MONTHLY: 12,
    Cadence.QUARTERLY: 4,
    Cadence.SEMIANNUAL: 2,
    Cadence.ANNUAL: 1,
    Cadence.PER_ANNIVERSARY: 1,
    Cadence.EVERY_FOUR_YEARS: 0.25,
    Cadence.ONE_TIME: 0,
}

CADENCE_MONTHS: dict[Cadence, int] = {
    Cadence.MONTHLY: 1,
    Cadence.QUARTERLY: 3,
    Cadence.SEMIANNUAL: 6,
    Cadence.ANNUAL: 12,
    Cadence.PER_ANNIVERSARY: 12,
    Cadence.EVERY_FOUR_YEARS: 48,
}
