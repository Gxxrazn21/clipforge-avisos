"""Avisador de directos en la nube (GitHub Actions) para ClipForge.

Cada pocos minutos mira quién de `canales.json` está en directo y, si es un directo nuevo,
avisa por Telegram con los botones «🎬 Sacar clips» y «▶️ Ver directo». El botón lo recoge
ClipForge en el PC cuando está abierto (Telegram guarda la pulsación hasta 24 h), así que se
puede tocar aunque el PC esté apagado: al encenderlo y abrir ClipForge, empieza.

Variables de entorno (secretos del repositorio): TELEGRAM_TOKEN, TELEGRAM_CHAT_ID.
Sin ellas (o con --prueba) solo imprime lo que enviaría.
"""
import html
import json
import os
import re
import sys
import time
from pathlib import Path

import requests

HERE = Path(__file__).parent
CANALES = HERE / "canales.json"
ESTADO = HERE / "estado.json"
TWITCH_CLIENT_ID = "kimne78kx3ncx6brgo4mv6wki5h1ko"     # el público de la web de Twitch
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/130 Safari/537.36",
      "Accept-Language": "es-ES,es;q=0.9"}


def handle(ch: str) -> str:
    return ch.rstrip("/").split("/")[-1].lstrip("@")


def kick(chs):
    try:
        from curl_cffi import requests as cr       # Kick está detrás de Cloudflare
    except ImportError:
        cr = None
    out, fallos = [], 0
    for ch in chs:
        slug = handle(ch).lower()
        try:
            if cr is not None:
                r = cr.get(f"https://kick.com/api/v2/channels/{slug}", impersonate="chrome", timeout=20)
            else:
                r = requests.get(f"https://kick.com/api/v2/channels/{slug}", headers=UA, timeout=20)
            d = r.json()
        except Exception:      # noqa: BLE001
            fallos += 1
            continue
        ls = d.get("livestream")
        if ls and ls.get("is_live", True):
            cats = ls.get("categories") or [{}]
            out.append(dict(canal=ch, id=f"kick:{ls.get('id')}", titulo=ls.get("session_title") or "",
                            viendo=int(ls.get("viewer_count") or 0), categoria=(cats[0] or {}).get("name", ""),
                            url=f"https://kick.com/{slug}"))
    if fallos:
        print(f"Kick: {fallos} canal(es) sin respuesta")
    return out


def twitch(chs):
    if not chs:
        return []
    logins = [re.sub(r"[^a-z0-9_]", "", handle(c).lower()) for c in chs]
    q = "{ " + " ".join(f'u{i}: user(login:"{lg}"){{ login stream{{ id title viewersCount game{{ name }} }} }}'
                         for i, lg in enumerate(logins)) + " }"
    d = requests.post("https://gql.twitch.tv/gql", json={"query": q}, headers={"Client-ID": TWITCH_CLIENT_ID, **UA},
                      timeout=20).json().get("data") or {}
    out = []
    for i, ch in enumerate(chs):
        u = d.get(f"u{i}") or {}
        st = u.get("stream")
        if st:
            out.append(dict(canal=ch, id=f"twitch:{st['id']}", titulo=st.get("title") or "",
                            viendo=int(st.get("viewersCount") or 0), categoria=(st.get("game") or {}).get("name", ""),
                            url=f"https://www.twitch.tv/{u.get('login')}"))
    return out


def youtube(chs):
    out = []
    for ch in chs:
        try:
            t = requests.get(ch.rstrip("/") + "/live", headers=UA, cookies={"CONSENT": "YES+1", "SOCS": "CAI"},
                             timeout=20).text
        except Exception:      # noqa: BLE001
            continue
        if '"isLiveNow":true' not in t:
            continue
        vid = re.search(r'<link rel="canonical" href="https://www.youtube.com/watch\?v=([\w-]{11})', t)
        title = re.search(r'<meta name="title" content="([^"]*)"', t)
        viewers = re.search(r'"concurrentViewers":"(\d+)"', t)
        if vid:
            out.append(dict(canal=ch, id=f"youtube:{vid.group(1)}", titulo=html.unescape(title.group(1)) if title else "",
                            viendo=int(viewers.group(1)) if viewers else 0, categoria="",
                            url=f"https://www.youtube.com/watch?v={vid.group(1)}"))
    return out


def en_directo(chs):
    by = {"kick": [], "twitch": [], "youtube": []}
    for c in chs:
        cl = c.lower()
        key = "kick" if "kick.com" in cl else "twitch" if "twitch.tv" in cl else "youtube" if "youtu" in cl else None
        if key:
            by[key].append(c)
    return kick(by["kick"]) + twitch(by["twitch"]) + youtube(by["youtube"])


def mensaje(lv: dict, modo: str) -> tuple[str, dict]:
    name = handle(lv["canal"])
    lines = [f"🔴 <b>{html.escape(name)}</b> está en directo"]
    if lv["titulo"]:
        lines.append(html.escape(lv["titulo"][:200]))
    extra = " · ".join(x for x in (lv["categoria"], f"{lv['viendo']:,} viendo".replace(",", ".") if lv["viendo"] else "") if x)
    if extra:
        lines.append(f"<i>{html.escape(extra)}</i>")
    if modo == "clips":
        lines.append("🎬 Está en «Clips»: si ClipForge está abierto, ya lo sigue solo.")
    else:
        lines.append("¿Quieres clips? Toca «Sacar clips» y abre ClipForge en el PC.")
    botones = [[{"text": "🎬 Sacar clips", "callback_data": f"follow|{lv['canal']}"[:64]},
                {"text": "▶️ Ver directo", "url": lv["url"]}]]
    return "\n".join(lines), {"inline_keyboard": botones}


ESTADO_PALABRAS = {"estado", "status", "progreso", "como vas", "cómo vas"}
CERRADO = "💤 <i>ClipForge está cerrado en tu PC: te contesto desde la nube.</i>"
AYUDA = ("🤖 <b>Comandos de ClipForge</b>\n"
         "/envivo — quién de tus canales está en directo ahora\n"
         "/seguir <i>nombre</i> — sigue ese canal: si está en vivo graba y te manda los clips; si no, espera a que prenda\n"
         "/seguir — sin nombre, te muestro los que están en vivo para elegir\n"
         "/detener — deja de seguir el canal actual\n"
         "/canales — tus canales y su modo\n"
         "/estado — qué está haciendo ClipForge ahora\n"
         "\nCon el PC apagado te contesto desde la nube y lo que pidas con /seguir empieza al abrir ClipForge.")


def _buscar(texto: str, canales: list) -> str | None:
    """«westcol», «@DjMaRiiO», «djma» o una URL → la URL del canal en tu lista."""
    t = texto.strip().rstrip("/")
    if t.startswith("http"):
        return t
    q = t.lower().lstrip("@")
    por = {handle(c["url"]).lower(): c["url"].rstrip("/") for c in canales}
    if q in por:
        return por[q]
    hits = [u for h, u in por.items() if h.startswith(q)] or [u for h, u in por.items() if q in h]
    return hits[0] if len(hits) == 1 else None


def respuesta(cmd: str, arg: str, crudo: str, vivos: list, canales: list) -> tuple[str, str, list | None] | None:
    """(tipo, texto, botones) para un comando escrito con ClipForge cerrado; None si no es un comando."""
    seguir = lambda v: {"text": f"🎬 Sacar clips de {handle(v['canal'])}", "callback_data": f"follow|{v['canal']}"[:64]}  # noqa: E731
    if cmd in ESTADO_PALABRAS or crudo in ESTADO_PALABRAS:
        en_vivo = ", ".join(handle(v["canal"]) for v in vivos[:8]) or "nadie de tu lista"
        return ("estado", "💤 <b>ClipForge está cerrado</b> (o tu PC apagado), así que ahora no saca clips.\n"
                f"☁️ Los avisos de directo siguen activos desde la nube.\n🔴 En directo ahora: {html.escape(en_vivo)}\n"
                "Abre ClipForge en el PC o escribe <code>/seguir nombre</code> y empezará al abrirlo.", None)
    if cmd in ("envivo", "vivo", "directos", "live"):
        if not vivos:
            return ("envivo", "😴 Nadie de tu lista está en directo ahora.\n" + CERRADO, None)
        lineas = ["🔴 <b>En directo ahora</b>"]
        for v in vivos[:12]:
            extra = " · ".join(x for x in (f"{v['viendo']:,} viendo".replace(",", ".") if v["viendo"] else "",
                                           v["categoria"]) if x)
            lineas.append(f"• <b>{html.escape(handle(v['canal']))}</b>" + (f" — {html.escape(extra)}" if extra else ""))
        lineas.append(CERRADO)
        return ("envivo", "\n".join(lineas), [[seguir(v), {"text": "▶️ Ver", "url": v["url"]}] for v in vivos[:8]])
    if cmd in ("canales", "lista"):
        vivo = {v["canal"].rstrip("/") for v in vivos}
        lineas = [f"📺 <b>Tus canales</b> ({len(canales)})"]
        for c in canales:
            tag = "Clips" if c.get("modo") == "clips" else "Aviso"
            lineas.append(f"• <b>{html.escape(handle(c['url']))}</b> · {tag}" + (" · 🔴 en vivo" if c["url"].rstrip("/") in vivo else ""))
        lineas.append("\nPara seguir uno: <code>/seguir nombre</code>\n" + CERRADO)
        return ("canales", "\n".join(lineas), None)
    if cmd in ("seguir", "sigue", "follow"):
        if not arg:
            if not vivos:
                return ("seguir", "😴 Ahora nadie de tu lista está en directo. Escribe <code>/seguir nombre</code> "
                        "y ClipForge lo seguirá al abrirlo.\n" + CERRADO, None)
            return ("seguir", "🎬 ¿A quién sigo? Están en directo (empieza al abrir ClipForge):\n" + CERRADO,
                    [[seguir(v)] for v in vivos[:8]])
        url = _buscar(arg, canales)
        if not url:
            return ("seguir", f"No encuentro «{html.escape(arg)}» entre tus canales. Escribe /canales para verlos.", None)
        return ("seguir:" + url, f"📝 Anotado: <b>{html.escape(handle(url))}</b>. En cuanto abras ClipForge en el PC "
                "empezará con él (el pedido vale 12 h).\n" + CERRADO, None)
    if cmd in ("detener", "parar", "dejar", "stop"):
        return ("detener", "💤 ClipForge está cerrado: ahora no está siguiendo ningún canal.", None)
    if cmd in ("ayuda", "help", "start", "comandos"):
        return ("ayuda", AYUDA + "\n" + CERRADO, None)
    return None


def _tg(token: str, metodo: str, **data) -> dict:
    try:
        return requests.post(f"https://api.telegram.org/bot{token}/{metodo}", timeout=20, data=data).json()
    except Exception:      # noqa: BLE001
        return {}


def responder(token: str, chat: str, estado: dict, vivos: list, canales: list) -> bool:
    """Si escribiste un comando (o tocaste «Sacar clips») y ClipForge no lo contestó (PC apagado o app
    cerrada), contesta la nube.

    Lee los mensajes pendientes SIN confirmarlos (no se pasa offset), así ClipForge los sigue
    recibiendo al abrirse (y hace lo que pediste con /seguir o el botón). Si ClipForge está
    escuchando, Telegram responde 409 y no se hace nada.
    """
    r = _tg(token, "getUpdates", timeout=0, allowed_updates=json.dumps(["callback_query", "message"]))
    if not r.get("ok"):
        return False                                   # 409: ClipForge está abierto y escuchando
    hechos = set(estado.get("respondidos", []))
    cambiado = False
    dados: set = set()                                 # una sola respuesta por tipo aunque repitas el comando
    for u in r.get("result", []):
        if u["update_id"] in hechos:
            continue
        cq = u.get("callback_query")
        if cq:
            data = str(cq.get("data", ""))
            if not data.startswith("follow|") or str((cq.get("from") or {}).get("id")) != str(chat):
                continue
            hechos.add(u["update_id"])
            cambiado = True
            nombre = handle(data.split("|", 1)[1])
            _tg(token, "answerCallbackQuery", callback_query_id=cq.get("id"),
                text=f"Anotado: al abrir ClipForge empezará con {nombre}"[:190])
            if ("boton", nombre) not in dados:
                dados.add(("boton", nombre))
                _tg(token, "sendMessage", chat_id=chat, parse_mode="HTML",
                    text=f"📝 Anotado: <b>{html.escape(nombre)}</b>. En cuanto abras ClipForge en el PC empezará con él "
                         f"(el pedido vale 12 h).\n{CERRADO}")
            continue
        msg = u.get("message") or {}
        if str((msg.get("chat") or {}).get("id")) != str(chat):
            continue
        texto = (msg.get("text") or "").strip()
        if not texto or time.time() - msg.get("date", 0) < 90:
            continue                                   # dale tiempo a ClipForge a contestar primero
        palabra, _, arg = texto.partition(" ")
        out = respuesta(palabra.lower().lstrip("/").split("@")[0], arg.strip(), texto.lower(), vivos, canales)
        if out is None:
            continue
        hechos.add(u["update_id"])
        cambiado = True
        tipo, texto_r, botones = out
        if tipo in dados:
            continue
        dados.add(tipo)
        datos = {"chat_id": chat, "text": texto_r, "parse_mode": "HTML", "disable_web_page_preview": "true"}
        if botones:
            datos["reply_markup"] = json.dumps({"inline_keyboard": botones})
        _tg(token, "sendMessage", **datos)
    if cambiado:
        estado["respondidos"] = sorted(hechos)[-300:]
    return cambiado


def main():
    prueba = "--prueba" in sys.argv
    token, chat = os.environ.get("TELEGRAM_TOKEN", ""), os.environ.get("TELEGRAM_CHAT_ID", "")
    if not (token and chat):
        prueba = True
    canales = json.loads(CANALES.read_text(encoding="utf-8"))
    if os.environ.get("SALUDO") == "true" and not prueba:
        # ejecución manual con "saludo": confirma que la nube puede escribirte
        requests.post(f"https://api.telegram.org/bot{token}/sendMessage", timeout=20, data={
            "chat_id": chat, "parse_mode": "HTML",
            "text": f"☁️ <b>Avisos desde la nube activos.</b>\nReviso tus {len(canales)} canales cada ~5 min, "
                    "aunque tu PC esté apagado."})
    modos = {c["url"]: c.get("modo", "aviso") for c in canales}
    try:
        estado = json.loads(ESTADO.read_text(encoding="utf-8"))
    except Exception:      # noqa: BLE001
        estado = {"avisados": []}
    avisados = estado.get("avisados", [])
    t0 = time.time()
    vivos = en_directo(list(modos))
    print(f"{len(vivos)} de {len(modos)} en directo ({time.time() - t0:.1f}s): "
          + ", ".join(handle(v["canal"]) for v in vivos))
    nuevos = [v for v in vivos if v["id"] not in avisados]
    if "--sembrar" in sys.argv:
        # primera puesta en marcha: lo que ya está en directo cuenta como avisado (sin spam inicial)
        estado["avisados"] = (avisados + [v["id"] for v in nuevos])[-500:]
        ESTADO.write_text(json.dumps(estado, indent=1), encoding="utf-8")
        print(f"sembrados {len(nuevos)} directos como ya avisados")
        return
    for lv in nuevos:
        texto, teclado = mensaje(lv, modos.get(lv["canal"], "aviso"))
        if prueba:
            print("--- (prueba, no se envía)\n" + re.sub(r"<[^>]+>", "", texto))
            continue
        r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage", timeout=20, data={
            "chat_id": chat, "text": texto, "parse_mode": "HTML", "disable_web_page_preview": "true",
            "reply_markup": json.dumps(teclado)}).json()
        if not r.get("ok"):
            print("Telegram:", r.get("description"))
            continue
        avisados.append(lv["id"])
        print("avisado:", handle(lv["canal"]))
    respondio = False if prueba else responder(token, chat, estado, vivos, canales)
    if (nuevos or respondio) and not prueba:
        estado["avisados"] = avisados[-500:]
        ESTADO.write_text(json.dumps(estado, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
