import ssl

from celery import Celery

from app.core.config import get_config


config = get_config()
redis_url = config.get("celery_redis")

celery = Celery(
    "KokoBrothersBackend",
    broker=redis_url,
    backend=redis_url,
    broker_use_ssl={"ssl_cert_reqs": ssl.CERT_NONE},
    redis_backend_use_ssl={"ssl_cert_reqs": ssl.CERT_NONE},
    include=["tasks.tasks"],
)
