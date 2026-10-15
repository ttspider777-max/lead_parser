FROM python:3.11-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 DATA_DIR=/app/data WEB_PORT=8090

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8090
CMD ["python", "main.py"]
