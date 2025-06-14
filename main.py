import os
import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

# Chargement des cogs
cogs = ["cogs.moderation", "cogs.roles", "cogs.levels", "cogs.twitch_alerts", "cogs.tempvc"]
for cog in cogs:
    bot.load_extension(cog)

@bot.event
async def on_ready():
    print(f"Connecté en tant que {bot.user}")

bot.run(os.getenv("DISCORD_TOKEN"))