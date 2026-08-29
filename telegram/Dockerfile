FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir httpx==0.28.1 python-telegram-bot==21.10

COPY bot.py ./

ENV BACKEND_URL=http://backend:8000
CMD ["python", "bot.py"]
