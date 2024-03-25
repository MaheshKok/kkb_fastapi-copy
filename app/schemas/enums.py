from enum import Enum


class PositionEnum(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"


class SignalTypeEnum(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OptionTypeEnum(str, Enum):
    CE = "CE"
    PE = "PE"


class InstrumentTypeEnum(str, Enum):
    # we currently support only two types of instruments
    FUTIDX = "FUTIDX"  # Future Index
    OPTIDX = "OPTIDX"  # Option Index

    # FUTSTK and OPTSTK are not supported yet
    # FUTSTK = "FUTSTK"  # Future Stock
    # OPTSTK = "OPTSTK" # Option Stock


class ExchangeEnum(str, Enum):
    NSE = "NSE"
    BSE = "BSE"
    NFO = "NFO"
    CDS = "CDS"
    MCX = "MCX"
    NCDEX = "NCDEX"
    BFO = "BFO"


class ProductTypeEnum(str, Enum):
    CARRYFORWARD = "CARRYFORWARD"
    INTRADAY = "INTRADAY"
    DELIVERY = "DELIVERY"
    MARGIN = "MARGIN"
    BO = "BO"
    CO = "CO"


class BrokerNameEnum(str, Enum):
    ALICEBLUE = "ALICEBLUE"
    ANGELONE = "ANGELONE"
