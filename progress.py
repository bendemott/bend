# coding: utf-8
"""
The progress module provides functionality for reporting progress.
"""
from __future__ import division

__author__ = "Caleb"
__version__ = "0.8"
__status__ = "Development"
__project__ = "stockpile"

import datetime as _datetime
import os as _os
import socket as _socket
import sys as _sys
import time as _time

class StandardProgress:
	"""
	The StandardProgress class provides methods for reporting progress using the
	standard progress model.
	
	Instance Attributes:
		_buffer (list)
		- A buffered list of progress 2-tuples. A progress 2-tuple contains the UTC
		  time (float) that the progress was record, and a progress value (float or
		  2-tuple). If a progress value is a float, it's the percentage complete in
		  the range of `0.0` and `1.0`. If a progress value is a 2-tuple, it
		  contains the amount completed (int) and the total amount to complete
		  (int).
		_fd (int)
		- The file descriptor to write progress to.
		_header (str)
		- The message header that needs to be interpolated with: the timestamp
		  (str).
		_total (int)
		- The stored total amount value.
	"""
	
	def __init__(self, name, host=None, fd=None):
		"""
		Initializes a StandardProgress instance.
		
		Arguments:
			name (str)
			- The name of the program running.
			
		Optional Arguments:
			fd (int)
			- The file descriptor to write progress to; default is `3`.
		"""
		self._buffer = []
		self._fd = int(fd) if fd is not None else 3
		self._header = "<134>1 %%s %s %s %s status" % (_socket.gethostname(), name, _os.getpid())
		self._total = None
		
	def _format(self, progress):
		"""
		Formats the specified progress into a message.
		
		Arguments:
			progress (2-tuple)
			- A 2-tuple that contains the UTC time (float), and a value (float or
			  2-tuple). If the value is a float, it's the percentage complete in the
			  range of `0.0` and `1.0`. If the value is a 2-tuple, it contains the
			  amount completed (int) and the total amount to complete (int). 
		"""
		time, value = progress
		header = self._header % (_datetime.datetime.utcfromtimestamp(time).isoformat() + 'Z')
		
		if isinstance(value, float):
			perc = value
			frac = None
		else:
			perc = value[0] / value[1]
			frac = value
			
		data = ['status@ridersdiscount', 'progress="%.3f"' % perc]
		if frac:
			data.append('frac="%i,%i"' % frac)
			
		return "%s [%s]\n" % (header, ' '.join(data))
		
	def progress(self, percent=None, total=None, complete=None, remaining=None, write=False):
		"""
		Sets the progress.
		
		The progress can updated using multiple methods: percent-based, completed
		based and remaining-based. Percent-based is for when you only know the 
		percentage complete. Completed-based is for when you know the amount
		completed so far and the total amount to complete can change at run-time.
		Remaining-based is for you only know the remaining amount until completion
		and the total amount to complete. The `total` argument only needs to be
		passed the first time for the completed-based and remaining-based progress
		methods. The last known value for `total` will then be used for any
		subsequent calls. If `total` is passed, it's value will be updated.
		
		Percent-based Arguments:
			percent (float)
			- The percentage complete within the range of `0.0` and `1.0`.
			
		Completed-based Arguments:
			complete (int)
			- The amount completed.
			total (int)
			- The total amount to complete; default is last used value.
			
		Remaining-based Arguments:
			remaining (int)
			- The amount remaining until completion.
			total (int)
			- The total amount to complete; default is last used value.
		
		Optional Arguments:
			write (bool)
			- If `True`, the progress will be written immediately to the internal file
			  descriptor; otherwise, the progress will be buffered. 
		"""
		if percent is not None:
			exc = []
			if total is not None:
				exc.append("total:%r" % total)
			if complete is not None:
				exc.append("complete:%r" % complete)
			if remaining is not None:
				exc.append("remaining:%r" % remaining)
			if exc:
				raise ValueError("percent:%r is mutually exclusive with %s." % (percent, ', '.join(exc)))
			# Ensure percent is a float between 0.0 and 1.0.
			percent = float(percent)
			if not 0.0 <= percent <= 1.0:
				raise ValueError("percent:%r is not within the range of `0.0` and `1.0`.")
			# Set progress.
			self._buffer.append((_time.time(), percent))
		elif complete is not None and remaining is not None:
			raise ValueError("complete:%r and remaining:%r are mutually exclusive." % (complete, remaining))
		elif complete is not None:
			if total is None:
				if self._total is None:
					raise ValueError("total:%r needs to be set the first time complete:%r is used." % (total, complete))
				total = self._total
			else:
				total = int(total)
			complete = int(complete)
			if complete > total:
				raise ValueError("complete:%r cannot be greater than total:%r." % (complete, total))
			self._total = total
			# Set progress.
			self._buffer.append((_time.time(), (complete, total)))
		elif remaining is not None:
			if total is None:
				if self._total is None:
					raise ValueError("total:%r needs to be set the first time remaining:%r is used." % (total, remaining))
				total = self._total
			else:
				total = int(total)
			remaining = int(remaining)
			if remaining > total:
				raise ValueError("remaining:%r cannot be greater than total:%r." % (remaining, total))
			self._total = total
			# Set progress.
			self._buffer.append((_time.time(), (total - remaining, total)))
		elif total is not None:
			raise ValueError("total:%r cannot be set without complete:%r or remaining:%r." % (total, complete, remaining))
		else:
			raise ValueError("percent:%r, or either complete:%r or remaining with total:%r must be set." % (percent, complete, remaining, total))
			
		if write:
			# Write buffered progress.
			self.write()
	
	def write(self, fd=None):
		"""
		Write the buffered progresses to the specified file descriptor.
		
		Optional Arguments:
			fd (int)
			- The file descriptor to write to; default is the internet file descriptor
			  which is set in the constructor (default is `3`).
		"""
		fd = int(fd) if fd is not None else self._fd
		for progress in self._buffer:
			msg = self._format(progress)
			_os.write(fd, msg)
		del self._buffer[:]
