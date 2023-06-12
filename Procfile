web: gunicorn -w 7 -k uvicorn.workers.UvicornWorker app.main:app --host=0.0.0.0 --port=${PORT:-8000}
