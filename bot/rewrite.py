"""Reescritura del post con Gemini (capa gratuita)."""
import json
import os
import re
import time
import requests

API = "https://generativelanguage.googleapis.com/v1beta/"
_model_cache = {}
preferred = {"model": None}  # el último que funcionó (se guarda en state.json)


def pick_models(api_key):
    """Modelos Flash disponibles, del preferido al de reserva (Google retira y satura versiones)."""
    if os.environ.get("GEMINI_MODEL"):
        return [os.environ["GEMINI_MODEL"]]
    if "m" in _model_cache:
        return _model_cache["m"]
    r = requests.get(API + "models", headers={"x-goog-api-key": api_key},
                     params={"pageSize": 200}, timeout=30)
    r.raise_for_status()
    names = [m["name"].split("/", 1)[1] for m in r.json().get("models", [])
             if "generateContent" in m.get("supportedGenerationMethods", [])]
    bad = ("image", "tts", "audio", "live", "thinking", "exp", "embedding", "8b", "native")

    def ver(n):
        nums = re.findall(r"\d+(?:\.\d+)?", n)
        return float(nums[0]) if nums else 0

    flash = [n for n in names if "flash" in n and not any(b in n for b in bad)]
    full = sorted([n for n in flash if "lite" not in n and "preview" not in n], key=ver, reverse=True)
    prev = sorted([n for n in flash if "lite" not in n and "preview" in n], key=ver, reverse=True)
    lite = sorted([n for n in flash if "lite" in n], key=ver, reverse=True)
    order = []
    for n in (["gemini-flash-latest"] if "gemini-flash-latest" in names else []) + full + prev + \
            (["gemini-flash-lite-latest"] if "gemini-flash-lite-latest" in names else []) + lite:
        if n not in order:
            order.append(n)
    order = order or names[:3]
    _model_cache["m"] = order
    print("modelos Gemini:", ", ".join(order[:5]), flush=True)
    return order


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
- Va como pie de foto de la imagen: MÁXIMO 800 caracteres en total contando emojis, espacios y saltos de línea. Es un límite duro de Telegram.
- Prioriza lo que decide la inversión: ubicación, precio, alquiler, rentabilidad, reforma, honorarios. Fuera relleno, adjetivos y repeticiones.
- Español de España, cercano y fácil de entender para alguien que no es experto, pero serio. Párrafos cortos.
- Estructura:
  1) Primera línea: 🏠 <b>Ciudad · titular descriptivo</b>
  2) Una o dos frases cortas describiendo el piso y por qué la zona tiene demanda (solo con lo que diga el anuncio).
  3) 💰 <b>Precio X €</b>
  4) 📊 <b>Los números</b> y debajo una línea por dato con su emoji (🛏 alquiler por habitaciones, 🔑 alquiler tradicional, 🔨 reforma, 🧾 gastos fijos IBI y comunidad, 🏦 hipoteca si la detalla). Pon la rentabilidad bruta calculada como alquiler anual / precio, con un decimal.
  5) 👉 <b>En cristiano</b> una frase que traduzca la rentabilidad a algo tangible (por cada 100.000 € invertidos…).
  6) ✅ servicios que ofrezcan (llave en mano, firma a distancia, financiación…) en una sola línea, si los hay.
  7) 🤝 Honorarios de la inmobiliaria X € + IVA, si aparecen. Plazos de escritura o reserva si aparecen.
- NO incluyas datos de contacto, email, teléfono, referencia ni llamadas a escribir: se añaden después automáticamente.
- NUNCA nombres a la inmobiliaria de origen ({agencias}) ni a ninguna otra. Di "la inmobiliaria". Nada de enlaces ni @.
- No reproduzcas frases del original: redacta con tus palabras. Sin guiones largos.

ANUNCIO ORIGINAL:
"""


def rewrite(source_text, api_key=None):
    api_key = api_key or os.environ["GEMINI_API_KEY"]
    body = {
        "contents": [{"parts": [{"text": PROMPT.replace("{agencias}", os.environ.get("AGENCY_NAMES", "la de origen"))
                                  + source_text}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.6},
    }
    errors = []
    models = pick_models(api_key)
    if preferred["model"] in models:
        models = [preferred["model"]] + [m for m in models if m != preferred["model"]]
    for model in models[:6]:
        for attempt in range(2):
            try:
                r = requests.post(API + f"models/{model}:generateContent",
                                  headers={"x-goog-api-key": api_key}, json=body, timeout=120)
            except requests.RequestException as e:
                errors.append(f"{model}: {type(e).__name__}")
                break
            if r.status_code == 429 and attempt == 0:
                time.sleep(15)
                continue
            if r.status_code != 200:
                errors.append(f"{model}: HTTP {r.status_code}")
                break  # saturado, retirado o sin cuota: probar el siguiente modelo
            try:
                txt = r.json()["candidates"][0]["content"]["parts"][-1]["text"]
                data = json.loads(txt[txt.find("{"):txt.rfind("}") + 1])
            except Exception as e:  # noqa: BLE001
                errors.append(f"{model}: respuesta no válida ({type(e).__name__})")
                break
            if data.get("es_piso") is False:
                return data
            if data.get("copy") and data.get("titular"):
                print("redactado con", model, flush=True)
                preferred["model"] = model
                return data
            errors.append(f"{model}: JSON incompleto")
            break
    raise RuntimeError("Gemini falló: " + "; ".join(errors)[:300])
