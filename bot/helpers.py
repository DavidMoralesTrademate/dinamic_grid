def format_price(price, decimals=1):
    return round(float(price), decimals)

def calculate_order_prices(price, percentage_spread, num_orders, decimals=1):
    # Calcula precios decrecientes en un grid, por ejemplo
    factor = 1 - percentage_spread
    return [format_price(price * (factor ** i), decimals) for i in range(num_orders)]

def format_quantity(quantity, decimals=2):
    return round(float(quantity), decimals)
