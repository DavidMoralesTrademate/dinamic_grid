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
        """
        Procesa una orden ejecutada y coloca una orden contraria. Además, 
        invoca el rebalanceo de la grid cuando la orden se ejecuta completamente.
        """
        try:
            if order['filled'] == order['amount']:
                side = 'sell' if order['side'] == 'buy' else 'buy'
                spread_multiplier = 1 + self.percentage_spread if side == 'sell' else 1 - self.percentage_spread
                target_price = order['price'] * spread_multiplier

                # Crear la orden contraria correspondiente.
                new_order = await self.create_order(side, order['amount'], target_price)

                # Rebalancear la grid de forma dinámica.
                await self.rebalance_grid(order)

        except Exception as e:
            logging.error(f"Error procesando orden: {e}")

    async def create_order(self, side, amount, price):
        """
        Crea una nueva orden de compra o venta y asegura que no se duplique.
        """
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

        return None  # Evitar que se cuenten órdenes fallidas

    async def place_orders(self, price):
        """
        Coloca órdenes de compra en el grid inicial.
        """
        try:
            prices = calculate_order_prices(price, self.percentage_spread, self.num_orders, self.price_format)
            created_orders = 0  # Contador de órdenes creadas

            for p in prices:
                if created_orders >= self.num_orders:  # Evitar exceso de órdenes
                    break
                formatted_amount = format_quantity(self.amount / p / self.contract_size, self.amount_format)
                await self.create_order('buy', formatted_amount, p)
                created_orders += 1

        except Exception as e:
            logging.error(f"Error colocando órdenes: {e}")

    async def rebalance_grid(self, executed_order):
        """
        Rebalancea la grid de órdenes de forma dinámica tras la ejecución completa de una orden.
        
        Para una orden de compra ejecutada:
          - Se determina cuántas órdenes de compra faltan para llegar a 'num_orders'.
          - Se cancelan las órdenes de venta de mayor precio (que ya se generaron como contrapartida)
            para liberar espacio en la grid.
          - Se colocan nuevas órdenes de compra por debajo del precio más bajo actual.
        
        Para una orden de venta ejecutada se realiza el proceso inverso.
        """
        try:
            # Obtener las órdenes abiertas actuales
            orders = await self.exchange.fetch_open_orders(self.symbol)
            # Separar órdenes por lado
            buy_orders = [o for o in orders if o['side'] == 'buy']
            sell_orders = [o for o in orders if o['side'] == 'sell']

            if executed_order['side'] == 'buy':
                # La orden de compra se ejecutó: se asume que el precio bajó.
                missing_buy_orders = self.num_orders - len(buy_orders)
                if missing_buy_orders > 0:
                    # Cancelar las órdenes de venta de mayor precio para liberar espacio en la grid
                    sell_orders_sorted = sorted(sell_orders, key=lambda o: o['price'], reverse=True)
                    for i in range(min(missing_buy_orders, len(sell_orders_sorted))):
                        order_to_cancel = sell_orders_sorted[i]
                        try:
                            await self.exchange.cancel_order(order_to_cancel['id'], self.symbol)
                            logging.info(f"Cancelada orden de venta en {order_to_cancel['price']} para rebalancear grid.")
                        except Exception as cancel_error:
                            logging.error(f"Error al cancelar orden {order_to_cancel['id']}: {cancel_error}")

                    # Colocar nuevas órdenes de compra por debajo de la orden de compra más baja
                    if buy_orders:
                        lowest_buy_price = min(o['price'] for o in buy_orders)
                    else:
                        lowest_buy_price = executed_order['price']
                    for i in range(missing_buy_orders):
                        new_price = lowest_buy_price - (i + 1) * self.percentage_spread
                        formatted_amount = format_quantity(
                            self.amount / new_price / self.contract_size, self.amount_format
                        )
                        await self.create_order('buy', formatted_amount, new_price)
                        logging.info(f"Nueva orden de compra colocada en {new_price} para rebalancear grid.")

            elif executed_order['side'] == 'sell':
                # La orden de venta se ejecutó: se asume que el precio subió.
                missing_sell_orders = self.num_orders - len(sell_orders)
                if missing_sell_orders > 0:
                    # Cancelar las órdenes de compra de menor precio para liberar espacio en la grid
                    buy_orders_sorted = sorted(buy_orders, key=lambda o: o['price'])
                    for i in range(min(missing_sell_orders, len(buy_orders_sorted))):
                        order_to_cancel = buy_orders_sorted[i]
                        try:
                            await self.exchange.cancel_order(order_to_cancel['id'], self.symbol)
                            logging.info(f"Cancelada orden de compra en {order_to_cancel['price']} para rebalancear grid.")
                        except Exception as cancel_error:
                            logging.error(f"Error al cancelar orden {order_to_cancel['id']}: {cancel_error}")

                    # Colocar nuevas órdenes de venta por encima de la orden de venta más alta
                    if sell_orders:
                        highest_sell_price = max(o['price'] for o in sell_orders)
                    else:
                        highest_sell_price = executed_order['price']
                    for i in range(missing_sell_orders):
                        new_price = highest_sell_price + (i + 1) * self.percentage_spread
                        formatted_amount = format_quantity(
                            self.amount / new_price / self.contract_size, self.amount_format
                        )
                        await self.create_order('sell', formatted_amount, new_price)
                        logging.info(f"Nueva orden de venta colocada en {new_price} para rebalancear grid.")

        except Exception as e:
            logging.error(f"Error en rebalanceo de grid: {e}")
