#!/usr/bin/env python
# coding: utf-8
"""
Used by the process server to launcher a process.
"""

__author__ = "Caleb"
__version__ = "0.6"
__status__ = "Development"
__project__ = "stockpile"

import dev
from stockpile.processing.process import run_process

if __name__ == "__main__":
	exit(run_process())
