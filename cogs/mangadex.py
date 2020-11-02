import asyncio, discord, feedparser, json, os, re, aiohttp, sys
from PIL import Image
from io import BytesIO
from discord.ext import commands, tasks
from datetime import datetime, timedelta

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
        except aiohttp.InvalidURL as error:
            return {'status': -1, 'error': f"{error} is not a valid URL."}
        except aiohttp.ClientConnectorError:
            return {'status': -1, 'error': f"Could not connect to {rss_url}."}

class Mangadex(commands.Cog):
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

        # Start looking for updates as soon as the bot is ready every 15 minutes.
        self.look_for_updates.start(self.bot)


    """
    Set the user's RSS url for looking up mangas.

    Requires the RSS url. First tries to see if is a valid url. Then does a select against the database to see if there
    is any prior data for this user's ID. Updates the table is a row is found and inserts into the database if nothing
    is found.
    """
    @commands.command(aliases=['setdex', 'set'])
    async def setdexurl(self, ctx, rss_url, *args):
        # Database connection
        database = self.psql

        # Check if valid URL
        resp = get_rss_feed(rss_url)
        if resp['status'] != 200:
            if resp['status'] == -1:
                return await ctx.send(resp['error'])
            else:
                return await ctx.send(f"Got status code {resp.status}, excepted 200. Please try again later.")


        try:
            # Connect to the database and look up requesting user.
            select = database.select(
                table = "mangadex",
                columns = "*",
                condition = f"WHERE user_id = {ctx.author.id}"
            )

            if len(select) == 0:
                # User was not found.
                # Add URL, ID and channel ID (the request came from) to the database.
                database.insert(
                    table = "mangadex",
                    columns = "rss_feed, user_id, channel_id",
                    values = f"'{rss_url}', {ctx.author.id}, {ctx.channel.id}"
                )
                await ctx.send(f"Url has been saved. All updates will be sent to this channel.")
            else:
                # The user was found.
                # Update the URL and the channel ID (the request came from).
                database.update(
                    table = "mangadex",
                    values = f"rss_feed='{rss_url}', channel_id={ctx.channel.id}",
                    condition = f"WHERE user_id = {ctx.author.id}"
                )
                await ctx.send(f"URL has been updated. All updates will be sent to this channel.")
        except Exception as error:
            # Something went wrong.
            await ctx.send(error)


    """
    Function that runs every 15 minutes, responsible for sending
    updates to the users with new chapters to read.
    """
    @tasks.loop(seconds=900)
    async def look_for_updates(self, bot, *args):
        self.bot = bot
        database = self.psql


        """ " " " " " " " " " " " "
        " BEING HELPER FUNCTIONS  "
        " " " " " " " " " " " " """

        """
        Gets the cover image and returns a Pillow (PIL) image.
        """
        async def get_cover_image(manga_url, channel):
            async with aiohttp.ClientSession() as session:
                async with session.get(manga_url) as resp:
                    if resp.status != 200:
                        await channel.send(f"Failed to retreive manga {manga_url}.")

                    html = await resp.text()
                    manga = json.loads(html)
                    # Extact link to cover.
                    cover_url = manga['data']['mainCover']

                async with session.get(cover_url) as resp:
                    if resp.status != 200:
                        await channel.send(f"Failed to retreive cover file {manga['data']['title']}.")

                    # Create an object from the data.
                    data = BytesIO(await resp.read())
                    # Create an image from the data.
                    image = Image.open(data)

                    return image

        """
        Takes a list of Pillow (PIL) images and pastes them together horizontally after having resized all images to the
        height of the smallest image. Aspect ratio is maintained.
        """
        async def concatenate_images(img_list):
            # Get the height of the smallest image and and set it as the max allowed height.
            max_height = min(x.height for x in img_list)
            # Loop all images which are too high and resize.
            for img in [i for i in img_list if i.height > max_height]:
                img.thumbnail((img.width, max_height), resample=Image.LANCZOS)

            # Calculate the width of the final image.
            total_width = sum(x.width for x in img_list)
            # Create an empty image with black color.
            concatenated_image = Image.new('RGB', (total_width, max_height), (0, 0, 0))

            # Paste each image at X = 0, Y = current_width.
            current_width = 0
            for img in img_list:
                concatenated_image.paste(img, (current_width, 0))
                current_width += img.width

            return concatenated_image

        """ " " " " " " " " " " "
        " END HELPER FUNCTIONS  "
        " " " " " " " " " " " """


        # Get all users from database whom we are looking up chapters for.
        try:
            select = database.select(table = "mangadex", columns = "*")
        except Exception as error:
            return print(f"Failed to connect to databse: {error}")

        # No data (no user as it set up yet).
        if len(select) == 0:
            return print("No user set up yet.")
        else:
            # Loop all users.
            for user in select:
                # User's data.
                user_id = user[0]
                rss_url = user[1]
                latest_chapter = user[2]
                channel = self.bot.get_channel(user[3])

                # Get rss data async
                resp = await get_rss_feed(rss_url)
                # Failed to get data
                if resp['status'] != 200:
                    if resp['status'] == -1:
                        return await channel.send(resp['error'])
                    else:
                        return await channel.send(f"Got status code {resp['status']}, excepted 200. Will try again later.")

                # Parse data
                try:
                    feed = feedparser.parse(resp['data'])
                except Exception as error:
                    return await channel.send(f"Failed to parse the RSS:\n{error}")

                if latest_chapter == None:
                    # First time looking up chapters.
                    # Save latest chapter's ID to database.
                    database.update(
                        table = "mangadex",
                        values = f"chapter_id='{feed['entries'][0]['id']}'",
                        condition = f"WHERE user_id = {user_id}"
                    )
                    await channel.send("Latest chapters has been saved and you will be informed of updates in the future.")

                elif latest_chapter != feed['entries'][0]['id']:
                    # Users has updates.
                    updates = {}
                    count = 0 # In case last seen chapter is of a manga no longer tracked.
                    message = None

                    # Loop all chapters.
                    for chapter in feed['entries']:
                        if chapter['id'] == latest_chapter:
                            # Current chapter is the latest. Stop looking for more.
                            message = 'NEW CHAPTERS TO READ!'
                        elif count == 100:
                            # In case of manga no longer being tracked (and thus latest chapter is no longer in the RSS
                            # feed), stop looking for updates after 100 iterations.
                            # Also useful in case of mega update or new manga added with a lot of recent updates..
                            message = 'Found at least 100 chapters and stopped looking.'
                        else:
                            # Add chapter to list of new ones and download image.
                            count += 1
                            manga_link = chapter['mangalink']

                            if not manga_link in updates:
                                # First chapter of this manga.
                                updates[manga_link] = {}
                            if not "message" in  updates[manga_link]:
                                # Place holder for chapters for this manga.
                                updates[manga_link]["message"] = []
                            if not "image" in  updates[manga_link]:
                                # Link to image.
                                url = f"{manga_link[:20]}/api/v2/{manga_link[21:]}"
                                # Cover image for this manga in Pillow (PIL) format.
                                updates[manga_link]["image"] = await get_cover_image(url, channel)

                            # Add name of chapter. Will later on be added to final message.
                            # This way makes all the chapters sorted by manga.
                            updates[manga_link]["message"].append(f"{chapter['title']}")

                        if message is not None:
                            # Message has been set, all updates found. Inform the user.
                            # Get all images and chapters.
                            img_list = []
                            for u in updates:
                                img_list.append(updates[u]['image'])
                                for msg in updates[u]['message']:
                                    message += f"\n{msg}"

                            with BytesIO() as image_binary:
                                # Build the images from all cover images.
                                tmp_img = await concatenate_images(img_list)
                                tmp_img.save(image_binary, 'PNG')
                                image_binary.seek(0)
                                # Send information about new chapters with the image.
                                await channel.send(content=message, file=discord.File(fp=image_binary, filename='image.jpg'))

                            # Update database with new latest chapter.
                            database.update(
                                table = "mangadex",
                                values = f"chapter_id='{feed['entries'][0]['id']}'",
                                condition = f"WHERE user_id = {user_id}"
                            )

                            # Stop the loop.
                            break
                else:
                    # No updates, nothing to do.
                    # await channel.send("Nothing new yet.")
                    pass

    # Do not start looking before the bot has connected to Discord nad is ready.
    @look_for_updates.before_loop
    async def before_looking(self):
        print("Waiting for bot to start...")
        await self.bot.wait_until_ready()
        print("Start looking for updates.")


def setup(bot):
    bot.add_cog(Mangadex(bot))