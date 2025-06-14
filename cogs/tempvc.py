from discord.ext import commands
import discord
import asyncio
import os

TEMP_VC_TRIGGER_ID = int(os.getenv("TEMP_VC_TRIGGER_ID"))

class TempVC(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if after.channel and after.channel.id == TEMP_VC_TRIGGER_ID:
            guild = member.guild
            category = after.channel.category
            temp_channel = await guild.create_voice_channel(name=f"🔊 {member.display_name}", category=category)
            await member.move_to(temp_channel)
            await asyncio.sleep(1)
            await after.channel.set_permissions(member, connect=False)
            while True:
                await asyncio.sleep(60)
                if len(temp_channel.members) == 0:
                    await temp_channel.delete()
                    break

def setup(bot):
    bot.add_cog(TempVC(bot))