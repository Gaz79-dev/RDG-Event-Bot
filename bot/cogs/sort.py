import discord
from discord.ext import commands
from discord import app_commands
import os
from typing import List, Dict

# Use relative import to go up one level to the 'bot' package root
from .event_management import create_event_embed, PersistentEventView
from ..utils.database import Database

class SortCog(commands.Cog):
    """A cog for containing the /sort command."""
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def repost_sorted_events(self, interaction: discord.Interaction, sort_order: str):
        """The core logic for deleting and re-posting events in a channel."""
        db: Database = self.bot.db
        channel: discord.TextChannel = interaction.channel

        all_events = await db.get_upcoming_events()
        if not all_events:
            await interaction.followup.send("There are no active events to sort.", ephemeral=True)
            return

        event_messages_to_delete = []
        events_to_repost = []
        for event in all_events:
            if event.get('message_id') and event.get('channel_id') == channel.id:
                event_messages_to_delete.append(event['message_id'])
                events_to_repost.append(event)
        
        if not events_to_repost:
            await interaction.followup.send("No sortable event messages from this bot were found in this channel.", ephemeral=True)
            return

        # Delete the old messages
        try:
            await channel.delete_messages([discord.Object(id=mid) for mid in event_messages_to_delete])
        except Exception as e:
            print(f"Could not bulk delete messages: {e}. Trying one-by-one.")
            for msg_id in event_messages_to_delete:
                try:
                    await (await channel.fetch_message(msg_id)).delete()
                except Exception as individual_e:
                     print(f"Could not delete message {msg_id}: {individual_e}")

        # Sort the events list in Python
        events_to_repost.sort(key=lambda e: e['event_time'], reverse=(sort_order == 'DESC'))

        # Re-post the events in the new order
        for event_data in events_to_repost:
            view = PersistentEventView(db)
            embed = await create_event_embed(self.bot, event_data['event_id'], db)
            content = " ".join([f"<@&{rid}>" for rid in event_data.get('mention_role_ids', [])])
            
            new_message = await channel.send(content=content, embed=embed, view=view)
            await db.update_event_message_id(event_data['event_id'], new_message.id)

        await interaction.followup.send("Events have been re-sorted in this channel.", ephemeral=True)

    @app_commands.command(name="sort", description="Re-sorts all event messages in this channel by date.")
    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(order="The order to sort the events in.")
    @app_commands.choices(order=[
        discord.app_commands.Choice(name="Ascending (Soonest First)", value="ASC"),
        discord.app_commands.Choice(name="Descending (Furthest First)", value="DESC"),
    ])
    async def sort(self, interaction: discord.Interaction, order: str):
        await interaction.response.defer(ephemeral=True, thinking=True)
        await self.repost_sorted_events(interaction, order)

async def setup(bot: commands.Bot):
    await bot.add_cog(SortCog(bot))
