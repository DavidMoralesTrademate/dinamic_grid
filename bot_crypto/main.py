from bot_crypto.core import BotMain

CONFIG = {
    'exchange_options': {
        'apiKey': 'cxakp_ofHZL7daTQnJp93TqurJ3A',
        'secret': 'Tu2ytzA9Sk1rsUeyUuGrrj', 
    },
    'exchange_name':'Crypto.com',
    'account':'dm0012', 
    'symbols': ['BTC/USD:USD'],
    'amount': 10,
    'percentage_spread': 0.0005,
    'num_orders': 40,
    'bias': 'long',
    'price_format': 2,
    'amount_format': 2,
    'contract_size': 0.1,
    'total_buys_filled': 0,
    'total_sells_filled': 0,
}

if __name__ == "__main__":
    bot = BotMain(CONFIG)
    bot.run()