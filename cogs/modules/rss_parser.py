import time
import aiohttp

"""
Retreives the data from RSS URL and return the status codes as well as the data. Return -1 if something went wrong.
"""
async def get_rss_feed(rss_url):
    async with aiohttp.ClientSession() as session:
        try:
            retry_count = 0
            while retry_count < 5:
                async with session.get(rss_url) as resp:
                    if resp.status == 200:
                        return {'status': resp.status, 'data': await resp.text()}
                    else:
                        retry_count += 1
                        time.sleep(60)
            if retry_count == 5:
                raise ValueError('To many failed connection attempts', retry_count)
        except aiohttp.InvalidURL as error:
            return {'status': -1, 'data': f"Error: {rss_url} is not a valid URL.", 'error': error}
        except aiohttp.ClientConnectorError as error:
            return {'status': -1, 'data': f"Error: Could not connect to {rss_url}.", 'error': error}
        except ValueError as error:
            return {'status': -1, 'data': f"Error: Could not connect to {rss_url} after {retry_count} attempts.", 'error': error}