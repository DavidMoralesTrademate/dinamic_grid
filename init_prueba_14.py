from bot.core import BotMain

CONFIG = {
    'exchange_options': {
        'apiKey': 'f76999e1-492a-4076-8ec9-d708fc4824e1',
        'secret': '07531DF9F47BFD06C2FC8333B26150B5', 
        'password': 'Bitcoin1.',
    },
    'exchange_name':'OKX',
    'account':'dm0014', 
    'symbols': ['BTC/USDT:USDT'],
    'amount': 1000,
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