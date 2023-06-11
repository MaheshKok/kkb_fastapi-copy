from cachetools import TTLCache


current_and_next_expiry_cache = TTLCache(maxsize=128, ttl=60 * 60 * 24)
