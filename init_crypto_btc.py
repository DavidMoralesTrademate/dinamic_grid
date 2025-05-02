from bot_crypto.core import BotMain

CONFIG = {
    'exchange_options': {
        'apiKey': 'ryP5r4NykiMFMgirpDrzz2',
        'secret': 'cxakp_vtir5djaq3FxzMka6cV7Ca', 
    },
    'exchange_name':'Crypto.com',
    'account':'Cuenta principal', 
    'symbols': ['BTC/USD:USD'],
    'amount': 10,
    'percentage_spread': 0.1/100,
    'num_orders': 30,
    'bias': 'short',
    'price_format': 1,
    'amount_format': 1,
    'contract_size': 0.0114,
    'total_buys_filled': 0,
    'total_sells_filled': 0,
    'contracts': 0.0114
}

if __name__ == "__main__":
    bot = BotMain(CONFIG)
    bot.run()