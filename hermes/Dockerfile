FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir httpx==0.28.1 python-telegram-bot==21.10

COPY tools.py telegram_bot.py mcp_server.py ./

ENV BACKEND_URL=http://backend:8000
# Default: keep the MCP server alive (Hermes can also exec it directly).
# For the Telegram fallback worker, override CMD with: python telegram_bot.py
CMD ["python", "mcp_server.py"]
