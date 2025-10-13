# MK Finder - MVP (FastAPI + Railway + Telegram)

## Despliegue rápido
1. Sube estos archivos a un repo (GitHub).
2. En Railway: **New Project → Deploy from GitHub**.
3. Variables:
   - `TELEGRAM_BOT_TOKEN` = token de @BotFather
   - (luego del primer deploy) `PUBLIC_BASE_URL` = URL pública de Railway
4. Deploy → verifica `/health`.
5. Webhook Telegram:
   ```bash
   curl -X GET "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/setWebhook?url=$PUBLIC_BASE_URL/bot/telegram/webhook"
   ```
6. Escribe al bot y prueba:  
   `venta en Miraflores y San Isidro, 2 dorm, hasta 250k usd, con ascensor`

> Nota: `BOT_WEBHOOK_SECRET` se deja vacío para el MVP.

## Endpoints
- `/` raíz
- `/health`
- `/docs` Swagger
- `POST /nlu/parse`
- `POST /buscar`
- `POST /bot/telegram/webhook` (Telegram)

## Próximo sprint
- ProperatiAdapter y UrbaniaAdapter → guardar en NocoDB
- Dedupe + ranking
- Frontend ligero (Next.js / GitHub Pages) consumiendo el API
