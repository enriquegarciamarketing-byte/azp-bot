"""Reescritura del post con Gemini (capa gratuita)."""
import json
import os
import time
import requests

MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"

PROMPT = """Eres el redactor del canal de Telegram AZ Pisos, que comparte pisos off market para inversores particulares.
Te paso el anuncio original de una inmobiliaria. Devuelve SOLO un JSON válido con esta forma:

{
  "ciudad": "Oviedo",
  "provincia": "Asturias",
  "titular": "4 habitaciones en Oviedo rentando un 14%",
  "precio": 116900,
  "alquiler_mes": 1370,
  "superficie_m2": 85,
  "habitaciones": 4,
  "reforma": 4200,
  "contacto": {"email": null, "telefono": "+34 672 581 622", "whatsapp_url": null, "referencia": "REF 516"},
  "copy": "..."
}

Reglas de datos
- Números como enteros en euros, sin puntos ni símbolos. Usa null si el dato no aparece. No inventes nada.
- alquiler_mes es el alquiler principal del anuncio (si hay varias opciones, la más rentable que el anuncio presente como viable).
- reforma es lo que hay que invertir en reforma o adecuación/amueblado para esa opción de alquiler.
- titular: máximo 42 caracteres, gancho para inversor, con el dato estrella (rentabilidad redondeada, precio o ubicación). Sin emojis.
- contacto: copia LITERALMENTE el email, teléfono, enlace de WhatsApp y la referencia o asunto que el anuncio pide indicar al contactar (p. ej. "REF 56"). No lo cambies.

Reglas del copy (texto para Telegram en HTML, solo etiquetas <b> e <i>)
- Español de España, cercano y fácil de entender para alguien que no es experto, pero serio. Párrafos cortos.
- Estructura:
  1) Primera línea: 🏠 <b>Ciudad · titular descriptivo</b>
  2) Dos o tres frases describiendo el piso y por qué la zona tiene demanda (solo con lo que diga el anuncio).
  3) 💰 <b>Precio X €</b>
  4) 📊 <b>Los números</b> y debajo una línea por dato con su emoji (🛏 alquiler por habitaciones, 🔑 alquiler tradicional, 🔨 reforma, 🧾 gastos fijos IBI y comunidad, 🏦 hipoteca si la detalla). Pon la rentabilidad bruta calculada como alquiler anual / precio, con un decimal.
  5) 👉 <b>En cristiano</b> una frase que traduzca la rentabilidad a algo tangible (por cada 100.000 € invertidos…).
  6) ✅ servicios que ofrezcan (llave en mano, firma a distancia, financiación…), si los hay.
  7) 🤝 Honorarios de la inmobiliaria X € + IVA, si aparecen. Plazos de escritura o reserva si aparecen.
- NO incluyas datos de contacto, email, teléfono, referencia ni llamadas a escribir: se añaden después automáticamente.
- NUNCA nombres a la inmobiliaria de origen ({agencias}) ni a ninguna otra. Di "la inmobiliaria". Nada de enlaces ni @.
- No reproduzcas frases del original: redacta con tus palabras. Sin guiones largos.

ANUNCIO ORIGINAL:
"""


def rewrite(source_text, api_key=None, retries=3):
    api_key = api_key or os.environ["GEMINI_API_KEY"]
    body = {
        "contents": [{"parts": [{"text": PROMPT.replace("{agencias}", os.environ.get("AGENCY_NAMES", "la de origen"))
                                  + source_text}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.6},
    }
    last = None
    for attempt in range(retries):
        try:
            r = requests.post(URL, params={"key": api_key}, json=body, timeout=90)
            if r.status_code in (429, 500, 503):
                time.sleep(20 * (attempt + 1))
                last = f"HTTP {r.status_code}"
                continue
            r.raise_for_status()
            txt = r.json()["candidates"][0]["content"]["parts"][0]["text"]
            data = json.loads(txt)
            if not data.get("copy") or not data.get("titular"):
                raise ValueError("JSON incompleto")
            return data
        except Exception as e:  # noqa: BLE001
            last = str(e)[:200]
            time.sleep(5)
    raise RuntimeError(f"Gemini falló: {last}")
