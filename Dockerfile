FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY . /app
RUN python -m pip install --no-cache-dir .

VOLUME ["/data"]
ENV TRACEWEAVE_DATA_DIR=/data
ENTRYPOINT ["traceweave"]
