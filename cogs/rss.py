import json
from discord.ext import commands, tasks
from bs4 import BeautifulSoup
import discord
import feedparser
import psycopg2
# Internal modules
import cogs.modules.psql as psql
import cogs.modules.rss_parser as rss_parser

"""
Retreives the data from RSS URL and return the status codes as well as the data. Return -1 if something went wrong.
"""


class RSS(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

        # Import database settings from file and set up connection.
        with open('psql', 'r') as db_file:
            db_settings = json.load(db_file)
            self.psql = psql.PSQL(
                db_settings["host"],
                db_settings["username"],
                db_settings["password"],
                db_settings["database"],
                db_settings["port"]
            )

        # Start looking for updates as soon as the bot is ready every 3 hours.
        self.look_for_updates_rss.start(self.bot)

    """
    Save an RSS URL to parse.

    Requires the RSS url. First tries to see if is a valid url. Then does a select against the database to see if there
    is any prior data for this user's ID. Updates the table if a row is found and inserts into the database if nothing
    is found.
    """
    @commands.command(aliases=['srss'])
    async def setrss(self, ctx, name=None, rss_url=None, *args):
        if name is None or  rss_url is None:
            return await ctx.send('Name or URL is missing. Command is `!setrss Name https://rss.url`')

        # Database connection
        database = self.psql

        # Check if valid URL
        resp = await rss_parser.get_rss_feed(rss_url)
        if resp['status'] != 200:
            if resp['status'] == -1:
                await ctx.send(resp['data'])
                return print(resp['error'])
            else:
                # Should not happen?
                await ctx.send('Unhandled error. Check console for error message.')
                return print(resp['error'])

        # Get latest post and save it along with the other data.
        try:
            feed = feedparser.parse(resp['data'])
        except Exception as error:
            return await ctx.send(f"Failed to parse the RSS:\n{error}")

        try:
            # Connect to the database and look user and RSS name.
            select = database.select(
                table = "rss_feeds",
                columns = "*",
                condition = f"WHERE user_id = {ctx.author.id} AND name = '{name}'"
            )

            if len(select) == 0:
                # RSS was not found.
                # Add URL, ID, latest post, channel ID (the request came from) and name to the database.
                database.insert(
                    table = "rss_feeds",
                    columns = "user_id, url, latest, channel_id, name",
                    values = f"{ctx.author.id}, '{rss_url}', '{feed['entries'][0]['title']}', {ctx.channel.id}, '{name}'"
                )
                await ctx.send("Url has been saved. All updates will be sent to this channel.")
            else:
                # The RSS feed was found.
                # Update the URL and the channel ID (the request came from).
                database.update(
                    table = "rss_feeds",
                    values = f"url='{rss_url}', channel_id={ctx.channel.id}",
                    condition = f"WHERE id = '{select[0][0]}'"
                )
                await ctx.send("URL has been updated. All updates will be sent to this channel.")
        except psycopg2.OperationalError as error:
            # Something went wrong.
            await ctx.send(error)


    @tasks.loop(hours=3)
    async def look_for_updates_rss(self, bot, *args):
        self.bot = bot
        database = self.psql
        table = 'rss_feeds'

        # Get all RSS feeds to check for updates.
        try:
            select = database.select(table = table, columns = "*")
        except Exception as error:
            return print(f"Failed to connect to databse: {error}")

        # No data (no user has it set up yet).
        if len(select) == 0:
            return print("No user set up yet. (RSS feed)")
        else:
            # Loop all users' feed.
            for rss_feed in select:
                # User's data.
                db_id = rss_feed[0]
                user_id = rss_feed[1]
                rss_url = rss_feed[2]
                latest = rss_feed[3]
                channel = self.bot.get_channel(rss_feed[4])
                rss_feed_name = rss_feed[5]

                # Get rss data async
                resp = await rss_parser.get_rss_feed(rss_url)
                # Failed to get data
                if resp['status'] != 200:
                    if resp['status'] != -1:
                        return await channel.send(f"Received error for <@{user_id}>: {resp['error']}")
                    else:
                        return await channel.send(f"Could not get updates for <@{user_id}>: {resp['error']}.")

                # Parse data
                try:
                    feed = feedparser.parse(resp['data'])
                except Exception as error:
                    return await channel.send(f"Failed to parse the RSS:\n{error}")

                if latest is None:
                    # First time parsing this RSS feed.
                    # Save latest update to database.
                    database.update(
                        table = table,
                        values = f"latest = '{feed['entries'][0]['title']}'",
                        condition = f"WHERE id = {db_id}"
                    )
                    await channel.send(f"Latest update has been saved and you will be informed of updates in the future. ({rss_feed_name})")

                elif latest != feed['entries'][0]['title']:
                    # Users has updates.
                    stop_looking = False

                    # Loop all chapters.
                    for update in feed['entries']:
                        if update['title'] == latest:
                            # Current update is the latest. Stop looking for more.
                            stop_looking = True
                        else:
                            # Message for removed embeds and phone notification text.
                            message = f"*{rss_feed_name}* - {update['title']}"
                            # Gather data for embed.
                            embed_title        = update['title']
                            embed_post_link    = update['link']
                            embed_description  = BeautifulSoup(update['description'], features='html.parser').p.text
                            embed_author_name  = feed['feed']['title_detail']['value']
                            embed_author_link  = feed['feed']['link']
                            try:
                                embed_author_icon  = feed['feed']['image']['href']
                            except KeyError:
                                embed_author_icon = ''

                            # Create embed.
                            embed=discord.Embed(title=embed_title, url=embed_post_link, description=embed_description)
                            embed.set_author(name=embed_author_name, url=embed_author_link, icon_url=embed_author_icon)

                            # Send update to channel.
                            await channel.send(embed=embed, content=message)
                            # Add name of update.

                        if stop_looking:
                            # All updates found.
                            # Update database with new latest update.
                            database.update(
                                table = "rss_feeds",
                                values = f"latest='{feed['entries'][0]['title']}'",
                                condition = f"WHERE id = {db_id}"
                            )

                            # Stop the loop.
                            break
                else:
                    # No updates, nothing to do.
                    # await channel.send("Nothing new yet.")
                    pass

    # Do not start looking before the bot has connected to Discord nad is ready.
    @look_for_updates_rss.before_loop
    async def before_looking(self):
        print("RSS function is waiting for bot to start.")
        await self.bot.wait_until_ready()
        print("Ready start RSS functionality.")

def setup(bot):
    bot.add_cog(RSS(bot))