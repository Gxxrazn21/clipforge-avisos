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


def main():
    prueba = "--prueba" in sys.argv
    token, chat = os.environ.get("TELEGRAM_TOKEN", ""), os.environ.get("TELEGRAM_CHAT_ID", "")
    if not (token and chat):
        prueba = True
    canales = json.loads(CANALES.read_text(encoding="utf-8"))
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
    if nuevos and not prueba:
        estado["avisados"] = avisados[-500:]
        ESTADO.write_text(json.dumps(estado, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
