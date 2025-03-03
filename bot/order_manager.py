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
        self.order_counter = 0  # Contador para client_order_id

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
            logging.info(f"Procesando orden ejecutada: {self.active_orders}")

            if order['filled'] == order['amount']:
                side = 'sell' if order['side'] == 'buy' else 'buy'
                spread_multiplier = 1 + self.percentage_spread if side == 'sell' else 1 - self.percentage_spread
                target_price = order['price'] * spread_multiplier

                # Buscar el client_order_id correspondiente al precio ejecutado
                client_order_id = next((key for key, val in self.active_orders.items() if val[2] == order['price']), None)

                if client_order_id:
                    self.active_orders.pop(client_order_id, None)

                # Crear la nueva orden contraria y agregarla al SortedDict con un nuevo client_order_id
                new_order = await self.create_order(side, order['amount'], target_price)
                if new_order:
                    new_client_order_id = f"grid_{self.order_counter:04d}_{side}"
                    self.order_counter += 1
                    self.active_orders[new_client_order_id] = (side, order['amount'], new_order['price'], new_order['id'])

        except Exception as e:
            logging.error(f"Error procesando orden: {e}")

    async def create_order(self, side, amount, price):
        """Crea una nueva orden de compra o venta con un client order ID."""
        try:
            client_order_id = f"grid_{self.order_counter:04d}_{side}"  # ID único
            self.order_counter += 1  # Incrementar contador

            params = {'clOrdID': client_order_id, 'posSide': 'long'}  # Para OKX u otros exchanges compatibles

            logging.info(f"Intentando crear orden: {side.upper()} {amount} @ {price} (ID: {client_order_id})")

            order = await self.exchange.create_order(self.symbol, 'limit', side, amount, price, params=params)

            if order:
                logging.info(f"Orden creada exitosamente: {side.upper()} {amount} @ {price}, ID: {order['id']}")
                return {'id': order['id'], 'price': price, 'amount': amount, 'client_order_id': client_order_id}

        except Exception as e:
            logging.error(f"Error creando orden: {e}")

        return None

    async def place_orders(self, price):
        """Coloca órdenes de compra en el grid y las almacena en SortedDict."""
        try:
            prices = calculate_order_prices(price, self.percentage_spread, self.num_orders, self.price_format)
            created_orders = 0  # Contador de órdenes creadas

            for p in prices:
                if created_orders >= self.num_orders:  # Evitar exceso de órdenes
                    break

                formatted_amount = format_quantity(self.amount / p / self.contract_size, self.amount_format)

                # Verificar si ya existe una orden en ese precio
                if not any(val[2] == p for val in self.active_orders.values()):
                    new_order = await self.create_order('buy', formatted_amount, p)

                    if new_order:  # Solo contar si la orden se creó exitosamente
                        created_orders += 1
                        self.active_orders[new_order['client_order_id']] = ('buy', formatted_amount, new_order['price'], new_order['id'])

        except Exception as e:
            logging.error(f"Error colocando órdenes: {e}")
