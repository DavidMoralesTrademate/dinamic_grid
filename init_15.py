from bot.hola import BotMain

CONFIG = {
    'exchange_options': {
        'apiKey': '658ca219-bd5d-42f1-8f80-ffe1edce2ed1',
        'secret': 'DDF28BBD70C80C10B69225D991FE1DB5', 
        'password': 'Bitcoin1.',
    },
    'exchange_name':'OKX',
    'account':'dm0015', 
    'symbols': ['BTC/USDT:USDT'],
    'amount': 80000,
    'contracts' : 100,
    'percentage_spread': 0.0005,
    'num_orders': 60,
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