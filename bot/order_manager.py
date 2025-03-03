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

        self.total_buys_filled = 0
        self.total_sells_filled = 0

        self._rebalance_lock = asyncio.Lock()

        self.orders_by_id = {}
        self.orders_by_price = SortedDict()
    
    def _add_order_local(self, order):
        """
        Añade la orden a las estructuras locales, salvo que price=None.
        """
        oid = order['id']
        price = order['price']

        # NEW: check if price is None => no la insertamos
        if price is None:
            logging.debug(f"No se añade la orden {oid} al local, price=None.")
            return

        self.orders_by_id[oid] = order

        if price not in self.orders_by_price:
            self.orders_by_price[price] = set()
        self.orders_by_price[price].add(oid)

    def _remove_order_local(self, order):
        oid = order['id']
        price = order['price']
        if oid in self.orders_by_id:
            del self.orders_by_id[oid]
        # Si price is None, no estaba en el SortedDict
        if price is not None and price in self.orders_by_price:
            self.orders_by_price[price].discard(oid)
            if not self.orders_by_price[price]:
                del self.orders_by_price[price]

    def _update_local_orders(self, order):
        """
        Actualiza el estado local de la orden recibida:
         - Si está abierta o parcialmente llena, la guardamos.
         - Si está cerrada o cancelada, la removemos.
        """
        oid = order.get('id')
        status = order.get('status')
        price = order.get('price')

        if not oid:
            return

        # Revisar estado
        if status in ('open', 'partially_filled'):
            existing = self.orders_by_id.get(oid)
            # Si la orden existía y cambió de precio
            if existing:
                old_price = existing['price']
                # Si sale None en la nueva => no reordenamos
                if price is None:
                    # Mantenemos la info antigua pero actualizamos status
                    existing.update(order)
                    self.orders_by_id[oid] = existing
                else:
                    # Compara con old_price, si difiere, quitar del old y poner en new
                    if old_price != price:
                        # Quitar del old_price
                        if old_price is not None and old_price in self.orders_by_price:
                            self.orders_by_price[old_price].discard(oid)
                            if not self.orders_by_price[old_price]:
                                del self.orders_by_price[old_price]
                        # Actualizar la orden
                        existing.update(order)
                        # Añadir al nuevo price
                        if price not in self.orders_by_price:
                            self.orders_by_price[price] = set()
                        self.orders_by_price[price].add(oid)
                        self.orders_by_id[oid] = existing
                    else:
                        # mismo precio (o ambos None?), actualizamos
                        existing.update(order)
                        self.orders_by_id[oid] = existing
            else:
                # Orden nueva
                self._add_order_local(order)

        elif status in ('closed', 'canceled', 'filled'):
            self._remove_order_local(order)
        else:
            # Otros estados
            pass

    async def check_orders(self):
        reconnect_attempts = 0
        while True:
            try:
                self.print_active_orders()
                orders = await self.exchange.watch_orders(self.symbol)
                if not orders:
                    continue
                for o in orders:
                    self._update_local_orders(o)
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
                # Añadimos localmente. Podría carecer de 'price' si el exchange no lo manda
                self._add_order_local(order)
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
        print("\n=== Órdenes Activas ===")
        if not self.orders_by_id:
            print("No hay órdenes activas en orders_by_id.")
            return

        print(f"Total de órdenes activas: {len(self.orders_by_id)}")

        for price in self.orders_by_price.keys():
            order_ids = self.orders_by_price[price]
            print(f"Precio: {price}, Cant. órdenes: {len(order_ids)}")
            for oid in order_ids:
                od = self.orders_by_id.get(oid, {})
                side = od.get('side', '?')
                status = od.get('status', '?')
                amount = od.get('amount', '?')
                filled = od.get('filled', '?')
                print(f"   - ID={oid}, side={side}, status={status}, amount={amount}, filled={filled}")
        print("=== Fin de órdenes activas ===\n")



    # async def rebalance_grid(self):
    #     """
    #     Mantiene siempre self.num_orders órdenes activas (compras + ventas),
    #     sin exceder las ventas que la posición neta respalda (net_pos).

    #     Algoritmo simple:
    #      1. Calcular net_pos = total_buys_filled - total_sells_filled
    #      2. max_sells_allowed = max(net_pos, 0)
    #      3. Idealmente 50:50 entre BUY y SELL => buy_target = sell_target = self.num_orders // 2
    #         pero sell_target no puede pasar de max_sells_allowed.
    #      4. Ajustar abriendo/cerrando las órdenes necesarias.
    #     """
    #     async with self._rebalance_lock:
    #         try:
    #             open_orders = await self.exchange.fetch_open_orders(self.symbol)
    #             buy_orders = [o for o in open_orders if o['side'] == 'buy']
    #             sell_orders = [o for o in open_orders if o['side'] == 'sell']

    #             num_buy_orders = len(buy_orders)
    #             num_sell_orders = len(sell_orders)

    #             net_pos = self.total_buys_filled - self.total_sells_filled
    #             max_sells_allowed = max(net_pos, 0)

    #             # Determinamos cuántas SELL queremos en total
    #             # Ejemplo 50:50:
    #             half = self.num_orders // 2
    #             desired_sell = min(half, max_sells_allowed)
    #             desired_buy = self.num_orders - desired_sell

    #             logging.info(f"[Rebalance] net_pos={net_pos}, buys_open={num_buy_orders}, sells_open={num_sell_orders}")
    #             logging.info(f"[Rebalance] desired_buy={desired_buy}, desired_sell={desired_sell}")
    #             logging.info(f"[Rebalance] num_buy_orders={self.total_buys_filled}, num_sell_orders={self.total_sells_filled}, num_will_orders_sell={net_pos}")

    #             # Ajustar SELL al desired_sell
    #             if num_sell_orders > desired_sell:
    #                 print('ya podemos empezar a cancelar')
    #                 # Cancelar las que sobran
    #                 excess = num_sell_orders - desired_sell
    #                 print('el exeso es ', excess)
    #                 # Criterio: cancelar las + lejanas del precio ejecutado
    #                 # (puedes cambiar a 'reverse=True' si quieres cancelar las + caras primero)
                    
    #                 sell_orders_sorted = sorted(
    #                     sell_orders, 
    #                     key=lambda o: abs(o['price']),
    #                     reverse=True
    #                 )

    #                 print('ordenadas las ordenes de venta ', sell_orders_sorted)
    #                 for i in range(excess):
    #                     if i < len(sell_orders_sorted):
    #                         to_cancel = sell_orders_sorted[i]
    #                         try:
    #                             await self.exchange.cancel_order(to_cancel['id'], self.symbol)
    #                             logging.info(f"[Rebalance] Cancelada SELL {to_cancel['id']} @ {to_cancel['price']}")
    #                         except Exception as e:
    #                             logging.error(f"Error cancelando SELL {to_cancel['id']}: {e}")

                    
    #             # elif num_sell_orders < desired_sell:
    #             #     # Falta crear SELL
    #             #     missing = desired_sell - num_sell_orders
    #             #     current_price = executed_order['price']
    #             #     for i in range(missing):
    #             #         new_sell_price = current_price * (1 + self.percentage_spread*(i+1))
    #             #         amount = executed_order['amount']
    #             #         created = await self.create_order('sell', amount, new_sell_price)
    #             #         if created:
    #             #             logging.info(f"[Rebalance] SELL creada @ {new_sell_price} para completar {desired_sell}")

    #             # # Ajustar BUY al desired_buy (luego de modificar SELL)
    #             # open_orders = await self.exchange.fetch_open_orders(self.symbol)
    #             # buy_orders = [o for o in open_orders if o['side'] == 'buy']
    #             # sell_orders = [o for o in open_orders if o['side'] == 'sell']
    #             # num_buy_orders = len(buy_orders)
    #             # num_sell_orders = len(sell_orders)

    #             # if num_buy_orders > desired_buy:
    #             #     # Cancelar las que sobran
    #             #     excess = num_buy_orders - desired_buy
    #             #     current_price = executed_order['price']
    #             #     buy_orders_sorted = sorted(
    #             #         buy_orders,
    #             #         key=lambda o: abs(o['price'] - current_price),
    #             #         reverse=True
    #             #     )
    #             #     for i in range(excess):
    #             #         if i < len(buy_orders_sorted):
    #             #             to_cancel = buy_orders_sorted[i]
    #             #             try:
    #             #                 await self.exchange.cancel_order(to_cancel['id'], self.symbol)
    #             #                 logging.info(f"[Rebalance] Cancelada BUY {to_cancel['id']} @ {to_cancel['price']}")
    #             #             except Exception as e:
    #             #                 logging.error(f"Error cancelando BUY {to_cancel['id']}: {e}")
    #             # elif num_buy_orders < desired_buy:
    #             #     # Falta crear BUY
    #             #     missing = desired_buy - num_buy_orders
    #             #     current_price = executed_order['price']
    #             #     for i in range(missing):
    #             #         new_buy_price = current_price * (1 - self.percentage_spread*(i+1))
    #             #         amount = executed_order['amount']
    #             #         created = await self.create_order('buy', amount, new_buy_price)
    #             #         if created:
    #             #             logging.info(f"[Rebalance] BUY creada @ {new_buy_price} para completar {desired_buy}")

    #             logging.info("[Rebalance] Finalizado el rebalance.")
    #         except Exception as e:
    #             logging.error(f"Error en el rebalanceo de la grid: {e}")
