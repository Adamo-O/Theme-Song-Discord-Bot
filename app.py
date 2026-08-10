import asyncio
import discord
import os
# from curl_cffi import requests
import requests
import re
import datetime
import random

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
import shutil
import subprocess
import tempfile

# from dotenv import load_dotenv
# load_dotenv()

# -------------------------------------------
# MongoDB connection
# -------------------------------------------

uri = os.environ.get('MONGODB_URI')
password = os.environ.get('MONGODB_PASSWORD')

client = MongoClient(uri, username='admin', password=password)

# -------------------------------------------
# YouTube cookies (optional fallback for authentication)
# -------------------------------------------
# Write cookies from environment variable to file if present
youtube_cookies = os.environ.get('YOUTUBE_COOKIES')
if youtube_cookies:
	with open('cookies.txt', 'w') as f:
		f.write(youtube_cookies)
	print('YouTube cookies loaded from environment variable', flush=True)
else:
	print('No YouTube cookies set (using POT provider for authentication)', flush=True)

# Check for required binaries
node_path = shutil.which('node')
if node_path:
	result = subprocess.run(['node', '--version'], capture_output=True, text=True)
	print(f'Node.js found: {node_path} ({result.stdout.strip()})', flush=True)
else:
	print('WARNING: Node.js not found - yt-dlp may fail to extract YouTube audio', flush=True)

ffmpeg_path = shutil.which('ffmpeg')
if ffmpeg_path:
	result = subprocess.run(['ffmpeg', '-version'], capture_output=True, text=True)
	version_line = result.stdout.split('\n')[0] if result.stdout else 'unknown'
	print(f'FFmpeg found: {ffmpeg_path} ({version_line})', flush=True)
else:
	print('WARNING: FFmpeg not found - audio playback will fail', flush=True)

users = client.theme_songsDB.userData

# -------------------------------------------
# Constants
# -------------------------------------------
# POT provider URL (for bypassing YouTube bot detection)
pot_provider_url = os.environ.get('POT_PROVIDER_URL', 'http://127.0.0.1:4416')
print(f'POT Provider URL: {pot_provider_url}', flush=True)

# Options for YoutubeDL
YDL_OPTIONS = {
	'format': 'bestaudio[acodec=opus]/bestaudio[acodec=aac]/bestaudio/best',  # Prefer Opus to avoid re-encoding
	'noplaylist': True,
	'skip_download': True,
	'quiet': True,
	'no_warnings': False,
	'extractor_args': {
		'youtube': {},
		'youtubepot-bgutilhttp': {'base_url': [pot_provider_url]},  # POT provider endpoint
	},
	'remote_components': ['ejs:github'],  # JS challenge solver for n-parameter deobfuscation
	'js_runtimes': {'node': {}},  # Node.js runtime for executing challenge solver scripts
}

# Add cookies if available (needed alongside POT for audio format access)
if os.path.exists('cookies.txt'):
	YDL_OPTIONS['cookiefile'] = 'cookies.txt' 

# Default theme song duration variables
min_theme_song_duration = 1.0
max_theme_song_duration = 20.0
default_theme_song_duration = 10.0

# Discord caps a select menu at 25 options
max_select_options = 25

# Cooldown constants
cooldown_voice_join = 60.0

# Audio cache
CACHE_DIR = '/tmp/theme_cache'
MAX_CACHE_FILES = 50
os.makedirs(CACHE_DIR, exist_ok=True)

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
	intents=intents,
	chunk_guilds_at_startup=False  # Don't fetch all members on startup to avoid rate limits
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
# Find a guild member by name, falling back to API fetch if not in cache
async def find_member(guild: discord.Guild, name: str):
	member = guild.get_member_named(name)
	if member:
		return member
	# Not in cache — search via API
	async for m in guild.fetch_members(limit=None):
		if m.name == name or (m.nick and m.nick == name):
			return m
	return None

# Search YoutubeDL for query/url and returns (info, url, http_headers)
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
					print(f'No search results for: {query}', flush=True)
					return (None, None, None)
			else:
				info = ydl.extract_info(query, download=False)
		except Exception as e:
			print(f'yt-dlp extraction error: {e}', flush=True)
			return (None, None, None)

		# Get the best audio URL - prefer opus but accept any audio format
		url = info.get('url')
		http_headers = info.get('http_headers', {})
		if not url:
			for fmt in info.get('formats', []):
				if fmt.get('acodec') and fmt.get('acodec') != 'none':
					url = fmt.get('url')
					http_headers = fmt.get('http_headers', http_headers)
					if fmt.get('acodec') == 'opus':
						break  # Prefer opus if available

		if url:
			print(f'Found audio URL for: {query}', flush=True)
		else:
			print(f'Could not find audio URL for: {query}', flush=True)

	return (info, url, http_headers)

# Extract YouTube video ID from a URL
def get_video_id(query: str):
	match = re.search(r'youtu\.be/([a-zA-Z0-9_-]{11})', query)
	if match:
		return match.group(1)
	match = re.search(r'[?&]v=([a-zA-Z0-9_-]{11})', query)
	if match:
		return match.group(1)
	match = re.search(r'embed/([a-zA-Z0-9_-]{11})', query)
	if match:
		return match.group(1)
	return None

# Evict oldest files from cache when over the limit
def _evict_cache():
	files = []
	for f in os.listdir(CACHE_DIR):
		path = os.path.join(CACHE_DIR, f)
		if os.path.isfile(path):
			files.append((os.path.getmtime(path), path))
	if len(files) > MAX_CACHE_FILES:
		files.sort()
		for _, path in files[:len(files) - MAX_CACHE_FILES]:
			os.unlink(path)
			print(f'Evicted from cache: {path}', flush=True)

# Download audio from YouTube, using cache when available
# Returns (info_dict, filepath)
def download_audio(query: str):
	video_id = get_video_id(query)

	# Check cache
	if video_id:
		for f in os.listdir(CACHE_DIR):
			if f.startswith(video_id + '.'):
				filepath = os.path.join(CACHE_DIR, f)
				os.utime(filepath)  # Touch for LRU
				print(f'Cache hit: {filepath}', flush=True)
				return ({}, filepath)

	# Cache miss — download
	tmp_dir = tempfile.mkdtemp(prefix='theme_')

	# Resolve whether the query is a URL or a search term once, up front.
	is_url = True
	try:
		requests.get(query, timeout=5)
	except requests.exceptions.RequestException:
		is_url = False
	target = query if is_url else f"ytsearch:{query}"

	# Player clients to try, in order. The default (POT-backed web) client works for
	# most videos, but some videos only expose PO-token-gated audio formats that
	# return "HTTP Error 403: Forbidden" on download. Falling back to other clients,
	# which expose non-gated formats, recovers those videos even if the POT provider
	# can't mint a working token.
	client_fallbacks = [None, ['tv'], ['ios'], ['android'], ['web_safari']]

	for clients in client_fallbacks:
		# Build extractor_args per attempt, preserving the POT provider config.
		extractor_args = {k: dict(v) for k, v in YDL_OPTIONS.get('extractor_args', {}).items()}
		if clients is not None:
			extractor_args.setdefault('youtube', {})['player_client'] = clients

		download_opts = {
			**YDL_OPTIONS,
			'format': 'bestaudio/best',
			'skip_download': False,
			'outtmpl': os.path.join(tmp_dir, '%(id)s.%(ext)s'),
			'extractor_args': extractor_args,
		}
		label = 'default' if clients is None else ','.join(clients)

		with YoutubeDL(download_opts) as ydl:
			try:
				info = ydl.extract_info(target, download=True)
				if not is_url and 'entries' in info:
					if info['entries']:
						info = info['entries'][0]
					else:
						print(f'No search results for: {query}', flush=True)
						shutil.rmtree(tmp_dir, ignore_errors=True)
						return (None, None)

				filepath = ydl.prepare_filename(info)
				if not os.path.exists(filepath):
					print(f'Downloaded file not found (client={label}): {filepath}', flush=True)
					continue

				# Move to cache
				if video_id:
					ext = os.path.splitext(filepath)[1]
					cache_path = os.path.join(CACHE_DIR, f'{video_id}{ext}')
					shutil.move(filepath, cache_path)
					shutil.rmtree(tmp_dir, ignore_errors=True)
					_evict_cache()
					print(f'Cached: {cache_path} (client={label})', flush=True)
					return (info, cache_path)

				print(f'Downloaded audio to: {filepath} (client={label})', flush=True)
				return (info, filepath)
			except Exception as e:
				print(f'yt-dlp download error (client={label}): {e}', flush=True)
				continue

	print(f'All download attempts failed for: {query}', flush=True)
	shutil.rmtree(tmp_dir, ignore_errors=True)
	return (None, None)

# Gets theme song of given member from database
def get_member_theme_song(member: discord.Member):
	member_obj = users.find_one({"_id": str(member.id)})
	if member_obj and "theme_song" in member_obj:
		print(f'Member {member.name} found in database.')
		return member_obj["theme_song"]

	print(f'Could not find member {member.name}.')

# Gets outro song of given member from database
def get_member_outro_song(member: discord.Member):
	member_obj = users.find_one({"_id": str(member.id)})
	if member_obj and "outro_song" in member_obj:
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

# Reads the ?t= start offset out of a YouTube link. Returns 0.0 when there isn't one.
def get_url_start_time(query: str):
	url_start_time = re.search(r"\?t=\d+", query)
	if url_start_time is None:
		return 0.0
	return float(url_start_time.group()[3:])

# Clamps a requested duration so playback never runs past the end of the video.
# Returns the requested duration unchanged when the video length is unknown,
# which is the case for cycle entries added before video_duration was stored.
def clamp_duration_to_video(duration: float, video_duration, start_time: float=0.0):
	if video_duration is None:
		return float(duration)
	try:
		available = float(video_duration) - float(start_time)
	except (TypeError, ValueError):
		return float(duration)
	if available <= 0:
		return float(duration)
	return min(float(duration), available)

# DB CHANGE NEEDED: add theme_song_cycle array field to user documents.
def get_member_song_cycle(member: discord.Member):
	member_obj = users.find_one({"_id": str(member.id), "theme_song_cycle": { "$exists": True }})
	if member_obj:
		print(f'Song cycle of member {member.name} found in database.')
		return member_obj.get("theme_song_cycle", [])
	print(f'Could not find member song cycle for {member.name}.')
	return []

def add_to_cycle(member: discord.Member, url: str, duration: float, title: str, video_duration=None, start_time: float=0.0):
	song_obj = {"url": str(url), "duration": float(duration), "title": str(title), "start_time": float(start_time)}
	# Stored so a later duration change can be clamped without re-fetching the video
	if video_duration is not None:
		song_obj["video_duration"] = float(video_duration)
	users.update_one({"_id": str(member.id)}, { "$push": {"theme_song_cycle": song_obj} }, upsert=True)
	return song_obj

def remove_from_cycle(member: discord.Member, index: int):
	song_cycle = get_member_song_cycle(member)
	if not song_cycle:
		return None
	if index < 0 or index >= len(song_cycle):
		return None
	removed_song = song_cycle.pop(index)
	users.update_one({"_id": str(member.id)}, { "$set": {"theme_song_cycle": song_cycle} }, upsert=True)
	return removed_song

# Sets every cycle song's duration for the given member, clamped per song to the
# video length. Returns number of songs updated.
def set_cycle_durations(member: discord.Member, new_duration: float):
	song_cycle = get_member_song_cycle(member)
	if not song_cycle:
		return 0
	for song in song_cycle:
		song["duration"] = clamp_duration_to_video(new_duration, song.get("video_duration"), song.get("start_time", 0.0))
	users.update_one({"_id": str(member.id)}, { "$set": {"theme_song_cycle": song_cycle} }, upsert=True)
	print(f'Set duration of {len(song_cycle)} cycle songs for {member.name} to {str(new_duration)}.')
	return len(song_cycle)

# Sets one cycle song's duration by index. Returns the updated song, or None if the
# index is out of range. The stored duration is clamped to the video length.
def set_cycle_song_duration(member: discord.Member, index: int, new_duration: float):
	song_cycle = get_member_song_cycle(member)
	if not song_cycle or index < 0 or index >= len(song_cycle):
		return None
	song = song_cycle[index]
	song["duration"] = clamp_duration_to_video(new_duration, song.get("video_duration"), song.get("start_time", 0.0))
	users.update_one({"_id": str(member.id)}, { "$set": {"theme_song_cycle": song_cycle} }, upsert=True)
	print(f'Set duration of cycle song {str(index + 1)} for {member.name} to {str(song["duration"])}.')
	return song

def clear_cycle(member: discord.Member):
	users.update_one({"_id": str(member.id)}, { "$unset": {"theme_song_cycle": ""} }, upsert=True)

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

	tmp_file = None
	try:
		# Download audio from YouTube to a temp file
		video, tmp_file = download_audio(query)
		if video is None or tmp_file is None:
			print(f'Failed to download audio for {member.name}: {query}', flush=True)
			return

		voice: discord.VoiceClient = dget(bot.voice_clients, guild=member.guild)

		# Join the channel that the member is connected to
		channel = member.voice.channel
		if voice and voice.is_connected():
			await voice.move_to(channel)
		else:
			voice = await channel.connect()

		# Options for FFmpeg (no HTTP options needed for local files)
		url_start_time = re.search(r"\?t=\d+", query)

		if (url_start_time is None):
			FFMPEG_OPTIONS = {
				'options': '-vn'
			}
		else:
			start_time = float(url_start_time.group()[3:])
			end_time = start_time + duration
			print(f'start time: {str(datetime.timedelta(seconds=start_time))}\nduration: {str(duration)}\nend time: {str(end_time)}')
			FFMPEG_OPTIONS = {
				'before_options': f'-ss {str(datetime.timedelta(seconds=start_time))} -accurate_seek',
				'options': f'-vn -to {str(datetime.timedelta(seconds=end_time))}'
			}

		# Play audio from downloaded file
		videoSource = FFmpegOpusAudio(tmp_file, **FFMPEG_OPTIONS)

		await bot.loop.run_in_executor(None, playAudio, voice, videoSource, duration)

		await voice.disconnect()

	except Exception as e:
		print(f'Error playing audio for {member.name}: {e}', flush=True)
		# Ensure we disconnect if connected
		voice = dget(bot.voice_clients, guild=member.guild)
		if voice and voice.is_connected():
			try:
				await voice.disconnect()
			except Exception:
				pass
	finally:
		# Clean up temp files that aren't in the cache
		if tmp_file and os.path.exists(tmp_file) and not tmp_file.startswith(CACHE_DIR):
			try:
				shutil.rmtree(os.path.dirname(tmp_file), ignore_errors=True)
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

	# Defer the response immediately since yt-dlp extraction can take a while
	await interaction.response.defer(ephemeral=True)

	# If song link is a youtube short, convert to correct youtube link
	if 'shorts' in song and 'http' in song:
		song = convert_yt_short(song)

	if float(theme_song_duration) < min_theme_song_duration or float(theme_song_duration) > max_theme_song_duration:
		await interaction.followup.send(f'💢 Song duration must be between {str(min_theme_song_duration)} and {str(max_theme_song_duration)}.', ephemeral=True)
		return

	# Search for the video first to validate it exists
	video, source, _ = search(song)
	if video is None or source is None:
		await interaction.followup.send(f'❌ Could not find video: {song}', ephemeral=True)
		return

	# If video duration is shorter than theme song duration, set it to video duration
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

	# Only save to database after validation passes
	set_member_theme_song(user, song)
	if set_member_song_duration(user, theme_song_duration):
		username = "Your" if interaction.user.id == user.id else f'{user.display_name}\'s'
		await interaction.followup.send(f'✅ {username} theme song is now {song}.\n⏱ It will play for {str(theme_song_duration)} seconds.', ephemeral=True)
	else:
		await interaction.followup.send('❌ Duration not set. Cannot set a duration without a theme song.', ephemeral=True)

async def change_outro_user(interaction: discord.Interaction, user: typing.Union[discord.User, discord.Member], song: str, outro_duration: float=default_theme_song_duration):
	print(f'change outro theme triggered. Changing {user.name}\'s outro to {song} with duration {str(outro_duration)}')

	# Defer the response immediately since yt-dlp extraction can take a while
	await interaction.response.defer(ephemeral=True)

	# If song link is a youtube short, convert to correct youtube link
	if 'shorts' in song and 'http' in song:
		song = convert_yt_short(song)

	if float(outro_duration) < min_theme_song_duration or float(outro_duration) > max_theme_song_duration:
		await interaction.followup.send(f'💢 Outro duration must be between {str(min_theme_song_duration)} and {str(max_theme_song_duration)}.', ephemeral=True)
		return

	# Search for the video first to validate it exists
	video, source, _ = search(song)
	if video is None or source is None:
		await interaction.followup.send(f'❌ Could not find video: {song}', ephemeral=True)
		return

	# If video duration is shorter than outro duration, set it to video duration
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

	# Only save to database after validation passes
	set_outro_song(user, song)
	if set_outro_duration(user, outro_duration):
		username = "Your" if interaction.user.id == user.id else f'{user.display_name}\'s'
		await interaction.followup.send(f'✅ {username} outro is now {song}.\n⏱ It will play for {str(outro_duration)} seconds.', ephemeral=True)
	else:
		await interaction.followup.send('❌ Duration not set. Cannot set a duration without an outro.', ephemeral=True)

# -------------------------------------------
# Events
# -------------------------------------------
# Runs when bot is ready
@bot.event
async def on_ready():
	print(f'Logged in as {bot.user}')
	await bot.change_presence(activity = discord.Activity(type=discord.ActivityType.listening, name=f'Back online! | /help'))
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

		print(f'{str(member.name)} has joined voice channel {member.voice.channel.name} in server: {member.guild.name}', flush=True)
		song_cycle = get_member_song_cycle(member)
		if song_cycle:
			selected = random.choice(song_cycle)
			cycle_url = selected.get("url")
			cycle_duration = selected.get("duration", default_theme_song_duration)
			if cycle_url:
				await play(member, cycle_url, float(cycle_duration))
				return

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
		await interaction.response.defer(ephemeral=True)
		# Sync globally and copy to current guild for immediate availability
		synced_commands = await bot.tree.sync()
		bot.tree.copy_global_to(guild=interaction.guild)
		guild_commands = await bot.tree.sync(guild=interaction.guild)
		await interaction.followup.send(f'Synced {len(synced_commands)} global + {len(guild_commands)} guild commands.', ephemeral=True)
		await send_message_to_user(f'Synced commands: {synced_commands}')
	else:
		await interaction.response.send_message("You must be the server owner to use this command.", ephemeral=True)

async def user_autocomplete(interaction: discord.Interaction, current: str):
	# Fetch members matching the query instead of relying on cache
	if current:
		members = []
		async for member in interaction.guild.fetch_members(limit=25):
			if current.lower() in member.name.lower():
				members.append(member)
	else:
		members = []
		async for member in interaction.guild.fetch_members(limit=25):
			members.append(member)
	return [discord.app_commands.Choice(name=m.name, value=m.name) for m in members[:25]]

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
		member = await find_member(interaction.guild, user)
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
	member = await find_member(interaction.guild, user)
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
	member = await find_member(interaction.guild, user)
	if member is None:
		await interaction.response.send_message(f'Could not find user {user}.', ephemeral=True)
	else:
		await change_outro_user(interaction, member, song, outro_duration)

@bot.tree.command(
	name="add-to-cycle",
	description="Add a song to user's theme song cycle."
)
@discord.app_commands.checks.cooldown(1, 60, key=lambda i: (i.guild_id, i.user.id))
async def add_to_cycle_command(interaction: discord.Interaction, song: str, duration: float=default_theme_song_duration):
	print(f'add_to_cycle triggered. Adding {interaction.user.name}\'s cycle song to {song} with duration {str(duration)}')

	# Defer the response immediately since yt-dlp extraction can take a while
	await interaction.response.defer(ephemeral=True)

	# If song link is a youtube short, convert to correct youtube link
	if 'shorts' in song and 'http' in song:
		song = convert_yt_short(song)

	if float(duration) < min_theme_song_duration or float(duration) > max_theme_song_duration:
		await interaction.followup.send(f'💢 Song duration must be between {str(min_theme_song_duration)} and {str(max_theme_song_duration)}.', ephemeral=True)
		return

	# Search for the video first to validate it exists
	video, source, _ = search(song)
	if video is None or source is None:
		await interaction.followup.send(f'❌ Could not find video: {song}', ephemeral=True)
		return

	# If video duration is shorter than theme song duration, set it to video duration.
	# video_duration is missing/None for livestreams, in which case no clamp is applied.
	start_time = get_url_start_time(song)
	video_duration = video.get('duration')
	duration = clamp_duration_to_video(duration, video_duration, start_time)

	title = video.get('title', 'Unknown title')
	add_to_cycle(interaction.user, song, duration, title, video_duration, start_time)
	await interaction.followup.send(f'✅ Added to your cycle:\n🎵 {title}\n🔗 {song}\n⏱ It will play for {str(duration)} seconds.', ephemeral=True)

@bot.tree.command(
	name="cycle",
	description="Print the user's theme song cycle."
)
@discord.app_commands.checks.cooldown(1, 60, key=lambda i: (i.guild_id, i.user.id))
async def print_cycle(interaction: discord.Interaction):
	print(f'cycle triggered with user: {interaction.user.name}')
	song_cycle = get_member_song_cycle(interaction.user)
	if not song_cycle:
		await interaction.response.send_message('❌ Your cycle is empty. Use `/add-to-cycle` to add songs.', ephemeral=True)
		return

	lines = []
	for index, song in enumerate(song_cycle, start=1):
		title = song.get("title", "Unknown title")
		url = song.get("url", "Unknown URL")
		duration = song.get("duration", default_theme_song_duration)
		lines.append(f'{index}. {title}\n🔗 {url}\n⏱ It will play for {str(duration)} seconds.')

	await interaction.response.send_message(f'🎵 Your theme song cycle:\n\n' + '\n\n'.join(lines), ephemeral=True)

@bot.tree.command(
	name="remove-from-cycle",
	description="Remove a song from user's theme song cycle."
)
@discord.app_commands.checks.cooldown(1, 60, key=lambda i: (i.guild_id, i.user.id))
async def remove_from_cycle_command(interaction: discord.Interaction, index: int):
	print(f'remove_from_cycle triggered with user: {interaction.user.name}')
	song_cycle = get_member_song_cycle(interaction.user)
	if not song_cycle:
		await interaction.response.send_message('❌ Your cycle is empty.', ephemeral=True)
		return
	if index < 1 or index > len(song_cycle):
		await interaction.response.send_message(f'❌ Invalid index. Use `/cycle` to view your list (1-{len(song_cycle)}).', ephemeral=True)
		return

	removed_song = remove_from_cycle(interaction.user, index - 1)
	if removed_song:
		title = removed_song.get("title", "Unknown title")
		url = removed_song.get("url", "Unknown URL")
		duration = removed_song.get("duration", default_theme_song_duration)
		await interaction.response.send_message(f'✅ Removed from your cycle:\n🎵 {title}\n🔗 {url}\n⏱ It will play for {str(duration)} seconds.', ephemeral=True)
	else:
		await interaction.response.send_message('❌ Could not remove that index.', ephemeral=True)

@bot.tree.command(
	name="clear-cycle",
	description="Clear the user's theme song cycle."
)
@discord.app_commands.checks.cooldown(1, 60, key=lambda i: (i.guild_id, i.user.id))
async def clear_cycle_command(interaction: discord.Interaction):
	print(f'clear_cycle triggered with user: {interaction.user.name}')
	clear_cycle(interaction.user)
	await interaction.response.send_message('🗑️ Your cycle has been cleared.', ephemeral=True)

# Asks for the new duration once a cycle song has been picked
class CycleDurationModal(discord.ui.Modal, title='Set cycle song duration'):
	def __init__(self, member: discord.Member, index: int, song: dict):
		super().__init__()
		self.member = member
		self.index = index
		self.duration_input = discord.ui.TextInput(
			label='Duration in seconds',
			placeholder=f'Between {str(min_theme_song_duration)} and {str(max_theme_song_duration)}',
			default=str(song.get('duration', default_theme_song_duration)),
			required=True,
			max_length=6
		)
		self.add_item(self.duration_input)

	async def on_submit(self, interaction: discord.Interaction):
		raw_duration = self.duration_input.value.strip()
		try:
			new_duration = float(raw_duration)
		except ValueError:
			await interaction.response.send_message(f'💢 "{raw_duration}" is not a number.', ephemeral=True)
			return

		if new_duration < min_theme_song_duration or new_duration > max_theme_song_duration:
			await interaction.response.send_message(f'💢 Song duration must be between {str(min_theme_song_duration)} and {str(max_theme_song_duration)}.', ephemeral=True)
			return

		updated_song = set_cycle_song_duration(self.member, self.index, new_duration)
		if updated_song is None:
			await interaction.response.send_message('❌ That song is no longer in your cycle. Run `/set-cycle-duration` again.', ephemeral=True)
			return

		title = updated_song.get('title', 'Unknown title')
		applied_duration = updated_song.get('duration', new_duration)
		message = f'✅ Updated:\n🎵 {title}\n⏱ It will now play for {str(applied_duration)} seconds.'
		if applied_duration < new_duration:
			message += f'\n⚠️ Shortened from {str(new_duration)}s because the video is not long enough.'
		await interaction.response.send_message(message, ephemeral=True)

# Dropdown listing the member's cycle so they can pick which song to edit
class CycleSongSelect(discord.ui.Select):
	def __init__(self, member: discord.Member, song_cycle: list):
		self.member = member
		options = []
		for index, song in enumerate(song_cycle[:max_select_options]):
			title = str(song.get('title', 'Unknown title'))
			duration = song.get('duration', default_theme_song_duration)
			options.append(discord.SelectOption(
				label=f'{str(index + 1)}. {title}'[:100],
				description=f'Currently {str(duration)} seconds'[:100],
				value=str(index)
			))
		super().__init__(placeholder='Choose a song to change the duration of...', min_values=1, max_values=1, options=options)

	async def callback(self, interaction: discord.Interaction):
		index = int(self.values[0])
		# Re-read in case the cycle changed while the menu was open
		song_cycle = get_member_song_cycle(self.member)
		if index >= len(song_cycle):
			await interaction.response.send_message('❌ That song is no longer in your cycle. Run `/set-cycle-duration` again.', ephemeral=True)
			return
		await interaction.response.send_modal(CycleDurationModal(self.member, index, song_cycle[index]))

class CycleDurationView(discord.ui.View):
	def __init__(self, interaction: discord.Interaction, member: discord.Member, song_cycle: list):
		super().__init__(timeout=120)
		self.interaction = interaction
		self.member = member
		self.add_item(CycleSongSelect(member, song_cycle))

	async def interaction_check(self, interaction: discord.Interaction):
		if interaction.user.id != self.member.id:
			await interaction.response.send_message('❌ This menu is not yours.', ephemeral=True)
			return False
		return True

	async def on_timeout(self):
		for item in self.children:
			item.disabled = True
		try:
			await self.interaction.edit_original_response(view=self)
		except discord.HTTPException:
			pass

@bot.tree.command(
	name="set-cycle-duration",
	description="Change the duration of one song in the user's theme song cycle."
)
@discord.app_commands.checks.cooldown(1, 60, key=lambda i: (i.guild_id, i.user.id))
async def set_cycle_duration_command(interaction: discord.Interaction):
	print(f'set_cycle_duration triggered with user: {interaction.user.name}')
	song_cycle = get_member_song_cycle(interaction.user)
	if not song_cycle:
		await interaction.response.send_message('❌ Your cycle is empty. Use `/add-to-cycle` to add songs.', ephemeral=True)
		return

	prefix = ''
	if len(song_cycle) > max_select_options:
		prefix = f'⚠️ Showing the first {str(max_select_options)} of {str(len(song_cycle))} songs (Discord menu limit).\n'

	view = CycleDurationView(interaction, interaction.user, song_cycle)
	await interaction.response.send_message(f'{prefix}🔁 Pick a song to change its duration:', view=view, ephemeral=True)

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
		updated_cycle_songs = set_cycle_durations(interaction.user, theme_song_duration)
		if set_member_song_duration(interaction.user, theme_song_duration) or updated_cycle_songs:
			message = f'✅ Your theme song duration is now {str(theme_song_duration)} seconds.'
			if updated_cycle_songs:
				message += f'\n🔁 Also applied to all {str(updated_cycle_songs)} songs in your cycle.'
			await interaction.response.send_message(message, ephemeral=True)
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
