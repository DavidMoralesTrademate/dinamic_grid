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

        self.active_orders = SortedDict()  # {client_order_id: (side, cantidad, precio, id_orden)}

    async def check_orders(self):
        """Monitorea órdenes en tiempo real sin bloquear el loop."""
        reconnect_attempts = 0
        while True:
            try:
                orders = await self.exchange.watch_orders(self.symbol)
                if not orders:
                    continue
                for order in orders:
                    asyncio.create_task(self.process_order(order))  # Se procesa en paralelo
                reconnect_attempts = 0  
            except Exception as e:
                reconnect_attempts += 1
                wait_time = min(2 ** reconnect_attempts, 60)
                logging.error(f"Error en check_orders ({reconnect_attempts} intento): {e}")
                logging.info(f"Reintentando en {wait_time} segundos...")
                await asyncio.sleep(wait_time)

    async def process_order(self, order):
        """Procesa una orden ejecutada y coloca la orden contraria con el mismo `client_order_id`."""
        try:
            logging.info(f"Procesando orden ejecutada: {self.active_orders}")

            # Buscamos la orden en `active_orders`
            client_id = None
            for key, value in self.active_orders.items():
                if value[3] == order['id']:  # Buscamos por el ID de la orden en el exchange
                    client_id = key
                    break

            if not client_id:
                logging.warning(f"Orden ejecutada no encontrada en active_orders: {order['id']}")
                

            side, cantidad, precio, _ = self.active_orders.pop(client_id)

            # Generar la orden contraria con el mismo grid_id
            grid_id = client_id.split('_')[1]  # Extraer el número de grid
            new_side = 'sell' if side == 'buy' else 'buy'
            new_price = precio * (1 + self.percentage_spread if new_side == 'sell' else 1 - self.percentage_spread)
            new_client_id = f"grid_{grid_id}_{new_side}"

            new_order = await self.create_order(new_side, cantidad, new_price, new_client_id)
            if new_order:
                self.active_orders[new_client_id] = (new_side, cantidad, new_price, new_order['id'])

        except Exception as e:
            logging.error(f"Error procesando orden: {e}")

    async def create_order(self, side, amount, price, client_order_id):
        """Crea una nueva orden con `client_order_id`."""
        try:
            logging.info(f"Intentando crear orden: {side.upper()} {amount} @ {price} con ID {client_order_id}")

            order = await self.exchange.create_order(
                self.symbol, 'limit', side, amount, price,
                params={'posSide': 'long', 'clOrdID': client_order_id}
            )

            if order:
                logging.info(f"Orden creada: {side.upper()} {amount} @ {price}, ID: {order['id']}")
                return {'id': order['id'], 'price': price, 'amount': amount}

            logging.warning(f"No se recibió respuesta de la orden {side.upper()} @ {price}")
        except Exception as e:
            logging.error(f"Error creando orden: {e}")

        return None  

    async def place_orders(self, price):
        """Coloca órdenes iniciales y asigna `client_order_id`."""
        try:
            prices = calculate_order_prices(price, self.percentage_spread, self.num_orders, self.price_format)

            for i, p in enumerate(prices):
                formatted_amount = format_quantity(self.amount / p / self.contract_size, self.amount_format)

                client_order_id = f"grid_{i:04d}_buy"

                new_order = await self.create_order('buy', formatted_amount, p, client_order_id)

                if new_order:
                    self.active_orders[client_order_id] = ('buy', formatted_amount, p, new_order['id'])

        except Exception as e:
            logging.error(f"Error colocando órdenes: {e}")
