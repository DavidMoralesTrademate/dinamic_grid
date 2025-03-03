import asyncio
import logging
from bot.helpers import calculate_order_prices, format_quantity
from sortedcontainers import SortedDict

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
        self.half = self.num_orders // 2

        self.total_buys_filled = 0
        self.total_sells_filled = 0

        self._rebalance_lock = asyncio.Lock()


    async def check_orders(self):
        reconnect_attempts = 0
        while True:
            try:
                self.print_active_orders()
                orders = await self.exchange.watch_orders(self.symbol)
                if not orders:
                    continue
                for o in orders:
                    await self.process_order(o)
                reconnect_attempts = 0
            except Exception as e:
                reconnect_attempts += 1
                wait_time = min(2 ** reconnect_attempts, 60)
                logging.error(f"Error en check_orders ({reconnect_attempts} intento): {e}")
                logging.info(f"Reintentando en {wait_time} segundos...")
                await asyncio.sleep(wait_time)

    async def process_order(self, order):
        try:
            # Si se llenó completamente
            if order.get('filled') == order.get('amount'):
                side = order.get('side')
                if side == 'buy':
                    self.total_buys_filled += 1
                else:
                    self.total_sells_filled += 1

                side_counter = 'sell' if side == 'buy' else 'buy'
                spread_multiplier = (1 + self.percentage_spread) if side_counter == 'sell' else (1 - self.percentage_spread)
                # Por seguridad, si no hay un price, evita multiplicar None
                price = order.get('price')
                if price is not None:
                    target_price = price * spread_multiplier
                    await self.create_order(side_counter, order['amount'], target_price)
                else:
                    logging.warning(f"No se crea la contraria. La orden {order['id']} no tiene price.")
        except Exception as e:
            logging.error(f"Error procesando orden: {e}")

    async def create_order(self, side, amount, price):
        try:
            params = {'posSide': 'long'}  # si usas Hedge Mode
            order = await self.exchange.create_order(
                self.symbol, 'limit', side, amount, price, params=params
            )
            if order:
                logging.info(f"Orden creada: {side.upper()} {amount} @ {price}, ID={order['id']}")
                return order
            else:
                logging.warning(f"No se recibió respuesta en create_order: {side.upper()} {amount} @ {price}")
        except Exception as e:
            logging.error(f"Error creando orden: {e}")
        return None

    async def place_orders(self, price):
        try:
            prices = calculate_order_prices(
                price, 
                self.percentage_spread, 
                self.num_orders, 
                self.price_format
            )
            created_orders = 0
            for p in prices:
                if created_orders >= self.num_orders:
                    break
                formatted_amount = format_quantity(self.amount / p / self.contract_size, self.amount_format)
                await self.create_order('buy', formatted_amount, p)
                created_orders += 1
        except Exception as e:
            logging.error(f"Error colocando órdenes: {e}")

    def print_active_orders(self):
        print(f"\n=== Numero de Match: {self.total_sells_filled}, Match profit: {self.total_sells_filled * (self.amount*self.percentage_spread) } ===")

        print(f"maximo de ordenes de venta: {self.total_buys_filled - self.total_sells_filled}")

        print("=== Fin de recuento ===\n")


    async def rebalance_grid(self):
        async with self._rebalance_lock:
            try:
                if self.total_buys_filled - self.total_sells_filled > self.half:
                    print(f"\n=== NECESITAMOS REVALANCEAR ===")

                    print(f"NECESITAMOS REVALANCEAR")
                    
                    print("=== NECESITAMOS REVALANCEAR ===\n")
                    return
                else: return
                
                # buy_orders = [o for o in open_orders if o['side'] == 'buy']
                # sell_orders = [o for o in open_orders if o['side'] == 'sell']

                # num_buy_orders = len(buy_orders)
                # num_sell_orders = len(sell_orders)

                # net_pos = self.total_buys_filled - self.total_sells_filled
                # max_sells_allowed = max(net_pos, 0)

                # # Determinamos cuántas SELL queremos en total
                # # Ejemplo 50:50:
                # half = self.num_orders // 2
                # desired_sell = min(half, max_sells_allowed)
                # desired_buy = self.num_orders - desired_sell

                # logging.info(f"[Rebalance] net_pos={net_pos}, buys_open={num_buy_orders}, sells_open={num_sell_orders}")
                # logging.info(f"[Rebalance] desired_buy={desired_buy}, desired_sell={desired_sell}")
                # logging.info(f"[Rebalance] num_buy_orders={self.total_buys_filled}, num_sell_orders={self.total_sells_filled}, num_will_orders_sell={net_pos}")

                # # Ajustar SELL al desired_sell
                # if num_sell_orders > desired_sell:
                #     print('ya podemos empezar a cancelar')
                #     # Cancelar las que sobran
                #     excess = num_sell_orders - desired_sell
                #     print('el exeso es ', excess)
                #     # Criterio: cancelar las + lejanas del precio ejecutado
                #     # (puedes cambiar a 'reverse=True' si quieres cancelar las + caras primero)
                    
                #     sell_orders_sorted = sorted(
                #         sell_orders, 
                #         key=lambda o: abs(o['price']),
                #         reverse=True
                #     )

                #     print('ordenadas las ordenes de venta ', sell_orders_sorted)
                #     for i in range(excess):
                #         if i < len(sell_orders_sorted):
                #             to_cancel = sell_orders_sorted[i]
                #             try:
                #                 await self.exchange.cancel_order(to_cancel['id'], self.symbol)
                #                 logging.info(f"[Rebalance] Cancelada SELL {to_cancel['id']} @ {to_cancel['price']}")
                #             except Exception as e:
                #                 logging.error(f"Error cancelando SELL {to_cancel['id']}: {e}")

                    
                # elif num_sell_orders < desired_sell:
                #     # Falta crear SELL
                #     missing = desired_sell - num_sell_orders
                #     current_price = executed_order['price']
                #     for i in range(missing):
                #         new_sell_price = current_price * (1 + self.percentage_spread*(i+1))
                #         amount = executed_order['amount']
                #         created = await self.create_order('sell', amount, new_sell_price)
                #         if created:
                #             logging.info(f"[Rebalance] SELL creada @ {new_sell_price} para completar {desired_sell}")

                # # Ajustar BUY al desired_buy (luego de modificar SELL)
                # open_orders = await self.exchange.fetch_open_orders(self.symbol)
                # buy_orders = [o for o in open_orders if o['side'] == 'buy']
                # sell_orders = [o for o in open_orders if o['side'] == 'sell']
                # num_buy_orders = len(buy_orders)
                # num_sell_orders = len(sell_orders)

                # if num_buy_orders > desired_buy:
                #     # Cancelar las que sobran
                #     excess = num_buy_orders - desired_buy
                #     current_price = executed_order['price']
                #     buy_orders_sorted = sorted(
                #         buy_orders,
                #         key=lambda o: abs(o['price'] - current_price),
                #         reverse=True
                #     )
                #     for i in range(excess):
                #         if i < len(buy_orders_sorted):
                #             to_cancel = buy_orders_sorted[i]
                #             try:
                #                 await self.exchange.cancel_order(to_cancel['id'], self.symbol)
                #                 logging.info(f"[Rebalance] Cancelada BUY {to_cancel['id']} @ {to_cancel['price']}")
                #             except Exception as e:
                #                 logging.error(f"Error cancelando BUY {to_cancel['id']}: {e}")
                # elif num_buy_orders < desired_buy:
                #     # Falta crear BUY
                #     missing = desired_buy - num_buy_orders
                #     current_price = executed_order['price']
                #     for i in range(missing):
                #         new_buy_price = current_price * (1 - self.percentage_spread*(i+1))
                #         amount = executed_order['amount']
                #         created = await self.create_order('buy', amount, new_buy_price)
                #         if created:
                #             logging.info(f"[Rebalance] BUY creada @ {new_buy_price} para completar {desired_buy}")

                logging.info("[Rebalance] Finalizado el rebalance.")
            except Exception as e:
                logging.error(f"Error en el rebalanceo de la grid: {e}")
