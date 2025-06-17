import os
import asyncio
import aiohttp
from dotenv import load_dotenv

load_dotenv()

TWITCH_CLIENT_ID = os.getenv("TWITCH_CLIENT_ID")
TWITCH_CLIENT_SECRET = os.getenv("TWITCH_CLIENT_SECRET")
TWITCH_STREAMER_LOGIN = os.getenv("TWITCH_STREAMER_LOGIN")
WEBHOOK_CALLBACK_URL = os.getenv("WEBHOOK_CALLBACK_URL")  # L'URL publique de ton webhook Railway

async def get_oauth_token():
    url = "https://id.twitch.tv/oauth2/token"
    params = {
        "client_id": TWITCH_CLIENT_ID,
        "client_secret": TWITCH_CLIENT_SECRET,
        "grant_type": "client_credentials"
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(url, params=params) as resp:
            data = await resp.json()
            return data.get("access_token")

async def get_user_id(token):
    url = f"https://api.twitch.tv/helix/users?login={TWITCH_STREAMER_LOGIN}"
    headers = {
        "Client-ID": TWITCH_CLIENT_ID,
        "Authorization": f"Bearer {token}"
    }
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as resp:
            data = await resp.json()
            return data["data"][0]["id"]

async def create_eventsub_subscription(token, user_id, type_, callback_url):
    url = "https://api.twitch.tv/helix/eventsub/subscriptions"
    headers = {
        "Client-ID": TWITCH_CLIENT_ID,
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    json_data = {
        "type": type_,
        "version": "1",
        "condition": {
            "broadcaster_user_id": user_id
        },
        "transport": {
            "method": "webhook",
            "callback": callback_url,
            "secret": "monsecretpourverifier"  # À changer, voir plus bas
        }
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, json=json_data) as resp:
            resp_data = await resp.json()
            print(f"Création abonnement {type_} :", resp_data)

async def main():
    token = await get_oauth_token()
    user_id = await get_user_id(token)

    # Types d’événements que tu veux suivre
    event_types = [
        "channel.follow",           # Nouveau follower
        "channel.subscribe"         # Nouvel abonné (t1, t2, t3 inclus)
    ]

    for event_type in event_types:
        await create_eventsub_subscription(token, user_id, event_type, WEBHOOK_CALLBACK_URL)

if __name__ == "__main__":
    asyncio.run(main())
