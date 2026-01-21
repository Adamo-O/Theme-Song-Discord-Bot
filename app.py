import asyncio
import discord
import os
# from curl_cffi import requests
import requests
import re
import datetime

from pymongo.mongo_client import MongoClient
from discord import FFmpegOpusAudio
from discord.ext import commands
from discord.utils import get as dget
# from youtube_dl import YoutubeDL
from yt_dlp import YoutubeDL

# from curl_cffi import requests as req_curl

# Imports for unblocking the blocking functions
import functools
import typing
import time

# from dotenv import load_dotenv
# load_dotenv()

# -------------------------------------------
# MongoDB connection
# -------------------------------------------

uri = os.environ.get('MONGODB_URI')
password = os.environ.get('MONGODB_PASSWORD')

client = MongoClient(uri, username='admin', password=password)

users = client.theme_songsDB.userData

# -------------------------------------------
# Constants
# -------------------------------------------
# Options for YoutubeDL
YDL_OPTIONS = {
	'format': 'bestaudio/best',
	'noplaylist': True,
	'skip_download': True,
	'quiet': True,
	'no_warnings': False,
	'extractor_args': {'youtube': {'js_runtimes': ['nodejs']}},
} 

# Default theme song duration variables
min_theme_song_duration = 1.0
max_theme_song_duration = 20.0
default_theme_song_duration = 10.0

# Cooldown constants
cooldown_voice_join = 60.0

# Default user used for confirming bot login via DM
default_log_user = 318887467707138051

# -------------------------------------------
# Bot setup
# -------------------------------------------

# Set intents (read members in guild)
intents = discord.Intents.default()
intents.members = True
intents.voice_states = True

commands_synced = False

# Setup bot attributes
bot = commands.Bot(
	command_prefix="$",
	description="Plays a unique theme song for each user in the server.",
	help_command=commands.DefaultHelpCommand(no_category="Theme song commands"),
	intents=intents
)

# ------------------------------------------
# Unblocking functions for scaling
# ------------------------------------------
# Python > 3.9
# def to_thread(func: typing.Callable) -> typing.Coroutine:
# 	@functools.wraps(func)
# 	async def wrapper(*args, **kwargs):
# 		return await asyncio.to_thread(func, *args, **kwargs)
# 	return wrapper

# Python < 3.9
def to_thread(func: typing.Callable) -> typing.Coroutine:
	@functools.wraps(func)
	async def wrapper(*args, **kwargs):
		wrapped = functools.partial(func, *args, **kwargs)
		return await bot.loop.run_in_executor(None, wrapped)
	return wrapper

# -------------------------------------------
# Helper methods
# -------------------------------------------
# Search YoutubeDL for query/url and returns (info, url)
def search(query: str):
	with YoutubeDL(YDL_OPTIONS) as ydl:
		try:
			# Check if query is a URL
			try:
				requests.get(query, timeout=5)
			except requests.exceptions.RequestException:
				# Not a URL, search for it
				info = ydl.extract_info(f"ytsearch:{query}", download=False)
				if 'entries' in info and info['entries']:
					info = info['entries'][0]
				else:
					print(f'No search results for: {query}')
					return (None, None)
			else:
				info = ydl.extract_info(query, download=False)
		except Exception as e:
			print(f'yt-dlp extraction error: {e}')
			return (None, None)

		# Get the best audio URL - prefer opus but accept any audio format
		url = info.get('url')
		if not url:
			for fmt in info.get('formats', []):
				if fmt.get('acodec') and fmt.get('acodec') != 'none':
					url = fmt.get('url')
					if fmt.get('acodec') == 'opus':
						break  # Prefer opus if available

		if url:
			print(f'Found audio URL for: {query}')
		else:
			print(f'Could not find audio URL for: {query}')

	return (info, url)

# Gets theme song of given member from database
def get_member_theme_song(member: discord.Member):
	member_obj = users.find_one({"_id": str(member.id)})
	if member_obj:
		print(f'Member {member.name} found in database.')
		return member_obj["theme_song"]

	print(f'Could not find member {member.name}.')

# Gets outro song of given member from database
def get_member_outro_song(member: discord.Member):
	member_obj = users.find_one({"_id": str(member.id)})
	if member_obj:
		print(f'Member {member.name} found in database.')
		return member_obj["outro_song"]

	print(f'Could not find member {member.name}.')

# Gets theme song duration of given member from database
# Returns the number of seconds to play the theme song for
def get_member_song_duration(member: discord.Member):

	# Find user by id that has a duration
	member_with_duration = users.find_one({"_id": str(member.id), "duration": { "$exists": True }})
	if member_with_duration:
		print(f'Song duration of member {member.name} found in database.')
		return float(member_with_duration["duration"])
	print('Could not find member song duration. Default is 10 seconds.')

	# User duration not found, set their duration to default
	users.update_one({"_id": str(member.id)}, { "$set": {"duration": str(default_theme_song_duration)} }, upsert=True)
	return default_theme_song_duration

def get_member_outro_duration(member: discord.Member):

	# Find user by id that has a duration
	member_with_duration = users.find_one({"_id": str(member.id), "outro_duration": { "$exists": True }})
	if member_with_duration:
		print(f'Song duration of member {member.name} found in database.')
		return float(member_with_duration["outro_duration"])
	print('Could not find member song duration. Default is 10 seconds.')

	# User duration not found, set their duration to default
	users.update_one({"_id": str(member.id)}, { "$set": {"outro_duration": str(default_theme_song_duration)} }, upsert=True)
	return default_theme_song_duration

# Adds or changes member's theme song in database
def set_member_theme_song(member: discord.Member, new_theme: str):
	users.update_one({"_id": str(member.id)}, { "$set": {"theme_song": str(new_theme)}}, upsert=True)
	print(f'Setting {member.name}\'s theme song to {new_theme}. Their ID is {str(member.id)}.')

# Adds or changes member's outro song in database
def set_outro_song(member: discord.Member, new_outro: str):
	users.update_one({"_id": str(member.id)}, {"$set": {"outro_song": str(new_outro)}}, upsert=True)
	print(f'Setting {member.name}\'s theme song to {new_outro}. Their ID is {str(member.id)}.')

# Adds or changes member's theme song duration in database
def set_member_song_duration(member: discord.Member, new_duration: float):
	if users.find_one({"_id": str(member.id)}):
		print(f'Setting {member.name}\'s song duration to {str(new_duration)}. Their ID is {str(member.id)}.')
		users.update_one({"_id": str(member.id)}, { "$set": {"duration": str(new_duration)} }, upsert=True)
		return True
	else:
		print(f'Member {member.name} not found in the database. Duration not added.')
		return False

# Adds or changes member's outro duration in database
def set_outro_duration(member: discord.Member, new_duration: float):
	if users.find_one({"_id": str(member.id)}):
		print(f'Setting {member.name}\'s song duration to {str(new_duration)}. Their ID is {str(member.id)}.')
		users.update_one({"_id": str(member.id)}, { "$set": {"outro_duration": str(new_duration)} }, upsert=True)
		return True
	else:
		print(f'Member {member.name} not found in the database. Duration not added.')
		return False

# Removes member from database
def delete_member_theme_song(member: discord.Member):
	users.delete_one({"_id": str(member.id)})

# Convert youtube short link to cleaned youtube link
def convert_yt_short(url: str):
	return url.replace('shorts/', 'watch?v=').replace('?feature=share', '')

# Plays audio of youtube video in member's voice channel via FFmpegOpusAudio
# @to_thread
def playAudio(voice: discord.VoiceClient, videoSource, duration: float):
# async def playAudio(voice: discord.VoiceClient, source: str, FFMPEG_OPTIONS: dict[str, str], duration: float):
	# Play audio from youtube video
	# videoSource = await FFmpegOpusAudio.from_probe(source, **FFMPEG_OPTIONS, method='fallback') # TODO: check if method fallback helps
	# videoSource = await FFmpegOpusAudio.from_probe(source, **FFMPEG_OPTIONS)
	# voice.is_playing()
	voice.stop() # TODO check if better
	voice.play(videoSource)

	# Play for constant amount of time (seconds)
	time.sleep(duration)

	voice.stop()

	# bot.loop.create_task(voice.disconnect())
	# bot.loop.run_in_executor(None, voice.disconnect)
	
	# # Disconnect from current voice channel
	# await voice.disconnect()

async def play(member: discord.Member, query: str, duration: float):
	if query is None:
		return

	try:
		# Search for audio on youtube
		video, source = search(query)
		if video is None or source is None:
			print(f'Failed to get audio for {member.name}: {query}')
			return

		voice: discord.VoiceClient = dget(bot.voice_clients, guild=member.guild)

		# Join the channel that the member is connected to
		channel = member.voice.channel
		if voice and voice.is_connected():
			await voice.move_to(channel)
		else:
			voice = await channel.connect()

		# Options for FFmpeg
		url_start_time = re.search(r"\?t=\d+", query)

		if (url_start_time is None):
			FFMPEG_OPTIONS = {
				'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
				'options': '-vn'
			}
		else:
			start_time = float(url_start_time.group()[3:])
			end_time = start_time + duration
			print(f'start time: {str(datetime.timedelta(seconds=start_time))}\nduration: {str(duration)}\nend time: {str(end_time)}')
			FFMPEG_OPTIONS = {
				'before_options': f'-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -ss {str(datetime.timedelta(seconds=start_time))} -accurate_seek',
				'options': f'-vn -to {str(datetime.timedelta(seconds=end_time))}'
			}

		# Play audio from youtube video
		videoSource = await FFmpegOpusAudio.from_probe(source, **FFMPEG_OPTIONS, method='fallback')

		await bot.loop.run_in_executor(None, playAudio, voice, videoSource, duration)

		await voice.disconnect()

	except Exception as e:
		print(f'Error playing audio for {member.name}: {e}')
		# Ensure we disconnect if connected
		voice = dget(bot.voice_clients, guild=member.guild)
		if voice and voice.is_connected():
			try:
				await voice.disconnect()
			except Exception:
				pass

# Direct messaging for logging
# @to_thread
async def send_message_to_user(message: str, user_id: int=default_log_user):
	user = bot.get_user(user_id)
	print(user)
	if user:
		await user.send(message)
	return

async def change_theme_user(interaction: discord.Interaction, user: typing.Union[discord.User, discord.Member], song: str, theme_song_duration: float=default_theme_song_duration):
	print(f'change_theme triggered. Changing {user.name}\'s theme song to {song} with duration {str(theme_song_duration)}')
	# If song link is a youtube short, convert to correct youtube link
	if 'shorts' in song and 'http' in song:
		song = convert_yt_short(song)

	set_member_theme_song(user, song)
	if float(theme_song_duration) < min_theme_song_duration or float(theme_song_duration) > max_theme_song_duration:
		await interaction.response.send_message(f'💢 Song duration must be between {str(min_theme_song_duration)} and {str(max_theme_song_duration)}.', ephemeral=True)
	else:
		# If video duration is shorter than theme song duration, set it to video duration
		video, source = search(song)
		url_start_time = re.search(r"\?t=\d+", song)
		if (url_start_time is None):
			start_time = 0.0
		else:
			start_time = float(url_start_time.group()[3:])

		video_duration = video['duration']
		if theme_song_duration > float(video_duration):
			theme_song_duration = float(video_duration)
		elif start_time + theme_song_duration > float(video_duration):
			theme_song_duration = float(video_duration) - start_time
		
		if set_member_song_duration(user, theme_song_duration):
			username = "Your" if interaction.user.id == user.id else f'{user.display_name}\'s'
			await interaction.response.send_message(f'✅ {username} theme song is now {song}.\n⏱ It will play for {str(theme_song_duration)} seconds.', ephemeral=True)
		else:
			await interaction.response.send_message('❌ Duration not set. Cannot set a duration without a theme song.', ephemeral=True)

async def change_outro_user(interaction: discord.Interaction, user: typing.Union[discord.User, discord.Member], song: str, outro_duration: float=default_theme_song_duration):
	print(f'change outro theme triggered. Changing {user.name}\'s outro to {song} with duration {str(outro_duration)}')
	# If song link is a youtube short, convert to correct youtube link
	if 'shorts' in song and 'http' in song:
		song = convert_yt_short(song)

	set_outro_song(user, song)
	if float(outro_duration) < min_theme_song_duration or float(outro_duration) > max_theme_song_duration:
		await interaction.response.send_message(f'💢 Outro duration must be between {str(min_theme_song_duration)} and {str(max_theme_song_duration)}.', ephemeral=True)
	else:
		# If video duration is shorter than theme song duration, set it to video duration
		video, source = search(song)
		url_start_time = re.search(r"\?t=\d+", song)
		if (url_start_time is None):
			start_time = 0.0
		else:
			start_time = float(url_start_time.group()[3:])

		video_duration = video['duration']
		if outro_duration > float(video_duration):
			outro_duration = float(video_duration)
		elif start_time + outro_duration > float(video_duration):
			outro_duration = float(video_duration) - start_time
		
		if set_outro_duration(user, outro_duration):
			username = "Your" if interaction.user.id == user.id else f'{user.display_name}\'s'
			await interaction.response.send_message(f'✅ {username} outro is now {song}.\n⏱ It will play for {str(outro_duration)} seconds.', ephemeral=True)
		else:
			await interaction.response.send_message('❌ Duration not set. Cannot set a duration without an outro.', ephemeral=True)

# -------------------------------------------
# Events
# -------------------------------------------
# Runs when bot is ready
@bot.event
async def on_ready():
	print(f'Logged in as {bot.user}')
	await bot.change_presence(activity = discord.Activity(type=discord.ActivityType.listening, name=f'{len(bot.guilds)} servers'))
	await send_message_to_user(f'Logged in as {bot.user}')

cooldown_voice_join_v2 = commands.CooldownMapping.from_cooldown(1, 60.0, commands.BucketType.guild)

# def get_ratelimit(member: discord.Member):
# 	bucket = cooldown_voice_join_v2
# 	print('cooldown bucket: ', bucket)
# 	return bucket.update_rate_limit()

# last_executed = time.time()
# def start_event_cooldown():
# 	if last_executed + cooldown_voice_join < time.time():
# 		last_executed = time.time()
# 		return True
# 	return False

# Runs when a voice channel updates
@bot.event
# @commands.Cog.listener()
# @commands.cooldown(1, 60.0, commands.BucketType.guild)
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
	# Don't do anything if a bot joins
	if member.bot:
		return

	# Runs if member is here now that wasn't before (i.e. member joined)
	if not before.channel and after.channel:
		# ratelimit = get_ratelimit(member)
		# print('ratelimit: ', ratelimit)
		# if ratelimit:
		# 	return

		print(f'{str(member.name)} has joined voice channel {member.voice.channel.name} in server: {member.guild.name}')
		url = get_member_theme_song(member)
		if url is not None:
			await play(member, url, get_member_song_duration(member))

# -------------------------------------------
# Commands
# -------------------------------------------
@bot.tree.command(
	name="sync",
	description="Sync bot commands (Server owner only)"
)
@discord.app_commands.checks.cooldown(1, 3600, key=lambda i: (i.guild_id, i.user.id))
async def sync(interaction: discord.Interaction):
	if interaction.user.id == default_log_user:
		synced_commands = await bot.tree.sync()
		await send_message_to_user(f'Synced commands: {synced_commands}')
	else:
		await interaction.response.send_message("You must be the server owner to use this command.", ephemeral=True)

async def user_autocomplete(interaction: discord.Interaction, current: str):
	usernames = interaction.guild.members
	return [discord.app_commands.Choice(name=username.name, value=username.name) for username in usernames if current.lower() in username.name.lower()]

# Prints author's theme song
# If author inputted another user's name, print that user's theme song instead
@bot.tree.command(
	name="print",
	description="Print the user's theme song and its duration, as well as the outro and its duration.",
)
@discord.app_commands.checks.cooldown(1, 60, key=lambda i: (i.guild_id, i.user.id))
@discord.app_commands.autocomplete(user=user_autocomplete)
async def print_theme(interaction: discord.Interaction, user: str):
	if user:
		member = interaction.guild.get_member_named(user)
		if member is None:
			await interaction.response.send_message(f'Could not find user {user}.', ephemeral=True)
		else:
			print(f'print_theme printing theme song of other user {member.name}')
			theme_song = get_member_theme_song(member)
			theme_song_duration = get_member_song_duration(member)
			outro = get_member_outro_song(member)
			outro_duration = get_member_outro_duration(member)
			if theme_song and outro:
				await interaction.response.send_message(f'🎵✨ {member.name}\'s theme song is {theme_song}\n⏱ It will play for {str(theme_song_duration)} seconds.\n\n🎵👋 {member.name}\'s outro song is {outro}\n⏱ It will play for {str(outro_duration)} seconds.', ephemeral=True)
			elif theme_song:
				await interaction.response.send_message(f'🎵✨ {member.name}\'s theme song is {theme_song}\n⏱ It will play for {str(theme_song_duration)} seconds.', ephemeral=True)
			elif outro:
				await interaction.response.send_message(f'🎵👋 {member.name}\'s outro song is {outro}\n⏱ It will play for {str(outro_duration)} seconds.', ephemeral=True)
	else:
		print(f'print_theme triggered with user: {interaction.user.name}')
		theme_song = get_member_theme_song(interaction.user)
		theme_song_duration = get_member_song_duration(interaction.user)
		outro = get_member_outro_song(interaction.user)
		outro_duration = get_member_outro_duration(interaction.user)
		if theme_song and outro:
			await interaction.response.send_message(f'🎵✨ {interaction.user}\'s theme song is {theme_song}\n⏱ It will play for {str(theme_song_duration)} seconds.\n\n🎵👋 {member.name}\'s outro song is {outro}\n⏱ It will play for {str(outro_duration)} seconds.', ephemeral=True)
		elif theme_song:
			await interaction.response.send_message(f'🎵✨ {interaction.user}\'s theme song is {theme_song}\n⏱ It will play for {str(theme_song_duration)} seconds.', ephemeral=True)
		elif outro:
			await interaction.response.send_message(f'🎵👋 {interaction.user}\'s outro song is {outro}\n⏱ It will play for {str(outro_duration)} seconds.', ephemeral=True)

# Change author's theme song to inputted song
@bot.tree.command(
	name="set",
	description="Change user's theme song to url or search query",
)
@discord.app_commands.checks.cooldown(1, 60, key=lambda i: (i.guild_id, i.user.id))
async def change_theme(interaction: discord.Interaction, song: str, theme_song_duration: float=default_theme_song_duration):
	await change_theme_user(interaction, interaction.user, song, theme_song_duration)

# Change other user's theme song to inputted song if user has administrative permissions
@bot.tree.command(
	name="set-other",
	description="Change *other* user's theme song to url or search query. Be careful with this one!",
)
@discord.app_commands.checks.cooldown(1, 60, key=lambda i: (i.guild_id, i.user.id))
@discord.app_commands.guild_only()
@discord.app_commands.autocomplete(user=user_autocomplete)
@discord.app_commands.default_permissions()
async def change_theme_other(interaction: discord.Interaction, user: str, song: str, theme_song_duration: float=default_theme_song_duration):
	member = interaction.guild.get_member_named(user)
	if member is None:
		await interaction.response.send_message(f'Could not find user {user}.', ephemeral=True)
	else:
		await change_theme_user(interaction, member, song, theme_song_duration)

@bot.tree.command(
	name="set-outro",
	description="Change user's outro song to url or search query."
)
@discord.app_commands.checks.cooldown(1, 60, key=lambda i: (i.guild_id, i.user.id))
async def change_outro(interaction: discord.Interaction, song: str, outro_duration: float=default_theme_song_duration):
	await change_outro_user(interaction, interaction.user, song, outro_duration)

@bot.tree.command(
	name="set-outro-other",
	description="Change *other* user's outro song to url or search query. Be careful with this one!"
)
@discord.app_commands.checks.cooldown(1, 60, key=lambda i: (i.guild_id, i.user.id))
@discord.app_commands.guild_only()
@discord.app_commands.autocomplete(user=user_autocomplete)
@discord.app_commands.default_permissions()
async def change_outro_other(interaction: discord.Interaction, user: str, song: str, outro_duration: float=default_theme_song_duration):
	member = interaction.guild.get_member_named(user)
	if member is None:
		await interaction.response.send_message(f'Could not find user {user}.', ephemeral=True)
	else:
		await change_outro_user(interaction, member, song, outro_duration)

@bot.tree.command(
	name="set-duration",
	description="Change user's theme song duration",
)
@discord.app_commands.checks.cooldown(1, 60, key=lambda i: (i.guild_id, i.user.id))
async def change_song_duration(interaction: discord.Interaction, theme_song_duration: float):
	print(f'change_song_duration triggered. Changing {interaction.user.name}\'s song duration to {str(theme_song_duration)}')
	if float(theme_song_duration) < min_theme_song_duration or float(theme_song_duration) > max_theme_song_duration:
		await interaction.response.send_message(f'💢 Your song duration must be between {str(min_theme_song_duration)} and {str(max_theme_song_duration)}.', ephemeral=True)
	else:
		if set_member_song_duration(interaction.user, theme_song_duration):
			await interaction.response.send_message(f'✅ Your theme song duration is now {str(theme_song_duration)} seconds.', ephemeral=True)
		else:
			await interaction.response.send_message('❌ Duration not set. Cannot set a duration without a theme song.', ephemeral=True)

@bot.tree.command(
	name="set-outro-duration",
	description="Change user's outro duration",
)
@discord.app_commands.checks.cooldown(1, 60, key=lambda i: (i.guild_id, i.user.id))
async def change_outro_duration(interaction: discord.Interaction, outro_duration: float):
	print(f'change_outro_duration triggered. Changing {interaction.user.name}\'s song duration to {str(outro_duration)}')
	if float(outro_duration) < min_theme_song_duration or float(outro_duration) > max_theme_song_duration:
		await interaction.response.send_message(f'💢 Your outro duration must be between {str(min_theme_song_duration)} and {str(max_theme_song_duration)}.', ephemeral=True)
	else:
		if set_outro_duration(interaction.user, outro_duration):
			await interaction.response.send_message(f'✅ Your outro duration is now {str(outro_duration)} seconds.', ephemeral=True)
		else:
			await interaction.response.send_message('❌ Duration not set. Cannot set a duration without an outro.', ephemeral=True)

@bot.tree.command(
	name="outro",
	description="Trigger outro song and disconnect user."
)
@discord.app_commands.checks.cooldown(1, 60, key=lambda i: (i.guild_id, i.user.id))
async def outro(interaction: discord.Interaction):
	print(f'Outro for {interaction.user.name}')
	url = get_member_outro_song(interaction.user)
	if url is not None:
		await interaction.response.send_message(f'👋 See ya!\n🎵 Playing {str(url)}', ephemeral=True)
		await play(interaction.user, url, get_member_outro_duration(interaction.user))
		await interaction.user.move_to(None)
	else:
		await interaction.response.send_message('❌ Outro song not set. Please use `/set-outro` before running this.', ephemeral=True)

# Delete author's theme song
@bot.tree.command(
	name="delete",
	description="Delete user's theme song",
)
@discord.app_commands.checks.cooldown(1, 60, key=lambda i: (i.guild_id, i.user.id))
async def delete_theme(interaction: discord.Interaction):
	print(f'delete_theme triggered with user {interaction.user.name}')
	await interaction.response.send_message('❎ Your theme song has been deleted.', ephemeral=True)
	delete_member_theme_song(interaction.user)

# -------------------------------------------
# Error Handling
# -------------------------------------------
# Handles all command errors
@bot.tree.error
async def on_command_error(interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
	# If command on cooldown, respond to interaction with cooldown error information
	if isinstance(error, discord.app_commands.CommandOnCooldown):
		await interaction.response.send_message(str(error), ephemeral=True)

# Run bot using secret token
if __name__ == '__main__':
	bot.run(os.environ.get('DISCORD_TOKEN'), reconnect=True)