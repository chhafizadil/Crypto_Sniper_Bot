# Koyeb process configuration.
# Changes:
# - Updated to use gunicorn for stable server operation with health check.

web: gunicorn -w 1 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000 main:app
