import asyncio
import logging
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
        # Lock para evitar rebalanceos concurrentes
        self._rebalance_lock = asyncio.Lock()

    async def check_orders(self):
        """Monitorea el estado de las órdenes en tiempo real con reconexión inteligente."""
        reconnect_attempts = 0
        while True:
            try:
                orders = await self.exchange.watch_orders(self.symbol)
                if not orders:
                    continue
                for order in orders:
                    # Procesa cada orden de forma concurrente.
                    asyncio.create_task(self.process_order(order))
                reconnect_attempts = 0
            except Exception as e:
                reconnect_attempts += 1
                wait_time = min(2 ** reconnect_attempts, 60)
                logging.error(f"Error en check_orders ({reconnect_attempts} intento): {e}")
                logging.info(f"Reintentando en {wait_time} segundos...")
                await asyncio.sleep(wait_time)

    async def process_order(self, order):
        """Procesa una orden ejecutada, coloca la orden contraria y llama al rebalanceo."""
        try:
            if order['filled'] == order['amount']:
                # Colocar la orden contraria: si se llenó una orden de compra, se coloca la de venta, y viceversa.
                side_counter = 'sell' if order['side'] == 'buy' else 'buy'
                spread_multiplier = 1 + self.percentage_spread if side_counter == 'sell' else 1 - self.percentage_spread
                target_price = order['price'] * spread_multiplier
                await self.create_order(side_counter, order['amount'], target_price)
                
                # Llamar al rebalanceo dinámico.
                await self.rebalance_grid()
        except Exception as e:
            logging.error(f"Error procesando orden: {e}")

    async def create_order(self, side, amount, price):
        """Crea una nueva orden de compra o venta."""
        try:
            order = await self.exchange.create_order(
                self.symbol, 'limit', side, amount, price, params={'posSide': 'long'}
            )
            if order:
                logging.info(f"Orden creada exitosamente: {side.upper()} {amount} @ {price}, ID: {order['id']}")
                return {'id': order['id'], 'price': price, 'amount': amount}
            logging.warning(f"No se recibió respuesta de la orden {side.upper()} @ {price}")
        except Exception as e:
            logging.error(f"Error creando orden: {e}")
        return None

    async def place_orders(self, price):
        """Coloca órdenes de compra en la grid estática inicial."""
        try:
            prices = calculate_order_prices(price, self.percentage_spread, self.num_orders, self.price_format)
            created_orders = 0
            for p in prices:
                if created_orders >= self.num_orders:
                    break
                formatted_amount = format_quantity(self.amount / p / self.contract_size, self.amount_format)
                await self.create_order('buy', formatted_amount, p)
                created_orders += 1
        except Exception as e:
            logging.error(f"Error colocando órdenes: {e}")

    async def rebalance_grid(self):
        """
        Rebalancea la grid dinámicamente cuando una orden se ejecuta completamente.
        
        Para el lado de compra:
          - Se cancelan las órdenes de compra que tengan precio mayor o igual que el precio ejecutado.
          - Se consulta cuántas órdenes de compra quedan activas y se crean únicamente las que falten,
            ubicándolas por debajo del precio más bajo actual, evitando duplicados.
        
        Para el lado de venta:
          - Se cancelan las órdenes de venta con precio menor o igual que el precio ejecutado.
          - No se crean nuevas órdenes de venta aquí para evitar errores de posición;
            la orden contraria ya se coloca en process_order.
        """
        async with self._rebalance_lock:
            try:
                open_orders = await self.exchange.fetch_open_orders(self.symbol)
                
                print(open_orders)
                
                
            except Exception as e:
                logging.error(f"Error en el rebalanceo de la grid: {e}")
