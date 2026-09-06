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
DATA_IMPORTING = "importing"

STALE_CATALOG_DAYS = 183
FEE_WARNING_DAYS = 45
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
    INSURANCE = "insurance"
    EARNING = "earning"


class Cadence(StrEnum):
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    SEMIANNUAL = "semiannual"
    ANNUAL = "annual"
    ONE_TIME = "one_time"
    PER_ANNIVERSARY = "per_anniversary"


class ResetRule(StrEnum):
    CALENDAR = "calendar"
    CARDMEMBER_YEAR = "cardmember_year"


class AppliesTo(StrEnum):
    PRIMARY = "primary"
    PRIMARY_AND_AU = "primary_and_au"
    AU_OWN_ALLOTMENT = "au_own_allotment"


class Role(StrEnum):
    PRIMARY = "primary"
    AUTHORIZED_USER = "authorized_user"


CADENCE_MONTHS: dict[Cadence, int] = {
    Cadence.MONTHLY: 1,
    Cadence.QUARTERLY: 3,
    Cadence.SEMIANNUAL: 6,
    Cadence.ANNUAL: 12,
    Cadence.PER_ANNIVERSARY: 12,
}
