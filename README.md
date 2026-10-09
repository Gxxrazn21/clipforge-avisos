# ClipForge · avisos de directo

Revisa cada 5 minutos si los canales de `canales.json` están en directo y avisa por Telegram con
los botones «🎬 Sacar clips» y «▶️ Ver directo». ClipForge, en el PC, recoge el botón cuando se
abre (Telegram guarda la pulsación hasta 24 h).

Con ClipForge cerrado, la nube también contesta los comandos del bot: `/envivo`, `/canales`,
`/estado`, `/ayuda`. Y anota lo que pidas con `/seguir nombre` o con el botón, para que ClipForge
empiece con ese canal en cuanto lo abras (el pedido vale 12 h).

- Secretos del repositorio: `TELEGRAM_TOKEN` y `TELEGRAM_CHAT_ID` (no están en el código).
- `estado.json`: directos ya avisados y mensajes ya contestados (para no repetir).
- Probar a mano: pestaña **Actions → Avisos de directo → Run workflow**.

## Cada 5 minutos de verdad (cron-job.org)

El horario propio de GitHub (`schedule`) es gratis pero muy poco fiable: en la práctica lo lanza
cada 5-7 horas. El ritmo de 5 minutos lo da [cron-job.org](https://cron-job.org) (gratis), que cada
5 minutos le pide a GitHub que ejecute el flujo («workflow_dispatch»).

Lo que hace cron-job.org en cada llamada:

- **URL:** `https://api.github.com/repos/Gxxrazn21/clipforge-avisos/actions/workflows/avisos.yml/dispatches`
- **Método:** `POST`
- **Cabeceras:**
  - `Accept: application/vnd.github+json`
  - `Authorization: Bearer <token de GitHub>`
  - `X-GitHub-Api-Version: 2022-11-28`
  - `Content-Type: application/json`
- **Cuerpo:** `{"ref":"main"}`
- **Respuesta buena:** `204 No Content`

El token es uno «fine-grained» de GitHub limitado a este repositorio con el permiso
**Actions: Read and write**. No da acceso a nada más.
