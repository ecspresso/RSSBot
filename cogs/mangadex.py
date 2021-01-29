import asyncio, discord, feedparser, json, os, re, aiohttp, sys, time
from PIL import Image
from io import BytesIO
from discord.ext import commands, tasks

# To make loading modules from /modules possible.
PACKAGE_PARENT = '..'
SCRIPT_DIR = os.path.dirname(os.path.realpath(os.path.join(os.getcwd(), os.path.expanduser(__file__))))
sys.path.append(os.path.normpath(os.path.join(SCRIPT_DIR, PACKAGE_PARENT)))

import modules.helper.psql as psql
import modules.helper.rss_parser as rss_parser

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
        self.look_for_updates_manga.start(self.bot)


    """
    Set the user's RSS url for looking up mangas.

    Requires the RSS url. First tries to see if is a valid url. Then does a select against the database to see if there
    is any prior data for this user's ID. Updates the table if a row is found and inserts into the database if nothing
    is found.
    """
    @commands.command(aliases=['setdex', 'set'])
    async def setdexurl(self, ctx, rss_url, *args):
        # Database connection
        database = self.psql

        # Check if valid URL
        resp = rss_parser.get_rss_feed(rss_url)
        if resp['status'] != 200:
            if data['status'] == -1:
                if data['error'] == 'invalid_url_error':
                    await ctx.send(f'Error: {rss_url} is not a valid URL.')
                if data['error'] == 'connection_error':
                    await ctx.send(f'Error: Could not connect to {rss_url}.')
                if data['error'] == 'retry_error':
                    await ctx.send(f'Error: Could not connect to {rss_url} after 5 attempts.')

                return print(data['error'])
            else:
                # Should not happen?
                await ctx.send('Unhandled error. Check console for error message.')
                return print(data['error'])

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
    async def look_for_updates_manga(self, bot, *args):
        self.bot = bot
        database = self.psql


        """ " " " " " " " " " " " "
        " BEING HELPER FUNCTIONS  "
        " " " " " " " " " " " " """

        """
        Gets the cover image and returns a Pillow (PIL) image.
        """
        async def get_cover_image(manga_url):
            async with aiohttp.ClientSession() as session:
                try:
                    retry_count = 0
                    success = False
                    while retry_count < 5 and not success:
                        async with session.get(manga_url) as resp:
                            if resp.status == 200:
                                html = await resp.text()
                                manga = json.loads(html)
                                # Extact link to cover.
                                cover_url = manga['data']['mainCover']
                                success = True
                            else:
                                retry_count += 1
                                time.sleep(60)
                    if retry_count == 5:
                        raise ValueError('To many failed connection attempts', retry_count)

                    retry_count = 0
                    while retry_count < 5 and success:
                        async with session.get(cover_url) as resp:
                            if resp.status == 200:
                                # Create an object from the data.
                                data = BytesIO(await resp.read())
                                # Create an image from the data.
                                image = Image.open(data)

                                return {'status': resp.status, 'error': None, 'data': image}
                            else:
                                retry_count += 1
                                time.sleep(60)
                    if retry_count == 5:
                        raise ValueError('To many failed connection attempts', retry_count)

                except aiohttp.InvalidURL as error:
                    return {'status': -1, 'data': f"{error} is not a valid URL.", 'error': 'invalid_url_error'}
                except aiohttp.ClientConnectorError:
                    return {'status': -1, 'data': f"Could not connect to {rss_url}.", 'error': 'connection_error'}
                except ValueError as error:
                    return {'status': -1, 'data': f"Failed to download data after {data.retry_count} attempts", 'error': 'retry_error'}

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

        # No data (no user has it set up yet).
        if len(select) == 0:
            return print("No user set up yet. (Mangadex)")
        else:
            # Loop all users.
            for user in select:
                # User's data.
                user_id = user[0]
                rss_url = user[1]
                latest_chapter = user[2]
                channel = self.bot.get_channel(user[3])

                # Get rss data async
                resp = await rss_parser.get_rss_feed(rss_url)
                # Failed to get data
                if resp['status'] != 200:
                    if resp['status'] == -1:
                        if resp['error'] == 'invalid_url_error':
                            await ctx.send(f'Error: Your URL is not valid <@{user_id}>.')
                        if resp['error'] == 'connection_error':
                            await ctx.send(f'Error: Could not get updates for <@{user_id}>. Connection failed.')
                        if resp['error'] == 'retry_error':
                            await ctx.send(f'Error: Could not get updates for <@{user_id}>\' after 5 attempts.')

                        print(data['error'])
                        continue
                    else:
                        # Should not happen?
                        await ctx.send('Unhandled error. Check console for error message.')
                        return print(data['error'])

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
                    error_message = None
                    done = False
                    end_of_feed = False

                    # Loop all chapters.
                    for chapter in feed['entries']:
                        if chapter['id'] == latest_chapter:
                            # Current chapter is the latest. Stop looking for more.
                            done = True
                        else:
                            # Add chapter to list of new ones and prepare embed data.
                            count += 1
                            manga_link = chapter['mangalink']

                            if not manga_link in updates:
                                # Prepare data for embed (step 1: get manga data, not just this chapter).
                                api_link = f"{manga_link[:20]}/api/v2/{manga_link[21:]}"
                                data = await rss_parser.get_rss_feed(api_link)
                                if data['status'] != 200:
                                    if data['status'] == -1:
                                        if data['error'] == 'invalid_url_error':
                                            await ctx.send(f'Error: One of <@{user_id}> updates had an invalid url.\n{manga_link}')
                                            print(data['error'])
                                            continue
                                        if data['error'] == 'connection_error':
                                            await ctx.send(f'Error: Could not get updates for <@{user_id}>. Connection failed.')
                                        if data['error'] == 'retry_error':
                                            await ctx.send(f'Error: Could not get updates for <@{user_id}>\' after 5 attempts.')

                                        return print(data['error'])
                                    else:
                                        # Should not happen?
                                        await ctx.send('Unhandled error. Check console for error message.')
                                        return print(data['error'])

                                manga_data = json.loads(data['data'])

                                # Prepare data for embed (step 2: store data).
                                updates[manga_link] = {
                                    'description': chapter['summary'],
                                    'thumbnail':   manga_data['data']['mainCover'],
                                    'author_name': manga_data['data']['title'],
                                    'author_link': manga_link
                                }


                            if not "chapters" in updates[manga_link]:
                                # Place holder for chapters for this manga.
                                updates[manga_link]["chapters"] = []

                            if not "image" in  updates[manga_link]:
                                # Link to image.
                                url = f"{manga_link[:20]}/api/v2/{manga_link[21:]}"
                                # Cover image for this manga in Pillow (PIL) format.
                                image_data = await get_cover_image(url)
                                if image_data['status'] != 200:
                                    if image_data['status'] == -1:
                                        return print(f"Failed to get cover image:\n{image_data['error']}")
                                    else:
                                        # Should not happen?
                                        await ctx.send('Unhandled error. Check console for error message.')
                                        return print(image_data['error'])
                                else:
                                    updates[manga_link]['image'] = image_data['data']

                            # Add name and link of chapter.
                            # This way makes all the chapters sorted by manga.
                            updates[manga_link]["chapters"].append({
                                'title': chapter['title'],
                                'url':   chapter['id']
                            })

                            if len(feed['entries']) == count:
                                done = True
                                # If we reached the end of the feed means that the latest saved chapter has been remove
                                # or was not found for some other reason. This should act as a fail safe.
                                end_of_feed = True
                            elif count == 100:
                                # In case of manga no longer being tracked (and thus latest chapter is no longer in the RSS
                                # feed), stop looking for updates after 100 iterations.
                                # Also useful in case of mega update or new manga added with a lot of recent updates..
                                done = True


                        if done is True:
                            if end_of_feed:
                                error_message = 'Reached end of feed without finding the latest chapter.'
                            elif count == 100:
                                error_message = 'Found at least 100 chapters and stopped looking.'


                            embed = discord.Embed(
                                title = 'New chapters to read',
                                description = 'Here are the latests chapters from MangaDex.',
                                url = 'https://mangadex.org/follows',
                                colour = discord.Color(16225313)
                            )
                            embed.set_author(
                                name='MangaDex',
                                url='https://mangadex.com',
                                icon_url='https://mangadex.org/favicon-192x192.png'
                            )

                            img_list = []

                            # If we reached end of feed or found more that 100 updates.
                            # Then only give the user the 10 latest updates or, if less
                            # than 10 updates, how ever many we have.
                            if error_message is not None:
                                if len(updates) > 10:
                                    index_length = 10
                                else:
                                    index_length = len(updates)

                                embed.set_footer(text=f"Only showing {index_length} updates the because the previously saved chapter was not found.\nReason: {error_message}")

                                # Replace all found chapters with only the 10 first ones.
                                updates_temp = {}
                                for index in range(index_length):
                                    manga_link = f"{feed['entries'][index]['mangalink']}"

                                    if manga_link not in updates_temp:
                                        updates_temp[manga_link] = updates[manga_link]
                                        updates_temp[manga_link]["chapters"] = []

                                    updates_temp[manga_link]["chapters"].append({
                                        'title': feed['entries'][index]['title'],
                                        'url':   feed['entries'][index]['id']
                                    })

                                updates = updates_temp

                            # Loop all updates and add name and links to embed.
                            for this_update in updates:
                                for this_chapter in updates[this_update]['chapters']:
                                    embed.add_field(
                                        name=this_chapter['title'],
                                        value=this_chapter['url'],
                                        inline=False
                                    )

                                    # Download cover is not already done.
                                    if updates[this_update]['image'] not in img_list:
                                        img_list.append(updates[this_update]['image'])

                            with BytesIO() as image_binary:
                                # Build the images from all cover images.
                                tmp_img = await concatenate_images(img_list)
                                tmp_img.save(image_binary, 'PNG')
                                # Set image at frame 0.
                                image_binary.seek(0)
                                # Create discord file.
                                cover_images = discord.File(fp=image_binary, filename='cover_images.jpg')
                                # Add file to embed.
                                embed.set_image(url="attachment://cover_images.jpg")
                                # Send.
                                await channel.send(embed=embed, file=cover_images)


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
    @look_for_updates_manga.before_loop
    async def before_looking(self):
        print("MangaDex function is waiting for bot to start.")
        await self.bot.wait_until_ready()
        print("Start looking for updates.")


def setup(bot):
    bot.add_cog(Mangadex(bot))