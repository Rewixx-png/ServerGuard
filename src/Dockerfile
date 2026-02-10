FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY bot.py .
# Copy scripts folder so the bot can upload them to agents
COPY scripts/ scripts/
CMD ["python", "bot.py"]
