"""Ejecútalo UNA vez en tu ordenador para conectar la cuenta SECUNDARIA de Telegram (solo lectura de canales).

    py -m pip install telethon
    py generar_sesion.py

Te pedirá api_id, api_hash, el número de la cuenta secundaria y el código que le llega.
La cadena que imprime es la llave de esa cuenta: guárdala SOLO como secreto TG_SESSION en GitHub.
"""
from telethon.sessions import StringSession
from telethon.sync import TelegramClient

api_id = int(input("api_id: ").strip())
api_hash = input("api_hash: ").strip()
with TelegramClient(StringSession(), api_id, api_hash) as client:
    me = client.get_me()
    print(f"\nConectado como: {me.first_name} (+{me.phone})")
    print("\n=== TG_SESSION (cópiala entera, no la compartas con nadie) ===\n")
    print(client.session.save())
    input("\nPulsa Enter para cerrar...")
