import discord
from discord.ext import commands
import os

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ID du salon lobby à modifier par le tien
LOBBY_VOICE_CHANNEL_ID = 1383427337277935631

@bot.event
async def on_ready():
    print(f"✅ Connecté en tant que {bot.user}")

@bot.event
async def on_voice_state_update(member, before, after):
    # Création du salon temporaire
    if after.channel and after.channel.id == LOBBY_VOICE_CHANNEL_ID:
        guild = member.guild
        category = after.channel.category

        temp_channel = await guild.create_voice_channel(
            name=f"🎮 {member.display_name}",
            category=category,
            user_limit=5,  # tu peux changer
            reason="Salon temporaire auto"
        )

        await member.move_to(temp_channel)

    # Suppression du salon temporaire vide
    if before.channel and before.channel != after.channel:
        if before.channel.members == [] and "🎮" in before.channel.name:
            try:
                await before.channel.delete(reason="Salon temporaire vide")
            except Exception as e:
                print(f"Erreur suppression salon : {e}")

@bot.command()
async def rename(ctx, *, new_name: str):
    """Renommer son salon temporaire"""
    if ctx.author.voice and ctx.author.voice.channel:
        vc = ctx.author.voice.channel
        if "🎮" in vc.name:
            try:
                await vc.edit(name=f"🎮 {new_name}")
                await ctx.send(f"✅ Salon renommé en **{new_name}**")
            except Exception as e:
                await ctx.send(f"❌ Erreur : {e}")
        else:
            await ctx.send("Tu n'es pas dans un salon temporaire.")
    else:
        await ctx.send("Tu dois être dans un salon vocal.")

# Utilise une variable d'environnement
import os
bot.run(os.getenv("MTM4MzQzNTU0NTk5MjEwMjA2OQ.GHF5v-.aTu7zoZYQYMNwXTv9SbHSyvKC5G_QJTjILgrtk"))
