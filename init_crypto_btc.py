from inverse.core import BotMain

CONFIG = {
    'exchange_options': {
        'apiKey': 'ryP5r4NykiMFMgirpDrzz2',
        'secret': 'cxakp_vtir5djaq3FxzMka6cV7Ca', 
    },
    'exchange_name':'Crypto.com',
    'account':'Cuenta principal', 
    'symbols': ['BTC/USD:USD'],
    'amount': 10,
    'percentage_spread': 0.05/100,
    'num_orders': 20,
    'bias': 'short',
    'price_format': 0,
    'amount_format': 0,
    'contract_size': 0.0001,
    'total_buys_filled': 0,
    'total_sells_filled': 0,
}

if __name__ == "__main__":
    bot = BotMain(CONFIG)
    bot.run()