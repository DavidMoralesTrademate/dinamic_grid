import ccxt



def place_order(symbol, order_type, side, amount, price=None):
    # Configura tus credenciales de API de OKX
    api_key = 'ct4XFfEadTuEQamcZb1Sa3TCIO5i7lXnF6H6LpNmSrUE7eBAY0wkrtQfSRd1HSkY'
    secret = 'VRvkN0nRYS4sfLGE3WA1Iz2JxPTmV9opnBSl2D2MdzVnGA2RELr43uO4D9DPYAps'

    # Conecta con el intercambio
    exchange = ccxt.binance({
        'apiKey': api_key,
        'secret': secret,
        'enableRateLimit': True,
    })

    try:
        # Verifica si la orden es de tipo 'market' o 'limit'
        if order_type == 'limit':
            order = exchange.create_order(
                symbol=symbol,
                type=order_type,
                side=side,
                amount=amount,
                price=price,
            )
        elif order_type == 'market':
            order = exchange.create_order(
                symbol=symbol,
                type=order_type,
                side=side,
                amount=amount
            )
        else:
            raise ValueError("Tipo de orden no soportado. Usa 'limit' o 'market'.")

        print(f"Orden colocada: {order}")
        return order

    except ccxt.BaseError as e:
        print(f"Error al colocar la orden: {e}")

def format_price(price, decimals=1):
    return round(float(price), decimals)

def calculate_order_prices_buy(price, percentage_spread, num_orders, decimals=1):
    # Calcula precios decrecientes en un grid, por ejemplo
    factor = 1 - percentage_spread
    return [format_price(price * (factor ** i), decimals) for i in range(num_orders)]

print(prices_bid)
tasks = [
    place_order(
    symbol='SOL/USDT:USDT', 
    order_type='limit',   
    side='buy',           
    amount=int(25333/price),         
    price=price        
    )
    for price in prices_bid
]
