import asyncio
import logging
from sortedcontainers import SortedDict
from bot.helpers import calculate_order_prices, format_quantity, format_price

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
        
        # Estructura para almacenar órdenes activas ordenadas por precio
        self.active_orders = SortedDict()  # {precio: (cantidad_compra, id_orden)}
    
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
                
                print(self.active_orders)
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
                
                # Si era una compra ejecutada, la eliminamos del SortedDict
                if order['side'] == 'buy' and order['price'] in self.active_orders:
                    del self.active_orders[order['price']]
                
                # Crear la nueva orden contraria y agregarla al SortedDict como venta
                new_order = await self.create_order(side, order['amount'], target_price)
                if new_order:
                    print('hola deberia ser aqui')
                    self.active_orders[target_price] = (side, order['amount'], new_order['id'])
                
                logging.info(f"Orden procesada: {side.upper()} {order['amount']} @ {target_price}")
        except Exception as e:
            logging.error(f"Error procesando orden: {e}")

    
    async def create_order(self, side, amount, price):
        """Crea una nueva orden de compra o venta y la almacena en SortedDict."""
        try:
            formatted_amount = format_quantity(amount / price / self.contract_size, self.amount_format)
            order = await self.exchange.create_order(self.symbol, 'limit', side, formatted_amount, price, params={'posSide': 'long'})
            logging.info(f"Orden creada: {side.upper()} {formatted_amount} @ {price}")
            return {'id': order['id'], 'price': price, 'amount': formatted_amount}
        except Exception as e:
            logging.error(f"Error creando orden: {e}")
            return None
    
    async def place_orders(self, price):
        """Coloca órdenes de compra o venta en el grid y las almacena en SortedDict."""
        try:
            prices = calculate_order_prices(price, self.percentage_spread, self.num_orders, self.price_format)
            for p in prices:
                order = await self.create_order('buy', self.amount, p)
                if order:
                    self.active_orders[p] = ('buy', self.amount, order['id'])
        except Exception as e:
            logging.error(f"Error colocando órdenes: {e}")
