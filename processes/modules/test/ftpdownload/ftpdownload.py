# coding: utf-8
"""
This module contains the FTP Download process.
"""

__author__ = "Caleb"
__version__ = "0.7"
__status__ = "Development"
__project__ = "stockpile"

import dev
import os.path
from stockpile.processing.process import Process, Worker

class FtpDownloadProcess(Process):
	title = "FTP Download"
	desc = "This is a test process that downloads a file via FTP."
	worker = Worker("./ftpdownloader.py")

process = FtpDownloadProcess
