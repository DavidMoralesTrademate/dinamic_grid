from inverse.core import BotMain

CONFIG = {
    'exchange_options':{
        'apiKey': '43b21016-9cbf-4b01-8e70-30bcbde11481',
        'secret': 'EFA0EC41AC7C2393579A84A1DBD67D05', 
        'password': 'Bitcoin1.',
    },
    'exchange_name':'OKX',
    'account':'dm0015', 
    'symbols': ['BTC/USDT:USDT'],
    'amount': 7500,
    'contracts' : 10 ,
    'percentage_spread': 0.0005,
    'num_orders': 20,
    'bias': 'long',
    'price_format': 2,
    'amount_format': 2,
    'contract_size': 0.02,
    'total_buys_filled': 0,
    'total_sells_filled': 0,
}

if __name__ == "__main__":
    bot = BotMain(CONFIG)
    bot.run()