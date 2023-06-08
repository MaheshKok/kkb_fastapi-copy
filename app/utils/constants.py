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


EXPIRY_DATE_FORMAT = "%d %b %Y"


# strategy_id = UUID
# expiry = datetime.date object
# option_type = OptionType.CE or OptionType.PE
ONGOING_TRADES_REDIS_KEY = "strategy_id expiry option_type"
