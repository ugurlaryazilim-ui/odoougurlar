# Uğurlar Chat Service

Shopify mağazalar için **gerçek zamanlı canlı destek** chat servisi.

## 🚀 Teknoloji

- **FastAPI** + WebSocket (Python 3.12)
- **PostgreSQL** (Async - SQLAlchemy + asyncpg)
- **Redis** (Pub/Sub + Cache)
- **Odoo** entegrasyonu (JSON-RPC)
- **Docker** + Docker Compose

## 📦 Kurulum

```bash
# .env dosyasını oluştur
cp .env.example .env
# .env içindeki değerleri düzenle

# Docker ile başlat
docker compose up -d --build

# Logları izle
docker compose logs -f chat
```

## 🔗 Endpoints

| Endpoint | Metod | Açıklama |
|----------|-------|----------|
| `/health` | GET | Sistem durumu |
| `/api/chat/start` | POST | Sohbet başlat |
| `/api/chat/send` | POST | Mesaj gönder |
| `/api/chat/poll` | POST | Mesajları al (fallback) |
| `/api/operator/reply` | POST | Operatör cevabı (Odoo webhook) |
| `/ws/chat/{uid}` | WS | WebSocket bağlantısı |
| `/static/widget.js` | GET | Embed widget |

## 🛍️ Shopify Entegrasyonu

```html
<script>
  window.UGURLAR_CHAT_SERVER = 'https://chat.ugurlar.com';
</script>
<script src="https://chat.ugurlar.com/static/widget.js"></script>
```

## 📁 Yapı

```
ugurlar-chat/
├── app/
│   ├── api/          # REST endpoints
│   ├── models/       # SQLAlchemy models
│   ├── schemas/      # Pydantic schemas
│   ├── services/     # Business logic + Odoo bridge
│   ├── static/       # widget.js, widget.css
│   ├── websocket/    # WebSocket manager
│   ├── config.py     # Environment config
│   ├── database.py   # PostgreSQL async
│   ├── redis_client.py
│   └── main.py       # FastAPI app
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```
