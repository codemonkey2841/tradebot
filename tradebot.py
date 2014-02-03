#!/usr/bin/env python

""" It's Tradebot! """
import datetime
import logging
from btceapi import trade
from btceapi import keyhandler
from btceapi import public
from math import ceil
import sqlite3
import time

LIST_SIZE = 20

class TradeBot(object):
    """ The TradeBot class """

    api = None
    balance = [0.0, 0.0]
    curr = []
    database = None
    log = None
    simulation = False
    trade_increment = None
    trade_threshold = None
    wait = 15

    def __init__(self, args):
        verbosity = 0
        if args['verbosity'] == 'DEBUG':
            verbosity = logging.DEBUG
        elif args['verbosity'] == 'INFO':
            verbosity = logging.INFO
        elif args['verbosity'] == 'WARNING':
            verbosity = logging.WARNING
        elif args['verbosity'] == 'ERROR':
            verbosity = logging.ERROR
        elif args['verbosity'] == 'CRITICAL':
            verbosity = logging.CRITICAL
        self.log = logging.getLogger('tradebot')
        self.log.setLevel(verbosity)
        handler = logging.FileHandler(args['logfile'])
        handler.setLevel(verbosity)
        formatter = logging.Formatter('%(asctime)s %(message)s')
        handler.setFormatter(formatter)
        self.log.addHandler(handler)
        self.log.debug('Tradebot initiated.')

        self.api = trade.TradeAPI(args['api_key'],
                                  keyhandler.KeyHandler(args['api_file']))
        self.trade_threshold = args['trade_threshold']
        self.curr = [args['pair'][:3], args['pair'][4:]]
        self.wait = args['wait']
        self.trade_increment = args['trade_increment']
        self.update_balance()
        if args['simulation'] == "on":
            self.simulation = True
        self.database = sqlite3.connect(args['db'])
        self.initialize_db()

    def revert_on_cancel(self):
        """ Reverts last state on a cancel """
        cursor = self.database.cursor()
        cursor.execute("DELETE FROM trades ORDER BY timestamp DESC LIMIT 1")
        self.database.commit()

    def get_price_history(self, count=20):
        """ Gets the last trade price from btc-e """
        cursor = self.database.cursor()
        cursor.execute("SELECT price FROM prices ORDER BY timestamp DESC " \
            "LIMIT ?", (count,))
        rows = cursor.fetchall()
        if rows != None:
            temp = []
            for row in rows:
                temp.append(row[0])
            return temp
        else:
            return list(0)

    def average_price(self):
        """ Sets current price by averaging last LIST_SIZE results of
        get_last """
        cursor = self.database.cursor()
        delta = time.time() - (20 * self.wait)
        self.log.debug("Average price for prices since %f", delta)
        cursor.execute("SELECT avg(price) FROM prices WHERE timestamp > ?",
            (time.time() - (20 * self.wait),))
        row = cursor.fetchone()
        if row != None:
            if row[0] != None:
                return row[0]
        return -1

    def get_balance(self, get):
        """ Get balance information, assign balance of first pair to """
        return self.balance[get - 1]

    def update_balance(self):
        """ Update the balances of the primary currencies """

        if not self.simulation:
            account_info = vars(self.api.getInfo())
            self.balance[0] = float(account_info['balance_%s' % self.curr[0]])
            self.balance[1] = float(account_info['balance_%s' % self.curr[1]])

    def make_trade(self, action, trade_cost=None):
        """ Make a trade """
        if trade_cost == None:
            trade_cost = self.get_trade_cost()
        price = self.average_price()
        trade_info = str(action) + ',' + str(price)
        self.log.debug(trade_info)
        pair = '%s_%s' % (self.curr[0], self.curr[1])
        self.log.info('%sing %f %s', action, trade_cost, self.curr[0].upper())
        order = None
        if not self.simulation:
            result = self.api.trade(pair,
                                    action,
                                    ceil(price * 100000) / 100000.0,
                                    trade_cost)
            order = self.api.tradeHistory(from_id=result.order_id,
                                          end_id=result.order_id)
        else:
            if action == 'buy':
                self.balance[0] += trade_cost
                self.balance[1] -= ceil(trade_cost * price * 100000) / 100000.0
            elif action == 'sell':
                self.balance[0] -= trade_cost
                self.balance[1] += ceil(trade_cost * price * 100000) / 100000.0
            order = trade.OrderItem(order_id=-1, info={'pair': pair,
             'type': action,
             'amount': trade_cost,
             'rate': price,
             'timestamp_created': time.time(),
             'status': 1})
        cursor = self.database.cursor()
        cursor.execute('INSERT INTO trades (order_id, pair, type, amount, ' \
            'rate, timestamp, status, is_sim) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
            (order.order_id,
             order.pair,
             order.type,
             order.amount,
             order.rate,
             order.timestamp_created,
             order.status,
             self.simulation))
        self.database.commit()

    def check_if_changed(self):
        """ Check if changed """
        state, price = self.get_state()
        if state == 'buy' and self.average_price() < price:
            self.log.info('Buy price reached (%f %s)',
                          price,
                          self.curr[1].upper())
            value = self.get_trade_cost() * self.average_price()
            if self.get_balance(2) < value:
                self.log.warn('Balance too low: %f %s needed to buy',
                              value - self.get_balance(2),
                              self.curr[1].upper())
            else:
                self.log.debug('Ready to buy')
                self.make_trade('buy')
                self.check_if_changed()
        elif state == 'sell' and self.average_price() > price:
            self.log.info('Sell price reached (%f %s)',
                          price,
                          self.curr[1].upper())
            if self.get_balance(1) < self.get_trade_cost():
                self.log.warn('Balance too low: %f %s needed to sell',
                              self.get_trade_cost() - self.get_balance(1),
                              self.curr[0].upper())
            else:
                self.log.debug('Ready to sell')
                self.make_trade('sell')
                self.check_if_changed()

    def autocancel(self):
        """ Function to cancel orders that haven't been filled for awhile,
        not complete. """
        if self.simulation:
            return
        order_timeout = self.wait * 20
        current_time = datetime.datetime.now()
        pair = '%s_%s' % (self.curr[0], self.curr[1])
        orders = self.api.activeOrders(pair=pair)
        if not orders:
            return
        if len(orders) > 0:
            self.log.info('%d outstanding orders', len(orders))
        order_ages = []
        for order in orders:
            order_ages.append([order.order_id,
                               current_time - order.timestamp_created])

        for order in order_ages:
            if order[1].seconds > order_timeout:
                self.log.info('Cancelling %s', order[0])
                self.api.cancelOrder(order[0])
            self.revert_on_cancel()

    def refresh_price(self):
        """ Refreshes prices """
        self.update_price()
        self.update_balance()
        self.update_trades()
        self.autocancel()
        self.check_if_changed()

    def update_price(self):
        """ Get the current price via the API and insert it into the
        database """
        pair = "%s_%s" % (self.curr[0], self.curr[1])
        last = public.getTicker(pair).last
        cursor = self.database.cursor()
        self.log.debug("INSERTING price (%f, %s, %f)",
                        last,
                        pair,
                        time.time())
        cursor.execute("INSERT INTO prices (price, pair, timestamp) VALUES " \
            "(%f, ?, ?)" % last, (pair, time.time(),))
        self.database.commit()

    def get_trade_cost(self):
        """ Get calculated trade cost """
        if self.get_state()[0] == 'sell':
            return float(self.trade_increment * self.get_balance(1))
        elif self.get_state()[0] == 'buy':
            return float(self.trade_increment * self.get_balance(2)
                / self.average_price())
        else:
            return 0.0

    def get_state(self):
        """ Get the current trade state and price threshold """
        last = ''
        price = self.average_price()
        cursor = self.database.cursor()
        delta = time.time() - (20 * self.wait)
        cursor.execute("SELECT COUNT(*) FROM prices WHERE timestamp > ?",
                       (delta,))
        row = cursor.fetchone()
        if row[0] < 20:
            return ("build", price)
        cursor.execute("SELECT type, rate FROM trades WHERE pair = ? AND " \
            "is_sim = ? ORDER BY timestamp DESC LIMIT 1 ",
            ('%s_%s' % (self.curr[0], self.curr[1]), self.simulation))
        row = cursor.fetchone()
        if row != None:
            last = row[0]
            price = row[1]
        else:
            cursor.execute("INSERT INTO trades (order_id, pair, type, " \
                "amount, rate, timestamp, status, is_sim) VALUES (?, " \
                "?, ?, ?, ?, ?, ?, ?)",
                (-1,
                '%s_%s' % (self.curr[0], self.curr[1]),
                '',
                0,
                price,
                time.time(),
                1,
                self.simulation))
            self.database.commit()

        if self.get_balance(1) <= 0.0:
            state = 'buy'
            price -= price * self.trade_threshold
        elif self.get_balance(2) <= 0.0:
            state = 'sell'
            price += price * self.trade_threshold
        elif last == 'sell' or last == '':
            state = 'buy'
            price -= price * self.trade_threshold
        elif last == 'buy':
            state = 'sell'
            price += price * self.trade_threshold
        return (state, price)

    def get_orders(self):
        """ Retrieve active orders """
        return []

    def update_trades(self):
        """ Update state of trades via API """
        pass

    def get_trade_history(self, count=5):
        """ Get trade history for active pair """
        cursor = self.database.cursor()
        cursor.execute("SELECT Id, order_id, pair, type, amount, rate, " \
            "timestamp FROM trades WHERE status = 1 AND pair = ? AND " \
            "is_sim = ? AND type != '' ORDER BY timestamp DESC LIMIT ?",
            ("%s_%s" % (self.curr[0], self.curr[1]), self.simulation, count))
        result = cursor.fetchall()
        history = []
        for row in result:
            info = {
                "order_id": row[1],
                "pair": row[2],
                "type": row[3],
                "amount": row[4],
                "rate": row[5],
                "timestamp": time.mktime(datetime.datetime.strptime(row[6],
                    '%Y-%m-%d %H:%M:%S.%f').timetuple())}
            history.append(trade.TradeHistoryItem(row[0], info))
        return history

    def initialize_db(self):
        """ Initialize tables in database if they don't exist. """
        cursor = self.database.cursor()
        cursor.execute("CREATE TABLE IF NOT EXISTS trades(Id INTEGER PRIMARY " \
            "KEY AUTOINCREMENT, order_id INTEGER, pair TEXT, type TEXT, " \
            "amount REAL, rate REAL, timestamp REAL, status TEXT, is_sim " \
            "INTEGER)")
        cursor.execute("CREATE TABLE IF NOT EXISTS prices(Id INTEGER PRIMARY " \
            "KEY AUTOINCREMENT, price REAL, pair TEXT, timestamp REAL)")
        self.database.commit()
