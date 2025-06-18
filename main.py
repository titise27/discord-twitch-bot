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
GUIDE_CHANNEL_ID = int(os.getenv("GUIDE_CHANNEL_ID", 0))

TWITCH_CLIENT_ID = os.getenv("TWITCH_CLIENT_ID")
TWITCH_CLIENT_SECRET = os.getenv("TWITCH_CLIENT_SECRET")
TWITCH_STREAMER_LOGIN = os.getenv("TWITCH_STREAMER_LOGIN")
TWITCH_ALERT_CHANNEL_ID = int(os.getenv("TWITCH_ALERT_CHANNEL_ID", 0))

TWITTER_BEARER_TOKEN = os.getenv("TWITTER_BEARER_TOKEN")
TWITTER_USERNAME = os.getenv("TWITTER_USERNAME")
TWITTER_ALERT_CHANNEL_ID = int(os.getenv("TWITTER_ALERT_CHANNEL_ID", 0))
TWITTER_USER_URL = f"https://api.twitter.com/2/users/by/username/{TWITTER_USERNAME}"

twitter_headers = {"Authorization": f"Bearer {TWITTER_BEARER_TOKEN}"}

WEBHOOK_HOST = os.getenv("WEBHOOK_HOST", "0.0.0.0")
WEBHOOK_PORT = int(os.getenv("PORT", 8080))

UTC = timezone.utc
DATA_FILE = "data.json"

# Ajout d'une constante d'ID serveur
GUILD_ID = int(os.getenv("GUILD_ID", 0))

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
        "squad_messages": []
    }

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

data = load_data()

# --- Twitter ---
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
            await ch.send(f"F426 {tw['text']}\n{url}")
            data.setdefault("twitter_posted_tweets", []).append(tw["id"])
            save_data(data)

# --- Web ---
async def start_web_app():
    app = web.Application()
    app.add_routes([web.post("/webhook", lambda r: web.Response(text="OK"))])
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host=WEBHOOK_HOST, port=WEBHOOK_PORT)
    await site.start()
    logging.info(f"Webhook serveur démarré sur http://{WEBHOOK_HOST}:{WEBHOOK_PORT}")

# --- VCs temporaires (nettoyage) ---
@tasks.loop(minutes=1)
async def cleanup_empty_vcs():
    guild = discord.utils.get(bot.guilds, id=GUILD_ID)
    if not guild:
        return
    category = guild.get_channel(SQUAD_VC_CATEGORY_ID)
    if not category:
        return
    for vc in category.voice_channels:
        if not vc.members:
            await vc.delete()

@tasks.loop(hours=1)
async def cleanup_old_squad_messages():
    now = datetime.utcnow()
    announce_ch = bot.get_channel(SQUAD_ANNOUNCE_CHANNEL_ID)
    for entry in list(data.get("squad_messages", [])):
        message_id = entry.get("message_id")
        timestamp = datetime.fromisoformat(entry.get("timestamp"))
        if (now - timestamp).total_seconds() >= 86400:
            try:
                msg = await announce_ch.fetch_message(message_id)
                await msg.delete()
            except:
                pass
            data["squad_messages"].remove(entry)
    save_data(data)

# --- Commandes basiques ---
@bot.command()
async def ping(ctx):
    await ctx.send("Pong!")

@bot.command()
async def restart(ctx):
    if ctx.author.id != OWNER_ID:
        return await ctx.send("Tu n'as pas la permission.")
    await ctx.send("Redémarrage du bot...")
    await bot.close()
    os.execv(sys.executable, ['python'] + sys.argv)

# --- Commande modération ---
@bot.command()
@commands.has_permissions(kick_members=True)
async def kick(ctx, member: discord.Member, *, reason: str = None):
    await member.kick(reason=reason)
    await ctx.send(f"👢 {member} expulsé. Raison : {reason or 'Non spécifiée'}")

@bot.command()
@commands.has_permissions(ban_members=True)
async def ban(ctx, member: discord.Member, *, reason: str = None):
    await member.ban(reason=reason)
    await ctx.send(f"🔨 {member} banni. Raison : {reason or 'Non spécifiée'}")

@bot.command()
@commands.has_permissions(manage_messages=True)
async def clear(ctx, amount: int = 10):
    if amount < 1 or amount > 100:
        return await ctx.send("Le nombre doit être entre 1 et 100.")
    deleted = await ctx.channel.purge(limit=amount)
    await ctx.send(f"🧹 {len(deleted)} messages supprimés.", delete_after=5)

# --- Liste des salons vocaux créés dynamiquement ---
created_vcs = set()
created_vc_names = set()
squad_lock = asyncio.Lock()  # Ajout d'un verrou

# --- Flag pour éviter les doublons dans on_ready ---
on_ready_executed = False

# --- Log dans un channel spécifique ---
async def log_to_specific_channel(channel_id: int, message: str):
    channel = bot.get_channel(channel_id)
    if channel:
        await channel.send(message)

# --- Logs des événements modération ---
@bot.event
async def on_member_join(member):
    await log_to_specific_channel(LOG_ARRIVANTS_CHANNEL_ID, f"👋 {member.mention} a rejoint le serveur.")

@bot.event
async def on_member_update(before, after):
    added_roles = [r for r in after.roles if r not in before.roles]
    removed_roles = [r for r in before.roles if r not in after.roles]
    messages = []
    if added_roles:
        messages.append(f"➕ Rôles ajoutés à {after.mention} : {', '.join(r.name for r in added_roles)}")
    if removed_roles:
        messages.append(f"➖ Rôles retirés à {after.mention} : {', '.join(r.name for r in removed_roles)}")
    for msg in messages:
        await log_to_specific_channel(LOG_CHANNEL_ID, msg)

@bot.event
async def on_guild_channel_update(before, after):
    if before.name != after.name:
        await log_to_specific_channel(LOG_CHANNEL_UPDATE_CHANNEL_ID, f"✏️ Salon renommé : **{before.name}** → **{after.name}**")

# --- Commande squad ---
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
            return await interaction.response.send_message("Tu es déjà dans la squad.", ephemeral=True)
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
@commands.cooldown(1, 10, commands.BucketType.user)
async def squad(ctx, max_players: int = None, *, game_name: str = None):
    if not max_players or not game_name:
        return await ctx.send("Usage: !squad <nombre> <jeu>")

    async with squad_lock:
        category = ctx.guild.get_channel(SQUAD_VC_CATEGORY_ID)
        channel_name = f"{game_name} - Squad {ctx.author.display_name}"

        if channel_name in created_vc_names:
            return await ctx.send("Un salon pour cette squad existe déjà ou vient d'être créé. Merci de patienter une minute.")

        vc = await ctx.guild.create_voice_channel(
            name=channel_name,
            category=category,
            user_limit=max_players
        )
        created_vcs.add(vc.id)
        created_vc_names.add(channel_name)

        try:
            await ctx.author.move_to(vc)
        except:
            pass

        view = SquadJoinButton(vc, max_players)
        embed = discord.Embed(
            title=vc.name,
            description=f"Jeu : **{game_name}**\nMax joueurs : {max_players}",
            color=discord.Color.green()
        )
        announce = bot.get_channel(SQUAD_ANNOUNCE_CHANNEL_ID)
        msg = await (announce or ctx).send(embed=embed, view=view)
        view.message = msg
        data.setdefault("squad_messages", []).append({
            "message_id": msg.id,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
        save_data(data)

# --- Suppression automatique des messages de squad après 24h ---
@tasks.loop(hours=1)
async def cleanup_old_squad_messages():
    now = datetime.now(timezone.utc)
    announce_ch = bot.get_channel(SQUAD_ANNOUNCE_CHANNEL_ID)
    for entry in list(data.get("squad_messages", [])):
        message_id = entry.get("message_id")
        timestamp = datetime.fromisoformat(entry.get("timestamp"))
        if (now - timestamp).total_seconds() >= 86400:
            try:
                msg = await announce_ch.fetch_message(message_id)
                await msg.delete()
            except:
                pass
            data["squad_messages"].remove(entry)
    save_data(data)

# --- Suppression instantanée des vocaux quand vides ---
@bot.event
async def on_voice_state_update(member, before, after):
    logging.info(f"[voice_state] {member} before={before.channel} after={after.channel}")
    if before.channel and before.channel.id in created_vcs:
        if len(before.channel.members) == 0:
            created_vcs.discard(before.channel.id)
            created_vc_names.discard(before.channel.name)
            try:
                await before.channel.delete()
                logging.info(f"[voice_state] Salon supprimé : {before.channel.name}")
            except Exception as e:
                logging.warning(f"Erreur suppression salon vocal : {e}")

# --- Nettoyage périodique de sécurité (fallback) ---
@tasks.loop(minutes=1)
async def cleanup_empty_vcs():
    if not bot.guilds:
        return
    guild = bot.guilds[0]
    category = guild.get_channel(SQUAD_VC_CATEGORY_ID)
    if not category:
        return

    for vc in category.voice_channels:
        if len(vc.members) == 0:
            created_vc_names.discard(vc.name)
            created_vcs.discard(vc.id)
            await vc.delete()

# Lancer les tâches lors du démarrage
@bot.event
async def on_ready():
    global twitter_user_id, on_ready_executed
    if on_ready_executed:
        return
    on_ready_executed = True

    logging.info(f"Bot connecté en tant que {bot.user}")
    twitter_user_id = await fetch_twitter_user_id()
    if not twitter_check_loop.is_running():
        twitter_check_loop.start()
    if not cleanup_empty_vcs.is_running():
        cleanup_empty_vcs.start()
    if not cleanup_old_squad_messages.is_running():
        cleanup_old_squad_messages.start()
    await start_web_app()


# --- Règlement ---
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
        role = interaction.guild.get_role(MEMBRE_ROLE_ID)
        if role and role not in interaction.user.roles:
            await interaction.user.add_roles(role)
        await interaction.response.send_message("Règlement accepté !", ephemeral=True)

@bot.command()
@commands.has_permissions(administrator=True)
async def reglement(ctx):
    embed = discord.Embed(title="Règlement du serveur", description=reglement_texte, color=discord.Color.blue())
    view = ReglementView(TWITCH_CLIENT_ID, os.getenv("REDIRECT_URI"))
    msg = await ctx.send(embed=embed, view=view)
    data["reglement_message_id"] = msg.id
    save_data(data)

# --- Ready ---
@bot.event
async def on_ready():
    global twitter_user_id
    logging.info(f"Bot connecté en tant que {bot.user}")
    twitter_user_id = await fetch_twitter_user_id()
    await start_web_app()
    cleanup_empty_vcs.start()
    cleanup_old_squad_messages.start()
    twitter_check_loop.start()

# --- Lancement ---
if __name__ == "__main__":
    try:
        bot.run(DISCORD_TOKEN)
    except Exception as e:
        logging.error(f"Erreur au lancement du bot : {e}")
