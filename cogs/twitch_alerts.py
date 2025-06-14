from discord.ext import tasks, commands
import os
import requests

class TwitchAlerts(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.check_live_status.start()
        self.is_live = False

    def get_headers(self):
        return {
            "Client-ID": os.getenv("TWITCH_CLIENT_ID"),
            "Authorization": f"Bearer {self.get_access_token()}"
        }

    def get_access_token(self):
        url = "https://id.twitch.tv/oauth2/token"
        params = {
            "client_id": os.getenv("TWITCH_CLIENT_ID"),
            "client_secret": os.getenv("TWITCH_SECRET"),
            "grant_type": "client_credentials"
        }
        response = requests.post(url, params=params)
        return response.json()["access_token"]

    @tasks.loop(minutes=1)
    async def check_live_status(self):
        streamer = os.getenv("STREAMER_NAME")
        channel_id = int(os.getenv("ALERT_CHANNEL_ID"))
        url = f"https://api.twitch.tv/helix/streams?user_login={streamer}"
        response = requests.get(url, headers=self.get_headers())

        data = response.json().get("data", [])
        channel = self.bot.get_channel(channel_id)

        if data and not self.is_live:
            await channel.send(f"🔴 **{streamer} est en live !**
https://twitch.tv/{streamer}")
            self.is_live = True
        elif not data:
            self.is_live = False

def setup(bot):
    bot.add_cog(TwitchAlerts(bot))