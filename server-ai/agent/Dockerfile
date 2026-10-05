FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py read_tools.py ./
COPY web ./web

EXPOSE 8092

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8092"]
