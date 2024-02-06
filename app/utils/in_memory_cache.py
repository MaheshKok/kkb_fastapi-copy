from cachetools import TTLCache


current_and_next_expiry_cache = TTLCache(maxsize=128, ttl=60 * 60 * 24)
oanda_access_token_cache = TTLCache(maxsize=128, ttl=60 * 60 * 24)
usd_to_gbp_conversion_cache = TTLCache(maxsize=128, ttl=600)
