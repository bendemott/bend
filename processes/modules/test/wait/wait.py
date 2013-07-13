# coding: utf-8
"""
This module contains the Wait process.
"""

__author__ = "Caleb"
__version__ = "0.8"
__status__ = "Development"
__project__ = "stockpile"

import dev
from stockpile.processing.process import Process, Worker

class WaitProcess(Process):
	title = "Wait"
	desc = "This is a test process that waits."
	worker = Worker("./waiter.py")
	
process = WaitProcess
