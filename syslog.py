# coding: utf-8
"""
This module provides functions and constants for formatting syslog messages.

See:
	- http://tools.ietf.org/html/rfc5424
"""
__author__ = "Caleb"
__version__ = "0.1"
__status__ = "Prototype"

# RFC5424 6.2.1 Table 1: Syslog Message Facilities
KERNEL = 0
USER = 1
MAIL = 2
SYSTEM = 3
SECURITY = 4
SYSLOGD = 5
LINE_PRINTER = 6
NETWORK_NEWS = 7
UUCP = 8
CLOCKD = 9
SECURITY = 10
FTPD = 11
NTP = 12
LOG_AUDIT = 13
LOG_ALERT = 14
CLOCKD2 = 15
LOCAL0 = 16
LOCAL1 = 17
LOCAL2 = 18
LOCAL3 = 19
LOCAL4 = 20
LOCAL5 = 21
LOCAL6 = 22
LOCAL7 = 23

# RFC5424 6.2.1 Table 2: Syslog Message Severities
EMERGANCY = 0 # Sys is unusable.
ALERT = 1 # Action must be taken immediately.
CRITICAL = 2 # Critical conditions.
ERROR = 3 # Error conditions.
WARNING = 4 # Warning conditions.
NOTICE = 5 # Normal but significant condition.
INFO = 6 # Informational messages.
DEBUG = 7 # Debug-level messages. 

def prival(self, facility, severity):
	"""
	Calculates the priority value by multiplying the facility value by 8 and then
	adding the severity value to the product and returning the sum.
	
	Arguments:
		facility (int) -- The type of facility.
		severity (int) -- The severity level.
		
	Returns:
		(int) -- The calculated priority value.
	"""
	return facility * 8 + severity

def header(self, prival, version, timestamp=None, hostname=None, appname=None, procid=None, msgid=None):
	#TODO: Return the formatted header.
	pass



def format(self, )
