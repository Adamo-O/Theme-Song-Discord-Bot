import asyncio
import discord
import os
import requests
import re
import datetime

from pymongo import MongoClient
from discord.ext import commands
from discord.utils import get as dget
from youtube_dl import YoutubeDL

# from dotenv import load_dotenv
# load_dotenv()
# -------------------------------------------
# MongoDB and Heroku connections
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
	'format': 'bestaudio', 
	'noplaylist': 'True', 
	'cookiefile': 'cookies.txt'
} 

# Default theme song duration variables
min_theme_song_duration = 1.0
max_theme_song_duration = 20.0
default_theme_song_duration = 10.0

# Default user used for confirming bot login via DM
default_log_user = 318887467707138051

# -------------------------------------------
# Bot setup
# -------------------------------------------

# Set intents (read members in guild)
intents = discord.Intents.default()
intents.members = True

commands_synced = False

# Setup bot attributes
bot = commands.Bot(
	command_prefix="$",
	description="Plays a unique theme song for each user in the server.",
	help_command=commands.DefaultHelpCommand(no_category="Theme song commands"),
	intents=intents
)

# -------------------------------------------
# Helper methods
# -------------------------------------------
# Search YoutubeDL for query/url and returns (info, url)
def search(query: str):
	with YoutubeDL(YDL_OPTIONS) as ydl:
		try: requests.get(query)
		except: info = ydl.extract_info(f"ytsearch:{query}", download=False)['entries'][0]
		else: info = ydl.extract_info(query, download=False)
	return (info, info['formats'][0]['url'])

# Gets theme song of given member from database
def get_member_theme_song(member: discord.Member):
	member_obj = users.find_one({"_id": str(member.id)})
	if member_obj:
		print(f'Member {member.name} found in database.')
		return member_obj["theme_song"]

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

# Adds or changes member's theme song in database
def set_member_theme_song(member: discord.Member, new_theme: str):
	users.update_one({"_id": str(member.id)}, { "$set": {"theme_song": str(new_theme)}}, upsert=True)
	print(f'Setting {member.name}\'s theme song to {new_theme}. Their ID is {str(member.id)}.')

# Adds or changes member's theme song duration in database
def set_member_song_duration(member: discord.Member, new_duration: float):
	if users.find_one({"_id": str(member.id)}):
		print(f'Setting {member.name}\'s song duration to {str(new_duration)}. Their ID is {str(member.id)}.')
		users.update_one({"_id": str(member.id)}, { "$set": {"duration": str(new_duration)} }, upsert=True)
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
async def play(member: discord.Member, query: str):
	if query is None:
		return
		
	# Seach for audio on youtube
	video, source = search(query)
	voice = dget(bot.voice_clients, guild=member.guild)

	duration = get_member_song_duration(member)

	# Join the channel that the member is connected to
	channel = member.voice.channel
	if voice and voice.is_connected():
		await voice.move_to(channel)
	else:
		voice = await channel.connect()

	# Options for FFmpeg
	url_start_time = re.search("\?t=\d+", query)

	if (url_start_time is None):
		FFMPEG_OPTIONS = {
			'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
			'options': '-vn'
		}
	else:
		start_time = url_start_time.group()[3:]
		end_time = str(float(start_time) + float(duration))
		print(f'start time: {start_time}\nduration: {duration}\nend time: {end_time}')
		FFMPEG_OPTIONS = {
			'before_options': f'-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -ss {str(datetime.timedelta(seconds=float(start_time)))}',
			'options': f'-vn -to {str(datetime.timedelta(seconds=float(end_time)))} -c copy -copyts'
		}

	# Play audio from youtube video
	videoSource = await discord.FFmpegOpusAudio.from_probe(source, **FFMPEG_OPTIONS)
	voice.is_playing()
	voice.play(videoSource)

	# Play for constant amount of time (seconds)
	await asyncio.sleep(duration)

	voice.stop()
	
	# Disconnect from current voice channel
	await voice.disconnect()

# Direct messaging for logging
async def send_message_to_user(message: str, user_id: int=default_log_user):
	user = bot.get_user(user_id)
	print(user)
	if user:
		await user.send(message)
	return

# -------------------------------------------
# Events
# -------------------------------------------
# Runs when bot is ready
@bot.event
async def on_ready():
	print(f'Logged in as {bot.user}')
	await bot.change_presence(activity = discord.Activity(type=discord.ActivityType.listening, name=f'{len(bot.guilds)} servers'))
	await send_message_to_user(f'Logged in as {bot.user}')

# Runs when a voice channel updates
@bot.event
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
	# Don't do anything if a bot joins
	if member.bot:
		return

	# Runs if member is here now that wasn't before (i.e. member joined)
	if not before.channel and after.channel:
		print(f'{str(member.name)} has joined voice channel {member.voice.channel.name} in server: {member.guild.name}')
		url = get_member_theme_song(member)
		if url is not None:
			await play(member, url)

# -------------------------------------------
# Commands
# -------------------------------------------
@bot.tree.command(
	name="sync",
	description="Sync bot commands (Server owner only)"
)
async def sync(interaction: discord.Interaction):
	if interaction.user.id == default_log_user:
		synced_commands = await bot.tree.sync()
		await send_message_to_user(f'Synced commands: {synced_commands}')
	else:
		await interaction.response.send_message("You must be the server owner to use this command.", ephemeral=True)

# Prints author's theme song
# If author inputted another user's name, print that user's theme song instead
@bot.tree.command(
	name="print",
	description="Print the user's theme song and its duration when played.",
)
async def print_theme(interaction: discord.Interaction, user: str = ''):
	if user:
		member = interaction.guild.get_member_named(user)
		if member is None:
			await interaction.response.send_message(f'Could not find user {user}.', ephemeral=True)
		else:
			print(f'print_theme printing theme song of other user {member.name}')
			theme_song = get_member_theme_song(member)
			theme_song_duration = get_member_song_duration(member)
			await interaction.response.send_message(f'🎵 {member.name}\'s theme song is {theme_song}\n⏱ It will play for {str(theme_song_duration)} seconds.', ephemeral=True)
	else:
		print(f'print_theme triggered with user: {interaction.user.name}')
		theme_song = get_member_theme_song(interaction.user)
		theme_song_duration = get_member_song_duration(interaction.user)
		await interaction.response.send_message(f'🎵 Your theme song is {theme_song}.\n⏱ It will play for {str(theme_song_duration)} seconds.', ephemeral=True)

@print_theme.autocomplete('user')
async def user_autocomplete(interaction: discord.Interaction, current: str):
	usernames = bot.users
	return [discord.app_commands.Choice(name=usernames, value=usernames) for username in usernames if current.lower() in username.name.lower()]

# Change author's theme song to inputted song
@bot.tree.command(
	name="set",
	description="Change user's theme song to url or search query",
)
async def change_theme(interaction: discord.Interaction, song: str, theme_song_duration: float=default_theme_song_duration):
	print(f'change_theme triggered. Changing {interaction.user.name}\'s theme song to {song} with duration {str(theme_song_duration)}')
	# If song link is a youtube short, convert to correct youtube link
	if 'shorts' in song and 'http' in song:
		song = convert_yt_short(song)

	set_member_theme_song(interaction.user, song)
	if float(theme_song_duration) < min_theme_song_duration or float(theme_song_duration) > max_theme_song_duration:
		await interaction.response.send_message(f'💢 Your song duration must be between {str(min_theme_song_duration)} and {str(max_theme_song_duration)}.', ephemeral=True)
	else:
		# If video duration is shorter than theme song duration, set it to video duration
		video, source = search(song)
		url_start_time = re.search("\?t=\d+", song)
		if (url_start_time is None):
			start_time = 0.0
		else:
			start_time = url_start_time.group()[3:]

		if float(theme_song_duration) > float(video['duration']):
			theme_song_duration = float(video['duration'])
		elif float(video['duration']) - float(start_time) > theme_song_duration:
			theme_song_duration = float(video['duration']) - float(start_time)
		
		if set_member_song_duration(interaction.user, theme_song_duration):
			await interaction.response.send_message(f'✅ Your theme song is now {song}.\n⏱ It will play for {str(theme_song_duration)} seconds.', ephemeral=True)
		else:
			await interaction.response.send_message('❌ Duration not set. Cannot set a duration without a theme song.', ephemeral=True)

@bot.tree.command(
	name="set-duration",
	description="Change user's theme song duration",
)
async def change_song_duration(interaction: discord.Interaction, theme_song_duration: float):
	print(f'change_song_duration triggered. Changing {interaction.user.name}\'s song duration to {str(theme_song_duration)}')
	if float(theme_song_duration) < min_theme_song_duration or float(theme_song_duration) > max_theme_song_duration:
		await interaction.response.send_message(f'💢 Your song duration must be between {str(min_theme_song_duration)} and {str(max_theme_song_duration)}.', ephemeral=True)
	else:
		if set_member_song_duration(interaction.user, theme_song_duration):
			await interaction.response.send_message(f'✅ Your theme song duration is now {str(theme_song_duration)} seconds.', ephemeral=True)
		else:
			await interaction.response.send_message('❌ Duration not set. Cannot set a duration without a theme song.', ephemeral=True)

# Delete author's theme song
@bot.tree.command(
	name="delete",
	description="Delete user's theme song",
)
async def delete_theme(interaction: discord.Interaction):
	print(f'delete_theme triggered with user {interaction.user.name}')
	await interaction.response.send_message('❎ Your theme song has been deleted.', ephemeral=True)
	delete_member_theme_song(interaction.user)

# Run bot using secret token
if __name__ == '__main__':
	bot.run(os.environ.get('DISCORD_TOKEN'))