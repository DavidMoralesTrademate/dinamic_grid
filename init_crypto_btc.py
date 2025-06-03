from bot_crypto.core import BotMain

CONFIG = {
    'exchange_options':{
        'apiKey': '43b21016-9cbf-4b01-8e70-30bcbde11481',
        'secret': 'EFA0EC41AC7C2393579A84A1DBD67D05', 
        'password': 'Bitcoin1.',
    },
    'exchange_name':'Crypto.com',
    'account':'Cuenta principal', 
    'symbols': ['BTC/USDT:USDT'],
    'amount': 10,
    'percentage_spread': 0.1/100,
    'num_orders': 20,
    'bias': 'short',
    'price_format': 1,
    'amount_format': 1,
    'contract_size': 0.0073,
    'total_buys_filled': 0,
    'total_sells_filled': 0,
    'contracts': 0.0073
}

if __name__ == "__main__":
    bot = BotMain(CONFIG)
    bot.run()