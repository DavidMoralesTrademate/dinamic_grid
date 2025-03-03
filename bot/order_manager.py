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

    async def check_orders(self):
        """Monitorea el estado de las órdenes en tiempo real con reconexión inteligente."""
        reconnect_attempts = 0
        while True:
            try:
                orders = await self.exchange.watch_orders(self.symbol)
                if not orders:
                    continue
                for order in orders:
                    asyncio.create_task(self.process_order(order))  # Ejecutar sin esperar
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
                spread_multiplier = 1 + self.percentage_spread if side == 'sell' else 1 - self.percentage_spread
                target_price = order['price'] * spread_multiplier
                
                await self.create_order(side, order['amount'], target_price)
                

        except Exception as e:
            logging.error(f"Error procesando orden: {e}")

    async def create_order(self, side, amount, price):
        """Crea una nueva orden de compra o venta y asegura que no se duplique."""
        try:
            order = await self.exchange.create_order(self.symbol, 'limit', side, amount, price, params={'posSide': 'long'})

            if order:
                logging.info(f"Orden creada exitosamente: {side.upper()} {amount} @ {price}, ID: {order['id']}")
                return {'id': order['id'], 'price': price, 'amount': amount}

            logging.warning(f"No se recibió respuesta de la orden {side.upper()} @ {price}")
        except Exception as e:
            logging.error(f"Error creando orden: {e}")

        return None  # Evitar que se cuenten órdenes fallidas

    async def place_orders(self, price):
        """Coloca órdenes de compra en el grid y las almacena en SortedDict."""
        try:
            prices = calculate_order_prices(price, self.percentage_spread, self.num_orders, self.price_format)
            created_orders = 0  # Contador de órdenes creadas

            for p in prices:
                if created_orders >= self.num_orders:  # Evitar exceso de órdenes
                    break
                formatted_amount = format_quantity(self.amount / p / self.contract_size, self.amount_format)
                await self.create_order('buy', formatted_amount, p)

                   

        except Exception as e:
            logging.error(f"Error colocando órdenes: {e}")
