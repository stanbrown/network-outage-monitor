FROM python:3.12-slim

WORKDIR /app

COPY app.py /app/app.py
COPY static /app/static

ENV HOST=0.0.0.0
ENV PORT=8000
ENV TARGET_URL=https://www.google.com/generate_204
ENV CHECK_INTERVAL_SECONDS=5
ENV DATA_DIR=/data
ENV PYTHONUNBUFFERED=1

VOLUME ["/data"]

EXPOSE 8000

CMD ["python", "-u", "app.py"]
