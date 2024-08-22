from app.pydantic_models.enums import SignalTypeEnum


def get_test_post_trade_payload(action: SignalTypeEnum = SignalTypeEnum.BUY):
    return {
        "future_entry_price_received": 40600.5,
        "strategy_id": "0d478355-1439-4f73-a72c-04bb0b3917c7",
        "action": action,
        "received_at": "2023-05-22T05:11:00Z",
    }
