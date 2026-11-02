FROM python:3.13-alpine
WORKDIR /app
COPY bridge.py /app/bridge.py
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
CMD ["python3", "/app/bridge.py"]
