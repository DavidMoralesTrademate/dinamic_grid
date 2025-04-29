from bot_crypto.core import BotMain

CONFIG = {
    'exchange_options': {
        'apiKey': 'Tu2ytzA9Sk1rsUeyUuGrrj',
        'secret': 'cxakp_ofHZL7daTQnJp93TqurJ3A', 
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
    'contract_size': 0.1,
    'total_buys_filled': 0,
    'total_sells_filled': 0,
}

if __name__ == "__main__":
    bot = BotMain(CONFIG)
    bot.run()