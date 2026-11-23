# AZ Pisos · bot de publicación automática

Cada 10 minutos lee la versión web pública de los canales de origen (sin cuenta de Telegram) y, por cada piso nuevo, publica en tu canal:

1. Imagen AZ Pisos (plantilla roja) con ciudad, titular y precio · alquiler · rentabilidad
2. Copy reescrito para inversores (Gemini, capa gratuita), sin el nombre de la agencia y con su contacto y referencia tal cual
3. Las fotos del inmueble y los vídeos que la web deja descargar (los muy pesados aparecen como "Media is too big" y se omiten)

Si un canal anuncia que un piso que ya publicaste está adjudicado, responde a tu post con 🔴 RESERVADO y lo pone también sobre la imagen. El resto de avisos (artículos, récords…) se ignora.

## Secretos (Settings → Secrets and variables → Actions)

| Secreto | Valor |
|---|---|
| `BOT_TOKEN` | token de @AZPisos_bot (admin del canal con permiso para publicar y editar) |
| `DEST_CHANNEL` | `@tu_canal` (o el id `-100…` si es privado) |
| `SOURCE_CHANNELS` | canales de origen separados por comas |
| `AGENCY_NAMES` | nombres de las agencias a ocultar, separados por comas |
| `GEMINI_API_KEY` | clave de Google AI Studio |

Opcional, en *Variables*: `BACKFILL_MSGS` = 20 hace que la primera ejecución real publique lo que haya en los últimos 20 mensajes de cada canal. Sin ella arranca desde ahora.

## Probar
*Actions* → *AZ Pisos* → *Run workflow*. Con la casilla **prueba** marcada (por defecto) lee los últimos 40 mensajes, redacta y muestra en el log lo que publicaría, **sin publicar nada**. Desmárcala para una ejecución real.

## Notas
- `state.json` guarda qué se ha publicado ya; los nombres de canal y las referencias van cifrados.
- Espera 8 minutos tras cada post de origen antes de publicar, para que terminen de subir los álbumes.
- Si Gemini falla, reintenta en las siguientes ejecuciones (hasta 3 veces) sin dejar el post a medias.
- Plantilla de la imagen: `bot/card.py`. Estilo del copy: `bot/rewrite.py`.
