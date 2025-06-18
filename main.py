import os
import sys
import time
import json
import random
import logging
import asyncio
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import discord
from discord import ui
from discord.ext import commands, tasks
from aiohttp import web, ClientSession
from dotenv import load_dotenv

# --- Chargement et configuration ---
load_dotenv()
logging.basicConfig(level=logging.INFO)

# --- Bot Discord ---
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.voice_states = True
intents.reactions = True
bot = commands.Bot(command_prefix="!", intents=intents)

# --- Variables d’environnement ---
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
TEMP_VC_TRIGGER_ID = int(os.getenv("TEMP_VC_TRIGGER_ID", 0))
SQUAD_VC_CATEGORY_ID = int(os.getenv("SQUAD_VC_CATEGORY_ID", 0))
SQUAD_ANNOUNCE_CHANNEL_ID = int(os.getenv("SQUAD_ANNOUNCE_CHANNEL_ID", 0))
OWNER_ID = int(os.getenv("OWNER_ID", 0))
MEMBRE_ROLE_ID = int(os.getenv("MEMBRE_ROLE_ID", 0))
REGLEMENT_CHANNEL_ID = int(os.getenv("REGLEMENT_CHANNEL_ID", 0))
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID", 0))
LOG_ARRIVANTS_CHANNEL_ID = int(os.getenv("LOG_ARRIVANTS_CHANNEL_ID", 0))
LOG_CHANNEL_UPDATE_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_UPDATE_CHANNEL_ID", 0))
GUIDE_CHANNEL_ID = int(os.getenv("GUIDE_CHANNEL_ID", 0))

TWITCH_CLIENT_ID = os.getenv("TWITCH_CLIENT_ID")
TWITCH_CLIENT_SECRET = os.getenv("TWITCH_CLIENT_SECRET")
TWITCH_STREAMER_LOGIN = os.getenv("TWITCH_STREAMER_LOGIN")
TWITCH_ALERT_CHANNEL_ID = int(os.getenv("TWITCH_ALERT_CHANNEL_ID", 0))
TWITCH_FOLLOWER_ROLE_ID = int(os.getenv("TWITCH_FOLLOWER_ROLE_ID", 0))
TWITCH_SUB_T1_ROLE_ID = int(os.getenv("TWITCH_SUB_T1_ROLE_ID", 0))
TWITCH_SUB_T2_ROLE_ID = int(os.getenv("TWITCH_SUB_T2_ROLE_ID", 0))
TWITCH_SUB_T3_ROLE_ID = int(os.getenv("TWITCH_SUB_T3_ROLE_ID", 0))

TWITTER_BEARER_TOKEN = os.getenv("TWITTER_BEARER_TOKEN")
TWITTER_USERNAME = os.getenv("TWITTER_USERNAME")
TWITTER_ALERT_CHANNEL_ID = int(os.getenv("TWITTER_ALERT_CHANNEL_ID", 0))
TWITTER_USER_URL = f"https://api.twitter.com/2/users/by/username/{TWITTER_USERNAME}"

twitter_headers = {"Authorization": f"Bearer {TWITTER_BEARER_TOKEN}"}

WEBHOOK_HOST = os.getenv("WEBHOOK_HOST", "0.0.0.0")
WEBHOOK_PORT = int(os.getenv("PORT", 8080))

UTC = timezone.utc
DATA_FILE = "data.json"

# --- Variables globales ---
twitch_monitor = None
twitter_user_id = None

# --- Gestion persistante ---
def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    return {
        "linked_accounts": {},
        "reglement_message_id": None,
        "guide_message_id": None,
        "twitter_posted_tweets": [],
        "xp": {},
        "giveaways": {},
        "tickets": {},
        "polls": {},
        "twitch_subscribers": {}
    }

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

data = load_data()

# --- Fonctions de log — fiabilisées ---
async def log_to_discord(message: str):
    channel = bot.get_channel(LOG_CHANNEL_ID)
    if channel is None:
        try:
            channel = await bot.fetch_channel(LOG_CHANNEL_ID)
        except discord.NotFound:
            logging.error(f"Salon de logs introuvable (ID {LOG_CHANNEL_ID})")
            return
    await channel.send(f"📌 {message}")

async def log_to_specific_channel(channel_id: int, message: str):
    channel = bot.get_channel(channel_id)
    if channel is None:
        try:
            channel = await bot.fetch_channel(channel_id)
        except discord.NotFound:
            logging.error(f"Salon {channel_id} introuvable")
            return
    await channel.send(message)

# --- Gestion Twitter avec back-off sur 429 ---
async def fetch_twitter_user_id():
    async with ClientSession() as session:
        async with session.get(TWITTER_USER_URL, headers=twitter_headers) as resp:
            if resp.status == 429:
                reset_ts = resp.headers.get("x-rate-limit-reset")
                if reset_ts:
                    wait = max(int(reset_ts) - int(time.time()), 0)
                    await asyncio.sleep(wait + 1)
                    return await fetch_twitter_user_id()
                return None
            if resp.status != 200:
                return None
            data_json = await resp.json()
            return data_json.get("data", {}).get("id")

async def fetch_latest_tweets(user_id, since_id=None):
    url = f"https://api.twitter.com/2/users/{user_id}/tweets"
    params = {"max_results": 5, "tweet.fields": "created_at"}
    if since_id:
        params["since_id"] = since_id
    async with ClientSession() as session:
        async with session.get(url, headers=twitter_headers, params=params) as resp:
            if resp.status == 429:
                reset_ts = resp.headers.get("x-rate-limit-reset")
                if reset_ts:
                    wait = max(int(reset_ts) - int(time.time()), 0)
                    await asyncio.sleep(wait + 1)
                    return await fetch_latest_tweets(user_id, since_id)
                return []
            if resp.status != 200:
                return []
            data = await resp.json()
            return data.get("data", [])

# --- Envoi et mise à jour du guide tutoriel ---
async def envoyer_guide_tuto():
    channel = bot.get_channel(GUIDE_CHANNEL_ID)
    if not channel:
        return
    guide_id = data.get("guide_message_id")
    if guide_id:
        try:
            old = await channel.fetch_message(guide_id)
            await old.unpin()
            await old.delete()
        except:
            pass
        data["guide_message_id"] = None
        save_data(data)
    path = "assets/squad-guide.png"
    if not os.path.exists(path):
        return
    with open(path, "rb") as f:
        file = discord.File(f, filename="squad-guide.png")
        msg = await channel.send("📌 **Voici le guide pour créer une squad**", file=file)
    try:
        await msg.pin()
    except:
        pass
    data["guide_message_id"] = msg.id
    save_data(data)

# --- Règlement et vue du bouton ---
reglement_texte = """
📜 **・Règlement du serveur Discord**
... (ton texte complet) ...
"""

class ReglementView(ui.View):
    def __init__(self, client_id, redirect_uri):
        super().__init__(timeout=None)
        self.client_id = client_id
        self.redirect_uri = redirect_uri

    @ui.button(label="✅ J'accepte", style=discord.ButtonStyle.green, custom_id="accept_reglement")
    async def accept(self, interaction: discord.Interaction, button: ui.Button):
        role = interaction.guild.get_role(MEMBRE_ROLE_ID)
        if role and role not in interaction.user.roles:
            await interaction.user.add_roles(role)
        query = urlencode({
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": "user:read:email",
            "state": str(interaction.user.id)
        })
        twitch_url = f"https://id.twitch.tv/oauth2/authorize?{query}"
        await interaction.response.send_message(f"✅ Règlement accepté !\n🔗 {twitch_url}", ephemeral=True)

@bot.command()
@commands.has_permissions(administrator=True)
async def reglement(ctx):
    embed = discord.Embed(title="Règlement du serveur", description=reglement_texte, color=discord.Color.blue())
    view = ReglementView(TWITCH_CLIENT_ID, os.getenv("REDIRECT_URI"))
    msg = await ctx.send(embed=embed, view=view)
    data["reglement_message_id"] = msg.id
    save_data(data)

# --- Commandes modération et logs d’événements ---
@bot.command(name="kick")
@commands.has_permissions(kick_members=True)
async def kick(ctx, member: discord.Member, *, reason: str=None):
    await member.kick(reason=reason)
    await ctx.send(f"👢 {member} expulsé. Raison : {reason or 'Non spécifiée'}")
    await log_to_discord(f"{member} a été expulsé. Raison : {reason or 'Non spécifiée'}")

@bot.command(name="ban")
@commands.has_permissions(ban_members=True)
async def ban(ctx, member: discord.Member, *, reason: str=None):
    await member.ban(reason=reason)
    await ctx.send(f"🔨 {member} banni. Raison : {reason or 'Non spécifiée'}")
    await log_to_discord(f"{member} a été banni. Raison : {reason or 'Non spécifiée'}")

# --- Événements pour logs d’arrivants et changements de salons ---
@bot.event
async def on_member_join(member):
    await log_to_specific_channel(LOG_ARRIVANTS_CHANNEL_ID, f"👋 {member.mention} a rejoint le serveur.")

@bot.event
async def on_member_remove(member):
    await log_to_discord(f"👋 {member.name} a quitté le serveur.")

@bot.event
async def on_guild_channel_update(before, after):
    if before.name != after.name:
        await log_to_specific_channel(LOG_CHANNEL_UPDATE_CHANNEL_ID, f"🛠️ `{before.name}` renommé en `{after.name}`.")

@bot.event
async def on_message_delete(message):
    if message.author.bot or not message.guild:
        return
    await log_to_discord(f"🗑️ Message supprimé de {message.author.mention} dans {message.channel.mention} : `{message.content}`")

@bot.event
async def on_message_edit(before, after):
    if before.author.bot or not before.guild:
        return
    if before.content != after.content:
        await log_to_discord(f"✏️ Message modifié par {before.author.mention} dans {before.channel.mention}\nAvant: `{before.content}`\nAprès: `{after.content}`")

# --- Votre on_ready avec enregistrement de la vue du règlement ---
@bot.event
async def on_ready():
    # Enregistrement persistant de la vue pour le bouton règlement
    bot.add_view(ReglementView(TWITCH_CLIENT_ID, os.getenv("REDIRECT_URI")))

    logging.info(f"Connecté : {bot.user} ({bot.user.id})")
    await log_to_discord("✅ Bot connecté et prêt !")

    # Démarrage des tâches
    cleanup_empty_vcs.start()
    check_giveaways.start()
    twitch_check_loop.start()
    twitter_check_loop.start()
    await envoyer_guide_tuto()

    # Initialisation TwitchMonitor & Twitter
    global twitch_monitor, twitter_user_id
    if all([TWITCH_CLIENT_ID, TWITCH_CLIENT_SECRET, TWITCH_STREAMER_LOGIN, TWITCH_ALERT_CHANNEL_ID]):
        twitch_monitor = TwitchMonitor(TWITCH_CLIENT_ID, TWITCH_CLIENT_SECRET, TWITCH_STREAMER_LOGIN, TWITCH_ALERT_CHANNEL_ID)
    if TWITTER_BEARER_TOKEN and TWITTER_USERNAME:
        twitter_user_id = await fetch_twitter_user_id()

# --- Squad management ---
class SquadJoinButton(ui.View):
    def __init__(self, vc, max_members):
        super().__init__(timeout=None)
        self.vc = vc
        self.max_members = max_members
        self.message = None

    @ui.button(label="Rejoindre", style=discord.ButtonStyle.primary, custom_id="join_squad")
    async def join(self, interaction: discord.Interaction, button: ui.Button):
        member = interaction.user
        if member.voice and member.voice.channel == self.vc:
            return await interaction.response.send_message("Tu es déjà dans cette squad.", ephemeral=True)
        if len(self.vc.members) >= self.max_members:
            button.disabled = True
            if self.message:
                await self.message.edit(view=self)
            return await interaction.response.send_message("Cette squad est pleine.", ephemeral=True)
        await member.move_to(self.vc)
        await interaction.response.send_message(f"Tu as rejoint {self.vc.name} !", ephemeral=True)
        if len(self.vc.members) >= self.max_members:
            button.disabled = True
            await self.message.edit(view=self)

@bot.command()
async def squad(ctx, max_players: int=None, *, game_name: str=None):
    if not max_players or not game_name:
        return await ctx.send("Usage: !squad <nombre> <jeu>")
    category = ctx.guild.get_channel(SQUAD_VC_CATEGORY_ID)
    if category is None:
        return await ctx.send("Catégorie des salons vocaux introuvable.")
    suffix = random.randint(1000, 9999)
    vc_name = f"{game_name} - Squad {ctx.author.display_name} ({suffix})"
    vc = await ctx.guild.create_voice_channel(name=vc_name, category=category, user_limit=max_players)
    try:
        await ctx.author.move_to(vc)
    except:
        pass
    view = SquadJoinButton(vc, max_members=max_players)
    embed = discord.Embed(
        title=vc.name,
        description=f"Jeu : **{game_name}**\nMax joueurs : {max_players}",
        color=discord.Color.green()
    )
    announce = bot.get_channel(SQUAD_ANNOUNCE_CHANNEL_ID)
    msg = await (announce or ctx).send(embed=embed, view=view)
    view.message = msg

# --- Tâches récurrentes ---
@tasks.loop(minutes=1)
async def cleanup_empty_vcs():
    guild = bot.guilds[0] if bot.guilds else None
    if not guild:
        return
    category = guild.get_channel(SQUAD_VC_CATEGORY_ID)
    if not category:
        return
    for vc in category.voice_channels:
        if not vc.members:
            try:
                await vc.delete()
            except Exception as e:
                logging.error(f"Erreur suppression salon vide: {e}")

@tasks.loop(seconds=30)
async def check_giveaways():
    now = datetime.now(
