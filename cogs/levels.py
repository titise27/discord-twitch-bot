from discord.ext import commands
import discord
import asyncio

class Levels(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.user_times = {}

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if after.channel:
            self.user_times[member.id] = asyncio.get_event_loop().time()
        elif before.channel and member.id in self.user_times:
            duration = asyncio.get_event_loop().time() - self.user_times.pop(member.id)
            print(f"{member} est resté {duration / 3600:.2f} heures.")

def setup(bot):
    bot.add_cog(Levels(bot))