import discord
from discord.ext import commands
from dotenv import load_dotenv
import os
import json

load_dotenv()

intents = discord.Intents.default()
intents.messages = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"Connecté en tant que {bot.user}")

@bot.command()
async def ping(ctx):
    await ctx.send("Pong!")

if __name__ == "__main__":
    TOKEN = os.getenv("DISCORD_TOKEN")
    if not TOKEN:
        print("❌ Le token DISCORD_TOKEN est manquant dans les variables d'environnement.")
    else:
        bot.run(TOKEN)