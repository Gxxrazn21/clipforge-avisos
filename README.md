# ClipForge · avisos de directo

Revisa cada 5 minutos (GitHub Actions) si los canales de `canales.json` están en directo y avisa
por Telegram con los botones «🎬 Sacar clips» y «▶️ Ver directo». ClipForge, en el PC, recoge
el botón cuando se abre (Telegram guarda la pulsación hasta 24 h).

- Secretos del repositorio: `TELEGRAM_TOKEN` y `TELEGRAM_CHAT_ID` (no están en el código).
- `estado.json`: directos ya avisados (para no repetir).
- Probar a mano: pestaña **Actions → Avisos de directo → Run workflow**.
