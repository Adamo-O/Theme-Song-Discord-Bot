import asyncio
import discord
import os
import requests
import re

from pymongo import MongoClient
from discord.ext import commands
from discord.utils import get as dget
from youtube_dl import YoutubeDL

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

# Default user to log in DMs
default_log_user = '318887467707138051'

# -------------------------------------------
# Bot setup
# -------------------------------------------

# Set intents (read members in guild)
intents = discord.Intents.default()
intents.members = True

# Setup bot attributes
bot = commands.Bot(
	command_prefix="$",
	description="Plays a unique theme song for each user in the server.",
	help_command=commands.DefaultHelpCommand(no_category="Theme song commands"),
	activity = discord.Activity(type=discord.ActivityType.listening, name="$help and theme songs"),
	intents=intents
)

# -------------------------------------------
# Helper methods
# -------------------------------------------
# Search YoutubeDL for query/url and returns (info, url)
def search(query):
	with YoutubeDL(YDL_OPTIONS) as ydl:
		try: requests.get(query)
		except: info = ydl.extract_info(f"ytsearch:{query}", download=False)['entries'][0]
		else: info = ydl.extract_info(query, download=False)
	return (info, info['formats'][0]['url'])

# Gets theme song of given member from database
def get_member_theme_song(member):
	member_obj = users.find_one({"_id": str(member.id)})
	if member_obj:
		print(f'Member {member.name} found in database.')
		return member_obj["theme_song"]

	print(f'Could not find member {member.name}.')
	return

# Gets theme song duration of given member from database
# Returns the number of seconds to play the theme song for
def get_member_song_duration(member):

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
def set_member_theme_song(member, new_theme):
	users.update_one({"_id": str(member.id)}, { "$set": {"theme_song": str(new_theme)}}, upsert=True)
	print(f'Setting {member.name}\'s theme song to {new_theme}. Their ID is {str(member.id)}.')

# Adds or changes member's theme song duration in database
def set_member_song_duration(member, new_duration):
	if users.find_one({"_id": str(member.id)}):
		print(f'Setting {member.name}\'s song duration to {str(new_duration)}. Their ID is {str(member.id)}.')
		users.update_one({"_id": str(member.id)}, { "$set": {"duration": str(new_duration)} }, upsert=True)
		return True
	else:
		print(f'Member {member.name} not found in the database. Duration not added.')
		return False

# Removes member from database
def delete_member_theme_song(member):
	users.delete_one({"_id": str(member.id)})

# Plays audio of youtube video in member's voice channel via FFmpegOpusAudio
async def play(member, query):
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
			'before_options': f'-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -ss {str(start_time)}',
			'options': '-vn'
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

async def send_message_to_user(message=None, user: discord.User=bot.get_user(default_log_user)):
	await user.send(message)

# -------------------------------------------
# Events
# -------------------------------------------
# Runs when bot is ready
@bot.event
async def on_ready():
	await send_message_to_user('Logged in as {}'.format(bot.user))
	print('Logged in as {}'.format(bot.user))

# Runs when a voice channel updates
@bot.event
async def on_voice_state_update(member, before, after):
	# Don't do anything if a bot joins
	if member.bot:
		return
	# Runs if member is here now that wasn't before (i.e. member joined)
	if not before.channel and after.channel:
		print('{} has joined voice channel {} in server: {}'.format(str(member.name), member.voice.channel.name, member.guild.name))
		url = get_member_theme_song(member)
		await play(member, url)

# -------------------------------------------
# Commands
# -------------------------------------------
# Prints author's theme song
# If author inputted another user's name, print that user's theme song instead
@bot.command(
	help="Print the user's theme song and its duration when played.",
	brief="Print user's theme song.",
	name="print",
	aliases=["p"]
)
async def print_theme(ctx, user = None):
	if user:
		member = ctx.guild.get_member_named(user)
		if member is None:
			await ctx.send('Could not find user {}.'.format(user))
		else:
			print('print_theme printing theme song of other user {}'.format(member.name))
			theme_song = get_member_theme_song(member)
			theme_song_duration = get_member_song_duration(member)
			await ctx.send('🎵 {}\'s theme song is {}\n⏱ It will play for {} seconds.'.format(member.name, theme_song, str(theme_song_duration)))
	else:
		print('print_theme triggered with user: {}'.format(ctx.author.name))
		theme_song = get_member_theme_song(ctx.author)
		theme_song_duration = get_member_song_duration(ctx.author)
		await ctx.send('🎵 Your theme song is {}.\n⏱ It will play for {} seconds.'.format(theme_song, str(theme_song_duration)))

# Change author's theme song to inputted song
@bot.command(
	help="Change user's theme song to url or search query",
	brief="Change user's theme song",
	name="set",
	aliases=['set-theme', 'change-theme', 'change', 's', 'c']
)
async def change_theme(ctx, song, theme_song_duration=default_theme_song_duration):
	print('change_theme triggered. Changing {}\'s theme song to {} with duration {}'.format(ctx.author.name, song, str(theme_song_duration)))
	set_member_theme_song(ctx.author, song)
	if float(theme_song_duration) < min_theme_song_duration or float(theme_song_duration) > max_theme_song_duration:
		await ctx.send('💢 Your song duration must be between {} and {}.'.format(str(min_theme_song_duration), str(max_theme_song_duration)))
	else:
		# If video duration is shorter than theme song duration, set it to video duration
		video, source = search(song)
		if float(theme_song_duration) > float(video['duration']):
			theme_song_duration = float(video['duration'])
		if set_member_song_duration(ctx.author, theme_song_duration):
			await ctx.send('✅ Your theme song is now {}.\n⏱ It will play for {} seconds.'.format(song, str(theme_song_duration)))
		else:
			await ctx.send('❌ Duration not set. Cannot set a duration without a theme song.')

@bot.command(
	help="Change user's theme song duration",
	brief="Change song duration",
	name="set-duration",
	aliases=['set-length', 'change-duration', 'sd', 'st']
)
async def change_song_duration(ctx, theme_song_duration):
	print('change_song_duration triggered. Changing {}\'s song duration to {}'.format(ctx.author.name, str(theme_song_duration)))
	if float(theme_song_duration) < min_theme_song_duration or float(theme_song_duration) > max_theme_song_duration:
		await ctx.send('💢 Your song duration must be between {} and {}.'.format(str(min_theme_song_duration), str(max_theme_song_duration)))
	else:
		if set_member_song_duration(ctx.author, theme_song_duration):
			await ctx.send('✅ Your theme song duration is now {} seconds.'.format(str(theme_song_duration)))
		else:
			await ctx.send('❌ Duration not set. Cannot set a duration without a theme song.')

# Delete author's theme song
@bot.command(
	help="Delete user's theme song",
	brief="Delete user's theme song",
	name="delete",
	aliases=['del', 'delete-theme']
)
async def delete_theme(ctx):
	print('delete_theme triggered with user {}'.format(ctx.author.name))
	await ctx.send('❎ Your theme song has been deleted.'.format(ctx.author.name))
	delete_member_theme_song(ctx.author)

# Run bot using secret token
if __name__ == '__main__':
	bot.run(os.environ['DISCORD_TOKEN'])