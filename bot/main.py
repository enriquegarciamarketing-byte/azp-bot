"""AZ Pisos: lee los canales públicos de origen (web t.me/s) y republica en el canal propio.

Orden por piso: imagen AZ (plantilla A) → copy reescrito → fotos y vídeos.
Se ejecuta cada 10 min desde GitHub Actions. El estado vive en state.json (con nombres cifrados).
"""
import datetime as dt
import hashlib
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path

import requests

from bot import card, content, web_reader
from bot import rewrite as rw
from bot.rewrite import rewrite

ROOT = Path(__file__).resolve().parent.parent
STATE_FILE = ROOT / "state.json"
MODE = os.environ.get("MODE", "").strip().lower() or "real"   # real | prueba | privado
DRY = MODE == "prueba"
PREVIEW = MODE == "privado"

RESERVADO_TXT = ("🔴 <b>RESERVADO</b>\n"
                 "Este ya tiene dueño. Activa las notificaciones para no perderte el siguiente 🔔")


def env(name):
    v = os.environ.get(name, "").strip()
    if not v:
        sys.exit(f"Falta el secreto {name}")
    return v


def h(s):
    return hashlib.sha256(s.lower().encode()).hexdigest()[:12]


def log(*a):
    txt = " ".join(str(x) for x in a)
    txt = re.sub(r"https?://\S+", "[url]", txt)  # nunca enseñar tokens ni claves en el log público
    print(dt.datetime.now().strftime("%H:%M:%S"), txt, flush=True)


# ---------------- Bot API ----------------
class Bot:
    def __init__(self, token, chat):
        self.base = f"https://api.telegram.org/bot{token}/"
        self.chat = chat

    def call(self, method, data=None, files=None):
        for attempt in range(4):
            r = requests.post(self.base + method, data=data, files=files, timeout=300)
            j = r.json()
            if j.get("ok"):
                return j["result"]
            retry = (j.get("parameters") or {}).get("retry_after")
            if retry and attempt < 3:
                time.sleep(retry + 1)
                continue
            raise RuntimeError(f"{method}: {j.get('description')}")

    def photo(self, path, caption=None):
        with open(path, "rb") as f:
            d = {"chat_id": self.chat}
            if caption:
                d.update(caption=caption, parse_mode="HTML")
            return self.call("sendPhoto", d, {"photo": f})

    def text(self, html, reply_to=None):
        d = {"chat_id": self.chat, "text": html, "parse_mode": "HTML",
             "link_preview_options": json.dumps({"is_disabled": True})}
        if reply_to:
            d["reply_parameters"] = json.dumps({"message_id": reply_to})
        try:
            return self.call("sendMessage", d)
        except RuntimeError:
            d.update(text=re.sub(r"<[^>]+>", "", html))
            d.pop("parse_mode")
            return self.call("sendMessage", d)

    def album(self, items):
        """items: [(tipo, ruta)] máx. 10."""
        if len(items) == 1:
            kind, path = items[0]
            with open(path, "rb") as f:
                m = "sendPhoto" if kind == "photo" else "sendVideo"
                extra = {} if kind == "photo" else {"supports_streaming": "true"}
                return self.call(m, {"chat_id": self.chat, **extra}, {kind: f})
        media, files = [], {}
        for i, (kind, path) in enumerate(items):
            media.append({"type": kind, "media": f"attach://f{i}"})
            files[f"f{i}"] = open(path, "rb")
        try:
            return self.call("sendMediaGroup", {"chat_id": self.chat, "media": json.dumps(media)}, files)
        finally:
            for f in files.values():
                f.close()

    def caption(self, msg_id, html):
        return self.call("editMessageCaption", {"chat_id": self.chat, "message_id": msg_id,
                                                "caption": html, "parse_mode": "HTML"})


def private_chat(token):
    """Chat privado de quien haya escrito /start al bot (para el modo privado)."""
    fixed = os.environ.get("PREVIEW_CHAT", "").strip()
    if fixed:
        return fixed
    api = f"https://api.telegram.org/bot{token}/"
    me = requests.get(api + "getMe", timeout=30).json()
    log("bot conectado:", "@" + (me.get("result") or {}).get("username", "?") if me.get("ok") else me.get("description"))
    wh = requests.get(api + "getWebhookInfo", timeout=30).json().get("result") or {}
    if wh.get("url"):
        log("ojo: este bot tiene un webhook activo, así que otro programa recibe sus mensajes")
    r = requests.get(api + "getUpdates", timeout=30).json()
    if not r.get("ok"):
        log("getUpdates:", r.get("description"))
    chats = [u["message"]["chat"]["id"] for u in r.get("result", [])
             if u.get("message", {}).get("chat", {}).get("type") == "private"]
    log(f"mensajes privados pendientes: {len(chats)}")
    if not chats:
        sys.exit("No encuentro tu /start: escribe /start a este bot y vuelve a lanzar el modo privado")
    return chats[-1]


# ---------------- estado ----------------
def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"last": {}, "posts": [], "fails": {}}


def save_state(state):
    state["posts"] = state["posts"][-80:]
    state["fails"] = dict(list(state["fails"].items())[-30:])
    STATE_FILE.write_text(json.dumps(state, indent=1, ensure_ascii=False) + "\n")


# ---------------- piso ----------------
def publish_listing(bot, src_h, ev, workdir):
    u = ev["unit"]
    source_text = u["text"] + ("\n\nEnlaces del anuncio: " + " ".join(u["urls"]) if u["urls"] else "")
    data = rewrite(source_text)
    if data.get("es_piso") is False:
        log("descartado: no es un piso")
        return None
    data = content.normalize(data)

    contact = data.get("contacto") or {}
    for k, v in content.contact_from_source(u["text"], u["urls"]).items():
        if not contact.get(k):
            contact[k] = v

    city, prov = data.get("ciudad") or "España", data.get("provincia")
    city_line = f"{city} · {prov}" if prov and prov.lower() != city.lower() else city
    card_path = workdir / f"card_{u['ids'][0]}.jpg"
    problems = card.render(city_line, data["titular"], content.pick_kpis(data),
                           content.footer_left(data), "Info y contacto en el post", card_path)
    if problems:
        log("aviso tarjeta:", problems)
    copy_html = content.build_copy(data["copy"], contact)

    # descargar medios antes de publicar nada
    files = []
    for i, m in enumerate(ev["media"]):
        ext = "mp4" if m["type"] == "video" else "jpg"
        try:
            files.append((m["type"], web_reader.download(m["url"], workdir / f"m{u['ids'][0]}_{i}.{ext}")))
        except Exception as e:  # noqa: BLE001
            log("medio no descargado:", type(e).__name__)

    if DRY:
        log(f"[prueba] piso: {city_line} | {data['titular']} | {len(files)} medios | copy {len(copy_html)} car.")
        print(copy_html[:600])
        return {"s": src_h, "ids": [], "card": 0, "ref": "", "t": int(time.time()), "dry": True}

    card_msg = bot.photo(card_path)
    bot.text(copy_html)
    for i in range(0, len(files), 10):
        chunk = files[i:i + 10]
        try:
            bot.album(chunk)
        except Exception as e:  # noqa: BLE001
            log("álbum falló, uno a uno:", str(e)[:80])
            for it in chunk:
                try:
                    bot.album([it])
                except Exception as e2:  # noqa: BLE001
                    log("medio descartado:", str(e2)[:80])
    ref = (contact.get("referencia") or "").strip()
    return {"s": src_h, "ids": ev.get("all_ids", u["ids"]),
            "card": card_msg["message_id"], "ref": h(ref) if ref else "", "t": int(time.time())}


def mark_reserved(bot, state, src_h, ev):
    u = ev["unit"]
    mine = [p for p in state["posts"] if p["s"] == src_h and not p.get("dry")]
    target = None
    if u.get("reply_to"):
        target = next((p for p in mine if u["reply_to"] in p["ids"]), None)
    if not target:  # ¿menciona la referencia de algún piso?
        low = u["text"].lower()
        for p in reversed(mine):
            if p.get("ref") and any(h(c) == p["ref"] for c in re.findall(r"[\wÀ-ÿ]+(?:[ -]\w+)?", low)):
                target = p
                break
    if not target and re.search(r"[uú]ltim", u["text"], re.I):  # "último piso adjudicado"
        recent = [p for p in mine if time.time() - p["t"] < 21 * 86400]
        target = recent[-1] if recent else None
    if not target or target.get("r"):
        return
    if DRY:
        log("[prueba] marcaría como reservado el post", target["card"])
        return
    bot.text(RESERVADO_TXT, reply_to=target["card"])
    try:
        bot.caption(target["card"], "🔴 <b>RESERVADO</b>")
    except Exception as e:  # noqa: BLE001
        log("no se pudo marcar la imagen:", str(e)[:80])
    target["r"] = True


# ---------------- ciclo ----------------
def run():
    sources = [s.strip().lstrip("@") for s in env("SOURCE_CHANNELS").split(",") if s.strip()]
    if DRY:
        bot = None
    elif PREVIEW:
        token = env("BOT_TOKEN")
        bot = Bot(token, private_chat(token))
    else:
        bot = Bot(env("BOT_TOKEN"), env("DEST_CHANNEL"))
    env("GEMINI_API_KEY")
    backfill = int(os.environ.get("BACKFILL_MSGS") or 0)
    state = load_state()
    rw.preferred["model"] = state.get("gemini")
    now = dt.datetime.now(dt.timezone.utc)
    published = 0

    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        for n_src, src in enumerate(sources, 1):
            key = h(src)
            last = state["last"].get(key)
            if last is None or DRY or PREVIEW:
                page = web_reader.fetch_channel(src, None)
                newest = max((m["id"] for m in page), default=0)
                last = newest - (40 if (DRY or PREVIEW) else backfill)
                log(f"origen {n_src}: modo {MODE}, desde {last}")
            msgs = web_reader.fetch_channel(src, last)
            units = content.units_from_web(msgs)
            events, ready_upto = content.build_listings(units, now)
            log(f"origen {n_src}: {len(msgs)} mensajes nuevos, {len(events)} eventos")
            new_last = max(last, ready_upto)
            if PREVIEW:  # solo el último piso de cada canal, como muestra
                pisos = [e for e in events if e["tipo"] == "piso"]
                events = pisos[-1:]
            for ev in events:
                fkey = f"{key}:{ev['unit']['ids'][0]}"
                try:
                    if ev["tipo"] == "piso":
                        post = publish_listing(bot, key, ev, workdir)
                        if post:
                            state["posts"].append(post)
                            published += 1
                    else:
                        mark_reserved(bot, state, key, ev)
                    state["fails"].pop(fkey, None)
                except Exception as e:  # noqa: BLE001
                    fails = state["fails"].get(fkey, 0) + 1
                    state["fails"][fkey] = fails
                    log(f"origen {n_src}: error {type(e).__name__}: {str(e)[:150]} (intento {fails})")
                    if fails < 3:
                        new_last = min(new_last, min(ev.get("all_ids") or ev["unit"]["ids"]) - 1)
                        break
            state["last"][key] = new_last
    if MODE == "real":
        if rw.preferred["model"]:
            state["gemini"] = rw.preferred["model"]
        save_state(state)
    log(f"publicados {published}")


if __name__ == "__main__":
    run()
