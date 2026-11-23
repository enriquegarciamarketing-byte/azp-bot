"""Reescritura del post con Gemini (capa gratuita)."""
import json
import os
import re
import time
import requests

API = "https://generativelanguage.googleapis.com/v1beta/"
_model_cache = {}


def pick_model(api_key):
    """Elige el Gemini Flash disponible (Google retira versiones cada pocos meses)."""
    if os.environ.get("GEMINI_MODEL"):
        return os.environ["GEMINI_MODEL"]
    if "m" in _model_cache:
        return _model_cache["m"]
    r = requests.get(API + "models", headers={"x-goog-api-key": api_key},
                     params={"pageSize": 200}, timeout=30)
    r.raise_for_status()
    names = [m["name"].split("/", 1)[1] for m in r.json().get("models", [])
             if "generateContent" in m.get("supportedGenerationMethods", [])]
    bad = ("image", "tts", "audio", "live", "lite", "thinking", "exp", "preview", "embedding", "8b")
    flash = [n for n in names if "flash" in n and not any(b in n for b in bad)]
    if "gemini-flash-latest" in names:
        choice = "gemini-flash-latest"
    elif flash:
        def ver(n):
            nums = re.findall(r"\d+(?:\.\d+)?", n)
            return float(nums[0]) if nums else 0
        choice = sorted(flash, key=ver)[-1]
    else:
        choice = next((n for n in names if "flash" in n), names[0])
    _model_cache["m"] = choice
    print("modelo Gemini:", choice, flush=True)
    return choice

PROMPT = """Eres el redactor del canal de Telegram AZ Pisos, que comparte pisos off market para inversores particulares.
Te paso el anuncio original de una inmobiliaria. Devuelve SOLO un JSON válido con esta forma:

{
  "es_piso": true,
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
- es_piso: true solo si el anuncio presenta UN inmueble concreto en venta con su precio. false si es un artículo, una noticia, un aviso de reserva/adjudicación, un récord o publicidad del canal (en ese caso el resto de campos puede ir a null).
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
            url = API + f"models/{pick_model(api_key)}:generateContent"
            r = requests.post(url, headers={"x-goog-api-key": api_key}, json=body, timeout=90)
            if r.status_code in (429, 500, 503):
                time.sleep(20 * (attempt + 1))
                last = f"HTTP {r.status_code}"
                continue
            r.raise_for_status()
            txt = r.json()["candidates"][0]["content"]["parts"][0]["text"]
            data = json.loads(txt)
            if data.get("es_piso") is False:
                return data
            if not data.get("copy") or not data.get("titular"):
                raise ValueError("JSON incompleto")
            return data
        except Exception as e:  # noqa: BLE001
            last = re.sub(r"https?://\S+", "[url]", str(e))[:200]
            time.sleep(5)
    raise RuntimeError(f"Gemini falló: {last}")
