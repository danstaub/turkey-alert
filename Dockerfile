FROM python:3.12-slim
WORKDIR /app
COPY server.py turkey_alert.py ./
COPY subscribers.json ./
# .env is NOT copied: set env vars in your host (Railway / Fly.io / VPS)
ENV PORT=8000
EXPOSE 8000
CMD ["python3", "server.py"]
