FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY api/ ./api/

RUN mkdir -p /meta

EXPOSE 8290

CMD ["python", "api/schedules_api.py", "--host", "0.0.0.0", "--port", "8290"]
