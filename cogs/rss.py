import asyncio, discord, feedparser, json, os, aiohttp, sys
from discord.ext import commands, tasks

# To make loading modules from /modules possible.
PACKAGE_PARENT = '..'
SCRIPT_DIR = os.path.dirname(os.path.realpath(os.path.join(os.getcwd(), os.path.expanduser(__file__))))
sys.path.append(os.path.normpath(os.path.join(SCRIPT_DIR, PACKAGE_PARENT)))

import modules.psql.psql as psql

"""
Retreives the data from RSS URL and return the status codes as well as the data. Return -1 if something went wrong.
"""
async def get_rss_feed(rss_url):
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(rss_url) as resp:
                if resp.status == 200:
                    return {'status': resp.status, 'data': await resp.text()}
                else:
                    try:
                        text = await resp.text()
                    except:
                        text = 'No text'
                    return {'status': resp.status, 'data': text}
        except aiohttp.InvalidURL as error:
            return {'status': -1, 'error': f"{error} is not a valid URL.", 'data': None}
        except aiohttp.ClientConnectorError:
            return {'status': -1, 'error': f"Could not connect to {rss_url}.", 'data': None}

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
        resp = await get_rss_feed(rss_url)
        if resp['status'] != 200:
            if resp['status'] == -1:
                return await ctx.send(resp['error'])
            else:
                return await ctx.send(f"Got status code {resp.status}, excepted 200. Please try again later.")


        try:
            # Connect to the database and look user and RSS name.
            select = database.select(
                table = "rss_feeds",
                columns = "*",
                condition = f"WHERE user_id = {ctx.author.id} AND name = '{name}'"
            )

            if len(select) == 0:
                # RSS was not found.
                # Add URL, ID, channel ID (the request came from) and name to the database.
                database.insert(
                    table = "rss_feeds",
                    columns = "user_id, url, channel_id, name",
                    values = f"{ctx.author.id}, '{rss_url}', {ctx.channel.id}, '{name}'"
                )
                await ctx.send(f"Url has been saved. All updates will be sent to this channel.")
            else:
                # The RSS feed was found.
                # Update the URL and the channel ID (the request came from).
                database.update(
                    table = "rss_feeds",
                    values = f"url='{rss_url}', channel_id={ctx.channel.id}",
                    condition = f"WHERE id = '{select[0][0]}'"
                )
                await ctx.send(f"URL has been updated. All updates will be sent to this channel.")
        except Exception as error:
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
                resp = await get_rss_feed(rss_url)
                # Failed to get data
                if resp['status'] != 200:
                    if resp['status'] != -1:
                        return await channel.send(resp['status'])
                    else:
                        return await channel.send(f"Got status code {resp['status']}, excepted 200. Please try again later.")

                # Parse data
                try:
                    feed = feedparser.parse(resp['data'])
                except Exception as error:
                    return await channel.send(f"Failed to parse the RSS:\n{error}")

                if latest == None:
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
                    message = [f"*{rss_feed_name}*"]
                    stop_looking = False

                    # Loop all chapters.
                    for update in feed['entries']:
                        if update['title'] == latest:
                            # Current update is the latest. Stop looking for more.
                            stop_looking = True
                        else:
                            # Add name of update.
                            message.append(f"[{update['title']}]({update['link']})")

                        if stop_looking:
                            # Messages has been set, all updates found. Inform the user.
                            await channel.send('\n'.join(message))

                            # Update database with new latest update.
                            database.update(
                                table = "rss_feeds",
                                values = f"latest='{update['title']}'",
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
        print("Waiting for bot to start before looking for RSS updates...")
        await self.bot.wait_until_ready()
        print("Ready start RSS functionality.")

def setup(bot):
    bot.add_cog(RSS(bot))