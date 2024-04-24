web: NEW_RELIC_CONFIG_FILE=newrelic.ini newrelic-admin run-program gunicorn -w 7 -k uvicorn.workers.UvicornWorker app.main:app
cron: python cron/scheduler.py
