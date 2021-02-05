import aiofiles
import aiohttp
import json
import os
import platform
import psycopg2
import tarfile
import zipfile
from arsenic import get_session, browsers, services
from discord.ext import commands, tasks
# Internal modules
import cogs.modules.psql as psql
import cogs.modules.rss_parser as rss_parser

"""
Retreives the data from RSS URL and return the status codes as well as the data. Return -1 if something went wrong.
"""


class TwichPrime(commands.Cog):
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
        self.look_for_twitch_prime_loot.start(self.bot)

    @commands.command(aliases=['twitchprime'])
    async def twitchprime(self, ctx, *args):
        # Database connection
        database = self.psql

        try:
            # Connect to the database
            select = database.select(
                table = "twitch_prime_users",
                columns = "*",
                condition = f"WHERE user_id = {ctx.author.id}"
            )

            if len(select) == 0:
                # User was not were not found.
                # User ID and channel ID (the request came from) to the database.
                database.insert(
                    table = "twitch_prime_users",
                    columns = "user_id, channel_id",
                    values = f"{ctx.author.id}, {ctx.channel.id}"
                )
                await ctx.send("All updates will be sent to this channel.")
            else:
                # User was found.
                # Update the channel ID (the request came from).
                database.update(
                    table = "twitch_prime_users",
                    values = f"channel_id={ctx.channel.id}",
                    condition = f"WHERE user_id='{ctx.author.id}'"
                )
                await ctx.send("All updates will be sent to this channel.")
        except psycopg2.OperationalError as error:
            # Something went wrong.
            await ctx.send(error)


    @tasks.loop(hours=3)
    async def look_for_updates_twitch(self, bot, *args):
        self.bot = bot
        database = self.psql
        twitch_prime_url = 'https://gaming.amazon.com/home'
        table_users = 'twitch_prime_users'
        table_updates = 'twitch_prime_updates'

        # Get latest loot.
        service = services.Geckodriver(binary='./geckodriver')
        browser = browsers.Firefox(**{'moz:firefoxOptions': {'args': ['-headless']}})
        async with get_session(service, browser) as session:
            await session.get(twitch_prime_url)
            offer = await session.wait_for_element(10, '.offer')
            text = await offer.get_element('.tw-amazon-ember-bold')
            latest_loot = await text.get_text()

        # Get all RSS feeds to check for updates.
        try:
            select = database.select(table = table_updates, columns = "loot")
        except Exception as error:
            return print(f"Failed to connect to databse: {error}")

        last_seen_loot = select[0][0]

        if latest_loot != last_seen_loot:
            pass


        # database.update(
        #     table = "rss_feeds",
        #     values = f"latest='{feed['entries'][0]['title']}'",
        #     condition = f"WHERE id = {db_id}"
        # )

        # No data (no user has it set up yet).
        # if len(select) == 0:
        #     return print("No user set up yet. (Twitch Prime)")
        # else:
        #     # Loop
        #     for rss_feed in select:
        #         # User's data.
        #         user_id = rss_feed[0]
        #         channel = self.bot.get_channel(rss_feed[1])
        #         await channel.send(f"<@{user_id}>: {loot}")


    # Do not start looking before the we have gecko and the bot has connected to Discord and is ready.
    @look_for_updates_twitch.before_loop
    async def before_looking(self):
        print('Look for geckodriver.')
        files = os.listdir('.')

        if "geckodriver" not in files:
            print('Geckodriver was not found. Will download now.')
            os_name = platform.system()

            if os_name == 'Windows':
                gecko_url = 'https://github.com/mozilla/geckodriver/releases/download/v0.29.0/geckodriver-v0.29.0-win64.zip'
                file_name = 'geckodriver.zip'
            elif os_name == 'Linux':
                gecko_url = 'https://github.com/mozilla/geckodriver/releases/download/v0.29.0/geckodriver-v0.29.0-linux64.tar.gz'
                file_name = 'geckodriver.tar.gz'


            async with aiohttp.ClientSession() as session:
                try:
                    async with session.get(gecko_url) as resp:
                        if resp.status == 200:
                            file = await aiofiles.open(file_name, mode='wb')
                            await file.write(await resp.read())
                            await file.close()
                except Exception as error:
                    print(error)

            if os_name == 'Windows':
                with zipfile.ZipFile(file, 'r') as zip_file:
                    zip_file.extractall()
                os.rename('geckodriver.exe', 'geckodriver')
            elif os_name == 'Linux':
                with tarfile.open(file, 'r') as tar_file:
                    tar_file.extractall()
            os.remove(file)


        print("Twitch Prime function is waiting for bot to start.")
        await self.bot.wait_until_ready()
        print("Ready start Twitch Prime functionality.")

def setup(bot):
    bot.add_cog(TwichPrime(bot))