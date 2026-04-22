FROM python:3.11-slim

WORKDIR /app

# Sadece standart kütüphane kullanıyoruz, ek paket gerekmez
COPY sync_agent.py .
COPY config.json .

# images klasörünü oluştur
RUN mkdir -p /app/images/Gonderilenler /app/images/Hatalilar

CMD ["python", "-u", "sync_agent.py"]
