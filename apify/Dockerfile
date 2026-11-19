FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY collector.py ./
COPY app ./app
COPY config ./config
RUN mkdir -p /app/data /app/logs && useradd -r -u 10001 collector && chown -R collector:collector /app
USER collector
CMD ["python", "collector.py"]
