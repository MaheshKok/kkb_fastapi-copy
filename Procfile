web: gunicorn -w 7 -k uvicorn.workers.UvicornWorker app.main:app
worker: celery -A tasks.tasks.celery worker -l info -O fair --without-gossip --without-mingle --without-heartbeat --concurrency=7
