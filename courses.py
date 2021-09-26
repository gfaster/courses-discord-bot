import csv
from dotenv import dotenv_values
from databases import Database
import discord
from discord.ext import commands
import asyncio
from cache import AsyncLRU
import json



config = dotenv_values('.env')
database = Database("sqlite:///{0}".format(config['DATABASE']))



command_prefix = '$coursebot '
bot = commands.Bot(command_prefix=command_prefix)
list_channel = None
server = None
re_emoji = None


@bot.event
async def on_ready():
	global list_channel
	global server
	global re_emoji

	await setup_db()

	list_channel = bot.get_channel(int(config['LIST_CHANNEL']))
	assert list_channel is not None
	# list_channel = bot.get_channel(891458306399412255)
	server = list_channel.guild
	assert server is not None

	re_emoji = bot.get_emoji(int(config['REACT_EMOJI_ID']))
	assert re_emoji is not None

	print(f'Logged in as {bot.user} (ID: {bot.user.id})')
	# print('beginning course setup...')
	# await load_courses()

async def setup_db():
	queries = [
		'''CREATE TABLE IF NOT EXISTS Courses 
		(id INTEGER PRIMARY KEY NOT NULL,
			course_number VARCHAR(16),
			message_id INTEGER, 
			channel_id INTEGER,
			role_id INTEGER,
			name VARCHAR(1024))''',
		'CREATE UNIQUE INDEX IF NOT EXISTS idx_course_number on Courses(course_number)',
		'CREATE UNIQUE INDEX IF NOT EXISTS idx_message_id on Courses(message_id)',
		'CREATE UNIQUE INDEX IF NOT EXISTS idx_channel_id on Courses(channel_id)',
		'CREATE UNIQUE INDEX IF NOT EXISTS idx_role_id on Courses(role_id)',
	]

	for query in queries:
		await database.execute(query=query)

def channel_title_san(string):
	return string.replace(' ', '').lower()

@AsyncLRU(maxsize=1024)
async def get_info_by_id(d_id, id_type):
	assert id_type in ('message', 'channel', 'role')
	column = id_type + '_id'

	if column == 'message_id':
		query = "SELECT * FROM Courses WHERE message_id=:id"
	elif column == 'channel_id':
		query = "SELECT * FROM Courses WHERE channel_id=:id"
	elif column == 'role_id':
		query = "SELECT * FROM Courses WHERE role_id=:id"
	else:
		raise Exception('This should never be raised.')
	
	values = {'id':d_id}
	db_values = await database.fetch_one(query=query, values=values)

	if db_values is None:
		return None

	out = {
		'course_number': db_values[1],
		'message_id': db_values[2],
		'channel_id': db_values[3],
		'role_id': db_values[4],
		'name': db_values[5]
	}
	return out

async def get_info_by_number(course_number):
	query = "SELECT * FROM Courses WHERE course_number=:course_number"
	
	values = {'course_number':course_number}
	db_values = await database.fetch_one(query=query, values=values)

	if db_values is None:
		return None

	out = {
		'course_number': db_values[1],
		'message_id': db_values[2],
		'channel_id': db_values[3],
		'role_id': db_values[4],
		'name': db_values[5]
	}
	return out


@bot.event
async def on_raw_reaction_add(reaction):
	if reaction.user_id == int(config['APP_ID']):
		return

	row_info = await get_info_by_id(reaction.message_id, 'message')
	if row_info is None:
		return

	user = await server.fetch_member(reaction.user_id)
	role = server.get_role(row_info['role_id'])
	await user.add_roles(role)

@bot.event
async def on_raw_reaction_remove(reaction):
	row_info = await get_info_by_id(reaction.message_id, 'message')
	if row_info is None:
		return

	user = await server.fetch_member(reaction.user_id)
	role = server.get_role(row_info['role_id'])
	await user.remove_roles(role)

async def add_db_class(course_number, message_id, channel_id, role_id, course_name):
	query = '''INSERT INTO Courses(course_number, message_id, channel_id, role_id, name)
				VALUES(:course_number, :message_id, :channel_id, :role_id, :course_name)'''
	values = {'course_number': course_number, 'message_id': message_id,
			'channel_id': channel_id, 'role_id': role_id, 'course_name': course_name}
	await database.execute(query=query, values=values)

async def setup_channel(course_number, course_name):
	short_num = channel_title_san(course_number)

	existing = await get_info_by_number(course_number.upper())
	if existing is not None:
		raise ValueError(f'Entry for {course_number} already exists')
	

	msg = await list_channel.send(content=f'{course_number.upper()} - {course_name}')
	channel = await server.create_text_channel(short_num)

	category=bot.get_channel(int(config['CLASSES_CATEGORY_ID']))
	assert category is not None
	await channel.move(category=category, end=True)
	role = await server.create_role(name=short_num)

	await msg.add_reaction(re_emoji)

	overwrite = discord.PermissionOverwrite()
	overwrite.read_messages = False
	await channel.set_permissions(server.default_role, overwrite=overwrite)

	overwrite = discord.PermissionOverwrite()
	overwrite.read_messages = True
	await channel.set_permissions(role, overwrite=overwrite)

	mod_role = server.get_role(int(config['MOD_ROLE_ID']))
	await channel.set_permissions(mod_role, overwrite=overwrite)

	await channel.edit(topic=course_name)

	await add_db_class(course_number.upper(), msg.id, channel.id, role.id, course_name)

async def load_courses():
	with open('courselist.json', 'r') as f:
		courses = json.load(f)['courses']
		i = 0
		for course in courses:
			print(f'loading {i}/{len(courses)} ({course["num"]})    ', end='\r')
			try:
				await setup_channel(course['num'], course['name'])
			except:
				print(f'\nfailed to set up {course["num"]}')

			await asyncio.sleep(1.5)
			i += 1
		print('done!')
	
	
@bot.command()
async def delete_all_yespleaseactually(ctx):
	if ctx.author.id != int(config['ADMIN_ID']):
		await ctx.send('Nice try.')
		return

	query = "SELECT * FROM Courses"
	courselist = await database.fetch_all(query=query)

	for row in courselist:
		try:
			msg = await list_channel.fetch_message(row[2])
			await msg.delete()
			await server.get_channel(row[3]).delete(reason='PURGE')
			await server.get_role(row[4]).delete(reason='PURGE')
		except Exception as e:
			print(f'could not delete {row[1]}')
			raise e

	query = "DELETE FROM Courses"
	await database.execute(query=query)



# @bot.command()
async def debug_test(ctx):
	await setup_channel('asdf 1234', 'Test Course')
	await ctx.send('OK!')

bot.run(config['TOKEN'])