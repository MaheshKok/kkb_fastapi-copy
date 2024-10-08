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
EDELWEISS_DATE_FORMAT = "%d %b %Y"  # 22 Jun 2024
REDIS_DATE_FORMAT = "%Y-%m-%d"  # 2024-06-22
SQLALCHEMY_DATE_FORMAT = "%Y-%m-%d"  # 2024-06-22
ALICE_BLUE_EXPIRY_DATE_FORMAT = ANGELONE_EXPIRY_DATE_FORMAT = "%d%b%y"  # 22JUN24
FUT = "FUT"
TRADES_AND_OPTION_CHAIN_REDIS = "trades_and_option_chain_redis"
AB_NFO_CONTRACTS_URL = "https://v2api.aliceblueonline.com/restpy/static/contract_master/NFO.csv"
ANGELONE_ONE_CONTRACTS_URL = (
    "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
)
# Choose the column to be used as the key
INSTRUMENT_COLUMN = "Trading Symbol"
SYMBOL_STR = "symbol"
NAME_STR = "name"
ANGELONE_BROKER = "angelone_broker"
STRATEGY = "strategy"

update_trade_columns = {
    "exit_price",
    "profit",
    "future_exit_price_received",
    "future_profit",
    "exit_received_at",
    "exit_at",
}


class SYMBOL:
    BANKNIFTY = "BANKNIFTY"
    NIFTY = "NIFTY"
