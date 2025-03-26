import ccxt

# Autenticación
api_key = '2f1cb002-ede2-4083-a049-262281a041d9'
api_secret = '9D4E9E1882E6B0DF1478598B824C7887'
password = 'Bitcoin1.'  # OKX requiere 'password' además de key y secret

# Instancia del exchange
exchange = ccxt.okx({
    'apiKey': api_key,
    'secret': api_secret,
    'password': password,
    'enableRateLimit': True,
})

exchange.load_markets()

symbol = 'BTC/USDT:USDT'  # importante el formato si usas contratos perpetual
try:
    open_orders = exchange.fetch_open_orders(symbol)
    if open_orders:
        for order in open_orders:
            pos_side = order.get('info', {}).get('posSide', 'N/A')
            print(f"ID: {order['id']}, Tipo: {order['type']}, Lado: {order['side']}, "
                  f"PosSide: {pos_side}, Precio: {order['price']}, Cantidad: {order['amount']}")
    else:
        print("No hay órdenes abiertas.")
except Exception as e:
    print("Error al obtener las órdenes:", str(e))