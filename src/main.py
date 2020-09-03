#!/usr/bin/env python3

#
# Simple air-quality alert system using the purple-air API
#

"""
Configuration format 
{
	"email": {
		"login_required": true,
		"email_addr": "jeremy.lorelli.1337@gmail.com", // Email address to send FROM 
		"email_pw": "1234",
		"smtp_addr": "localhost",
		"smtp_port": 224,
		// Addresses to send the status emails to
		"addresses": [
			"jeremy.lorelli.1337@gmail.com"
		]
	},
	"report_threshold": 150, // An AQI over this number will trigger a report 
	// These are sensor IDs obtained from the sensor map 
	"sensors": [
		"61605",
		"61217",
		"38085",
		"60059"
	]
}
"""

import json, http, os, sys, email, smtplib, requests, argparse, time 

argparse = argparse.ArgumentParser(description='Simple alert system for poor air quality')
argparse.add_argument('--config', type=str, dest='config', default='/etc/air-alert.json', help='Path to the air quality alert config')
args = argparse.parse_args()

# Load the config
cfg = None
with open(args.config, "r") as fp:
	cfg = json.load(fp)

def get_or_set_default(section, name, default):
	try:
		if section[name] is None:
			return default
		return section[name]
	except:
		return default 

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
report_threshold = get_or_set_default(cfg, 'report_threshold', 150)

sensor_data = []

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
	for sensor in sensors:
		sensor_data.append(SensorJSON.read_sensor(sensor))


def main():
	print("Populating sensor data...")
	grab_sensors()
	print("Done.")

	# Test to make sure none of the sensors are higher than the max AQI
	bad = False 
	for sensor in sensor_data:
		if sensor.calc_aqi() > report_threshold:
			bad = True
	if not bad:
		print("All AQIs are below the threshold.")
		return

	print("Air quality is above threshold of {0}. Sending email.".format(report_threshold))

	msg = email.message.EmailMessage() 
	msg['Subject'] = 'Air Quality Alert'
	msg['From'] = 'air-report'
	msg['To'] = 'jeremy.lorelli.1337@gmail.com'

	body = "Poor air quality has been detected in the immediate vicinity of SLAC.\nThose who are sensitive to poor air quality should remain indoors.\nOthers should consider wearing masks or respirators\n\nSummary of the sensors and their detected AQIs:\n\n"

	for sensor in sensor_data:
		body += "Location: {0}\nLast Sampled: {2}\nAQI: {1}\n\n".format(sensor.label, int(sensor.calc_aqi()), sensor.pretty_last_seen())

	msg.set_content(body)

	s = smtplib.SMTP(smtp_addr, smtp_port)
	s.ehlo()
	s.starttls()
	if login_required:
		try:
			s.login(user=email_addr, password=email_pw)
		except smtplib.SMTPAuthenticationError:
			print("Authentication failed for SMTP server")
		except:
			print("Error while authenticating SMTP server")
	s.send_message(msg)
	s.quit()

if __name__ == "__main__":
	main()