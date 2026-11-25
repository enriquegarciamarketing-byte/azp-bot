"""Lectura con una cuenta de Telegram (secundaria): da los vídeos completos, no solo los cortos."""
import os

from telethon.sessions import StringSession
from telethon.sync import TelegramClient
from telethon.tl.types import (MessageEntityTextUrl, MessageEntityUrl,
                               MessageMediaDocument, MessageMediaPhoto)

MAX_VIDEO_BYTES = 1_500_000_000  # no bajar vídeos absurdamente grandes


def connect():
    """Devuelve un cliente conectado o None si no hay sesión válida (se usará la web pública)."""
    sess = os.environ.get("TG_SESSION", "").strip()
    api_id = os.environ.get("TG_API_ID", "").strip()
    api_hash = os.environ.get("TG_API_HASH", "").strip()
    if not (sess and api_id and api_hash):
        return None
    client = TelegramClient(StringSession(sess), int(api_id), api_hash)
    client.connect()
    if not client.is_user_authorized():
        client.disconnect()
        return None
    return client


def _kind(m):
    if isinstance(m.media, MessageMediaPhoto):
        return "photo"
    if isinstance(m.media, MessageMediaDocument) and m.document:
        mime = m.document.mime_type or ""
        if mime.startswith("video/"):
            return "video" if (m.document.size or 0) <= MAX_VIDEO_BYTES else None
        if mime.startswith("image/"):
            return "photo"
    return None


def _urls(m):
    out = []
    for ent, txt in m.get_entities_text():
        if isinstance(ent, MessageEntityTextUrl):
            out.append(ent.url)
        elif isinstance(ent, MessageEntityUrl):
            out.append(txt)
    return out


class TgReader:
    def __init__(self, client):
        self.client = client

    def fetch_channel(self, channel, after_id):
        """Mismo formato que web_reader.fetch_channel (álbumes agrupados en un mensaje)."""
        if after_id is None:
            raw = list(reversed(self.client.get_messages(channel, limit=40)))
        else:
            raw = list(self.client.iter_messages(channel, min_id=after_id, reverse=True, limit=300))
        out, by_gid = [], {}
        for m in raw:
            if m is None or getattr(m, "action", None):
                continue
            kind = _kind(m)
            item = {"type": kind, "msg": m} if kind else None
            gid = m.grouped_id
            if gid and gid in by_gid:
                d = by_gid[gid]
                d["ids"].append(m.id)
                if item:
                    d["media"].append(item)
                if m.raw_text and not d["text"]:
                    d["text"], d["urls"] = m.raw_text, _urls(m)
                d["has_media"] = d["has_media"] or bool(item)
                continue
            d = {"id": m.id, "ids": [m.id], "date": m.date, "text": m.raw_text or "",
                 "urls": _urls(m), "media": [item] if item else [], "skipped_videos": 0,
                 "thumbs": [], "has_media": bool(item),
                 "reply_to": m.reply_to.reply_to_msg_id if m.reply_to else None}
            out.append(d)
            if gid:
                by_gid[gid] = d
        return out

    def download(self, media, path):
        p = self.client.download_media(media["msg"], file=str(path))
        if not p:
            raise RuntimeError("descarga vacía")
        return p
