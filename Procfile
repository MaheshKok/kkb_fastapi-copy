web: NEW_RELIC_CONFIG_FILE=newrelic.ini newrelic-admin run-program uvicorn app.main:app --host=0.0.0.0 --port=${PORT:-8000}
worker: NEW_RELIC_CONFIG_FILE=newrelic.ini newrelic-admin run-program celery -A main.celery worker -l info -O fair --without-gossip --without-mingle --without-heartbeat --concurrency=7
