class Environment:
    PRODUCTION = "production"
    TEST = "test"


class ConfigFile:
    DEVELOPMENT = "starter.toml"
    PRODUCTION = "starter.toml"
    TEST = "local.toml"


class OptionType:
    CE = "CE"
    PE = "PE"


# strategy_id = UUID
# expiry = datetime.date object
# option_type = OptionType.CE or OptionType.PE
ONGOING_TRADES_REDIS_KEY = "strategy_id expiry option_type"


# EXPIRY DATE FORMAT
EDELWEISS_DATE_FORMAT = "%d %b %Y"
REDIS_DATE_FORMAT = "%Y-%m-%d"
SQLALCHEMY_DATE_FORMAT = "%Y-%m-%d"
