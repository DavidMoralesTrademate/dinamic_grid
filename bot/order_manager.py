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

    async def check_orders(self):
        """Monitorea el estado de las órdenes en tiempo real con reconexión inteligente."""
        reconnect_attempts = 0
        while True:
            try:
                orders = await self.exchange.watch_orders(self.symbol)
                if not orders:
                    continue
                for order in orders:
                    # Procesar cada orden de forma concurrente.
                    asyncio.create_task(self.process_order(order))
                reconnect_attempts = 0
            except Exception as e:
                reconnect_attempts += 1
                wait_time = min(2 ** reconnect_attempts, 60)
                logging.error(f"Error en check_orders ({reconnect_attempts} intento): {e}")
                logging.info(f"Reintentando en {wait_time} segundos...")
                await asyncio.sleep(wait_time)

    async def process_order(self, order):
        """Procesa una orden ejecutada, coloca la orden contraria y rebalancea la grid."""
        try:
            if order['filled'] == order['amount']:
                # Colocar orden contraria: si se llenó una orden de compra, se coloca la de venta, y viceversa.
                side_counter = 'sell' if order['side'] == 'buy' else 'buy'
                spread_multiplier = 1 + self.percentage_spread if side_counter == 'sell' else 1 - self.percentage_spread
                target_price = order['price'] * spread_multiplier
                await self.create_order(side_counter, order['amount'], target_price)
                
                # Rebalancear la grid de forma dinámica.
                await self.rebalance_grid(order)
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

    async def rebalance_grid(self, executed_order):
        """
        Rebalancea la grid dinámicamente tras que una orden se ejecute por completo.
        
        - Si la orden ejecutada es de compra (mercado bajista):
            * Cancela órdenes de compra con precio mayor o igual al precio ejecutado.
            * Consulta cuántas órdenes de compra quedan activas y crea solo las que faltan,
              colocándolas por debajo del precio más bajo actual.
        
        - Si la orden ejecutada es de venta (mercado alcista):
            * Cancela órdenes de venta con precio menor o igual al precio ejecutado.
            * Consulta cuántas órdenes de venta quedan activas y crea solo las que faltan,
              colocándolas por encima del precio más alto actual.
        """
        try:
            # Obtener órdenes abiertas actuales.
            open_orders = await self.exchange.fetch_open_orders(self.symbol)
            if executed_order['side'] == 'buy':
                # Orden de compra ejecutada: se asume que el precio bajó.
                new_base = executed_order['price']
                # Cancelar órdenes de compra que estén por encima o iguales a new_base.
                buy_orders = [o for o in open_orders if o['side'] == 'buy']
                for order in buy_orders:
                    if order['price'] >= new_base:
                        try:
                            await self.exchange.cancel_order(order['id'], self.symbol)
                            logging.info(f"Cancelada orden de compra en {order['price']} fuera del nuevo grid.")
                        except Exception as cancel_error:
                            logging.error(f"Error cancelando orden de compra {order['id']}: {cancel_error}")
                # Actualizar órdenes abiertas.
                open_orders = await self.exchange.fetch_open_orders(self.symbol)
                buy_orders = [o for o in open_orders if o['side'] == 'buy']
                current_buy_count = len(buy_orders)
                missing_buy = self.num_orders - current_buy_count
                if missing_buy > 0:
                    # Usar el precio más bajo de las órdenes de compra actuales o new_base si no hay.
                    lowest_buy = min([o['price'] for o in buy_orders]) if buy_orders else new_base
                    # Crear solo las órdenes que falten.
                    for i in range(1, missing_buy + 1):
                        new_price = lowest_buy - i * self.percentage_spread
                        formatted_amount = format_quantity(self.amount / new_price / self.contract_size, self.amount_format)
                        await self.create_order('buy', formatted_amount, new_price)
                        logging.info(f"Nueva orden de compra colocada en {new_price} para rebalancear grid.")
            elif executed_order['side'] == 'sell':
                # Orden de venta ejecutada: se asume que el precio subió.
                new_base = executed_order['price']
                # Cancelar órdenes de venta que estén por debajo o iguales a new_base.
                sell_orders = [o for o in open_orders if o['side'] == 'sell']
                for order in sell_orders:
                    if order['price'] <= new_base:
                        try:
                            await self.exchange.cancel_order(order['id'], self.symbol)
                            logging.info(f"Cancelada orden de venta en {order['price']} fuera del nuevo grid.")
                        except Exception as cancel_error:
                            logging.error(f"Error cancelando orden de venta {order['id']}: {cancel_error}")
                # Actualizar órdenes abiertas.
                open_orders = await self.exchange.fetch_open_orders(self.symbol)
                sell_orders = [o for o in open_orders if o['side'] == 'sell']
                current_sell_count = len(sell_orders)
                missing_sell = self.num_orders - current_sell_count
                if missing_sell > 0:
                    highest_sell = max([o['price'] for o in sell_orders]) if sell_orders else new_base
                    for i in range(1, missing_sell + 1):
                        new_price = highest_sell + i * self.percentage_spread
                        formatted_amount = format_quantity(self.amount / new_price / self.contract_size, self.amount_format)
                        await self.create_order('sell', formatted_amount, new_price)
                        logging.info(f"Nueva orden de venta colocada en {new_price} para rebalancear grid.")
        except Exception as e:
            logging.error(f"Error en el rebalanceo de la grid: {e}")
