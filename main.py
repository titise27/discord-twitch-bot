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

print("🚀 main.py chargé (version mise à jour)")
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
DISCORD_TOKEN                = os.getenv("DISCORD_TOKEN")
TEMP_VC_TRIGGER_ID           = int(os.getenv("TEMP_VC_TRIGGER_ID", 0))
SQUAD_VC_CATEGORY_ID         = int(os.getenv("SQUAD_VC_CATEGORY_ID", 0))
SQUAD_ANNOUNCE_CHANNEL_ID    = int(os.getenv("SQUAD_ANNOUNCE_CHANNEL_ID", 0))
GUIDE_CHANNEL_ID             = int(os.getenv("GUIDE_CHANNEL_ID", 0))
REGLEMENT_CHANNEL_ID         = int(os.getenv("REGLEMENT_CHANNEL_ID", 0))
MEMBRE_ROLE_ID               = int(os.getenv("MEMBRE_ROLE_ID", 0))
LOG_CHANNEL_ID               = int(os.getenv("LOG_CHANNEL_ID", 0))
LOG_ARRIVANTS_CHANNEL_ID     = int(os.getenv("LOG_ARRIVANTS_CHANNEL_ID", 0))
LOG_CHANNEL_UPDATE_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_UPDATE_CHANNEL_ID", 0))

TWITCH_CLIENT_ID             = os.getenv("TWITCH_CLIENT_ID")
TWITCH_CLIENT_SECRET         = os.getenv("TWITCH_CLIENT_SECRET")
TWITCH_STREAMER_LOGIN        = os.getenv("TWITCH_STREAMER_LOGIN")
TWITCH_ALERT_CHANNEL_ID      = int(os.getenv("TWITCH_ALERT_CHANNEL_ID", 0))
TWITCH_FOLLOWER_ROLE_ID      = int(os.getenv("TWITCH_FOLLOWER_ROLE_ID", 0))
TWITCH_SUB_T1_ROLE_ID        = int(os.getenv("TWITCH_SUB_T1_ROLE_ID", 0))
TWITCH_SUB_T2_ROLE_ID        = int(os.getenv("TWITCH_SUB_T2_ROLE_ID", 0))
TWITCH_SUB_T3_ROLE_ID        = int(os.getenv("TWITCH_SUB_T3_ROLE_ID", 0))

TWITTER_BEARER_TOKEN         = os.getenv("TWITTER_BEARER_TOKEN")
TWITTER_USERNAME             = os.getenv("TWITTER_USERNAME")
TWITTER_ALERT_CHANNEL_ID     = int(os.getenv("TWITTER_ALERT_CHANNEL_ID", 0))
TWITTER_USER_URL             = f"https://api.twitter.com/2/users/by/username/{TWITTER_USERNAME}"
twitter_headers              = {"Authorization": f"Bearer {TWITTER_BEARER_TOKEN}"}

WEBHOOK_HOST                 = os.getenv("WEBHOOK_HOST", "0.0.0.0")
WEBHOOK_PORT                 = int(os.getenv("PORT", 8080))
UTC                           = timezone.utc
DATA_FILE                    = "data.json"

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
        "twitch_subscribers": {},
        "active_squads": {}
    }

def save_data(data):
    try:
        with open(DATA_FILE, "w") as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        logging.error(f"[Save Data Error] {e}")

data = load_data()

# --- Fonctions de log fiabilisées ---
async def log_to_discord(message: str):
    channel = bot.get_channel(LOG_CHANNEL_ID) or await bot.fetch_channel(LOG_CHANNEL_ID)
    if channel:
        await channel.send(f"📌 {message}")
    else:
        logging.error(f"[Log] Salon introuvable {LOG_CHANNEL_ID}")

async def log_to_specific_channel(channel_id: int, message: str):
    channel = bot.get_channel(channel_id) or await bot.fetch_channel(channel_id)
    if channel:
        await channel.send(message)
    else:
        logging.error(f"[Log] Salon introuvable {channel_id}")

# --- Protection anti-spam & timeout ---
user_squad_cooldowns = {}  # user_id: timestamp

@tasks.loop(seconds=60)
async def cleanup_old_squads():
    now = datetime.now(UTC)
    g = bot.guilds[0] if bot.guilds else None
    if not g:
        return
    for vc_id, info in list(data.get("active_squads", {}).items()):
        vc = g.get_channel(int(vc_id))
        if not vc or not vc.members:
            try:
                ch = bot.get_channel(info['channel_id'])
                if ch:
                    msg = await ch.fetch_message(info['message_id'])
                    await msg.delete()
                if vc:
                    await vc.delete()
            except Exception:
                pass
            data["active_squads"].pop(vc_id, None)
            save_data(data)

# --- Squad creation modal ---
class SquadSetupModal(discord.ui.Modal, title="Créer une Squad"):
    def __init__(self, member: discord.Member):
        super().__init__()
        self.member = member
        self.game_name = discord.ui.TextInput(
            label="Nom du jeu",
            placeholder="Ex: Valorant, Rocket League...",
            required=True,
            max_length=50
        )
        self.max_players = discord.ui.TextInput(
            label="Nombre de joueurs max",
            placeholder="Ex: 3, 5, 10...",
            required=True,
            max_length=2
        )
        self.add_item(self.game_name)
        self.add_item(self.max_players)

    async def on_submit(self, interaction: discord.Interaction):
        now_ts = time.time()
        last_ts = user_squad_cooldowns.get(self.member.id, 0)
        if now_ts - last_ts < 60:
            return await interaction.response.send_message(
                "⏳ Attends quelques secondes avant de recréer une squad.", ephemeral=True
            )
        user_squad_cooldowns[self.member.id] = now_ts

        try:
            game_name = self.game_name.value.title()
            max_players = int(self.max_players.value)
        except Exception:
            return await interaction.response.send_message("❌ Valeurs invalides.", ephemeral=True)

        guild = interaction.guild
        category = guild.get_channel(SQUAD_VC_CATEGORY_ID)
        if not category:
            return await interaction.response.send_message("❌ Catégorie introuvable.", ephemeral=True)

        suffix = random.randint(1000, 9999)
        vc_name = f"{game_name} - Squad {self.member.display_name} ({suffix})"
        try:
            vc = await guild.create_voice_channel(
                name=vc_name, category=category, user_limit=max_players
            )
        except Exception as e:
            logging.error(f"[Create VC Error] {e}")
            return

        try:
            await self.member.move_to(vc)
        except Exception as e:
            logging.warning(f"[Move Error] {e}")

        view = SquadJoinButton(vc, max_members=max_players)
        embed = discord.Embed(
            title=vc.name,
            description=(
                f"🎮 Jeu : **{game_name}**\n"
                f"👥 Joueurs : 1 / {max_players}\n\n"
                f"👤 Membres :\n• {self.member.display_name}"
            ),
            color=discord.Color.green()
        )

        announce_ch = interaction.client.get_channel(SQUAD_ANNOUNCE_CHANNEL_ID)
        if announce_ch:
            try:
                msg = await announce_ch.send(embed=embed, view=view)
                view.message = msg
            except Exception as e:
                logging.error(f"[Send Embed Error] {e}")
                return
            data.setdefault("active_squads", {})[str(vc.id)] = {
                "channel_id": announce_ch.id,
                "message_id": msg.id
            }
            save_data(data)

        await interaction.response.send_message("✅ Squad créée avec succès !", ephemeral=True)

# --- Squad join button view ---
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

        try:
            await user.move_to(self.vc)
        except Exception as e:
            logging.warning(f"[Move Error] {e}")

        await interaction.response.send_message(f"Tu as rejoint **{self.vc.name}** !", ephemeral=True)
        await asyncio.sleep(1)

        players = [m for m in self.vc.members if not m.bot]
        lines = [
            f"🎮 Jeu : **{self.vc.name.split(' - ')[0]}**",
            f"👥 Joueurs : {len(players)} / {self.max_members}",
            "",
            "👤 Membres :"
        ] + [f"• {p.display_name}" for p in players]
        embed = discord.Embed(title=self.vc.name, description="\n".join(lines), color=discord.Color.green())

        try:
            await self.message.edit(embed=embed, view=self)
        except Exception:
            pass

        if not players:
            try:
                await self.message.delete()
                await self.vc.delete()
            except:
                pass
            data["active_squads"].pop(str(self.vc.id), None)
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
    async def accept(self, inter, btn):
        role = inter.guild.get_role(MEMBRE_ROLE_ID)
        if role and role not in inter.user.roles:
            await inter.user.add_roles(role)
        q = urlencode({
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": "user:read:email",
            "state": str(inter.user.id)
        })
        url = f"https://id.twitch.tv/oauth2/authorize?{q}"
        await inter.response.send_message(f"✅ Règlement accepté !\n🔗 {url}", ephemeral=True)

@bot.command()
@commands.has_permissions(administrator=True)
async def reglement(ctx):
    embed = discord.Embed(title="Règlement du serveur", description=reglement_texte, color=discord.Color.blue())
    view = ReglementView(TWITCH_CLIENT_ID, os.getenv("REDIRECT_URI"))
    msg = await ctx.send(embed=embed, view=view)
    data["reglement_message_id"] = msg.id
    save_data(data)

# --- Modération ---
@bot.command(name="kick")
@commands.has_permissions(kick_members=True)
async def kick(ctx, member: discord.Member, *, reason=None):
    await member.kick(reason=reason)
    await ctx.send(f"👢 {member} expulsé. Raison : {reason or 'Non spécifiée'}")
    await log_to_discord(f"{member} expulsé. Raison : {reason or 'Non spécifiée'}")

@bot.command(name="ban")
@commands.has_permissions(ban_members=True)
async def ban(ctx, member: discord.Member, *, reason=None):
    await member.ban(reason=reason)
    await ctx.send(f"🔨 {member} banni. Raison : {reason or 'Non spécifiée'}")
    await log_to_discord(f"{member} banni. Raison : {reason or 'Non spécifiée'}")

@bot.command()
@commands.has_permissions(manage_messages=True)
async def clear(ctx, amount: int = 5):
    try:
        deleted = await ctx.channel.purge(limit=amount + 1)
        await ctx.send(f"🧹 {len(deleted) - 1} messages supprimés.", delete_after=3)
    except Exception as e:
        await ctx.send(f"❌ Erreur lors de la suppression : {e}")

@bot.command()
@commands.has_permissions(administrator=True)
async def link(ctx, *, url: str = None):
    if not url:
        return await ctx.send("❌ Utilisation: !link <url>")
    await ctx.author.send(f"🔗 Voici ton lien : {url}")
    await ctx.send("✅ Lien envoyé en message privé !")

# --- Logs d’événements ---
@bot.event
async def on_member_join(m):
    await log_to_specific_channel(LOG_ARRIVANTS_CHANNEL_ID, f"👋 {m.mention} a rejoint")
@bot.event
async def on_member_remove(m):
    await log_to_discord(f"👋 {m.name} a quitté")
@bot.event
async def on_guild_channel_update(b, a):
    if b.name != a.name:
        await log_to_specific_channel(LOG_CHANNEL_UPDATE_CHANNEL_ID, f"🛠️ {b.name} -> {a.name}")
@bot.event
async def on_message_delete(msg):
    if msg.author.bot or not msg.guild:
        return
    await log_to_discord(f"🗑️ Supprimé: {msg.author}: {msg.content}")
@bot.event
async def on_message_edit(b, a):
    if b.author.bot or not b.guild or b.content == a.content:
        return
    await log_to_discord(f"✏️ Édité par {b.author} dans {b.channel}\nAvant:{b.content}\nAprès:{a.content}")

# --- on_ready ---
@bot.event
async def on_ready():
    cleanup_old_squads.start()
    bot.add_view(ReglementView(TWITCH_CLIENT_ID, os.getenv("REDIRECT_URI")))
    logging.info(f"Connecté: {bot.user}")
    await log_to_discord("✅ Bot prêt !")
    cleanup_empty_vcs.start()
    check_giveaways.start()
    twitch_check_loop.start()
    twitter_check_loop.start()
    await envoyer_guide_tuto()

# --- Squads & trigger logic are handled in on_voice_state_update above ---

# --- Tâches récurrentes (squads cleanup déjà défini) ---
@tasks.loop(minutes=1)
async def cleanup_empty_vcs():
    g = bot.guilds[0] if bot.guilds else None
    if not g:
        return
    c = g.get_channel(SQUAD_VC_CATEGORY_ID)
    if not c:
        return
    for vc in c.voice_channels:
        if not vc.members:
            try:
                await vc.delete()
            except:
                pass

@tasks.loop(seconds=30)
async def check_giveaways():
    now = datetime.now(UTC)
    for gid, g in list(data.get("giveaways", {}).items()):
        if now >= datetime.fromisoformat(g["end_time"]):
            ch = bot.get_channel(g["channel_id"])
            if ch:
                try:
                    msg = await ch.fetch_message(g["message_id"])
                except:
                    data["giveaways"].pop(gid, None)
                    continue
                users = [
                    u for r in msg.reactions if str(r.emoji) == "🎉"
                    for u in await r.users().flatten() if not u.bot
                ]
                if users:
                    await ch.send(f"🎊 {random.choice(users).mention} a gagné {g['prize']}")
                else:
                    await ch.send("Personne n'a participé.")
            data["giveaways"].pop(gid, None)
    save_data(data)

@tasks.loop(minutes=1)
async def twitch_check_loop():
    if twitch_monitor:
        await twitch_monitor.check_stream()

@tasks.loop(minutes=2)
async def twitter_check_loop():
    ch = bot.get_channel(TWITTER_ALERT_CHANNEL_ID)
    if not ch or not twitter_user_id:
        return
    since = max(data.get("twitter_posted_tweets", ["0"]))
    for tw in reversed(await fetch_latest_tweets(twitter_user_id, since_id=since)):
        if tw["id"] not in data.get("twitter_posted_tweets", []):
            url = f"https://twitter.com/{TWITTER_USERNAME}/status/{tw['id']}"
            await ch.send(f"🐦 Nouveau tweet ({tw['created_at']}): {tw['text']}\n{url}")
            data.setdefault("twitter_posted_tweets", []).append(tw["id"])
    save_data(data)

# --- Twitter & Twitch helper functions & classes omitted for brevity ---
# (fetch_twitter_user_id, fetch_latest_tweets, TwitchMonitor, webhook handlers, etc.)

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
