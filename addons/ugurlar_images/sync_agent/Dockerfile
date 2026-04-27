FROM python:3.11-slim

WORKDIR /app

# Pillow bağımlılıkları
RUN pip install --no-cache-dir Pillow

# Sync agent dosyalarını kopyala
COPY sync_agent.py .

# Çalıştır
CMD ["python", "-u", "sync_agent.py"]
