#!/usr/bin/env python3

"""
This file is part of AirAlert. It is subject to 
the license terms in the LICENSE.txt file found in the top-level directory 
of this distribution and at: 
   https://confluence.slac.stanford.edu/display/ppareg/LICENSE.html. 
No part of AirAlert, including this file, may be 
copied, modified, propagated, or distributed except according to the terms 
contained in the LICENSE.txt file.
"""

# TODO: Clean this script up. It's quite a mess

"""
{
	"email": {
		"login_required": true,
		"use_tls": true,
		"sender_email": "your.email.here@example.com",
		"email_addr": "jeremy.lorelli.1337@gmail.com",
		"email_pw": "1234",
		"smtp_addr": "smtp.gmail.com",
		"smtp_port": 587,
		"addresses": [
			"jeremy.lorelli.1337@gmail.com"
		]
	},
	"report_threshold": 1,
	"update_period": 1,
	"status_email_hour": 13,
	"cooldown_time": 15,
	"normal_email_text": "The air quality at SLAC has returned to safe or moderately safe levels\n",
	"unhealthy_email_text": "An unhealthy AQI has been detected in the immediate vicinity of SLAC.\nSensitive groups should stay indoors and use masks or respirators.\nOthers should limit their outdoor activities and consider using PPE\n\n",
	"status_email_text": "Good morning, here is your daily air quality summary:\n\n",
	"sensors": [
		"61605",
		"38085",
		"60059"
	]
}
"""

import json, http, os, sys, email, smtplib, requests, argparse, time, datetime, asyncio, threading

argparse = argparse.ArgumentParser(description='Simple alert system for poor air quality')
argparse.add_argument('--config', type=str, dest='config', default='/etc/air-alert.json', help='Path to the air quality alert config')
argparse.add_argument('--state-file', type=str, dest='statefile', default='/srv/air-alert-statefile.json', help='File where the app state is saved')
argparse.add_argument('--daemonize', action='store_true', dest='DAEMON', help='Run the script as a daemon')
args = argparse.parse_args()

# Log print
def log(_str):
	print(time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time())) + ": " + _str)

# Load the config
cfg = None
with open(args.config, "r") as fp:
	try:
		cfg = json.load(fp)
	except:
		print("Configuration failed to load: ")

def get_or_set_default(section, name, default):
	try:
		if section[name] is None:
			raise Exception()
		return section[name]
	except:
		raise Exception()

# Try to set the sensors from the config. Default if it's not possible
sensors = get_or_set_default(cfg, 'sensors', ["61605", "61217", "38085", "60059"])

# Try to set various params
if not cfg:
	cfg = dict()
	cfg['email'] = None
login_required = get_or_set_default(cfg['email'], 'login_required', False)
email_addr = get_or_set_default(cfg['email'], 'email_addr', "")
email_pw = get_or_set_default(cfg['email'], 'email_pw', "")
smtp_addr = get_or_set_default(cfg['email'], 'smtp_addr', "")
smtp_port = get_or_set_default(cfg['email'], 'smtp_port', 0)
addresses = get_or_set_default(cfg['email'], 'addresses', [])
use_tls = get_or_set_default(cfg['email'], 'use_tls', True)
report_threshold = get_or_set_default(cfg, 'report_threshold', 150)
sender_email = get_or_set_default(cfg['email'], 'sender_email', '')
cooldown_time = get_or_set_default(cfg, 'cooldown_time', 15)
update_period = get_or_set_default(cfg, 'update_period', 60)
status_email_hour = get_or_set_default(cfg, 'status_email_hour', 6) # The hour at which to send the email
normal_email_text = get_or_set_default(cfg, 'normal_email_text', 'Configuration Error')
unhealthy_email_text = get_or_set_default(cfg, 'unhealthy_email_text', 'Configuration Error')
status_email_text = get_or_set_default(cfg, 'status_email_text', 'Configuration Error')
air_qualities = get_or_set_default(cfg, 'qualities', {})
sensor_data = []

def get_aqi_string(aqi):
	if aqi <= 50:
		return air_qualities['good']
	elif aqi <= 100:
		return air_qualities['moderate']
	elif aqi <= 150:
		return air_qualities['unhealthy_s']
	elif aqi <= 200:
		return air_qualities['unhealthy']
	elif aqi <= 300:
		return air_qualities['unhealthy_v']
	else:
		return air_qualities['hazardous']

"""
GlobalState class which handles any and all global state.
It allows the state to be saved to a file and loaded lader, in case of a restart
"""
class GlobalState():
	def __init__(self, state_save_file: str):
		self.file = state_save_file
		self.data = dict()
		if os.path.exists(state_save_file):
			self.load()
		else:
			# Just write out an empty file 
			self.save()

	def set_value(self, key: str, val):
		self.data[key] = val
	
	def get_value(self, key: str, default=None):
		try:
			return self.data[key]
		except:
			return default
	
	def save(self):
		with open(self.file, "w") as fp:
			json.dump(self.data, fp)

	def load(self):
		with open(self.file, "r") as fp:
			self.data = json.load(fp)
			if not self.data:
				self.data = dict()

# Global state object
state = GlobalState(args.statefile)

class EmailProvider():
	def __init__(self):
		log("Connecting to SMTP server at {0}:{1}".format(smtp_addr, smtp_port))
		self.smtp_server = smtplib.SMTP(smtp_addr, int(smtp_port))
		self.smtp_server.ehlo() 
		if use_tls:
			self.smtp_server.starttls()
		if login_required:
			try: 
				self.smtp_server.login(email_addr, email_pw)
			except:
				log("Fatal error: Login failed")
				exit(1)
	
	def send_high_email(self, aqi):
		msg = email.message.EmailMessage()
		# Collect recipients
		msg['To'] = ", ".join(addresses)
		msg['From'] = sender_email
		msg['Subject'] = 'Air Quality Alert'

		content = unhealthy_email_text.replace('$LEVEL_STRING', get_aqi_string(aqi)).replace('$AQI', str(aqi))
		content += "A summary of the sensor data follows:\n\n"

		for sens in sensor_data:
			content += "Location: {0}\nLast sampled: {1}\nAQI: {2}\n\n".format(sens.label, sens.pretty_last_seen(), int(sens.calc_aqi()))

		msg.set_content(content)
		self.smtp_server.send_message(msg)

	def send_low_email(self, aqi):
		msg = email.message.EmailMessage()
		# Collect recipients
		msg['To'] = ", ".join(addresses)
		msg['From'] = sender_email
		msg['Subject'] = 'Air Quality Alert'

		content = normal_email_text.replace('$LEVEL_STRING', get_aqi_string(aqi)).replace('$AQI', str(aqi))
		content += "A summary of the sensor data follows:\n\n"

		for sens in sensor_data:
			content += "Location: {0}\nLast sampled: {1}\nAQI: {2}\n\n".format(sens.label, sens.pretty_last_seen(), int(sens.calc_aqi()))

		msg.set_content(content)
		self.smtp_server.send_message(msg)

	def send_status_email(self, aqi):
		msg = email.message.EmailMessage()
		# Collect recipients
		msg['To'] = ", ".join(addresses)
		msg['From'] = sender_email
		msg['Subject'] = 'Daily Air Quality Summary'

		content = status_email_text.replace('$LEVEL_STRING', get_aqi_string(aqi)).replace('$AQI', str(aqi))

		for sens in sensor_data:
			content += "Location: {0}\nLast sampled: {1}\nAQI: {2}\n\n".format(sens.label, sens.pretty_last_seen(), int(sens.calc_aqi()))

		msg.set_content(content)
		self.smtp_server.send_message(msg)

email_provider = EmailProvider()
email_mutex = threading.Lock()

"""
Simple class that manages json data for each sensor
Check is_valid to ensure that the sensor data is valid 
"""
class SensorJSON():
	"""
	Reads sensor data from an individual sensor
	"""
	@staticmethod
	def read_sensor(sensor: str):
		req = requests.get('https://www.purpleair.com/json?show={0}'.format(sensor))
		if(req.status_code != 200):
			print("Failed to get sensor data for sensor with id {0}".format(sensor))
		return SensorJSON(req.content)

	def __init__(self, val: bytes):
		self.json = json.loads(val)
		self.valid = True # Set to false if we're not valid 
		self.label = self.get_field('Label') or 'None'
		self.temp = self.get_field('temp_f') or 0 
		self.last_seen = self.get_field('LastSeen') or 0
		self.pm25 = self.get_field('PM2_5Value') or 0.0
		self.aqi = None 

	def pretty_last_seen(self):
		return time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(self.last_seen))

	"""
	Returns the specified field or None if not found.
	"""
	def get_field(self, name: str):
		try:
			return self.json['results'][0][name]
		except:
			self.valid = False 
			return None 

	def is_valid(self) -> bool:
		return self.valid 

	"""
	Calculates the AQI based on this sensor's data.
	This isn't an average value, only the current one returned by the sensor
	What a horrible function! 
	Equation documented at: https://forum.airnowtech.org/t/the-aqi-equation/169
	"""
	def calc_aqi(self) -> float:
		conc_in = float(self.pm25)
		aqi_lo = 0.0
		aqi_hi = 0.0
		conc_lo = 0.0
		conc_hi = 0.0
		if conc_in > 250.5:
			conc_lo = 250.5
			conc_hi = 500.4
			aqi_lo = 301.0
			aqi_hi = 500.0
		elif conc_in > 150.5:
			conc_lo = 150.5
			conc_hi = 250.4
			aqi_lo = 201.0 
			aqi_hi = 300.0 
		elif conc_in > 55.5:
			conc_lo = 55.5
			conc_hi = 150.4
			aqi_lo = 151.0
			aqi_hi = 200.0
		elif conc_in > 35.5:
			conc_lo = 35.5
			conc_hi = 55.4
			aqi_lo = 101.0 
			aqi_hi = 150.0 
		elif conc_in > 12.1:
			conc_lo = 12.1 
			conc_hi = 35.4
			aqi_lo = 51.0
			aqi_hi = 100.0
		else:
			conc_lo = 0.0
			conc_hi = 12.0
			aqi_lo = 0.0
			aqi_hi = 50.0
		return ((aqi_hi-aqi_lo)/(conc_hi-conc_lo)) * (conc_in - conc_lo) + aqi_lo 
		

"""
Grabs the latest sensor data from the sensors in the sensor list 
"""
def grab_sensors():
	sensor_data.clear()
	for sensor in sensors:
		sensor_data.append(SensorJSON.read_sensor(sensor))


def newmain():
	if args.DAEMON:
		log("Populating sensor data...")
		grab_sensors()
		log("Done.")

	bad = False
	aqi = 0
	for sensor in sensor_data:
		saqi = sensor.calc_aqi()
		if saqi > report_threshold:
			bad = True
			if saqi > aqi:
				aqi = saqi
	if not bad:
		log("All sensors reported an AQI within the acceptable range.")
		if state.get_value('was_high') is True:
			log("Cooldown timer started....")
			time.sleep(cooldown_time * 60) # Sleep for a cooldown time so we don't spam the email if we hover around a specific time
			log("...Finished. Sending email")
			email_provider.send_low_email(round(aqi))

		state.set_value('was_high', False)
		return
	state.set_value('last_high_aqi', aqi)

	# If it was high last time, let's not report again
	if state.get_value('was_high'):
		state.set_value('was_high', True)
		return
	state.set_value('was_high', True)
	state.set_value('last_report_time', time.time())
	log("An AQI above {0} was detected. Sending alert email".format(report_threshold))

	email_provider.send_high_email(round(aqi))

def daily_email_thread():
	while True:
		# I hate nested loops 
		while True:
			now = datetime.datetime.now()
			current_time = [now.hour, now.minute]
			if current_time == [status_email_hour, 0]:
				break 
			else: 
				time.sleep(20)
		log("Sending daily status email")
		email_mutex.acquire()
		grab_sensors()
		# TODO: Clean this up...
		aqi = 0.0
		for sensor in sensor_data:
			saqi = sensor.calc_aqi()
			if saqi > aqi:
				aqi = saqi
		email_provider.send_status_email(round(aqi))
		email_mutex.release()
		time.sleep(120) # Hack so the timer doesnt get triggered immediately again

def main():
	if args.DAEMON:	
		threading.Thread(target=daily_email_thread).start()
		while True:
			# This mutex is actually so we can send daily emails without screwing up the sensor data if we update the sensors on 2 different threads
			email_mutex.acquire()
			newmain()
			email_mutex.release()
			state.save()
			time.sleep(update_period * 60)
	else:
		log("Populating sensor data...")
		grab_sensors()
		log("Done.")
		# Daily status email 
		now = datetime.datetime.now()
		if now.hour == status_email_hour:
			# TODO: Clean this up...
			aqi = 0.0
			for sensor in sensor_data:
				saqi = sensor.calc_aqi()
				if saqi > aqi:
					aqi = saqi
			email_provider.send_status_email(round(aqi))
		# Run normal routine
		newmain()
		state.save()

if __name__ == "__main__":
	main()