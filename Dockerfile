FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY avocado /app/avocado
COPY config.example.yaml /app/config.example.yaml

RUN mkdir -p /app/data

EXPOSE 8080

CMD ["python", "-m", "avocado.main"]

