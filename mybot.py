#!/usr/bin/env python
# coding: utf8

from telegram.ext import *
import json
import logging
from functions import *
from datetime import datetime, time, timedelta, date
import telegram
from threading import Timer
from peewee import SqliteDatabase, IntegerField, Model, CharField
import holidays

logging.basicConfig(
		format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
		level=logging.INFO)

log = logging.getLogger('traditionsbot')
db = SqliteDatabase(None)

class Subscribers(Model):
	chat_id = IntegerField(unique=True)
	first_name = CharField()

	class Meta:
		database = db

class TraditionsBot:
	umfrage_starter = None
	umfrage_timestamp = {}
	umfrage_approvers = []
	umfrage_name = None

	kuchen_starter = None
	kuchen_time = None
	job_queue = None

	def __init__(self, config):
		self.config = config

	def broadcast(self, message, bot, tastatur=None, author=None):
		today = date.today()
		holidays_nrw = holidays.DE(years=[2019, 2020, 2021], prov='NW')

		if today not in holidays_nrw:
			for sub in Subscribers.select():
				if sub.chat_id == author:
					continue
				try:
					bot.send_message(sub.chat_id, message, reply_markup=tastatur)
				except telegram.TelegramError as ex:
					log.warning(ex)

	def start(self, bot, update):
		u = update.message.from_user
		log.info(f'Registering new user: {u.first_name}, {u.id}')
		subscriber, new = Subscribers.get_or_create(chat_id=u.id, first_name=u.first_name)
		if new:
			update.message.reply_text(f'Guten Tag, {u.first_name}! Ich werde dich ab jetzt täglich mit der #traditionsinfo versorgen.')
		else:
			update.message.reply_text('Du bist schon angemeldet.')

	def stop(self, bot, update):
		try:
			sub = Subscribers.get(chat_id=update.message.from_user.id)
			sub.delete_instance()
			update.message.reply_text('Du erhältst nun keine Traditionsinfo mehr. Auf Wiedersehen!')
		except Subscribers.DoesNotExist:
			update.message.reply_text('Du bist nicht angemeldet.')

	def start_umfrage(self, bot, update):
		if self.umfrage_starter is not None:
			update.message.reply_text('Es läuft bereits eine Umfrage.')
			return
		rm = telegram.ReplyKeyboardMarkup(('ja', 'nein'), one_time_keyboard=True)
		update.message.reply_text('Mensa 12h15?', reply_markup=rm)
		#self.umfrage_starter = update.message.from_user

	def umfrage_handler(self, bot, update, groups):
		if self.umfrage_starter is not None:
			update.message.reply_text('Es läuft bereits eine Umfrage.')
			return
		group = groups[0]
		if group not in ['ja','nein']:
			update.message.reply_text('Keine gültige Eingabe')
			return
		self.umfrage_name = group
		umfrage(self, bot, update, group)


	def stop_umfrage(self, bot, update):
		
		log.info('Poll failed')

		self.broadcast(f"{self.umfrage_name}Deine Anfrage war nicht erfolgreich.", bot, tastatur=telegram.ReplyKeyboardRemove())

		self.umfrage_starter = None
		self.umfrage_approvers = []


	def umfrage(self, bot, update, group):
		if self.umfrage_starter is not None:
			update.message.reply_text('Es läuft bereits eine Umfrage.')
			return
		log.info('Starting poll')
		self.umfrage_starter = update.message.from_user
		self.umfrage_timestamp[groups] = datetime.now()
		update.message.reply_text(f'Die {group}umfrage wurde gestartet!')
		rm = telegram.ReplyKeyboardMarkup((('Ja', 'Nein'),), one_time_keyboard=True)
		self.broadcast(f'{update.message.from_user.first_name} fragt: {groups}?', bot, tastatur=rm, author=update.message.from_user.id)

		if self.job_queue is not None:
			self.job_queue.run_once(self.stop_umfrage, self.config['poll_duration'])

	def status(self, bot, update):
		if update.message.from_user.id != 10726796:
			return
		subs = Subscribers.select()
		st = 'not' if self.umfrage_timestamp == None else ''
		update.message.reply_text(f'I am running! Currently {len(subs)} subscribers. Poll is {st} running.')


	def send_broadcast(self, bot, update, args):
		if update.message.from_user.id != 10726796:
			return
		self.broadcast(" ".join(args), bot)

	def umfrage_jahandler(self, bot, update):
		if self.umfrage_starter is None or update.message.from_user == self.umfrage_starter or update.message.from_user in self.umfrage_approvers:
			return

		self.umfrage_approvers.append(update.message.from_user)
		approvers_limit = {'Heißgetränk':3, 'Galerie':1, 'Eis':3, 'Karte aufladen':1}


		if len(self.umfrage_approvers) >= approvers_limit[self.umfrage_name]:
			timestr = (time.now() + timedelta(minutes=5)).strftime("%H:%M")
			abfahrt = {'Treffen um 12h15 im Mensafoyer.'}
			log.info('Poll successful')
			approvers = self.umfrage_approvers
			participants = ', '.join([a.first_name for a in ha]) + f' und {self.umfrage_starter.first_name}'
			self.broadcast(f'{self.umfrage_name}! {emoji[self.umfrage_name]}\nMit {participants}. {abfahrt[self.umfrage_name]}', bot, tastatur=telegram.ReplyKeyboardRemove())
			self.umfrage_starter = None
			self.umfrage_approvers = []
def main():
	db.init("data.sqlite")
	Subscribers.create_table(safe=True)

	config = {}
	try:
		with open('config.json') as f:
			config = json.load(f)
	except (FileNotFoundError, json.decoder.JSONDecodeError):
		pass

	bot = TraditionsBot(config)

	updater = Updater(config['apikey'])
	j = updater.job_queue
	bot.job_queue = j
	j.run_daily(bot.notify, time=time(hour=12, minute=00), days=tuple(range(5)))

	updater.dispatcher.add_handler(CommandHandler('start', bot.start))
	updater.dispatcher.add_handler(CommandHandler('stop', bot.stop))
	updater.dispatcher.add_handler(CommandHandler('umfrage', bot.start_umfrage))
	updater.dispatcher.add_handler(CommandHandler('status', bot.status))
	updater.dispatcher.add_handler(CommandHandler('broadcast', bot.send_broadcast, pass_args=True))
	updater.dispatcher.add_handler(RegexHandler('(.{3,}[^1-9])', bot.umfrage_handler, pass_groups=True))
	updater.dispatcher.add_handler(RegexHandler('Ja', bot._jahandler))
	updater.dispatcher.add_handler(RegexHandler('([0-9][0-9]:[0-9][0-9])', bot.kuchen_timehandler, pass_groups=True))
	updater.start_polling()
	updater.idle()

if __name__ == '__main__':
	try:
		main()
	except (KeyboardInterrupt, SystemExit):
		log.info('Aborted')
