"""AZ Pisos: lee los canales de origen y republica en el canal propio.

Orden de publicación por piso: imagen AZ (plantilla A) → copy reescrito → fotos y vídeos.
Se ejecuta cada 10 min desde GitHub Actions. El estado se guarda en tus Mensajes guardados.
"""
import asyncio
import datetime as dt
import json
import os
import re
import sys
import tempfile
from pathlib import Path

from telethon import TelegramClient
from telethon.errors import MessageNotModifiedError
from telethon.sessions import StringSession
from telethon.tl.types import (MessageEntityTextUrl, MessageEntityUrl,
                               MessageMediaDocument, MessageMediaPhoto)

from bot import card, content
from bot.rewrite import rewrite

API_ID = int(os.environ["TG_API_ID"])
API_HASH = os.environ["TG_API_HASH"]
SESSION = os.environ["TG_SESSION"]
BOT_TOKEN = os.environ["BOT_TOKEN"]
DEST = os.environ["DEST_CHANNEL"]
DEST = int(DEST) if re.fullmatch(r"-?\d+", DEST) else DEST
SOURCES = [s.strip().lstrip("@") for s in os.environ["SOURCE_CHANNELS"].split(",") if s.strip()]
BACKFILL = int(os.environ.get("BACKFILL_MSGS", "0") or 0)

STATE_TAG = "#azpisos_state"
RESERVADO_TXT = ("🔴 <b>RESERVADO</b>\n"
                 "Este ya tiene dueño. Activa las notificaciones para no perderte el siguiente 🔔")


def log(*a):
    print(dt.datetime.now().strftime("%H:%M:%S"), *a, flush=True)


# ---------------- estado en Mensajes guardados ----------------
async def load_state(user):
    async for m in user.iter_messages("me", search=STATE_TAG, limit=10):
        if m.raw_text and m.raw_text.startswith(STATE_TAG):
            try:
                return m, json.loads(m.raw_text[len(STATE_TAG):])
            except json.JSONDecodeError:
                pass
    return None, {"last": {}, "posts": [], "fails": {}}


async def save_state(user, msg, state):
    state["posts"] = state["posts"][-45:]
    state["fails"] = dict(list(state["fails"].items())[-20:])
    txt = STATE_TAG + "\n" + json.dumps(state, separators=(",", ":"), ensure_ascii=False)
    while len(txt) > 4000 and state["posts"]:
        state["posts"].pop(0)
        txt = STATE_TAG + "\n" + json.dumps(state, separators=(",", ":"), ensure_ascii=False)
    try:
        if msg:
            await msg.edit(txt, parse_mode=None)
        else:
            await user.send_message("me", txt, parse_mode=None)
    except MessageNotModifiedError:
        pass


# ---------------- lectura ----------------
def has_media(m):
    if isinstance(m.media, MessageMediaPhoto):
        return True
    if isinstance(m.media, MessageMediaDocument) and m.document:
        mime = m.document.mime_type or ""
        return mime.startswith("video/") or mime.startswith("image/")
    return False


def urls_of(m):
    out = []
    for ent, txt in m.get_entities_text():
        if isinstance(ent, MessageEntityTextUrl):
            out.append(ent.url)
        elif isinstance(ent, MessageEntityUrl):
            out.append(txt)
    return out


def to_dict(m):
    return {"id": m.id, "date": m.date, "text": m.raw_text or "",
            "grouped_id": m.grouped_id, "has_media": has_media(m), "urls": urls_of(m),
            "reply_to": m.reply_to.reply_to_msg_id if m.reply_to else None}


# ---------------- publicación ----------------
async def publish_listing(user, bot, src, ev, workdir):
    u = ev["unit"]
    source_text = u["text"]
    if u["urls"]:
        source_text += "\n\nEnlaces del anuncio: " + " ".join(u["urls"])
    data = content.normalize(rewrite(source_text))

    contact = data.get("contacto") or {}
    fallback = content.contact_from_source(u["text"], u["urls"])
    for k, v in fallback.items():
        if not contact.get(k):
            contact[k] = v

    city = data.get("ciudad") or "España"
    prov = data.get("provincia")
    city_line = f"{city} · {prov}" if prov and prov.lower() != city.lower() else city
    card_path = workdir / f"card_{src}_{u['ids'][0]}.jpg"
    problems = card.render(city_line, data["titular"], content.pick_kpis(data),
                           content.footer_left(data), "Info y contacto en el post", card_path)
    if problems:
        log("aviso tarjeta:", problems)

    copy_html = content.build_copy(data["copy"], contact)

    # descargar medios antes de publicar nada (si falla, no queda el post a medias)
    files = []
    if ev["media_ids"]:
        msgs = await user.get_messages(src, ids=ev["media_ids"])
        for m in msgs:
            if m and has_media(m):
                p = await user.download_media(m, file=str(workdir) + "/")
                if p:
                    files.append(p)

    card_msg = await bot.send_file(DEST, str(card_path))
    try:
        copy_msg = await bot.send_message(DEST, copy_html, parse_mode="html", link_preview=False)
    except Exception:  # HTML mal formado: mandar en texto plano
        copy_msg = await bot.send_message(DEST, re.sub(r"<[^>]+>", "", copy_html),
                                          parse_mode=None, link_preview=False)
    for i in range(0, len(files), 10):
        chunk = files[i:i + 10]
        try:
            await bot.send_file(DEST, chunk, supports_streaming=True)
        except Exception as e:  # noqa: BLE001
            log("álbum falló, envío uno a uno:", type(e).__name__)
            for f in chunk:
                try:
                    await bot.send_file(DEST, f, supports_streaming=True)
                except Exception as e2:  # noqa: BLE001
                    log("medio descartado:", type(e2).__name__)

    return {"src": src, "ids": u["ids"] + ev["media_ids"], "card": card_msg.id,
            "copy": copy_msg.id, "ref": (contact.get("referencia") or "").lower()}


async def mark_reserved(bot, state, src, ev):
    u = ev["unit"]
    target = None
    if u.get("reply_to"):
        target = next((p for p in state["posts"] if p["src"] == src and u["reply_to"] in p["ids"]), None)
    if not target:
        low = u["text"].lower()
        target = next((p for p in reversed(state["posts"])
                       if p["src"] == src and p.get("ref") and p["ref"] in low), None)
    if not target or target.get("reservado"):
        return False
    await bot.send_message(DEST, RESERVADO_TXT, parse_mode="html", reply_to=target["card"])
    try:
        orig = await bot.get_messages(DEST, ids=target["copy"])
        if orig and orig.text:
            await bot.edit_message(DEST, target["copy"], "🔴 <b>RESERVADO</b>\n\n" + orig.text,
                                   parse_mode="html", link_preview=False)
    except Exception as e:  # noqa: BLE001
        log("no se pudo editar el copy:", type(e).__name__)
    target["reservado"] = True
    return True


# ---------------- ciclo ----------------
async def run():
    user = TelegramClient(StringSession(SESSION), API_ID, API_HASH)
    bot = TelegramClient(StringSession(), API_ID, API_HASH)
    await user.start()
    await bot.start(bot_token=BOT_TOKEN)
    bot.parse_mode = "html"

    state_msg, state = await load_state(user)
    now = dt.datetime.now(dt.timezone.utc)
    published = 0

    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        for n_src, src in enumerate(SOURCES, 1):
            last = state["last"].get(src)
            if last is None:
                latest = await user.get_messages(src, limit=1)
                last = (latest[0].id if latest else 0) - BACKFILL
                log(f"origen {n_src}: primera ejecución")
            msgs = [to_dict(m) async for m in user.iter_messages(src, min_id=last, reverse=True, limit=300)]
            if not msgs:
                state["last"][src] = last
                continue
            units = content.group_units(msgs)
            events, ready_upto = content.build_listings(units, now)
            new_last = max(last, ready_upto)
            for ev in events:
                key = f"{src}:{ev['unit']['ids'][0]}"
                try:
                    if ev["tipo"] == "piso":
                        state["posts"].append(await publish_listing(user, bot, src, ev, workdir))
                        published += 1
                    else:
                        await mark_reserved(bot, state, src, ev)
                    state["fails"].pop(key, None)
                except Exception as e:  # noqa: BLE001
                    fails = state["fails"].get(key, 0) + 1
                    state["fails"][key] = fails
                    log(f"origen {n_src}: error ({type(e).__name__}: {str(e)[:120]}) intento {fails}")
                    if fails < 3:
                        first = min(ev["unit"]["ids"] + ev["media_ids"])
                        new_last = min(new_last, first - 1)
                        break  # reintentar en la próxima ejecución
            state["last"][src] = new_last
            await save_state(user, state_msg, state)
            if state_msg is None:
                state_msg, _ = await load_state(user)

    log(f"publicados {published}")
    await user.disconnect()
    await bot.disconnect()


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyError as e:
        sys.exit(f"Falta el secreto {e}")
