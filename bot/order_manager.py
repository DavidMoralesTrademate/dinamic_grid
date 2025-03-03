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

        # Para rastrear cuántas órdenes de compra/venta se han llenado completamente
        self.total_buys_filled = 0
        self.total_sells_filled = 0

        # Lock para rebalanceo
        self._rebalance_lock = asyncio.Lock()

    async def check_orders(self):
        """
        Monitorea el estado de las órdenes en tiempo real.
        Procesamos cada orden secuencialmente (con 'await') para evitar problemas
        de "got Future attached to a different loop".
        """
        reconnect_attempts = 0
        while True:
            try:
                orders = await self.exchange.watch_orders(self.symbol)
                if not orders:
                    continue
                for order in orders:
                    # Procesar secuencialmente en este mismo loop:
                    await self.process_order(order)
                reconnect_attempts = 0
            except Exception as e:
                reconnect_attempts += 1
                wait_time = min(2 ** reconnect_attempts, 60)
                logging.error(f"Error en check_orders ({reconnect_attempts} intento): {e}")
                logging.info(f"Reintentando en {wait_time} segundos...")
                await asyncio.sleep(wait_time)

    async def process_order(self, order):
        """
        Procesa una orden ejecutada y, si se llena, coloca la orden contraria
        y luego hace el rebalance de la grid.
        """
        try:
            # A veces CCXT puede dar orden con partial fill, etc.
            # Verificamos si se llenó completamente:
            if order['filled'] == order['amount']:
                # Actualizar contadores
                if order['side'] == 'buy':
                    self.total_buys_filled += 1
                else:
                    self.total_sells_filled += 1

                # Colocar orden contraria
                side_counter = 'sell' if order['side'] == 'buy' else 'buy'
                spread_multiplier = 1 + self.percentage_spread if side_counter == 'sell' else 1 - self.percentage_spread
                target_price = order['price'] * spread_multiplier
                await self.create_order(side_counter, order['amount'], target_price)

                # Rebalance
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
        return None

    async def place_orders(self, price):
        """
        Coloca órdenes de compra en el grid inicial.
        """
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
        Mantiene siempre self.num_orders órdenes activas (compras + ventas),
        sin exceder las ventas que la posición neta respalda (net_pos).

        Algoritmo simple:
         1. Calcular net_pos = total_buys_filled - total_sells_filled
         2. max_sells_allowed = max(net_pos, 0)
         3. Idealmente 50:50 entre BUY y SELL => buy_target = sell_target = self.num_orders // 2
            pero sell_target no puede pasar de max_sells_allowed.
         4. Ajustar abriendo/cerrando las órdenes necesarias.
        """
        async with self._rebalance_lock:
            try:
                open_orders = await self.exchange.fetch_open_orders(self.symbol)
                buy_orders = [o for o in open_orders if o['side'] == 'buy']
                sell_orders = [o for o in open_orders if o['side'] == 'sell']

                num_buy_orders = len(buy_orders)
                num_sell_orders = len(sell_orders)
                total_open = num_buy_orders + num_sell_orders

                net_pos = self.total_buys_filled - self.total_sells_filled
                max_sells_allowed = max(net_pos, 0)

                # Determinamos cuántas SELL queremos en total
                # Ejemplo 50:50:
                half = self.num_orders // 2
                desired_sell = min(half, max_sells_allowed)
                desired_buy = self.num_orders - desired_sell

                logging.info(f"[Rebalance] net_pos={net_pos}, buys_open={num_buy_orders}, sells_open={num_sell_orders}")
                logging.info(f"[Rebalance] desired_buy={desired_buy}, desired_sell={desired_sell}")

                # Ajustar SELL al desired_sell
                if num_sell_orders > desired_sell:
                    # Cancelar las que sobran
                    excess = num_sell_orders - desired_sell
                    # Criterio: cancelar las + lejanas del precio ejecutado
                    # (puedes cambiar a 'reverse=True' si quieres cancelar las + caras primero)
                    current_price = executed_order['price']
                    sell_orders_sorted = sorted(
                        sell_orders, 
                        key=lambda o: abs(o['price'] - current_price),
                        reverse=True
                    )
                    for i in range(excess):
                        if i < len(sell_orders_sorted):
                            to_cancel = sell_orders_sorted[i]
                            try:
                                await self.exchange.cancel_order(to_cancel['id'], self.symbol)
                                logging.info(f"[Rebalance] Cancelada SELL {to_cancel['id']} @ {to_cancel['price']}")
                            except Exception as e:
                                logging.error(f"Error cancelando SELL {to_cancel['id']}: {e}")
                elif num_sell_orders < desired_sell:
                    # Falta crear SELL
                    missing = desired_sell - num_sell_orders
                    current_price = executed_order['price']
                    for i in range(missing):
                        new_sell_price = current_price * (1 + self.percentage_spread*(i+1))
                        amount = executed_order['amount']
                        created = await self.create_order('sell', amount, new_sell_price)
                        if created:
                            logging.info(f"[Rebalance] SELL creada @ {new_sell_price} para completar {desired_sell}")

                # Ajustar BUY al desired_buy (luego de modificar SELL)
                open_orders = await self.exchange.fetch_open_orders(self.symbol)
                buy_orders = [o for o in open_orders if o['side'] == 'buy']
                sell_orders = [o for o in open_orders if o['side'] == 'sell']
                num_buy_orders = len(buy_orders)
                num_sell_orders = len(sell_orders)

                if num_buy_orders > desired_buy:
                    # Cancelar las que sobran
                    excess = num_buy_orders - desired_buy
                    current_price = executed_order['price']
                    buy_orders_sorted = sorted(
                        buy_orders,
                        key=lambda o: abs(o['price'] - current_price),
                        reverse=True
                    )
                    for i in range(excess):
                        if i < len(buy_orders_sorted):
                            to_cancel = buy_orders_sorted[i]
                            try:
                                await self.exchange.cancel_order(to_cancel['id'], self.symbol)
                                logging.info(f"[Rebalance] Cancelada BUY {to_cancel['id']} @ {to_cancel['price']}")
                            except Exception as e:
                                logging.error(f"Error cancelando BUY {to_cancel['id']}: {e}")
                elif num_buy_orders < desired_buy:
                    # Falta crear BUY
                    missing = desired_buy - num_buy_orders
                    current_price = executed_order['price']
                    for i in range(missing):
                        new_buy_price = current_price * (1 - self.percentage_spread*(i+1))
                        amount = executed_order['amount']
                        created = await self.create_order('buy', amount, new_buy_price)
                        if created:
                            logging.info(f"[Rebalance] BUY creada @ {new_buy_price} para completar {desired_buy}")

                logging.info("[Rebalance] Finalizado el rebalance.")
            except Exception as e:
                logging.error(f"Error en el rebalanceo de la grid: {e}")
