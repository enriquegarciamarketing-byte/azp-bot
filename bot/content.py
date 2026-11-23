"""Lógica sin red: clasificar, elegir datos de la tarjeta, sanear copy y contacto."""
import html
import os
import re

# nombres de las agencias de origen (secreto AGENCY_NAMES, separados por comas) para no dejarlos en el repo público
AGENCIAS = [a.strip() for a in os.environ.get("AGENCY_NAMES", "").split(",") if a.strip()]
STATUS_RX = re.compile(r"\b(adjudicad[oa]|reservad[oa]|vendid[oa]|ya no est[aá] disponible|cerrad[oa])\b", re.I)


def eur(n, dec=0):
    s = f"{n:,.{dec}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return s


def classify(text):
    """'piso' | 'reservado' | 'otro' (prefiltro barato antes de gastar Gemini)."""
    t = (text or "").strip()
    if not t:
        return "otro"
    if len(t) > 250 and "€" in t:
        return "piso"
    if STATUS_RX.search(t) and len(t) < 400:
        return "reservado"
    return "otro"


def gross_yield(precio, alquiler_mes):
    if precio and alquiler_mes:
        return alquiler_mes * 12 / precio * 100
    return None


def pick_kpis(d):
    """3 tarjetas: precio, alquiler/mes, rentabilidad; si falta alguno, rellena con otros datos."""
    out = []
    if d.get("precio"):
        out.append(("Precio", f"{eur(d['precio'])} €"))
    if d.get("alquiler_mes"):
        out.append(("Alquiler/mes", f"{eur(d['alquiler_mes'])} €"))
    y = d.get("rentabilidad_bruta")
    if y:
        out.append(("Rentab. bruta", f"{eur(y, 1)}%"))
    extras = []
    if d.get("superficie_m2"):
        extras.append(("Superficie", f"{eur(d['superficie_m2'])} m²"))
    if d.get("habitaciones"):
        extras.append(("Habitaciones", str(d["habitaciones"])))
    if d.get("reforma"):
        extras.append(("Reforma", f"{eur(d['reforma'])} €"))
    for e in extras:
        if len(out) >= 3:
            break
        out.append(e)
    while len(out) < 3:
        out.append(("Tipo", "Off market"))
    # rentabilidad siempre en la 3ª tarjeta si existe
    out.sort(key=lambda kv: kv[0] == "Rentab. bruta")
    return out[:3]


def normalize(d):
    """Recalcula la rentabilidad con precio y alquiler (no fiarse del modelo)."""
    y = gross_yield(d.get("precio"), d.get("alquiler_mes"))
    if y:
        d["rentabilidad_bruta"] = round(y, 1)
    return d


def strip_agencies(text):
    t = re.sub(r"https?://\S+|t\.me/\S+|@\w+", "", text)
    if AGENCIAS:
        alt = "|".join(re.escape(a).replace("\\ ", "\\s?") for a in AGENCIAS)
        t = re.sub(rf"\b(de|por parte de)\s+({alt})\b", "de la inmobiliaria", t, flags=re.I)
        t = re.sub(rf"\b({alt})\b", "inmobiliaria", t, flags=re.I)
    return re.sub(r"[ \t]{2,}", " ", t)


EMAIL_RX = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
PHONE_RX = re.compile(r"\+?\d[\d \-]{7,}\d")
REF_RX = re.compile(r"asunto\s*[:\-]?\s*[\"“«']?([^\n\"”»']{2,40})", re.I)


def contact_from_source(text, urls=()):
    """Extracción literal del contacto del post original (respaldo si el modelo falla)."""
    email = EMAIL_RX.search(text or "")
    phone = PHONE_RX.search(text or "")
    wa = next((u for u in urls if "wa.me" in u or "whatsapp" in u), None)
    ref = REF_RX.search(text or "")
    c = {"email": email.group(0) if email else None,
         "telefono": phone.group(0).strip() if phone else None,
         "whatsapp_url": wa,
         "referencia": ref.group(1).strip() if ref else None}
    return c


def contact_block(c):
    e = html.escape
    ref = c.get("referencia")
    tail = f" indicando <b>{e(ref)}</b>" if ref else ""
    lines = []
    if c.get("email"):
        subj = f" con el asunto <b>{e(ref)}</b>" if ref else ""
        lines.append(f"📩 Escribe a {e(c['email'])}{subj}")
    if c.get("whatsapp_url"):
        lines.append(f'📲 <a href="{e(c["whatsapp_url"])}">WhatsApp</a>{tail}')
    elif c.get("telefono") and not c.get("email"):
        lines.append(f"📲 WhatsApp {e(c['telefono'])}{tail}")
    elif c.get("telefono"):
        lines.append(f"📞 {e(c['telefono'])}")
    if not lines:
        return ""
    return "\n".join(lines)


ALLOWED_TAGS = re.compile(r"</?(b|i|u|a)(\s[^>]*)?>")


def safe_html(text):
    """Escapa todo salvo <b>, <i>, <u> y <a href>."""
    parts, last = [], 0
    for m in ALLOWED_TAGS.finditer(text):
        parts.append(html.escape(text[last:m.start()], quote=False))
        parts.append(m.group(0))
        last = m.end()
    parts.append(html.escape(text[last:], quote=False))
    return "".join(parts)


def build_copy(body, contact):
    body = safe_html(strip_agencies(body.strip()))
    block = contact_block(contact)
    return body + ("\n\n" + block if block else "")


def footer_left(d):
    bits = []
    if d.get("habitaciones"):
        bits.append(f"{d['habitaciones']} hab")
    if d.get("superficie_m2"):
        bits.append(f"{eur(d['superficie_m2'])} m²")
    return " · ".join(bits) if bits else "Para inversores"


def group_units(msgs):
    """msgs: lista de dicts {id, date, text, grouped_id, has_media} ordenada por id.
    Junta álbumes (mismo grouped_id) en unidades."""
    units, by_gid = [], {}
    for m in msgs:
        gid = m.get("grouped_id")
        if gid and gid in by_gid:
            u = by_gid[gid]
            u["ids"].append(m["id"])
            if m.get("has_media"):
                u["media_ids"].append(m["id"])
            if m.get("text") and not u["text"]:
                u["text"] = m["text"]
                u["urls"] = m.get("urls", [])
            u["last_date"] = max(u["last_date"], m["date"])
            continue
        u = {"ids": [m["id"]], "media_ids": [m["id"]] if m.get("has_media") else [],
             "text": m.get("text") or "", "urls": m.get("urls", []),
             "date": m["date"], "last_date": m["date"], "reply_to": m.get("reply_to")}
        units.append(u)
        if gid:
            by_gid[gid] = u
    return units


def build_listings(units, now, settle_min=8, after_min=30, before_min=3):
    """Devuelve (eventos listos, id máximo procesable).
    evento = {'tipo': 'piso'|'reservado', 'unit': u, 'media_ids': [...]}"""
    events, ready_upto = [], 0
    i = 0
    n = len(units)
    while i < n:
        u = units[i]
        kind = classify(u["text"])
        if kind == "piso":
            media = []
            # medios justo antes (álbum publicado un instante antes del texto)
            j = i - 1
            if j >= 0 and not units[j]["text"] and units[j]["media_ids"] and \
                    (u["date"] - units[j]["last_date"]).total_seconds() <= before_min * 60 and \
                    not units[j].get("_used"):
                media += units[j]["media_ids"]
                units[j]["_used"] = True
            media += u["media_ids"]
            k, last = i + 1, u["last_date"]
            while k < n and not units[k]["text"] and \
                    (units[k]["date"] - u["date"]).total_seconds() <= after_min * 60:
                media += units[k]["media_ids"]
                units[k]["_used"] = True
                last = max(last, units[k]["last_date"])
                k += 1
            closed = k < n or (now - last).total_seconds() >= settle_min * 60
            if not closed:
                break  # esperar a que terminen de subir fotos
            events.append({"tipo": "piso", "unit": u, "media_ids": media})
            ready_upto = max(ready_upto, max(units[k - 1]["ids"]), max(u["ids"]))
            i = k
            continue
        if kind == "reservado":
            events.append({"tipo": "reservado", "unit": u, "media_ids": []})
        if not u["text"]:
            # medios sueltos: si viene algo detrás, ese algo decide (los adjunta o no);
            # si es lo último del canal y es reciente, esperar por si llega su texto
            if i + 1 >= n and (now - u["last_date"]).total_seconds() < 60 * 60:
                break
            if not u.get("_used") and i + 1 < n:
                i += 1  # no avanzar el estado aún: lo decide la unidad siguiente
                continue
        ready_upto = max(ready_upto, max(u["ids"]))
        i += 1
    return events, ready_upto
