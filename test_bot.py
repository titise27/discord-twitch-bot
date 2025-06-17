import os
import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

intents = discord.Intents.default()
intents.message_content = True  # Important pour recevoir les commandes

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"Connecté en tant que {bot.user} ({bot.user.id})")

@bot.command()
async def ping(ctx):
    await ctx.send("Pong!")

if __name__ == "__main__":
    TOKEN = os.getenv("DISCORD_TOKEN")
    if not TOKEN:
        print("❌ DISCORD_TOKEN manquant dans .env")
    else:
        bot.run(TOKEN)