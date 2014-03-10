#!/usr/bin/env python

""" It's a TradeBot """

import configparser
import curses
import httplib
import os
import signal
import ssl
import sys
import time
from tradebot import TradeBot

def on_exit(sig, func=None):
    curses.nocbreak()
    stdscr.keypad(0)
    curses.echo()
    curses.endwin()
    curses.curs_set(1)
    sys.exit()

def initialize():
    # Initialize curses screen
    stdscr = curses.initscr()
    curses.noecho()
    curses.cbreak()
    stdscr.keypad(1)
    curses.curs_set(0)

    # Initialize screen
    stdscr.addstr(0, 0, "=" * 82)
    stdscr.addstr(1, 36, "BTC-E BOT")
    stdscr.addstr(2, 0, "-" * 81)
    stdscr.addstr(4, 0, "=" * 81)
    stdscr.addstr(21, 0, " " * 70)
    stdscr.addstr(22, 0, "=" * 82)
    for i in range(1, 22):
        stdscr.addstr(i, 0, "|")
        stdscr.addstr(i, 81, "|")

    # Initialize top bar labels
    stdscr.addstr(3, 2, "SIM", curses.A_BOLD)
    stdscr.addstr(3, 12, "VERBOSE", curses.A_BOLD)
    stdscr.addstr(3, 24, "WAIT", curses.A_BOLD)
    stdscr.addstr(3, 35, "PAIR", curses.A_BOLD)
    stdscr.addstr(3, 50, "THRESH", curses.A_BOLD)
    stdscr.addstr(3, 65, "TRADE", curses.A_BOLD)
    stdscr.addstr(3, 6, "[   ]")
    stdscr.addstr(3, 20, "[ ]")
    stdscr.addstr(3, 29, "[   ]")
    stdscr.addstr(3, 40, "[       ]")
    stdscr.addstr(3, 57, "[     ]")
    stdscr.addstr(3, 71, "[       ]")

    # Initialize main area labels
    stdscr.addstr(5, 2, "BALANCE:", curses.A_BOLD)
    stdscr.addstr(5, 67, "PRICE HISTORY", curses.A_UNDERLINE)
    stdscr.addstr(6, 57, "CURRENT ->")
    stdscr.addstr(7, 2, "STATE:", curses.A_BOLD)
    stdscr.addstr(8, 2, "TRADE INCREMENT:", curses.A_BOLD)
    stdscr.addstr(9, 2, "TRADE THRESHOLD:", curses.A_BOLD)
    stdscr.addstr(10, 2, "AVERAGE PRICE:", curses.A_BOLD)
    stdscr.addstr(19, 2, "ORDER LIST (  )", curses.A_UNDERLINE)
    stdscr.addstr(12, 2, "TRADE HISTORY", curses.A_UNDERLINE)

    stdscr.refresh()
    return stdscr

def update(stdscr):
    curr1 = tradebot.curr[0].upper()
    curr2 = tradebot.curr[1].upper()

    stdscr.addstr(1, 56, "%s" % time.asctime())

    (state, thresh) = tradebot.get_state()
    if state == "buy":
        thresh = "< %f" % thresh
    elif state == "sell":
        thresh = "> %f" % thresh
    elif state == "build":
        thresh = "%f" % thresh
    stdscr.addstr(9, 20, "%s %s" % (thresh, curr2))
    stdscr.addstr(10, 20, "%f %s" % (tradebot.average_price(), curr2))
    stdscr.addstr(5, 12, "%f %s / %f %s"
        % (tradebot.get_balance(1), curr1, tradebot.get_balance(2),curr2))
    stdscr.addstr(7, 20, "%s   " % state.upper())
    stdscr.addstr(8, 20, "%f %s" % (tradebot.get_trade_cost(), curr1))

    # Top Bar values
    sim = "OFF"
    if tradebot.simulation:
        sim = "ON"
    stdscr.addstr(3, 7, "%3s" % sim)
    stdscr.addstr(3, 21, "%s" % args['verbosity'][:1])
    stdscr.addstr(3, 30, "%3d" % tradebot.wait)
    stdscr.addstr(3, 41, "%s_%s" % (tradebot.curr[0], tradebot.curr[1]))
    stdscr.addstr(3, 58, "%.02f%%" % (tradebot.trade_threshold * 100))
    stdscr.addstr(3, 72, "%6.02f%%" % (tradebot.trade_increment * 100))

    # Price History
    line = 6
    history = tradebot.get_price_history()
    for item in history:
        stdscr.addstr(line, 68, "%f %s" % (item, curr2))
        line += 1
        if line > 21:
            break
    
    # Completed trades
    history = tradebot.get_trade_history()
    line = 13
    for item in history:
        stdscr.addstr(line, 2, "%s: %s %f @ %.05f %s " % (item.timestamp,
                                                          item.type,
                                                          item.amount,
                                                          item.rate,
                                                          curr2))
        line += 1
    
    # Order list
    orders = tradebot.get_orders()
    stdscr.addstr(19, 14, "%2d" % len(orders))
    line = 20
    stdscr.addstr(20, 2, " " * 40)
    stdscr.addstr(21, 2, " " * 40)
    for order in orders:
        stdscr.addstr(line, 2, "%s %f @ %.05f %s" % (order.type,
                                                     order.amount,
                                                     order.rate,
                                                     curr2))
        line += 1
        if line > 21:
            break
    stdscr.refresh()

signal.signal(signal.SIGQUIT, on_exit)
signal.signal(signal.SIGTERM, on_exit)
signal.signal(signal.SIGINT, on_exit)

errlog = 'error.log'

config = configparser.ConfigParser()
config.read('tradebot.conf')

args = {}
if 'api_file' in config['BTC-E']:
    args['api_file'] = str(config['BTC-E']['api_file'])
else:
    sys.stderr.write('api_file not defined')
    sys.exit(1)
with open(args['api_file']) as f:
   args['api_key'] = f.readline().strip()
if 'increment' in config['TRADE']:
    args['trade_increment'] = float(config['TRADE']['increment'])
else:
    args['trade_increment'] = 0.012
if 'threshold' in config['TRADE']:
    args['trade_threshold'] = float(config['TRADE']['threshold'])
else:
    args['trade_threshold'] = 0.006
if 'pair' in config['BTC-E']:
    args['pair'] = str(config['BTC-E']['pair'])
else:
    args['pair'] = 'ltc_btc'
if 'wait' in config['TRADE']:
    args['wait'] = int(config['TRADE']['refresh'])
else:
    args['wait'] = 15
if 'simulation' in config['MAIN']:
    args['simulation'] = str(config['MAIN']['simulation'])
else:
    args['simulation'] = 'off'
if 'verbosity' in config['MAIN']:
    args['verbosity'] = config['MAIN']['verbosity'].upper()
else:
    args['verbosity'] = "ERROR"
if 'logfile' in config['MAIN']:
    args['logfile'] = str(config['MAIN']['logfile'])
else:
    args['logfile'] = 'tradebot.log'
if 'db' in config['MAIN']:
    args['db'] = str(config['MAIN']['db'])
else:
    args['db'] = 'tradebot.db'

sys.stderr = open(errlog, "w")

tradebot = TradeBot(args)

stdscr = initialize()

while True:
    try:
        stdscr.addstr(21, 2, " " * 70)
        tradebot.refresh_price()
        for i in range(tradebot.wait):
            update(stdscr)
            time.sleep(1)
    except (ssl.SSLError, httplib.HTTPException,ValueError):
        curses.start_color()
        curses.init_pair(1, curses.COLOR_RED, curses.COLOR_WHITE)
        for i in range(60):
            stdscr.addstr(21, 2, "Failed to connect to exchange. Retrying " \
                "in %d" % i, curses.color_pair(1))
    except Exception as e:
        curses.nocbreak()
        #stdscr.keypad(0)
        curses.echo()
        curses.endwin()
        curses.curs_set(1)
        import traceback
        type_, value_, traceback_ = sys.exc_info()
        for line in traceback.format_tb(traceback_):
            sys.stderr.write(line)
        sys.stderr.write(e.__class__.__name__ + ": ")
        sys.stderr.write(e.message)
        sys.exit()
