"""Lectura de canales públicos desde la web t.me/s/<canal> (sin cuenta de Telegram)."""
import datetime as dt
import re

import requests
from bs4 import BeautifulSoup

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/131.0 Safari/537.36",
      "Accept-Language": "es-ES,es;q=0.9"}
BG_RX = re.compile(r"background-image:\s*url\(['\"]?([^'\")]+)['\"]?\)")


def _post_id(href):
    m = re.search(r"/(\d+)(?:\?.*)?$", href or "")
    return int(m.group(1)) if m else None


def _text(node):
    if node is None:
        return "", []
    for br in node.find_all("br"):
        br.replace_with("\n")
    urls = [a.get("href") for a in node.find_all("a") if a.get("href")]
    return node.get_text().strip(), urls


def parse_page(html):
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for w in soup.select("div.tgme_widget_message[data-post]"):
        pid = _post_id("/" + w["data-post"])
        if pid is None:
            continue
        t = w.select_one("time[datetime]")
        date = dt.datetime.fromisoformat(t["datetime"]) if t else None
        text, urls = _text(w.select_one(".tgme_widget_message_text"))
        media, ids, skipped, thumbs = [], [pid], 0, []
        for a in w.select("a.tgme_widget_message_photo_wrap, a.tgme_widget_message_video_player"):
            mid = _post_id(a.get("href")) or pid
            if mid not in ids:
                ids.append(mid)
            if "tgme_widget_message_photo_wrap" in a.get("class", []):
                m = BG_RX.search(a.get("style", ""))
                if m:
                    url = m.group(1)
                    media.append({"type": "photo", "url": "https:" + url if url.startswith("//") else url})
            else:
                vid = next((v for v in a.select("video[src]") if "blured" not in v.get("class", [])), None)
                if vid:
                    media.append({"type": "video", "url": vid["src"]})
                else:
                    skipped += 1  # "Media is too big": la web no da el vídeo
                    th = a.select_one("i.tgme_widget_message_video_thumb")
                    m = BG_RX.search(th.get("style", "")) if th else None
                    if m and m.group(1).startswith(("http", "//")):
                        u = m.group(1)
                        thumbs.append({"type": "photo", "url": "https:" + u if u.startswith("//") else u})
        reply = w.select_one("a.tgme_widget_message_reply")
        out.append({"id": pid, "ids": sorted(ids), "date": date, "text": text, "urls": urls,
                    "media": media, "skipped_videos": skipped, "thumbs": thumbs,
                    "has_media": bool(media) or skipped > 0,
                    "reply_to": _post_id(reply.get("href")) if reply else None})
    return out


def fetch_channel(channel, after_id, max_pages=6):
    """Mensajes con id > after_id, del más antiguo al más nuevo."""
    msgs, before = {}, None
    for _ in range(max_pages):
        url = f"https://t.me/s/{channel}" + (f"?before={before}" if before else "")
        r = requests.get(url, headers=UA, timeout=30)
        r.raise_for_status()
        page = parse_page(r.text)
        if not page:
            break
        for m in page:
            msgs[m["id"]] = m
        oldest = min(m["id"] for m in page)
        if after_id is not None and oldest <= after_id:
            break
        if after_id is None:  # primera ejecución: con la última página basta
            break
        before = oldest
    return [msgs[k] for k in sorted(msgs) if after_id is None or k > after_id]


def download(url, path):
    with requests.get(url, headers=UA, timeout=120, stream=True) as r:
        r.raise_for_status()
        with open(path, "wb") as f:
            for chunk in r.iter_content(1 << 16):
                f.write(chunk)
    return path
