from inverse.core import BotMain

CONFIG = {
    'exchange_options': {
        'apiKey': 'ECyWeeY2f2zNQ6JmMnZm7Z',
        'secret': 'cxakp_CMzw3HAi7c1TqqEjnwJD6a', 
    },
    'exchange_name':'Crypto.com',
    'account':'Cuenta principal', 
    'symbols': ['BTC/USD:USD'],
    'amount': 10,
    'percentage_spread': 0.05/100,
    'num_orders': 90,
    'bias': 'short',
    'price_format': 4,
    'amount_format': 4,
    'contract_size': 0.0001,
    'total_buys_filled': 0,
    'total_sells_filled': 0,
}

if __name__ == "__main__":
    bot = BotMain(CONFIG)
    bot.run()