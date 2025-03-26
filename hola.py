from bot.hola import BotMain

CONFIG = {
    'exchange_options': {
        'apiKey': '2f1cb002-ede2-4083-a049-262281a041d9',
        'secret': '9D4E9E1882E6B0DF1478598B824C7887', 
        'password': 'Bitcoin1.',
    },
    'exchange_name':'OKX',
    'account':'dm0013', 
    'symbols': ['BTC/USDT:USDT'],
    'amount': 1000,
    'contracts' : 0.9,
    'percentage_spread': 0.005,
    'num_orders': 25,
    'bias': 'long',
    'price_format': 2,
    'amount_format': 2,
    'contract_size': 0.01,
    'total_buys_filled': 0,
    'total_sells_filled': 0,
}

if __name__ == "__main__":
    bot = BotMain(CONFIG)
    bot.run()