from enum import Enum


class ActionEnum(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class PositionEnum(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"
