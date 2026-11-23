"""Ejecútalo UNA vez en tu ordenador para conectar tu cuenta de Telegram (solo lectura de canales).

    pip install telethon
    python tools/generar_sesion.py

Te pedirá api_id, api_hash, tu número y el código que te llega por Telegram.
La cadena que imprime es la llave de tu cuenta: guárdala SOLO como secreto TG_SESSION en GitHub.
"""
from telethon.sessions import StringSession
from telethon.sync import TelegramClient

api_id = int(input("api_id: ").strip())
api_hash = input("api_hash: ").strip()
with TelegramClient(StringSession(), api_id, api_hash) as client:
    print("\n=== TG_SESSION (cópiala entera, no la compartas con nadie) ===\n")
    print(client.session.save())
