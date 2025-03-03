import asyncio
import logging
from bot.helpers import calculate_order_prices, format_quantity

class OrderManager:
    def __init__(self, exchange, symbol, config):
        self.exchange = exchange
        self.symbol = symbol
        self.percentage_spread = float(config['percentage_spread'])
        self.amount = float(config['amount'])
        self.num_orders = int(config['num_orders'])
        self.price_format = config.get('price_format')
        self.amount_format = config.get('amount_format')
        self.contract_size = config.get('contract_size')
        self.order_limit = 10  # Límite de órdenes abiertas permitidas
        self.orders = {}  # Diccionario para rastrear órdenes activas
        self.lowest_order_price = None  # Precio de la orden más baja en el grid
        self.highest_order_price = None  # Precio de la orden más alta en el grid
        self.min_order_amount = 0.01  # Monto mínimo permitido para órdenes

    async def check_orders(self):
        """Monitorea el estado de las órdenes en tiempo real con reconexión inteligente."""
        reconnect_attempts = 0
        while True:
            try:
                orders = await self.exchange.watch_orders(self.symbol)
                if not orders:
                    continue
                for order in orders:
                    await self.process_order(order)
                reconnect_attempts = 0  # Resetear intentos si hay éxito
            except Exception as e:
                reconnect_attempts += 1
                wait_time = min(2 ** reconnect_attempts, 60)  # Backoff exponencial
                logging.error(f"Error en check_orders ({reconnect_attempts} intento): {e}")
                logging.info(f"Reintentando en {wait_time} segundos...")
                await asyncio.sleep(wait_time)
    
    async def process_order(self, order):
        """Procesa una orden ejecutada y coloca una orden contraria."""
        try:
            if order['filled'] == order['amount']:
                side = 'sell' if order['side'] == 'buy' else 'buy'
                target_price = order['price'] * (1 + self.percentage_spread if side == 'sell' else 1 - self.percentage_spread)
                await self.create_order(side, order['amount'], target_price)
                
                # Reemplazar la orden en la estructura de seguimiento
                self.orders.pop(order['id'], None)
                await self.maintain_orders()
        except Exception as e:
            logging.error(f"Error procesando orden: {e}")
    
    async def create_order(self, side, amount, price):
        """Crea una nueva orden de compra o venta y la registra."""
        try:
            formatted_amount = max(format_quantity(amount / price / self.contract_size, self.amount_format), self.min_order_amount)
            order = await self.exchange.create_order(self.symbol, 'limit', side, formatted_amount, price, params={'posSide': 'long'})
            self.orders[order['id']] = order  # Guardar la orden en el diccionario
            self.update_grid_prices()
            logging.info(f"Orden creada: {side.upper()} {formatted_amount} @ {price}")
        except Exception as e:
            logging.error(f"Error creando orden: {e}")
    
    async def maintain_orders(self):
        """Mantiene siempre el número correcto de órdenes activas sin huecos."""
        try:
            await self.update_grid_prices()
            if self.lowest_order_price is None:
                self.lowest_order_price = await self.get_current_price()
            if len(self.orders) < self.num_orders:
                logging.info("Faltan órdenes en el grid. Creando nuevas órdenes...")
                await self.place_orders(self.lowest_order_price)
            elif len(self.orders) > self.num_orders:
                logging.info("Demasiadas órdenes abiertas. Eliminando las más alejadas...")
                await self.clean_far_orders()
        except Exception as e:
            logging.error(f"Error en maintain_orders: {e}")
    
    async def clean_far_orders(self):
        """Elimina las órdenes más alejadas para mantener el grid organizado."""
        try:
            open_orders = await self.exchange.fetch_open_orders(self.symbol)
            if open_orders:
                orders_sorted = sorted(open_orders, key=lambda x: float(x['price']))
                for order in orders_sorted[:len(open_orders) - self.num_orders]:
                    await self.exchange.cancel_order(order['id'], self.symbol)
                    logging.info(f"Orden cancelada: {order['id']} @ {order['price']}")
        except Exception as e:
            logging.error(f"Error en clean_far_orders: {e}")
    
    async def update_grid_prices(self):
        """Actualiza el precio más bajo y más alto del grid."""
        open_orders = await self.exchange.fetch_open_orders(self.symbol)
        if open_orders:
            prices = [float(order['price']) for order in open_orders]
            self.lowest_order_price = min(prices)
            self.highest_order_price = max(prices)
    
    async def get_current_price(self):
        """Obtiene el precio de mercado actual."""
        ticker = await self.exchange.fetch_ticker(self.symbol)
        return (ticker['bid'] + ticker['ask']) / 2
    
    async def place_orders(self, price):
        """Coloca órdenes de compra en el grid asegurando que no haya huecos."""
        try:
            if price is None:
                price = await self.get_current_price()
            prices = calculate_order_prices(price, self.percentage_spread, self.num_orders, self.price_format)
            tasks = [self.create_order('buy', self.amount, p) for p in prices]
            await asyncio.gather(*tasks, return_exceptions=True)
        except Exception as e:
            logging.error(f"Error colocando órdenes: {e}")