import os
import sys
import discord
from discord.ext import commands, tasks
from discord import ui
from aiohttp import web, ClientSession
from dotenv import load_dotenv
import asyncio
import logging
from datetime import datetime, timedelta, timezone
import json
import random

load_dotenv()
logging.basicConfig(level=logging.INFO)

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
TWITCH_FOLLOWER_ROLE_ID = int(os.getenv("TWITCH_FOLLOWER_ROLE_ID", 0))
TWITCH_SUB_T1_ROLE_ID = int(os.getenv("TWITCH_SUB_T1_ROLE_ID", 0))
TWITCH_SUB_T2_ROLE_ID = int(os.getenv("TWITCH_SUB_T2_ROLE_ID", 0))
TWITCH_SUB_T3_ROLE_ID = int(os.getenv("TWITCH_SUB_T3_ROLE_ID", 0))

TWITTER_BEARER_TOKEN = os.getenv("TWITTER_BEARER_TOKEN")
TWITTER_USERNAME = os.getenv("TWITTER_USERNAME")
TWITTER_ALERT_CHANNEL_ID = int(os.getenv("TWITTER_ALERT_CHANNEL_ID", 0))

WEBHOOK_HOST = os.getenv("WEBHOOK_HOST", "0.0.0.0")
WEBHOOK_PORT = int(os.getenv("PORT", 8080))

UTC = timezone.utc

DATA_FILE = "data.json"

# --- Gestion persistante ---
def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    return {
        "linked_accounts": {},
        "reglement_message_id": None,
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

async def log_to_discord(message: str):
    channel = bot.get_channel(LOG_CHANNEL_ID)
    if channel:
        try:
            await channel.send(f"📌 {message}")
        except Exception as e:
            logging.error(f"Erreur lors de l'envoi du log Discord : {e}")


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


# --- Interface bouton règlement ---
from urllib.parse import urlencode

from urllib.parse import urlencode

class ReglementView(ui.View):
    def __init__(self, twitch_client_id, redirect_uri):
        super().__init__(timeout=None)
        self.twitch_client_id = twitch_client_id
        self.redirect_uri = redirect_uri

    @ui.button(label="✅ J'accepte", style=discord.ButtonStyle.green, custom_id="accept_reglement")
    async def accept_button(self, interaction: discord.Interaction, button: ui.Button):
        member = interaction.user
        guild = interaction.guild
        role = guild.get_role(MEMBRE_ROLE_ID)

        # Donne le rôle "Membre" immédiatement
        if role and role not in member.roles:
            await member.add_roles(role)

        # Crée le lien Twitch OAuth2
        discord_id = member.id
        query = urlencode({
            "client_id": self.twitch_client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": "user:read:email",
            "state": str(discord_id)
        })
        twitch_url = f"https://id.twitch.tv/oauth2/authorize?{query}"

        # Message éphémère avec lien
        await interaction.response.send_message(
            content=(
                "✅ Tu as accepté le règlement !\n\n"
                "🔗 Tu peux maintenant lier ton compte Twitch pour obtenir automatiquement les rôles :\n"
                f"{twitch_url}"
            ),
            ephemeral=True
        )

# --- Commande règlement ---
@bot.command()
@commands.has_permissions(administrator=True)
async def reglement(ctx):
    embed = discord.Embed(
        title="Règlement du serveur",
        description=reglement_texte,
        color=discord.Color.blue()
    )

    # Ajout des paramètres Twitch à la vue
    view = ReglementView(TWITCH_CLIENT_ID, os.getenv("REDIRECT_URI"))

    msg = await ctx.send(embed=embed, view=view)
    data["reglement_message_id"] = msg.id
    save_data(data)


# --- Commandes modération ---
@bot.command(name="kick")
@commands.has_permissions(kick_members=True)
async def kick(ctx, member: discord.Member, *, reason: str = None):
    try:
        await member.kick(reason=reason)
        await ctx.send(f"👢 {member} a été expulsé du serveur. Raison : {reason if reason else 'Non spécifiée'}")
    except Exception as e:
        await ctx.send(f"Erreur lors de l'expulsion : {e}")

@bot.command(name="ban")
@commands.has_permissions(ban_members=True)
async def ban(ctx, member: discord.Member, *, reason: str = None):
    try:
        await member.ban(reason=reason)
        await ctx.send(f"🔨 {member} a été banni du serveur. Raison : {reason if reason else 'Non spécifiée'}")
    except Exception as e:
        await ctx.send(f"Erreur lors du bannissement : {e}")

@bot.command(name="clear")
@commands.has_permissions(manage_messages=True)
async def clear(ctx, amount: int = 10):
    if amount < 1 or amount > 100:
        await ctx.send("Le nombre de messages à supprimer doit être entre 1 et 100.")
        return
    deleted = await ctx.channel.purge(limit=amount)
    await ctx.send(f"🧹 {len(deleted)} messages supprimés.", delete_after=5)

@bot.command(name="move")
@commands.has_permissions(move_members=True)
async def move(ctx, member: discord.Member, channel: discord.VoiceChannel):
    try:
        await member.move_to(channel)
        await ctx.send(f"🔀 {member.mention} déplacé vers {channel.name}.")
    except Exception as e:
        await ctx.send(f"Erreur lors du déplacement : {e}")

@bot.command()
async def ping(ctx):
    await ctx.send("Pong!")       

@bot.command()
async def restart(ctx):
    if ctx.author.id != OWNER_ID:
        await ctx.send("Tu n'as pas la permission pour faire ça.")
        return
    await ctx.send("Redémarrage du bot...")
    await bot.close()
    os.execv(sys.executable, ['python'] + sys.argv)
    
async def envoyer_guide_tuto():
    channel = bot.get_channel(GUIDE_CHANNEL_ID)
    if not channel:
        logging.warning("Salon guide introuvable.")
        return

    guide_msg_id = data.get("guide_message_id")  # ✅ Remis au bon niveau

    if guide_msg_id:
        try:
            msg = await channel.fetch_message(guide_msg_id)
            logging.info("Le guide est déjà présent. Rien à faire.")
            return
        except discord.NotFound:
            logging.info("Le message du guide n'existe plus, on va le renvoyer.")
            data["guide_message_id"] = None
            save_data(data)

    image_path = "assets/squad-guide.png"
    if not os.path.exists(image_path):
        logging.warning("Image du guide introuvable.")
        return

    with open(image_path, "rb") as f:
        file = discord.File(f, filename="squad-guide.png")
        msg = await channel.send(content="📌 **Voici le guide pour créer une squad**", file=file)

        try:
            await msg.pin()
        except discord.Forbidden:
            logging.warning("Le bot n'a pas la permission d'épingler le message.")
        except Exception as e:
            logging.error(f"Erreur lors de l'épinglage : {e}")

        data["guide_message_id"] = msg.id
        save_data(data)
        logging.info("Guide envoyé, épinglé et ID sauvegardé.")


# --- Commande squad + bouton rejoindre ---
class SquadJoinButton(ui.View):
    def __init__(self, voice_channel: discord.VoiceChannel, max_members=5):
        super().__init__(timeout=None)
        self.voice_channel = voice_channel
        self.max_members = max_members
        self.message = None

    @ui.button(label="Rejoindre", style=discord.ButtonStyle.primary, custom_id="join_squad")
    async def join_button(self, interaction: discord.Interaction, button: ui.Button):
        member = interaction.user
        vc = self.voice_channel

        if member.voice and member.voice.channel == vc:
            await interaction.response.send_message("Tu es déjà dans cette squad.", ephemeral=True)
            return

        if len(vc.members) >= self.max_members:
            await interaction.response.send_message("Cette squad est pleine.", ephemeral=True)
            button.disabled = True
            if self.message:
                await self.message.edit(view=self)
            return

        try:
            await member.move_to(vc)
            await interaction.response.send_message(f"Tu as rejoint la squad {vc.name} !", ephemeral=True)
            if len(vc.members) >= self.max_members:
                button.disabled = True
                if self.message:
                    await self.message.edit(view=self)
        except Exception as e:
            await interaction.response.send_message(f"Impossible de te déplacer : {e}", ephemeral=True)

@bot.command()
async def squad(ctx, max_players: int = None, *, game_name: str = None):
    if max_players is None or game_name is None:
        await ctx.send("Usage: `!squad <nombre_de_joueurs> <nom_du_jeu>`")
        return
    if max_players < 1 or max_players > 99:
        await ctx.send("Le nombre de joueurs doit être entre 1 et 99.")
        return

    category = ctx.guild.get_channel(SQUAD_VC_CATEGORY_ID)
    if not category:
        await ctx.send("Catégorie des salons vocaux non trouvée.")
        return

    vc_name = f"{game_name} - Squad {ctx.author.display_name}"
    vc = await ctx.guild.create_voice_channel(name=vc_name, category=category, user_limit=max_players)

    # Déplacer l’auteur dans le salon vocal créé
    try:
        await ctx.author.move_to(vc)
    except Exception as e:
        await ctx.send(f"Impossible de te déplacer dans le salon vocal : {e}")

    view = SquadJoinButton(vc, max_members=max_players)
    embed = discord.Embed(
        title=vc.name,
        description=f"Jeu : **{game_name}**\nClique sur **Rejoindre** pour entrer dans la squad.\nMax joueurs : {max_players}",
        color=discord.Color.green()
    )

    announce_channel = bot.get_channel(SQUAD_ANNOUNCE_CHANNEL_ID)
    if announce_channel:
        msg = await announce_channel.send(embed=embed, view=view)
        view.message = msg
    else:
        # fallback si le channel n'existe pas
        msg = await ctx.send(embed=embed, view=view)
        view.message = msg

    # Envoi message privé à l'auteur pour confirmer la création
    try:
        await ctx.author.send(f"Ta squad pour {game_name} est prête ! Salon vocal : {vc.name}")
    except:
        pass

# --- Suppression des salons vocaux vides ---
@tasks.loop(minutes=1)
async def cleanup_empty_vcs():
    guild = bot.guilds[0]  # Attention, si tu es dans plusieurs serveurs, adapter ici
    category = guild.get_channel(SQUAD_VC_CATEGORY_ID)
    if not category:
        return

    for channel in category.voice_channels:
        if len(channel.members) == 0:
            try:
                await channel.delete()
                logging.info(f"Salon vocal {channel.name} supprimé car vide.")
            except Exception as e:
                logging.error(f"Erreur suppression salon vocal {channel.name}: {e}")

# --- XP simple système ---
@bot.event
async def on_message(message):
    if message.author.bot:
        return
    if message.guild is None:
        return

    # Ajouter XP
    user_id = str(message.author.id)
    xp = data.get("xp", {})
    current_xp = xp.get(user_id, 0)
    xp[user_id] = current_xp + random.randint(5, 10)
    data["xp"] = xp
    save_data(data)

    await bot.process_commands(message)

@bot.command()
async def xp(ctx, member: discord.Member = None):
    member = member or ctx.author
    xp = data.get("xp", {})
    user_xp = xp.get(str(member.id), 0)
    await ctx.send(f"{member.display_name} a {user_xp} points d'XP.")

# --- Giveaway (simplifié) ---
@bot.command()
@commands.has_permissions(manage_messages=True)
async def giveaway(ctx, duration: int, *, prize: str):
    embed = discord.Embed(title="🎉 Giveaway !", description=prize, color=discord.Color.gold())
    embed.set_footer(text=f"Durée : {duration} minutes")
    msg = await ctx.send(embed=embed)
    await msg.add_reaction("🎉")

    # Sauvegarde
    giveaway_id = str(msg.id)
    data["giveaways"][giveaway_id] = {
        "channel_id": ctx.channel.id,
        "message_id": msg.id,
        "prize": prize,
        "end_time": (datetime.now(UTC) + timedelta(minutes=duration)).isoformat()
    }
    save_data(data)

# Tâche de check des giveaways finis
@tasks.loop(seconds=30)
async def check_giveaways():
    now = datetime.now(UTC)
    giveaways = data.get("giveaways", {})
    to_remove = []
    for gid, gdata in giveaways.items():
        end_time = datetime.fromisoformat(gdata["end_time"])
        if now >= end_time:
            channel = bot.get_channel(gdata["channel_id"])
            if not channel:
                to_remove.append(gid)
                continue
            try:
                msg = await channel.fetch_message(gdata["message_id"])
            except:
                to_remove.append(gid)
                continue

            users = set()
            for reaction in msg.reactions:
                if str(reaction.emoji) == "🎉":
                    users = await reaction.users().flatten()
                    users = [u for u in users if not u.bot]
                    break
            if users:
                winner = random.choice(users)
                await channel.send(f"🎊 Félicitations {winner.mention}, tu as gagné le giveaway pour **{gdata['prize']}** !")
            else:
                await channel.send("Personne n'a participé au giveaway.")

            to_remove.append(gid)

    for gid in to_remove:
        data["giveaways"].pop(gid, None)
    if to_remove:
        save_data(data)

@bot.command()
async def guide(ctx):
    """Affiche le guide pour créer une squad"""
    image_path = "assets/squad-guide.png"
    try:
        with open(image_path, "rb") as f:
            file = discord.File(f, filename="squad-guide.png")
            await ctx.send("Voici le guide pour créer une squad :", file=file)
    except FileNotFoundError:
        await ctx.send("Image non trouvée. Assure-toi qu'elle est bien dans le dossier `assets`.")

# --- Twitch API monitoring simplifié (à compléter) ---
class TwitchMonitor:
    def __init__(self, client_id, client_secret, streamer_login, alert_channel_id):
        self.client_id = client_id
        self.client_secret = client_secret
        self.streamer_login = streamer_login
        self.alert_channel_id = alert_channel_id
        self.token = None
        self.token_expiry = None
        self.last_stream_live = False
        self.session = ClientSession()

    async def get_token(self):
        url = "https://id.twitch.tv/oauth2/token"
        params = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "client_credentials"
        }
        async with self.session.post(url, params=params) as resp:
            data = await resp.json()
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
        async with self.session.get(url, headers=headers) as resp:
            data = await resp.json()
            stream_data = data.get("data")
            channel = bot.get_channel(self.alert_channel_id)
            if stream_data:
                # Stream en direct
                if not self.last_stream_live:
                    self.last_stream_live = True
                    title = stream_data[0].get("title")
                    url_stream = f"https://www.twitch.tv/{self.streamer_login}"
                    await channel.send(f"🔴 {self.streamer_login} est en live : **{title}**\n{url_stream}")
            else:
                self.last_stream_live = False

twitch_monitor = None

@tasks.loop(minutes=1)
async def twitch_check_loop():
    if twitch_monitor:
        await twitch_monitor.check_stream()

# --- Événements Discord ---
@bot.event
async def on_ready():
    print(f"Connecté en tant que {bot.user} ({bot.user.id})")
    cleanup_empty_vcs.start()
    check_giveaways.start()
    twitch_check_loop.start()

    await envoyer_guide_tuto()  # 🔥 Envoie le guide si nécessaire

    global twitch_monitor
    if all([TWITCH_CLIENT_ID, TWITCH_CLIENT_SECRET, TWITCH_STREAMER_LOGIN, TWITCH_ALERT_CHANNEL_ID]):
        twitch_monitor = TwitchMonitor(
            TWITCH_CLIENT_ID, TWITCH_CLIENT_SECRET,
            TWITCH_STREAMER_LOGIN, TWITCH_ALERT_CHANNEL_ID
        )

# --- Logs des événements (rejoins, quitte, messages, etc.) ---
@bot.event
async def on_member_join(member):
    await log_to_discord(f"👋 {member.mention} a rejoint le serveur.")

@bot.event
async def on_member_remove(member):
    await log_to_discord(f"👋 {member.name} a quitté le serveur.")

@bot.event
async def on_member_ban(guild, user):
    await log_to_discord(f"⛔ {user} a été **banni** du serveur.")

@bot.event
async def on_member_unban(guild, user):
    await log_to_discord(f"🔓 {user} a été **débanni** du serveur.")

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
        await log_to_discord(
            f"✏️ Message modifié par {before.author.mention} dans {before.channel.mention}\n"
            f"Avant : `{before.content}`\nAprès : `{after.content}`"
        )


# --- Webhook HTTP simple ---
async def handle_webhook(request):
    try:
        data_json = await request.json()
        logging.info(f"Webhook reçu : {data_json}")
        return web.Response(text="Webhook reçu")
    except Exception as e:
        return web.Response(status=400, text=str(e))

from urllib.parse import urlencode

# Commande !link
@bot.command()
async def link(ctx):
    discord_id = ctx.author.id
    query = urlencode({
        "client_id": TWITCH_CLIENT_ID,
        "redirect_uri": os.getenv("REDIRECT_URI"),
        "response_type": "code",
        "scope": "user:read:email",
        "state": str(discord_id)
    })
    url = f"https://id.twitch.tv/oauth2/authorize?{query}"
    await ctx.send(f"Connecte ton compte Twitch ici : {url}")
 # Route de callback OAuth2 Twitch
async def twitch_callback(request):
    try:
        params = request.rel_url.query
        code = params.get("code")
        state = params.get("state")
        if not code or not state:
            return web.Response(status=400, text="Paramètres manquants.")

        discord_id = int(state)

        # Obtenir le token
        token_url = "https://id.twitch.tv/oauth2/token"
        payload = {
            "client_id": TWITCH_CLIENT_ID,
            "client_secret": TWITCH_CLIENT_SECRET,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": os.getenv("REDIRECT_URI")
        }

        async with ClientSession() as session:
            async with session.post(token_url, data=payload) as resp:
                token_data = await resp.json()

        access_token = token_data.get("access_token")
        if not access_token:
            return web.Response(status=400, text="Impossible d’obtenir un token.")

        # Obtenir infos utilisateur Twitch
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Client-Id": TWITCH_CLIENT_ID
        }

        async with ClientSession() as session:
            async with session.get("https://api.twitch.tv/helix/users", headers=headers) as user_resp:
                user_data = await user_resp.json()

        twitch_user = user_data["data"][0]
        twitch_login = twitch_user["login"]
        twitch_id = twitch_user["id"]

        # Obtenir l’ID du streamer
        streamer_url = f"https://api.twitch.tv/helix/users?login={TWITCH_STREAMER_LOGIN}"
        async with ClientSession() as session:
            async with session.get(streamer_url, headers=headers) as resp:
                result = await resp.json()
                streamer_id = result["data"][0]["id"]

        # Vérifie si le user suit le streamer
        check_url = f"https://api.twitch.tv/helix/users/follows?from_id={twitch_id}&to_id={streamer_id}"
        async with ClientSession() as session:
            async with session.get(check_url, headers=headers) as follow_resp:
                follow_data = await follow_resp.json()

        follows = follow_data.get("total", 0) > 0

        guild = bot.guilds[0]
        member = guild.get_member(discord_id)
        if not member:
            return web.Response(text="Utilisateur non trouvé sur Discord.")

        if follows:
            role = guild.get_role(TWITCH_FOLLOWER_ROLE_ID)
            if role:
                await member.add_roles(role)
            data["linked_accounts"][str(discord_id)] = twitch_login
            save_data(data)
            return web.Response(text="✅ Ton compte Twitch est lié. Tu es follower !")
        else:
            return web.Response(text="Ton compte Twitch est lié, mais tu n'es pas encore follower.")

    except Exception as e:
        return web.Response(status=500, text=f"Erreur : {str(e)}")



   
app = web.Application()
app.router.add_get("/auth/twitch/callback", twitch_callback)
app.router.add_post("/webhook", handle_webhook)

def run_webhook_app():
    runner = web.AppRunner(app)
    loop = asyncio.get_event_loop()
    loop.run_until_complete(runner.setup())
    site = web.TCPSite(runner, WEBHOOK_HOST, WEBHOOK_PORT)
    loop.run_until_complete(site.start())
    print(f"Webhook HTTP lancé sur http://{WEBHOOK_HOST}:{WEBHOOK_PORT}")

# --- Lancement du bot et du webhook ---
async def main():
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, WEBHOOK_HOST, WEBHOOK_PORT)
    await site.start()
    print(f"Webhook HTTP lancé sur http://{WEBHOOK_HOST}:{WEBHOOK_PORT}")
    
    await bot.start(DISCORD_TOKEN)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except RuntimeError as e:
        if "already running" in str(e).lower():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.create_task(main())
            loop.run_forever()
        else:
            raise