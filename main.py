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

# Variables globales

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
        "twitch_subscribers": {},
        "active_squads": {}
    }


def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)


data = load_data()

# --- Fonctions de log fiabilisées ---

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

# --- Guide tutoriel ---

async def envoyer_guide_tuto():
    channel = bot.get_channel(GUIDE_CHANNEL_ID)
    if not channel:
        return
    if data.get("guide_message_id"):
        try:
            old = await channel.fetch_message(data["guide_message_id"])
            await old.unpin(); await old.delete()
        except:
            pass
    path = "assets/squad-guide.png"
    if os.path.exists(path):
        with open(path, "rb") as f:
            file = discord.File(f, filename="squad-guide.png")
            msg = await channel.send("📌 **Voici le guide pour créer une squad**", file=file)
        try: await msg.pin()
        except: pass
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
    async def accept(self, inter, btn):
        role = inter.guild.get_role(MEMBRE_ROLE_ID)
        if role and role not in inter.user.roles:
            await inter.user.add_roles(role)
        q = urlencode({"client_id":self.client_id,"redirect_uri":self.redirect_uri,
                       "response_type":"code","scope":"user:read:email","state":str(inter.user.id)})
        url = f"https://id.twitch.tv/oauth2/authorize?{q}"
        await inter.response.send_message(f"✅ Règlement accepté !\n🔗 {url}", ephemeral=True)

@bot.command()
@commands.has_permissions(administrator=True)
async def reglement(ctx):
    embed = discord.Embed(title="Règlement du serveur", description=reglement_texte, color=discord.Color.blue())
    view = ReglementView(TWITCH_CLIENT_ID, os.getenv("REDIRECT_URI"))
    msg = await ctx.send(embed=embed, view=view)
    data["reglement_message_id"] = msg.id; save_data(data)

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
    except discord.Forbidden:
        await ctx.send("❌ Je n'ai pas la permission de supprimer les messages.")
    except discord.HTTPException as e:
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
async def on_member_join(m): await log_to_specific_channel(LOG_ARRIVANTS_CHANNEL_ID,f"👋 {m.mention} a rejoint")
@bot.event
async def on_member_remove(m): await log_to_discord(f"👋 {m.name} a quitté")
@bot.event
async def on_guild_channel_update(b,a):
    if b.name!=a.name: await log_to_specific_channel(LOG_CHANNEL_UPDATE_CHANNEL_ID,f"🛠️ {b.name}-> {a.name}")
@bot.event
async def on_message_delete(msg):
    if msg.author.bot or not msg.guild: return
    await log_to_discord(f"🗑️ Supprimé: {msg.author}:{msg.content}")
@bot.event
async def on_message_edit(b,a):
    if b.author.bot or not b.guild or b.content==a.content: return
    await log_to_discord(f"✏️ Édité par {b.author} dans {b.channel}\nAvant:{b.content}\nAprès:{a.content}")

# --- on_ready ---

@bot.event
async def on_ready():
    cleanup_old_squads.start()
    bot.add_view(ReglementView(TWITCH_CLIENT_ID,os.getenv("REDIRECT_URI")))
    logging.info(f"Connecté: {bot.user}")
    await log_to_discord("✅ Bot prêt !")
    cleanup_empty_vcs.start(); check_giveaways.start(); twitch_check_loop.start(); twitter_check_loop.start()
    await envoyer_guide_tuto()
    global twitch_monitor, twitter_user_id
    if all([TWITCH_CLIENT_ID, TWITCH_CLIENT_SECRET, TWITCH_STREAMER_LOGIN, TWITCH_ALERT_CHANNEL_ID]):
        twitch_monitor=TwitchMonitor(TWITCH_CLIENT_ID,TWITCH_CLIENT_SECRET,TWITCH_STREAMER_LOGIN,TWITCH_ALERT_CHANNEL_ID)
    if TWITTER_BEARER_TOKEN and TWITTER_USERNAME: twitter_user_id=await fetch_twitter_user_id()

# --- Squads ---
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
            f"👥 Joueurs : {len(players)} / {self.max_members}",
            "",
            "👤 Membres :"
        ]
        for p in players:
            lines.append(f"• {p.display_name}")

        description = "\n".join(lines)
        embed = discord.Embed(title=self.vc.name, description=description, color=discord.Color.green())

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



@bot.command()
async def squad(ctx: commands.Context, max_players: int = None, *, game_name: str = None):
    if not max_players or not game_name:
        return await ctx.send("Usage: !squad <n> <jeu>")

    category = ctx.guild.get_channel(SQUAD_VC_CATEGORY_ID)
    if not category:
        return await ctx.send("Catégorie introuvable.")

    suffix = random.randint(1000, 9999)
    vc_name = f"{game_name} - Squad {ctx.author.display_name} ({suffix})"
    vc = await ctx.guild.create_voice_channel(name=vc_name, category=category, user_limit=max_players)

    try:
        await ctx.author.move_to(vc)
    except:
        pass

    view = SquadJoinButton(vc, max_members=max_players)

    lines = [
        f"🎮 Jeu : **{game_name}**",
        f"👥 Joueurs : 0 / {max_players}",
        "",
        "👤 Membres : Aucun pour l'instant"
    ]
    description = "\n".join(lines)
    embed = discord.Embed(title=vc.name, description=description, color=discord.Color.green())

    channel = bot.get_channel(SQUAD_ANNOUNCE_CHANNEL_ID) or ctx
    msg = await channel.send(embed=embed, view=view)
    view.message = msg
    data.setdefault("active_squads", {})[str(vc.id)] = {
                "channel_id": announce_ch.id,
                "message_id": msg.id
            }
            try:
                save_data(data)
            except Exception as e:
                logging.error(f"[Save Data Error] {e}")

# --- Tâches récurrentes ---

@tasks.loop(minutes=1)
async def cleanup_empty_vcs():
    g=bot.guilds[0] if bot.guilds else None
    if not g: return
    c=g.get_channel(SQUAD_VC_CATEGORY_ID)
    if not c: return
    for vc in c.voice_channels:
        if not vc.members:
            await vc.delete()

@tasks.loop(seconds=30)
async def check_giveaways():
    now=datetime.now(UTC)
    for gid,g in list(data.get("giveaways",{}).items()):
        if now>=datetime.fromisoformat(g["end_time"]):
            ch=bot.get_channel(g["channel_id"])
            if ch:
                try: msg=await ch.fetch_message(g["message_id"]) 
                except: data["giveaways"].pop(gid);continue
                users=[u for r in msg.reactions if str(r.emoji)=="🎉" for u in await r.users().flatten() if not u.bot]
                if users: await ch.send(f"🎊 {random.choice(users).mention} a gagné {g['prize']}")
                else: await ch.send("Personne...")
            data["giveaways"].pop(gid)
    save_data(data)

@tasks.loop(minutes=1)
async def twitch_check_loop():
    if twitch_monitor: await twitch_monitor.check_stream()

@tasks.loop(minutes=2)
async def twitter_check_loop():
    ch=bot.get_channel(TWITTER_ALERT_CHANNEL_ID)
    if not ch or not twitter_user_id: return
    since=max(data.get("twitter_posted_tweets",["0"]))
    for tw in reversed(await fetch_latest_tweets(twitter_user_id,since_id=since)):
        if tw["id"] not in data.get("twitter_posted_tweets",[]):
            url=f"https://twitter.com/{TWITTER_USERNAME}/status/{tw['id']}"
            await ch.send(f"🐦 Nouveau tweet ({tw['created_at']}): {tw['text']}\n{url}")
            data.setdefault("twitter_posted_tweets",[]).append(tw["id"]);save_data(data)

# --- TwitchMonitor ---

class TwitchMonitor:
    def __init__(self,cid,secret,login,alert_ch):
        self.client_id=cid;self.client_secret=secret;self.streamer_login=login;self.alert_ch=alert_ch
        self.token=None;self.token_expiry=None;self.last_live=False;self.session=ClientSession()
    async def get_token(self):
        r=await self.session.post("https://id.twitch.tv/oauth2/token",params={"client_id":self.client_id,"client_secret":self.client_secret,"grant_type":"client_credentials"})
        d=await r.json();self.token=d.get("access_token");self.token_expiry=datetime.now(UTC)+timedelta(seconds=d.get("expires_in",3600))
    async def check_stream(self):
        if not self.token or datetime.now(UTC)>=self.token_expiry: await self.get_token()
        h={"Client-ID":self.client_id,"Authorization":f"Bearer {self.token}"}
        r=await self.session.get(f"https://api.twitch.tv/helix/streams?user_login={self.streamer_login}",headers=h);
        d=(await r.json()).get("data")
        ch=bot.get_channel(self.alert_ch)
        if d and not self.last_live:
            self.last_live=True; await ch.send(f"🔴 {self.streamer_login} is live: **{d[0].get('title')}** https://twitch.tv/{self.streamer_login}")
        elif not d: self.last_live=False

# --- Webhook & OAuth HTTP ---

async def handle_webhook(req):
    try:
        p=await req.json();logging.info(f"Webhook:{p}");return web.Response(text="OK")
    except Exception as e: return web.Response(status=400,text=str(e))

async def twitch_callback(req):
    q=req.rel_url.query;code,st=q.get('code'),q.get('state')
    if not code or not st: return web.Response(status=400,text="Missing")
    t=await ClientSession().post("https://id.twitch.tv/oauth2/token",data={"client_id":TWITCH_CLIENT_ID,"client_secret":TWITCH_CLIENT_SECRET,"code":code,"grant_type":"authorization_code","redirect_uri":os.getenv("REDIRECT_URI")});
    ad=await t.json();token=ad.get("access_token")
    if not token: return web.Response(status=400,text="No token")
    h={"Authorization":f"Bearer {token}","Client-Id":TWITCH_CLIENT_ID}
    u=await ClientSession().get("https://api.twitch.tv/helix/users",headers=h);ud=(await u.json())["data"][0]
    gid=int(st);g=bot.guilds[0];
    try:mem=await g.fetch_member(gid)
    except:mem=None
    if mem:
        r=g.get_role(TWITCH_FOLLOWER_ROLE_ID)
        if r: await mem.add_roles(r)
        data.setdefault("linked_accounts",{})[st]=ud["login"];save_data(data);print(f"Linked {ud['login']}")
    return web.Response(text="Linked")

# --- Voice state update squads ---

@bot.event
async def on_voice_state_update(member,before,after):
    for ch in (before.channel,after.channel):
        if not ch or str(ch.id) not in data.get("active_squads",{}): continue
        info=data["active_squads"][str(ch.id)];ct=bot.get_channel(info['channel_id']);
        try:m=await ct.fetch_message(info['message_id']);
        except:continue
        membs=[x for x in ch.members if not x.bot]
        if not membs:
            try: await m.delete();await ch.delete()
            except: pass
            data['active_squads'].pop(str(ch.id));save_data(data)
        else:
            emb=discord.Embed(title=ch.name,description=(f"🎮{ch.name.split(' - ')[0]}\n👥{len(membs)}/{ch.user_limit}\n"+"\n".join(f"• {x.display_name}" for x in membs)),color=discord.Color.green())
            try: await m.edit(embed=emb)
            except: pass

# --- Main ---


    # --- Création automatique de squad via le salon trigger ---
    if after.channel and after.channel.id == TEMP_VC_TRIGGER_ID:
        channel = member.guild.get_channel(GUIDE_CHANNEL_ID)  # Utilisé comme point d'entrée
        if channel:
            try:
                class LaunchView(discord.ui.View):
                    def __init__(self, m):
                        super().__init__(timeout=60)
                        self.member = m

                    @discord.ui.button(label="Créer une squad", style=discord.ButtonStyle.green, custom_id="launch_modal")
                    async def launch(self, interaction: discord.Interaction, button: discord.ui.Button):
                        if interaction.user.id != self.member.id:
                            return await interaction.response.send_message("Ce bouton ne t'est pas destiné.", ephemeral=True)
                        try:
                            await interaction.response.send_modal(SquadSetupModal(self.member))
                        except Exception as e:
                            logging.error(f"[Modal Launch Error] {e}")

                view = LaunchView(member)
                await channel.send(f"{member.mention}, clique ci-dessous pour créer ta squad :", view=view, delete_after=60)
            except Exception as e:
                print(f"❌ Erreur lors de l'envoi du modal dans un salon : {e}")
            except:
            print(f"❌ Impossible d'envoyer le modal à {member.display_name}")
def main():
    app=web.Application();app.router.add_post("/webhook",handle_webhook);app.router.add_get("/auth/twitch/callback",twitch_callback)
    r=web.AppRunner(app);loop=asyncio.get_event_loop();
    loop.run_until_complete(r.setup());loop.run_until_complete(web.TCPSite(r,WEBHOOK_HOST,WEBHOOK_PORT).start());
    loop.run_until_complete(bot.start(DISCORD_TOKEN))

if __name__=="__main__": main()


# --- Modal pour création de Squad personnalisée ---
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
            return await interaction.response.send_message("⏳ Attends quelques secondes avant de recréer une squad.", ephemeral=True)
        user_squad_cooldowns[self.member.id] = now_ts

        try:
            game_name = self.game_name.value.title()
            max_players = int(self.max_players.value)
        except:
            return await interaction.response.send_message("Erreur dans les données fournies.", ephemeral=True)

        guild = interaction.guild
        category = guild.get_channel(SQUAD_VC_CATEGORY_ID)
        if not category:
            return await interaction.response.send_message("Catégorie introuvable.", ephemeral=True)

        suffix = random.randint(1000, 9999)
        vc_name = f"{game_name} - Squad {self.member.display_name} ({suffix})"
        vc = await guild.create_voice_channel(
            name=vc_name,
            category=category,
            user_limit=max_players
        )

        try:
            try:
            await self.member.move_to(vc)
        except Exception as e:
            logging.warning(f"[Move Error] {e}")
        except:
            pass

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
        except Exception as e:
            logging.error(f"[Send Embed Error] {e}")
            return
            view.message = msg
            data.setdefault("active_squads", {})[str(vc.id)] = {
                "channel_id": announce_ch.id,
                "message_id": msg.id
            }
            try:
                save_data(data)
            except Exception as e:
                logging.error(f"[Save Data Error] {e}")

        await interaction.response.send_message("✅ Squad créée avec succès !", ephemeral=True)



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
            except:
                pass
            data["active_squads"].pop(vc_id, None)
            save_data(data)
