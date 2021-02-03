import os
from discord.ext import commands

with open('token', 'r') as token_file:
    token = token_file.read()


bot = commands.Bot(command_prefix = '!')

@bot.event
async def on_ready():
    print(f'{bot.user.name}-bot is ready.')

# @bot.event
# async def on_command_error(ctx, error):
#     if isinstance(error, commands.CommandNotFound):
#         return
#     await ctx.send(error)
#     print(error)

@bot.command()
async def load(ctx, extension):
    bot.load_extension(f'cogs.{extension}')
    await ctx.send(f"{extension} Loaded.")

@bot.command()
async def unload(ctx, extension):
    bot.unload_extension(f'cogs.{extension}')
    await ctx.send(f"{extension} Unloaded.")

@bot.command()
async def reload(ctx, extension):
    bot.reload_extension(f'cogs.{extension}')
    await ctx.send(f"{extension} Reloaded.")

if __name__ == '__main__':
    for file in os.listdir('./cogs'):
        if file.endswith('.py') and file != '__init__.py':
            bot.load_extension(f'cogs.{os.path.splitext(file)[0]}')
    bot.run(token)
