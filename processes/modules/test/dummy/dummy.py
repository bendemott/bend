# coding: utf-8
"""
This module contains the Dummy process.
"""

__author__ = "Caleb"
__version__ = "0.8"
__status__ = "Development"
__project__ = "stockpile"

import dev
from stockpile.processing.process import Process, Worker

# Shutup Scribes error checking about unused import.
dev = dev

class DummyProcess(Process):
	title = "Dummy"
	desc = "This is a test process that executes a script that does nothing."
	worker = Worker("./dummyworker.py")
	
process = DummyProcess
