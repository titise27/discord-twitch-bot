import os
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

# --- Configuration des intents et du bot ---
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.voice_states = True
intents.reactions = True
bot = commands.Bot(command_prefix="!", intents=intents)

print("🚀 main.py chargé (version mise à jour)")

# --- Chargement et configuration ---
load_dotenv()
logging.basicConfig(level=logging.INFO)

# --- Variables d’environnement ---
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID", 0))
SQUAD_VC_CATEGORY_ID = int(os.getenv("SQUAD_VC_CATEGORY_ID", 0))
SQUAD_ANNOUNCE_CHANNEL_ID = int(os.getenv("SQUAD_ANNOUNCE_CHANNEL_ID", 0))
MEMBRE_ROLE_ID = int(os.getenv("MEMBRE_ROLE_ID", 0))
GUIDE_CHANNEL_ID = int(os.getenv("GUIDE_CHANNEL_ID", 0))
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID", 0))
LOG_ARRIVANTS_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ARRIVANTS_CHANNEL_ID", 0))
LOG_CHANNEL_UPDATE_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_UPDATE_CHANNEL_ID", 0))

TWITCH_CLIENT_ID = os.getenv("TWITCH_CLIENT_ID")
TWITCH_CLIENT_SECRET = os.getenv("TWITCH_CLIENT_SECRET")
TWITCH_STREAMER_LOGIN = os.getenv("TWITCH_STREAMER_LOGIN")
TWITCH_ALERT_CHANNEL_ID = int(os.getenv("TWITCH_ALERT_CHANNEL_ID", 0))
TWITCH_FOLLOWER_ROLE_ID = int(os.getenv("TWITCH_FOLLOWER_ROLE_ID", 0))

TWITTER_BEARER_TOKEN = os.getenv("TWITTER_BEARER_TOKEN")
TWITTER_USERNAME = os.getenv("TWITTER_USERNAME")
TWITTER_ALERT_CHANNEL_ID = int(os.getenv("TWITTER_ALERT_CHANNEL_ID", 0))
TWITTER_USER_URL = f"https://api.twitter.com/2/users/by/username/{TWITTER_USERNAME}"

WEBHOOK_HOST = os.getenv("WEBHOOK_HOST", "0.0.0.0")
WEBHOOK_PORT = int(os.getenv("PORT", 8080))

UTC = timezone.utc
DATA_FILE = "data.json"

# --- Persistence des données ---
def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    return {
        "linked_accounts": {},
        "reglement_message_id": None,
        "guide_message_id": None,
        "twitter_posted_tweets": [],
        "giveaways": {},
        "tickets": {},
        "polls": {},
        "twitch_subscribers": {},
        "active_squads": {}
    }

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

data = load_data()

# --- Fonctions de log ---
async def log_to_discord(message: str):
    channel = bot.get_channel(LOG_CHANNEL_ID)
    if not channel:
        try:
            channel = await bot.fetch_channel(LOG_CHANNEL_ID)
        except discord.NotFound:
            logging.error(f"Salon de logs introuvable (ID {LOG_CHANNEL_ID})")
            return
    await channel.send(f"📌 {message}")

async def log_to_specific_channel(channel_id: int, message: str):
    channel = bot.get_channel(channel_id)
    if not channel:
        try:
            channel = await bot.fetch_channel(channel_id)
        except discord.NotFound:
            logging.error(f"Salon {channel_id} introuvable")
            return
    await channel.send(message)

# --- Twitter utils ---
async def fetch_twitter_user_id():
    async with ClientSession() as session:
        async with session.get(TWITTER_USER_URL, headers={"Authorization": f"Bearer {TWITTER_BEARER_TOKEN}"}) as resp:
            if resp.status == 429:
                reset = resp.headers.get("x-rate-limit-reset")
                if reset:
                    await asyncio.sleep(max(int(reset) - int(time.time()), 0) + 1)
                    return await fetch_twitter_user_id()
                return None
            if resp.status != 200:
                return None
            return (await resp.json()).get("data", {}).get("id")

async def fetch_latest_tweets(user_id, since_id=None):
    params = {"max_results": 5, "tweet.fields": "created_at"}
    if since_id:
        params["since_id"] = since_id
    async with ClientSession() as session:
        async with session.get(f"https://api.twitter.com/2/users/{user_id}/tweets",
                               headers={"Authorization": f"Bearer {TWITTER_BEARER_TOKEN}"}, params=params) as resp:
            if resp.status == 429:
                reset = resp.headers.get("x-rate-limit-reset")
                if reset:
                    await asyncio.sleep(max(int(reset) - int(time.time()), 0) + 1)
                    return await fetch_latest_tweets(user_id, since_id)
                return []
            if resp.status != 200:
                return []
            return (await resp.json()).get("data", [])

# --- Guide tutoriel ---
async def envoyer_guide_tuto():
    channel = bot.get_channel(GUIDE_CHANNEL_ID)
    if not channel:
        return
    if data.get("guide_message_id"):
        try:
            old = await channel.fetch_message(data["guide_message_id"])
            await old.unpin()
            await old.delete()
        except:
            pass
    path = "assets/squad-guide.png"
    if os.path.exists(path):
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
reglement_texte = (
    "📜 **・Règlement du serveur Discord**\n"
    "1. Respect.\n"
    "2. Pas de spam.\n"
    "..."
)

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
        q = urlencode({"client_id": self.client_id, "redirect_uri": self.redirect_uri,
                       "response_type": "code", "scope": "user:read:email", "state": str(interaction.user.id)})
        url = f"https://id.twitch.tv/oauth2/authorize?{q}"
        await interaction.response.send_message(f"✅ Règlement accepté !\n🔗 {url}", ephemeral=True)

@bot.command()
@commands.has_permissions(administrator=True)
async def reglement(ctx: commands.Context):
    embed = discord.Embed(title="Règlement du serveur", description=reglement_texte, color=discord.Color.blue())
    view = ReglementView(TWITCH_CLIENT_ID, os.getenv("REDIRECT_URI"))
    msg = await ctx.send(embed=embed, view=view)
    data["reglement_message_id"] = msg.id
    save_data(data)

# --- Modération commands ---
@bot.command(name="kick")
@commands.has_permissions(kick_members=True)
async def kick(ctx: commands.Context, member: discord.Member, *, reason: str=None):
    await member.kick(reason=reason)
    await ctx.send(f"👢 {member} expulsé. Raison : {reason or 'Non spécifiée'}")
    await log_to_discord(f"{member} expulsé. Raison : {reason or 'Non spécifiée'}")

@bot.command(name="ban")
@commands.has_permissions(ban_members=True)
async def ban(ctx: commands.Context, member: discord.Member, *, reason: str=None):
    await member.ban(reason=reason)
    await ctx.send(f"🔨 {member} banni. Raison : {reason or 'Non spécifiée'}")
    await log_to_discord(f"{member} banni. Raison : {reason or 'Non spécifiée'}")

@bot.command()
@commands.has_permissions(manage_messages=True)
async def clear(ctx: commands.Context, amount: int=5):
    deleted = await ctx.channel.purge(limit=amount+1)
    await ctx.send(f"🧹 {len(deleted)-1} messages supprimés.", delete_after=3)

@bot.command(name="link")
@commands.has_permissions(administrator=True)
async def link(ctx: commands.Context, *, url: str=None):
    if not url:
        return await ctx.send("❌ Utilisation: !link <url>")
    await ctx.author.send(f"🔗 Voici ton lien : {url}")
    await ctx.send("✅ Lien envoyé en MP !")

# --- Logs d’événements ---
@bot.event
async def on_member_join(member: discord.Member):
    await log_to_specific_channel(LOG_ARRIVANTS_CHANNEL_ID, f"👋 {member.mention} a rejoint")

@bot.event
async def on_member_remove(member: discord.Member):
    await log_to_discord(f"👋 {member.name} a quitté")

@bot.event
async def on_guild_channel_update(before, after):
    if before.name != after.name:
        await log_to_specific_channel(LOG_CHANNEL_UPDATE_CHANNEL_ID, f"🛠️ {before.name} -> {after.name}")

@bot.event
async def on_message_delete(msg: discord.Message):
    if not msg.author.bot:
        await log_to_discord(f"🗑️ Supprimé: {msg.author}: {msg.content}")

@bot.event
async def on_message_edit(before, after):
    if not before.author.bot and before.content != after.content:
        await log_to_discord(f"✏️ Édité par {before.author} dans {before.channel}\nAvant: {before.content}\nAprès: {after.content}")

# --- on_ready: envoi bouton squad ---
@bot.event
async def on_ready():
    print(f"✅ Connecté en tant que {bot.user}")
    SQUAD_TEXT_CHANNEL_ID = int(os.getenv("SQUAD_TEXT_CHANNEL_ID", 0))
    if channel:
        button = ui.Button(label="Créer un squad", style=discord.ButtonStyle.primary, custom_id="create_squad")
        view = ui.View()
        view.add_item(button)
        await channel.send("Clique sur le bouton pour créer un squad :", view=view)
        print(f"🎮 Bouton envoyé dans le salon {CHANNEL_ID}")
    bot.add_view(ReglementView(TWITCH_CLIENT_ID, os.getenv("REDIRECT_URI")))
    cleanup_empty_vcs.start()
    check_giveaways.start()
    twitch_check_loop.start()
    twitter_check_loop.start()
    await envoyer_guide_tuto()

# --- Modal et interaction ---
class SquadModal(ui.Modal, title="Créer ton squad"):
    squad_name = ui.TextInput(label="Nom du salon", placeholder="Ex: SquadAlpha", required=True)
    squad_players = ui.TextInput(label="Nombre de joueurs (1, 2 ou 3)", placeholder="Ex: 2", required=True)

    async def on_submit(self, interaction: discord.Interaction):
        players = self.squad_players.value
        if players not in ['1','2','3']:
            return await interaction.response.send_message("❌ Indique 1, 2 ou 3.", ephemeral=True)
        await interaction.channel.send(f"!squad {players} {self.squad_name.value}")
        await interaction.response.send_message(
            f"✅ Commande envoyée : !squad {players} {self.squad_name.value}", ephemeral=True
        )

@bot.event
async def on_interaction(interaction: discord.Interaction):
    if interaction.type == discord.InteractionType.component and interaction.data.get("custom_id") == "create_squad":
        await interaction.response.send_modal(SquadModal())

# --- Commande squad ---
@bot.command()
async def squad(ctx: commands.Context, max_players: int=None, *, game_name: str=None):
    if not max_players or not game_name:
        return await ctx.send("Usage: !squad <n> <jeu>")
    category = ctx.guild.get_channel(SQUAD_VC_CATEGORY_ID)
    if not category:
        return await ctx.send("Catégorie introuvable.")
    suffix = random.randint(1000,9999)
    vc_name = f"{game_name} - Squad {ctx.author.display_name} ({suffix})"
    vc = await ctx.guild.create_voice_channel(
        name=vc_name, category=category, user_limit=max_players
    )
    try:
        await ctx.author.move_to(vc)
    except:
        pass
    view = SquadJoinButton(vc, max_players)
    embed = discord.Embed(
        title=vc.name,
        description=(
            f"🎮 Jeu : **{game_name}**\n"
            f"👥 Joueurs : 0/{max_players}\n\n"
            "👤 Aucun pour l'instant"
        ),
        color=discord.Color.green()
    )
    announce_channel = bot.get_channel(SQUAD_ANNOUNCE_CHANNEL_ID) or ctx.channel
    msg = await announce_channel.send(embed=embed, view=view)
    view.message = msg
    data.setdefault("active_squads", {})[str(vc.id)] = {
        "channel_id": announce_channel.id,
        "message_id": msg.id
    }
    save_data(data)

class SquadJoinButton(ui.View):
    def __init__(self, vc: discord.VoiceChannel, max_members: int):
        super().__init__(timeout=None)
        self.vc = vc
        self.max_members = max_members
        self.message: discord.Message = None

    @ui.button(label="Rejoindre", style=discord.ButtonStyle.primary, custom_id="join_squad")
    async def join(self, interaction: discord.Interaction, button: ui.Button):
        user = interaction.user
        if user.voice and user.voice.channel == self.vc:
            return await interaction.response.send_message("Tu es déjà dans cette squad.", ephemeral=True)
        players = [m for m in self.vc.members if not m.bot]
        if len(players) >= self.max_members:
            button.disabled = True
            if self.message:
                await self.message.edit(view=self)
            return await interaction.response.send_message("Cette squad est pleine.", ephemeral=True)
        await user.move_to(self.vc)
        await interaction.response.send_message(f"Tu as rejoint **{self.vc.name}** !", ephemeral=True)
        await asyncio.sleep(1)
        players = [m for m in self.vc.members if not m.bot]
        lines = [
            f"🎮 Jeu : **{self.vc.name.split(' - ')[0]}**",
            f"👥 Joueurs : {len(players)}/{self.max_members}",
            "",
            "👤 Membres :"
        ] + [f"• {p.display_name}" for p in players]
        embed = discord.Embed(title=self.vc.name, description="\n".join(lines), color=discord.Color.green())
        if self.message:
            await self.message.edit(embed=embed, view=self)
        if not players or len(players) >= self.max_members:
            if self.message:
                try:
                    await self.message.delete()
                except:
                    pass
            try:
                await self.vc.delete()
            except:
                pass
            data.get("active_squads", {}).pop(str(self.vc.id), None)
            save_data(data)

# --- Tâches récurrentes ---
@tasks.loop(minutes=1)
async def cleanup_empty_vcs():
    guild = bot.guilds[0] if bot.guilds else None
    if guild:
        cat = guild.get_channel(SQUAD_VC_CATEGORY_ID)
        if cat:
            for vc in cat.voice_channels:
                if not vc.members:
                    await vc.delete()

@tasks.loop(seconds=30)
async def check_giveaways():
    now = datetime.now(UTC)
    for gid, g in list(data.get("giveaways", {}).items()):
        if now >= datetime.fromisoformat(g.get("end_time", now.isoformat())):
            ch = bot.get_channel(g.get("channel_id", 0))
            if ch:
                try:
                    msg = await ch.fetch_message(g.get("message_id", 0))
                except:
                    data["giveaways"].pop(gid, None)
                    continue
                users = [
                    u for r in msg.reactions if str(r.emoji) == "🎉"
                    for u in await r.users().flatten() if not u.bot
                ]
                if users:
                    await ch.send(f"🎊 {random.choice(users).mention} a gagné {g.get('prize','')}")
                else:
                    await ch.send("Personne...")
            data["giveaways"].pop(gid, None)
            save_data(data)

@tasks.loop(minutes=1)
async def twitch_check_loop():
    if twitch_monitor:
        await twitch_monitor.check_stream()

@tasks.loop(minutes=2)
async def twitter_check_loop():
    ch = bot.get_channel(TWITTER_ALERT_CHANNEL_ID)
    if ch and twitter_user_id:
        since = max(data.get("twitter_posted_tweets", ["0"]))
        for tw in reversed(await fetch_latest_tweets(twitter_user_id, since_id=since)):
            if tw.get("id") not in data.get("twitter_posted_tweets", []):
                url = f"https://twitter.com/{TWITTER_USERNAME}/status/{tw.get('id')}"
                await ch.send(f"🐦 Nouveau tweet ({tw.get('created_at')}): {tw.get('text')}\n{url}")
                data.setdefault("twitter_posted_tweets", []).append(tw.get("id"))
                save_data(data)

# --- TwitchMonitor ---
class TwitchMonitor:
    def __init__(self, client_id, client_secret, streamer_login, alert_channel_id):
        self.client_id = client_id
        self.client_secret = client_secret
        self.streamer_login = streamer_login
        self.alert_channel_id = alert_channel_id
        self.token = None
        self.token_expiry = None
        self.last_live = False
        self.session = None

    async def get_token(self):
        self.session = ClientSession()
        resp = await self.session.post(
            "https://id.twitch.tv/oauth2/token",
            params={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "grant_type": "client_credentials"
            }
        )
        d = await resp.json()
        self.token = d.get("access_token")
        self.token_expiry = datetime.now(UTC) + timedelta(seconds=d.get("expires_in", 3600))

    async def check_stream(self):
        if not self.token or datetime.now(UTC) >= self.token_expiry:
            await self.get_token()
        h = {"Client-ID": self.client_id, "Authorization": f"Bearer {self.token}"}
        resp = await self.session.get(
            f"https://api.twitch.tv/helix/streams?user_login={self.streamer_login}", headers=h
        )
        data_json = await resp.json()
        streams = data_json.get("data")
        ch = bot.get_channel(self.alert_channel_id)
        if streams and not self.last_live:
            self.last_live = True
            title = streams[0].get("title", "")
            await ch.send(f"🔴 {self.streamer_login} est en live : **{title}** https://twitch.tv/{self.streamer_login}")
        elif not streams:
            self.last_live = False

# --- Webhook & OAuth handlers ---
async def handle_webhook(request):
    try:
        payload = await request.json()
        logging.info(f"Webhook reçu : {payload}")
        return web.Response(text="OK")
    except Exception as e:
        return web.Response(status=400, text=str(e))

async def twitch_callback(request):
    params = request.rel_url.query
    code = params.get("code")
    state = params.get("state")
    if not code or not state:
        return web.Response(status=400, text="Missing code/state")
    token_resp = await ClientSession().post(
        "https://id.twitch.tv/oauth2/token",
        data={
            "client_id": TWITCH_CLIENT_ID,
            "client_secret": TWITCH_CLIENT_SECRET,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": os.getenv("REDIRECT_URI")
        }
    )
    token_data = await token_resp.json()
    access_token = token_data.get("access_token")
    if not access_token:
        return web.Response(status=400, text="No token")
    headers = {"Authorization": f"Bearer {access_token}", "Client-Id": TWITCH_CLIENT_ID}
    user_resp = await ClientSession().get("https://api.twitch.tv/helix/users", headers=headers)
    user_data = await user_resp.json()
    login = user_data.get("data", [{}])[0].get("login")
    guild = bot.guilds[0] if bot.guilds else None
    if guild:
        try:
            member = await guild.fetch_member(int(state))
            role = guild.get_role(TWITCH_FOLLOWER_ROLE_ID)
            if member and role:
                await member.add_roles(role)
        except:
            pass
    return web.Response(text="Linked")

@bot.event
async def on_voice_state_update(member, before, after):
    for ch in (before.channel, after.channel):
        if not ch or str(ch.id) not in data.get("active_squads", {}):
            continue
        info = data["active_squads"].get(str(ch.id), {})
        announce_ch = bot.get_channel(info.get("channel_id"))
        try:
            msg = await announce_ch.fetch_message(info.get("message_id"))
        except:
            continue
        membs = [m for m in ch.members if not m.bot]
        if not membs:
            await msg.delete()
            await ch.delete()
            data["active_squads"].pop(str(ch.id), None)
            save_data(data)
        else:
            desc = (
                f"🎮 {ch.name.split(' - ')[0]}\n"
                f"👥 {len(membs)}/{ch.user_limit}\n" +
                "\n".join(f"• {m.display_name}" for m in membs)
            )
            await msg.edit(embed=discord.Embed(title=ch.name, description=desc, color=discord.Color.green()))

# --- exécution principale ---
async def main():
    app = web.Application()
    app.router.add_post("/webhook", handle_webhook)
    app.router.add_get("/auth/twitch/callback", twitch_callback)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, WEBHOOK_HOST, WEBHOOK_PORT).start()

    global twitch_monitor, twitter_user_id
    if all([TWITCH_CLIENT_ID, TWITCH_CLIENT_SECRET, TWITCH_STREAMER_LOGIN, TWITCH_ALERT_CHANNEL_ID]):
        twitch_monitor = TwitchMonitor(
            TWITCH_CLIENT_ID, TWITCH_CLIENT_SECRET,
            TWITCH_STREAMER_LOGIN, TWITCH_ALERT_CHANNEL_ID
        )
    if TWITTER_BEARER_TOKEN and TWITTER_USERNAME:
        twitter_user_id = await fetch_twitter_user_id()

    cleanup_empty_vcs.start()
    check_giveaways.start()
    twitch_check_loop.start()
    twitter_check_loop.start()

    await bot.start(DISCORD_TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
