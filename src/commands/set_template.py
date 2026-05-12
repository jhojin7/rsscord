"""
src/commands/set_template.py
Example command using discord.py (commands extension) to set per-thread templates.
Adjust db helper import to match your project.
"""

from discord.ext import commands
from src.lib import db  # adapt to your DB helper

class TemplateCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name='set_template')
    @commands.has_permissions(manage_guild=True)
    async def set_template(self, ctx, thread_id: int, *, template_text: str):
        """
        Usage: !set_template <thread_id> <template>
        Example template: "{head} **{title}**\n{summary}\n{link}"
        """
        if len(template_text) > 4000:
            await ctx.send("Template too long (max 4000 chars).")
            return
        # Basic mention safety for non-admins
        if ('@everyone' in template_text or '@here' in template_text) and not ctx.author.guild_permissions.administrator:
            await ctx.send("You must be an admin to use @everyone or @here in templates.")
            return
        # Persist - adapt SQL to your schema
        await db.execute("UPDATE threads SET message_template = $1 WHERE id = $2", template_text, thread_id)
        await ctx.send(f"Template saved for thread {thread_id}")


def setup(bot):
    bot.add_cog(TemplateCog(bot))
