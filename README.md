# AZ Pisos · bot de publicación automática

Cada 10 minutos revisa los canales de origen y, por cada piso nuevo, publica en tu canal:

1. Imagen AZ Pisos (plantilla roja) con ciudad, titular y precio · alquiler · rentabilidad
2. Copy reescrito para inversores (Gemini, capa gratuita), sin el nombre de la agencia y con su contacto y referencia tal cual
3. Las fotos y vídeos del inmueble a calidad original

Si un canal anuncia que un piso que ya publicaste está adjudicado o reservado, responde a tu post con 🔴 RESERVADO y lo marca en el copy. El resto de avisos se ignora.

## Puesta en marcha (una sola vez, unos 15 min)

**1. Bot nuevo**
En Telegram abre @BotFather, envía `/newbot` y ponle nombre (p. ej. AZ Pisos Bot). Guarda el token.
Añade el bot como **administrador** de tu canal AZ Pisos con permiso para publicar y editar mensajes.

**2. Acceso de lectura con tu cuenta**
Entra en https://my.telegram.org con tu número, ve a *API development tools* y crea una app (nombre libre). Te da `api_id` y `api_hash`.
En tu ordenador:
```
pip install telethon
python tools/generar_sesion.py
```
Mete api_id, api_hash, tu número y el código que te llega. Copia la cadena larga que imprime: es la llave de tu cuenta, **solo** va en el secreto `TG_SESSION`.

**3. Repo en GitHub**
Crea un repo **público** con un nombre neutro (p. ej. `azp-bot`) y sube esta carpeta. Público = minutos de Actions ilimitados y gratis. Los canales de origen y las llaves van en secretos, así que no se ven.

**4. Secretos** (Settings → Secrets and variables → Actions → New repository secret)

| Secreto | Valor |
|---|---|
| `TG_API_ID` | el api_id |
| `TG_API_HASH` | el api_hash |
| `TG_SESSION` | la cadena del paso 2 |
| `BOT_TOKEN` | el token de @BotFather |
| `DEST_CHANNEL` | `@tu_canal` (o el id `-100…` si es privado) |
| `SOURCE_CHANNELS` | `pisaliaes,propex_oportunidades_rentables` |
| `AGENCY_NAMES` | `Pisalia,PropeX,Prop Ex` |
| `GEMINI_API_KEY` | la misma clave de Gemini que usa el bot de AZ Inversión |

Opcional, en la pestaña *Variables*: `BACKFILL_MSGS` = 15 para que la primera ejecución publique lo que haya en los últimos 15 mensajes de cada canal. Sin ella arranca desde ahora y solo publica lo nuevo.

**5. Probar**
Consejo: pon primero en `DEST_CHANNEL` un canal privado de pruebas. Pestaña *Actions* → *AZ Pisos* → *Run workflow*. Cuando te guste, cambia el secreto a tu canal real.

## Notas
- El estado (qué se ha publicado ya) se guarda en un mensaje de tus **Mensajes guardados** que empieza por `#azpisos_state`. No lo borres; si lo borras, el bot vuelve a empezar desde "ahora".
- Espera 8 minutos tras cada post de origen antes de publicar, para que terminen de subir todos los álbumes.
- Si Gemini falla, reintenta en las siguientes ejecuciones (hasta 3 veces) sin dejar el post a medias.
- Plantilla de la imagen: `bot/card.py`. Estilo del copy: `bot/rewrite.py`.
