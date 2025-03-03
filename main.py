from bot.core import BotMain

CONFIG = {
    'exchange_options': {
        'apiKey': '43b21016-9cbf-4b01-8e70-30bcbde11481',
        'secret': 'EFA0EC41AC7C2393579A84A1DBD67D05', 
        'password': 'Bitcoin1.',
    },
    'symbols': ['ETH/USDT:USDT'],
    'amount': 10,
    'percentage_spread': 0.000125,
    'num_orders': 10,
    'bias': 'long',
    'price_format': 1,
    'amount_format': 2,
    'contract_size': 0.1,
}

if __name__ == "__main__":
    bot = BotMain(CONFIG)
    bot.run()