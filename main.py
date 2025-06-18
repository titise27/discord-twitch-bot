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

# --- Fonctions de log ---
async def log_to_discord(message: str):
    channel = bot.get_channel(LOG_CHANNEL_ID)
    if channel:
        await channel.send(f"📌 {message}")

async def log_to_specific_channel(channel_id: int, message: str):
    channel = bot.get_channel(channel_id)
    if channel:
        await channel.send(message)

# --- Twitter avec back-off sur 429 ---
async def fetch_twitter_user_id():
    async with ClientSession() as session:
        async with session.get(TWITTER_USER_URL, headers=twitter_headers) as resp:
            if resp.status == 429:
                reset_ts = resp.headers.get("x-rate-limit-reset")
                if reset_ts:
                    wait = max(int(reset_ts) - int(time.time()), 0)
                    logging.warning(f"[Twitter] Rate limit hit, retry in {wait}s")
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
                    logging.warning(f"[Twitter] Rate limit tweets, retry in {wait}s")
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

@bot.command(name="updateguide")
@commands.has_permissions(administrator=True)
async def update_guide(ctx):
    await envoyer_guide_tuto()
    await ctx.send("✅ Guide mis à jour.", delete_after=5)

# --- Règlement et vue du bouton ---
# --- Texte règlement ---
reglement_texte = """
📜 **・Règlement du serveur Discord**

Bienvenue sur le serveur **Titise Arena**, le QG communautaire de **Titise95** ! 🎮  
Ici, on chill, on rigole, on discute — mais toujours dans le respect. Merci de lire et suivre les règles ci-dessous 👇

---

🔒 **・Règles générales**

**Respect & bienveillance**
> ✦ Aucune insulte, moquerie, discrimination ou harcèlement ne sera toléré.  
> ✦ Soyez cool les uns avec les autres 💙

**Pas de contenu NSFW**
> ✦ Contenu sexuel, choquant, gore ou violent interdit — même en MP via le serveur. 🚫

**Pas de spam ni de flood**
> ✦ Pas de messages en boucle, MAJ abusives, emojis ou bots en excès.

**Pas de publicité**
> ✦ Aucune pub (serveurs, chaînes, etc.) sans autorisation du staff.

**Langage correct**
> ✦ L'humour est bienvenu, mais dans le respect de tous.

---

🧠 **・Comportement attendu**

**Soyez mature & responsable**
> ✦ Pas de drama inutile. Faites preuve de bon sens.

**Pas de politique ou de religion**
> ✦ Ces sujets sensibles sont interdits ici.

**Respectez le staff**
> ✦ Les modérateurs sont là pour aider. Leur décision fait foi.

**Pseudo & avatar corrects**
> ✦ Pas de pseudo troll, impersonation, contenu offensant.

---

🔊 **・Canaux vocaux**

**Micro propre**
> ✦ Pas de cris, bruits parasites, musique forte. Push-to-talk recommandé 🎧

**Bonne ambiance**
> ✦ Pas de rage, clash, ou attitude toxique. On reste chill 😎

---

📺 **・Streams de Titise95**

**🚫 Pas de spoil !**
> ✦ Utilisez `||balises spoiler||` si besoin.

**Pas de backseat gaming**
> ✦ Ne donnez pas de conseils sauf si demandé.

**Respect de Titise95 & du staff**
> ✦ Pas de spam en MP, pas d'insistance pour jouer.

**Comportement clean en live**
> ✦ Pas de perturbations en vocal ou en messages.

---

⚠️ **・Sanctions**

🔸 Avertissement oral  
🔸 Mute temporaire  
🔸 Kick  
🔸 Ban définitif  

> Les sanctions sont appliquées selon la gravité et à la discrétion du staff.

---

📬 **・Besoin d’aide ? Une question ?**

> Contacte un modo en MP ou utilise le salon **#🛟・contact-staff**  
> On est là pour toi ❤️

---

🫶 Merci d’avoir lu le règlement !  
En restant sur **Titise Arena**, tu acceptes ces règles.

✅ Clique sur **J'accepte** ci-dessous pour accéder au serveur.  
🔗 Tu pourras ensuite **lier ton compte Twitch** pour recevoir le rôle `Follower` si tu suis la chaîne !

— *L’équipe Titise Arena*
"""

class ReglementView(ui.View):
    def __init__(self, client_id, redirect_uri):
        super().__init__(timeout=None)
        self.client_id = client_id
        self.redirect_uri = redirect_uri

    @ui.button(label="✅ J'accepte", style=discord.ButtonStyle.green, custom_id="accept_reglement")
    async def accept(self, interaction: discord.Interaction, button: ui.Button):
        member = interaction.user
        role = interaction.guild.get_role(MEMBRE_ROLE_ID)
        if role and role not in member.roles:
            await member.add_roles(role)
        query = urlencode({
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": "user:read:email",
            "state": str(member.id)
        })
        twitch_url = f"https://id.twitch.tv/oauth2/authorize?{query}"
        await interaction.response.send_message(f"✅ Règlement accepté !\n{twitch_url}", ephemeral=True)

@bot.command()
@commands.has_permissions(administrator=True)
async def reglement(ctx):
    embed = discord.Embed(title="Règlement du serveur", description=reglement_texte, color=discord.Color.blue())
    view = ReglementView(TWITCH_CLIENT_ID, os.getenv("REDIRECT_URI"))
    msg = await ctx.send(embed=embed, view=view)
    data["reglement_message_id"] = msg.id
    save_data(data)

# --- Commandes modération basiques ---
@bot.command(name="kick")
@commands.has_permissions(kick_members=True)
async def kick(ctx, member: discord.Member, *, reason: str = None):
    await member.kick(reason=reason)
    await ctx.send(f"👢 {member} expulsé. Raison: {reason or 'Non spécifiée'}")

@bot.command(name="ban")
@commands.has_permissions(ban_members=True)
async def ban(ctx, member: discord.Member, *, reason: str = None):
    await member.ban(reason=reason)
    await ctx.send(f"🔨 {member} banni. Raison: {reason or 'Non spécifiée'}")

@bot.command(name="clear")
@commands.has_permissions(manage_messages=True)
async def clear(ctx, amount: int = 10):
    if amount < 1 or amount > 100:
        return await ctx.send("Nombre entre 1 et 100.")
    deleted = await ctx.channel.purge(limit=amount)
    await ctx.send(f"🧹 {len(deleted)} messages supprimés.", delete_after=5)

@bot.command(name="move")
@commands.has_permissions(move_members=True)
async def move(ctx, member: discord.Member, channel: discord.VoiceChannel):
    await member.move_to(channel)
    await ctx.send(f"🔀 {member.mention} déplacé vers {channel.name}.")

@bot.command()
async def ping(ctx):
    await ctx.send("Pong!")

@bot.command()
async def restart(ctx):
    if ctx.author.id != OWNER_ID:
        return await ctx.send("Pas la permission.")
    await ctx.send("Redémarrage...")
    await bot.close()
    os.execv(sys.executable, ['python'] + sys.argv)

# --- Commande guide visuel ---
@bot.command()
async def guide(ctx):
    path = "assets/squad-guide.png"
    if os.path.exists(path):
        await ctx.send(file=discord.File(path))
    else:
        await ctx.send("Image introuvable.")

# --- Création et gestion des squads ---
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
            return await interaction.response.send_message("Déjà dans la squad.", ephemeral=True)
        if len(self.vc.members) >= self.max_members:
            button.disabled = True
            if self.message: await self.message.edit(view=self)
            return await interaction.response.send_message("Squad pleine.", ephemeral=True)
        await member.move_to(self.vc)
        await interaction.response.send_message(f"Tu as rejoint {self.vc.name} !", ephemeral=True)
        if len(self.vc.members) >= self.max_members:
            button.disabled = True
            await self.message.edit(view=self)

@bot.command()
async def squad(ctx, max_players: int=None, *, game_name: str=None):
    if not max_players or not game_name:
        return await ctx.send("Usage: !squad <nb> <jeu>")
    category = ctx.guild.get_channel(SQUAD_VC_CATEGORY_ID)
    vc = await ctx.guild.create_voice_channel(f"{game_name} - Squad {ctx.author.display_name}", category=category, user_limit=max_players)
    try:
        await ctx.author.move_to(vc)
    except:
        pass
    view = SquadJoinButton(vc, max_players)
    embed = discord.Embed(title=vc.name, description=f"Jeu: **{game_name}**\nMax: {max_players}", color=discord.Color.green())
    channel = bot.get_channel(SQUAD_ANNOUNCE_CHANNEL_ID)
    msg = await (channel or ctx).send(embed=embed, view=view)
    view.message = msg

# --- Tâches récurrentes ---
# --- Nettoyage des salons vocaux vides toutes les minutes ---
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
            await vc.delete()

# --- Gestion des giveaways toutes les 30 s ---
@tasks.loop(seconds=30)
async def check_giveaways():
    now = datetime.now(UTC)
    for gid, g in list(data.get("giveaways", {}).items()):
        end_time = datetime.fromisoformat(g["end_time"])
        if now >= end_time:
            ch = bot.get_channel(g["channel_id"])
            if ch:
                try:
                    msg = await ch.fetch_message(g["message_id"])
                except:
                    data["giveaways"].pop(gid, None)
                    continue
                users = []
                for r in msg.reactions:
                    if str(r.emoji) == "🎉":
                        users = [u for u in await r.users().flatten() if not u.bot]
                        break
                if users:
                    winner = random.choice(users)
                    await ch.send(f"🎊 {winner.mention} a gagné **{g['prize']}** !")
                else:
                    await ch.send("Personne n'a participé.")
            data["giveaways"].pop(gid, None)
    save_data(data)

# --- Vérification Twitch every minute ---
@tasks.loop(minutes=1)
async def twitch_check_loop():
    if twitch_monitor:
        await twitch_monitor.check_stream()

# --- Vérification Twitter every 2 minutes ---
@tasks.loop(minutes=2)
async def twitter_check_loop():
    ch = bot.get_channel(TWITTER_ALERT_CHANNEL_ID)
    if not ch or not twitter_user_id:
        return
    last_id = max(data.get("twitter_posted_tweets", [0])) if data.get("twitter_posted_tweets") else None
    tweets = await fetch_latest_tweets(twitter_user_id, since_id=last_id)
    for tw in reversed(tweets):
        if tw["id"] not in data.get("twitter_posted_tweets", []):
            url = f"https://twitter.com/{TWITTER_USERNAME}/status/{tw['id']}"
            await ch.send(f"🐦 {tw['text']}\n{url}")
            data.setdefault("twitter_posted_tweets", []).append(tw["id"])
            save_data(data)

# --- Classe TwitchMonitor ---
class TwitchMonitor:
    def __init__(self, cid, secret, login, alert_ch):
        self.client_id, self.client_secret = cid, secret
        self.streamer_login, self.alert_channel_id = login, alert_ch
        self.token, self.token_expiry, self.last_live = None, None, False
        self.session = ClientSession()

    async def get_token(self):
        url = "https://id.twitch.tv/oauth2/token"
        params = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "client_credentials"
        }
        async with self.session.post(url, params=params) as r:
            data = await r.json()
            self.token = data.get("access_token")
            self.token_expiry = datetime.now() + timedelta(seconds=data.get("expires_in", 3600))

    async def check_stream(self):
        if not self.token or datetime.now() >= self.token_expiry:
            await self.get_token()
        headers = {
            "Client-ID": self.client_id,
            "Authorization": f"Bearer {self.token}"
        }
        url = f"https://api.twitch.tv/helix/streams?user_login={self.streamer_login}"
        async with self.session.get(url, headers=headers) as r:
            res = await r.json()
            streams = res.get("data")
            ch = bot.get_channel(self.alert_channel_id)
            if streams and not self.last_live:
                self.last_live = True
                title = streams[0].get("title")
                await ch.send(f"🔴 {self.streamer_login} est en live : **{title}** https://twitch.tv/{self.streamer_login}")
            elif not streams:
                self.last_live = False

# --- Webhook & OAuth callback ---
async def handle_webhook(request):
    try:
        payload = await request.json()
        logging.info(f"Webhook reçu : {payload}")
        return web.Response(text="OK")
    except Exception as e:
        return web.Response(status=400, text=str(e))

async def twitch_callback(request):
    params = request.rel_url.query
    code, state = params.get("code"), params.get("state")
    if not code or not state:
        return web.Response(status=400, text="Params manquants")
    token_payload = {
        "client_id": TWITCH_CLIENT_ID,
        "client_secret": TWITCH_CLIENT_SECRET,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": os.getenv("REDIRECT_URI")
    }
    async with ClientSession() as session:
        async with session.post("https://id.twitch.tv/oauth2/token", data=token_payload) as resp:
            tok = await resp.json()
    access = tok.get("access_token")
    if not access:
        return web.Response(status=400, text="Pas de token")
    headers = {"Authorization": f"Bearer {access}", "Client-Id": TWITCH_CLIENT_ID}
    async with ClientSession() as session:
        async with session.get("https://api.twitch.tv/helix/users", headers=headers) as u_resp:
            ud = await u_resp.json()
            tu = ud["data"][0]
    follows_url = f"https://api.twitch.tv/helix/users/follows?from_id={tu['id']}&to_id={TUYOUR_STREAMER_ID}"
    async with ClientSession() as session:
        async with session.get(follows_url, headers=headers) as f_resp:
            fd = await f_resp.json()
    follows = fd.get("total", 0) > 0
    guild = bot.guilds[0]
    member = guild.get_member(int(state))
    if member and follows:
        role = guild.get_role(TWITCH_FOLLOWER_ROLE_ID)
        if role:
            await member.add_roles(role)
        data.setdefault("linked_accounts", {})[state] = tu["login"]
        save_data(data)
        return web.Response(text="✅ Compte lié et follower détecté")
    return web.Response(text="✅ Compte lié, pas de follow détecté")

# --- on_ready unique ---
@bot.event
async def on_ready():
    logging.info(f"Connecté : {bot.user} ({bot.user.id})")
    log_ch = bot.get_channel(LOG_CHANNEL_ID)
    if log_ch:
        await log_ch.send("✅ Bot connecté et prêt !")
    cleanup_empty_vcs.start()
    check_giveaways.start()
    twitch_check_loop.start()
    twitter_check_loop.start()
    await envoyer_guide_tuto()
    global twitch_monitor, twitter_user_id
    if all([TWITCH_CLIENT_ID, TWITCH_CLIENT_SECRET, TWITCH_STREAMER_LOGIN, TWITCH_ALERT_CHANNEL_ID]):
        twitch_monitor = TwitchMonitor(TWITCH_CLIENT_ID, TWITCH_CLIENT_SECRET, TWITCH_STREAMER_LOGIN, TWITCH_ALERT_CHANNEL_ID)
    if TWITTER_BEARER_TOKEN and TWITTER_USERNAME:
        twitter_user_id = await fetch_twitter_user_id()

# --- Démarrage du bot et serveur web ---
def main():
    app = web.Application()
    app.router.add_post("/webhook", handle_webhook)
    app.router.add_get("/auth/twitch/callback", twitch_callback)
    runner = web.AppRunner(app)
    loop = asyncio.get_event_loop()
    loop.run_until_complete(runner.setup())
    loop.run_until_complete(web.TCPSite(runner, WEBHOOK_HOST, WEBHOOK_PORT).start())
    loop.run_until_complete(bot.start(DISCORD_TOKEN))

if __name__ == "__main__":
    main()

