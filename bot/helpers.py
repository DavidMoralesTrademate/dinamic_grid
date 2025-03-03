def format_price(price, decimals=1):
    """Redondea el precio al número de decimales especificado de manera eficiente."""
    return round(float(price), decimals)

def calculate_order_prices(price, percentage_spread, num_orders, decimals):
    """Calcula los precios de las órdenes en un grid alcista de manera optimizada."""
    factor = 1 - percentage_spread  # Solo dirección alcista
    return [format_price(price * (factor ** i), decimals) for i in range(num_orders)]

def format_quantity(quantity, decimals=2):
    """Redondea la cantidad al número de decimales especificado sin errores de precisión."""
    return round(float(quantity), decimals)