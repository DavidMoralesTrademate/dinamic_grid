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
        self.order_limit = 100  # Límite de órdenes abiertas permitidas

        self.active_orders = SortedDict()  # {precio: (side, cantidad, id_orden)}

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
            print(self.active_orders)
            if order['filled'] == order['amount']:
                side = 'sell' if order['side'] == 'buy' else 'buy'
                target_price = order['price'] * (1 + self.percentage_spread if side == 'sell' else 1 - self.percentage_spread)


                # Si era una compra ejecutada, la eliminamos del SortedDict
                if order['side'] == 'buy' and order['price'] in self.active_orders:
                    del self.active_orders[order['price']]
                
                # Crear la nueva orden contraria y agregarla al SortedDict como venta
                new_order = await self.create_order(side, order['amount'], target_price)
                if new_order:
                    self.active_orders[new_order['price']] = (side, order['amount'], new_order['id'])


        except Exception as e:
            logging.error(f"Error procesando orden: {e}")
    
    async def create_order(self, side, amount, price):
        """Crea una nueva orden de compra o venta y asegura que no se duplique."""
        try:
            logging.info(f"Intentando crear orden: {side.upper()} {amount} @ {price}")

            order = await self.exchange.create_order(self.symbol, 'limit', side, amount, price, params={'posSide': 'long'})

            if order:
                logging.info(f"Orden creada exitosamente: {side.upper()} {amount} @ {price}, ID: {order['id']}")
                return {'id': order['id'], 'price': price, 'amount': amount}
            else:
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
                new_order = await self.create_order('buy', formatted_amount, p)

                if new_order:  # Solo contar si la orden se creó exitosamente
                    created_orders += 1
                    self.active_orders[p] = ('buy', formatted_amount, new_order['id'])

        except Exception as e:
            logging.error(f"Error colocando órdenes: {e}")


