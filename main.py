from bot.core import BotMain

CONFIG = {
    'exchange_options': {
        'apiKey': '43b21016-9cbf-4b01-8e70-30bcbde11481',
        'secret': 'EFA0EC41AC7C2393579A84A1DBD67D05', 
        'password': 'Bitcoin1.',
    },
    'symbols': ['BTC/USDT:USDT'],
    'amount': 100,
    'percentage_spread': 0.0005,
    'num_orders': 30,
    'bias': 'long',
    'price_format': 1,
    'amount_format': 2,
    'contract_size': 0.01,
}

if __name__ == "__main__":
    bot = BotMain(CONFIG)
    bot.run()