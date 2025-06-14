from discord.ext import commands

class Roles(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    async def role(self, ctx, role_name):
        role = discord.utils.get(ctx.guild.roles, name=role_name)
        if role:
            await ctx.author.add_roles(role)
            await ctx.send(f"Rôle {role_name} ajouté.")
        else:
            await ctx.send("Rôle introuvable.")

def setup(bot):
    bot.add_cog(Roles(bot))