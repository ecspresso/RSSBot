import time
from io import BytesIO
import json
import aiohttp
from PIL import Image


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
            return {'status': -1, 'data': f"Could not connect to {manga_url}.", 'error': 'connection_error'}
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