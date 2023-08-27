class Environment:
    PRODUCTION = "production"
    TEST = "test"


class ConfigFile:
    DEVELOPMENT = "development.toml"
    PRODUCTION = "production.toml"
    TEST = "test.toml"


class OptionType:
    CE = "CE"
    PE = "PE"


class Status:
    SUCCESS = "success"
    ERROR = "error"
    COMPLETE = "complete"
    REJECTED = "rejected"
    VALIDATION_PENDING = "validation pending"


# strategy_id = UUID
# expiry = datetime.date object
# option_type = OptionType.CE or OptionType.PE
ONGOING_TRADES_REDIS_KEY = "strategy_id expiry option_type"


# EXPIRY DATE FORMAT
EDELWEISS_DATE_FORMAT = "%d %b %Y"
REDIS_DATE_FORMAT = "%Y-%m-%d"
SQLALCHEMY_DATE_FORMAT = "%Y-%m-%d"
ALICE_BLUE_DATE_FORMAT = "%d%b%y"
FUT = "FUT"


update_trade_columns = {
    "exit_price",
    "profit",
    "future_exit_price",
    "future_profit",
    "exit_received_at",
    "exit_at",
}
