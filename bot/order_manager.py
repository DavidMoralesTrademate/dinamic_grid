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

        # Contadores de fills (ejecuciones totales)
        self.total_buys_filled = 0
        self.total_sells_filled = 0

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
        try:
            if order['filled'] == order['amount']:
                if order['side'] == 'buy':
                    self.total_buys_filled += 1
                else:
                    self.total_sells_filled += 1
                
                # Colocar la orden contraria
                side_counter = 'sell' if order['side'] == 'buy' else 'buy'
                spread_multiplier = 1 + self.percentage_spread if side_counter == 'sell' else 1 - self.percentage_spread
                target_price = order['price'] * spread_multiplier
                await self.create_order(side_counter, order['amount'], target_price)

                # Rebalancear la grid
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

    # async def rebalance_grid(self, executed_order):
    #     """
    #     Rebalancea la grid dinámicamente cuando una orden se ejecuta completamente.
        
    #     1. Calcula cuántas órdenes hay de compra y venta.
    #     2. Determina cuántas órdenes de venta máximo se permiten según la posición neta (net_pos).
    #     3. Cancela las órdenes de venta que excedan ese límite (si las hay).
    #     4. Si el total de órdenes abiertas excede self.num_orders, cancela las más alejadas del precio actual.
    #     5. Verifica la proporción BUY:SELL y la mantiene cerca de 50:50 (si net_pos lo permite).
    #     6. Si aún hay espacio y net_pos > 0, crea órdenes de venta adicionales (hasta un máximo).
    #     """
    #     async with self._rebalance_lock:
    #         try:
    #             # 0. Obtener las órdenes abiertas y la posición neta.
    #             open_orders = await self.exchange.fetch_open_orders(self.symbol)

    #             buy_orders = [o for o in open_orders if o['side'] == 'buy']
    #             sell_orders = [o for o in open_orders if o['side'] == 'sell']


                
    #             num_buy_orders = len(buy_orders)
    #             num_sell_orders = len(sell_orders)
    #             total_open = num_buy_orders + num_sell_orders

    #             net_pos = self.total_buys_filled - self.total_sells_filled  # compras llenadas - ventas llenadas

    #             print('-'*20)
    #             print(self.total_buys_filled, self.total_sells_filled)
    #             print(self.total_buys_filled - self.total_sells_filled)
    #             print('-'*20)

    #             max_sells_allowed = net_pos if net_pos > 0 else 0

            #     logging.info(f"Rebalance - net_pos={net_pos}, buys_open={num_buy_orders}, sells_open={num_sell_orders}, total_open={total_open}")
                
            #     # 1. Cancelar las órdenes de venta que excedan max_sells_allowed (si las hay).
            #     if num_sell_orders > max_sells_allowed:
            #         # Ejemplo: cancela las órdenes de venta con el precio más alto primero,
            #         # asumiendo que preferimos mantener ventas más cercanas al precio actual.
            #         sell_orders_sorted = sorted(sell_orders, key=lambda o: o['price'], reverse=True)
            #         excess = num_sell_orders - max_sells_allowed
            #         for i in range(excess):
            #             order_to_cancel = sell_orders_sorted[i]
            #             try:
            #                 await self.exchange.cancel_order(order_to_cancel['id'], self.symbol)
            #                 logging.info(f"Cancelada SELL {order_to_cancel['id']} @ {order_to_cancel['price']} (exceso).")
            #             except Exception as e:
            #                 logging.error(f"Error cancelando SELL {order_to_cancel['id']}: {e}")

            #     # 2. Volver a calcular el estado de órdenes tras las cancelaciones.
            #     open_orders = await self.exchange.fetch_open_orders(self.symbol)
            #     buy_orders = [o for o in open_orders if o['side'] == 'buy']
            #     sell_orders = [o for o in open_orders if o['side'] == 'sell']
            #     num_buy_orders = len(buy_orders)
            #     num_sell_orders = len(sell_orders)
            #     total_open = num_buy_orders + num_sell_orders

            #     # 3. Limitar total de órdenes a self.num_orders si excede.
            #     if total_open > self.num_orders:
            #         # Cancelar las órdenes más alejadas del precio actual hasta que total_open <= num_orders.
            #         # Obtén un precio de referencia (por ejemplo, el de la orden ejecutada).
            #         current_price = executed_order['price']

            #         # Función auxiliar para medir distancia desde el precio actual.
            #         def distance_from_price(o):
            #             return abs(o['price'] - current_price)

            #         # Ordenamos TODAS las órdenes por distancia, de mayor a menor.
            #         # La idea es cancelar primero las más lejanas.
            #         all_orders_sorted = sorted(open_orders, key=distance_from_price, reverse=True)

            #         # Cuántas órdenes tenemos de más
            #         to_cancel = total_open - self.num_orders

            #         for i in range(to_cancel):
            #             order_to_cancel = all_orders_sorted[i]
            #             try:
            #                 await self.exchange.cancel_order(order_to_cancel['id'], self.symbol)
            #                 logging.info(f"Cancelada {order_to_cancel['side'].upper()} {order_to_cancel['id']} @ {order_to_cancel['price']} (exceso total).")
            #             except Exception as e:
            #                 logging.error(f"Error cancelando orden {order_to_cancel['id']}: {e}")

            #         # Recalcular después de cancelar
            #         open_orders = await self.exchange.fetch_open_orders(self.symbol)
            #         buy_orders = [o for o in open_orders if o['side'] == 'buy']
            #         sell_orders = [o for o in open_orders if o['side'] == 'sell']
            #         num_buy_orders = len(buy_orders)
            #         num_sell_orders = len(sell_orders)
            #         total_open = num_buy_orders + num_sell_orders

            #     # 4. Verificar la proporción BUY:SELL (si net_pos > 0).
            #     #    Queremos estar cerca de 50:50 (por ejemplo, en el rango [40%, 60%]).
            #     if total_open > 0:
            #         ratio = num_buy_orders / total_open
            #         if ratio < 0.4:
            #             # Tenemos muy pocas BUY, o muchas SELL:
            #             # O bien cancelamos parte de las SELL, o añadimos BUY.
            #             # Pero si net_pos <= 0, añadir BUY no tiene sentido.
            #             # Ejemplo: Cancela parte de las SELL más lejanas para acercar el ratio.
            #             # (Siempre verificando que no caigamos por debajo de 0 SELL si net_pos>0).
                        
            #             # Cuántas sell deberíamos tener para ratio=0.5 => num_sell_desired = total_open//2 (aprox)
            #             # Asumimos total_open no cambiará mucho, pero ojo con la coherencia.
            #             num_sell_desired = total_open - (total_open // 2)  # la mitad aprox.
            #             if num_sell_orders > num_sell_desired:
            #                 to_cancel = num_sell_orders - num_sell_desired
            #                 sell_orders_sorted = sorted(sell_orders, key=lambda o: o['price'], reverse=True)
            #                 for i in range(to_cancel):
            #                     if i >= len(sell_orders_sorted):
            #                         break
            #                     order_to_cancel = sell_orders_sorted[i]
            #                     try:
            #                         await self.exchange.cancel_order(order_to_cancel['id'], self.symbol)
            #                         logging.info(f"Cancelada SELL {order_to_cancel['id']} @ {order_to_cancel['price']} (reequilibrio).")
            #                     except Exception as e:
            #                         logging.error(f"Error cancelando SELL {order_to_cancel['id']}: {e}")

            #         elif ratio > 0.6:
            #             # Tenemos muchas BUY o pocas SELL.
            #             # Posiblemente queramos cancelar parte de las BUY más lejanas,
            #             # o añadir SELL si net_pos > 0 y no excedemos max_sells_allowed.

            #             # Ejemplo: cancelamos parte de las BUY más lejanas.
            #             num_buy_desired = total_open // 2
            #             if num_buy_orders > num_buy_desired:
            #                 to_cancel = num_buy_orders - num_buy_desired
            #                 buy_orders_sorted = sorted(buy_orders, key=lambda o: o['price'])  # quizás cancelamos las más altas
            #                 for i in range(to_cancel):
            #                     if i >= len(buy_orders_sorted):
            #                         break
            #                     order_to_cancel = buy_orders_sorted[i]
            #                     try:
            #                         await self.exchange.cancel_order(order_to_cancel['id'], self.symbol)
            #                         logging.info(f"Cancelada BUY {order_to_cancel['id']} @ {order_to_cancel['price']} (reequilibrio).")
            #                     except Exception as e:
            #                         logging.error(f"Error cancelando BUY {order_to_cancel['id']}: {e}")

            #         # Recalcular después del reequilibrio
            #         open_orders = await self.exchange.fetch_open_orders(self.symbol)
            #         buy_orders = [o for o in open_orders if o['side'] == 'buy']
            #         sell_orders = [o for o in open_orders if o['side'] == 'sell']
            #         num_buy_orders = len(buy_orders)
            #         num_sell_orders = len(sell_orders)
            #         total_open = num_buy_orders + num_sell_orders

            #     # 5. (Opcional) Crear nuevas órdenes SELL si net_pos > 0 y hay margen
            #     #    para aumentar la proporción SELL y no exceder self.num_orders ni max_sells_allowed.
            #     if net_pos > 0:
            #         # Recalcula cuántas sell podemos aún colocar.
            #         max_additional_sell = max_sells_allowed - num_sell_orders
            #         if max_additional_sell > 0 and total_open < self.num_orders:
            #             # EJEMPLO: creamos sell cerca del precio ejecutado con incrementos de spread.
            #             current_price = executed_order['price']
            #             for i in range(max_additional_sell):
            #                 if (num_buy_orders + num_sell_orders) >= self.num_orders:
            #                     break
            #                 new_sell_price = current_price * (1 + self.percentage_spread * (i + 1))
            #                 # Aquí decides el amount, p.ej. igual que la orden de compra que se llenó:
            #                 amount = executed_order['amount']

            #                 created = await self.create_order('sell', amount, new_sell_price)
            #                 if created:
            #                     logging.info(f"SELL adicional creada @ {new_sell_price} para equilibrar.")
            #                     num_sell_orders += 1
            #                     total_open += 1
            #                     if num_sell_orders >= max_sells_allowed or total_open >= self.num_orders:
            #                         break

            # except Exception as e:
            #     logging.error(f"Error en el rebalanceo de la grid: {e}")





    async def rebalance_grid(self, executed_order):
        async with self._rebalance_lock:
            try:
                # 1. Cargar órdenes abiertas y calcular net_pos
                open_orders = await self.exchange.fetch_open_orders(self.symbol)

                buy_orders = [o for o in open_orders if o['side'] == 'buy']
                sell_orders = [o for o in open_orders if o['side'] == 'sell']

                num_buy_orders = len(buy_orders)
                num_sell_orders = len(sell_orders)
                total_open = num_buy_orders + num_sell_orders

                print('-'*20)
                print(self.total_buys_filled, self.total_sells_filled)
                print(self.total_buys_filled - self.total_sells_filled)
                print('-'*20)

                

                net_pos = self.total_buys_filled - self.total_sells_filled
                max_sells_allowed = max(net_pos, 0)

                # 2. Determinar cuántas órdenes queremos de venta (sell_target) y de compra (buy_target).
                sell_target = min(max_sells_allowed, self.num_orders)
                buy_target = self.num_orders - sell_target

                logging.info(f"[Rebalance] net_pos={net_pos}, buy_orders={num_buy_orders}, sell_orders={num_sell_orders}, total_open={total_open}")
                logging.info(f"[Rebalance] buy_target={buy_target}, sell_target={sell_target}")

                # 3A. Ajustar SELL al sell_target
                # 3A-1: Si hay más SELL de las necesarias, cancela las sobrantes.
                if num_sell_orders > sell_target:
                    # Decide el criterio de qué órdenes SELL cancelar.
                    # Por ejemplo, cancelar las más alejadas del precio actual, o las más caras, etc.
                    current_price = executed_order['price']
                    sell_orders_sorted = sorted(
                        sell_orders, 
                        key=lambda o: abs(o['price'] - current_price), 
                        reverse=True  # primero las más alejadas
                    )
                    excess_sells = num_sell_orders - sell_target
                    for i in range(excess_sells):
                        order_to_cancel = sell_orders_sorted[i]
                        try:
                            await self.exchange.cancel_order(order_to_cancel['id'], self.symbol)
                            logging.info(f"[Rebalance] Cancelada SELL {order_to_cancel['id']} @ {order_to_cancel['price']} (exceso).")
                        except Exception as e:
                            logging.error(f"Error cancelando SELL {order_to_cancel['id']}: {e}")

                elif num_sell_orders < sell_target:
                    # 3A-2: Si faltan SELL, crear las necesarias. 
                    # Aqui decides los precios usando tu lógica de grid (arriba del precio actual).
                    current_price = executed_order['price']
                    missing = sell_target - num_sell_orders
                    for i in range(missing):
                        # Ejemplo: escalonar con el spread
                        price_for_sell = current_price * (1 + self.percentage_spread*(i+1))
                        # La cantidad la puedes basar en la última orden ejecutada o un valor fijo.
                        amount = executed_order['amount']  # ejemplo
                        created = await self.create_order('sell', amount, price_for_sell)
                        if created:
                            logging.info(f"[Rebalance] SELL adicional creada @ {price_for_sell} para completar {sell_target}.")

                # 3B. Ajustar BUY al buy_target
                # (Haz de nuevo fetch_open_orders tras lo anterior, para estar seguro de tu estado actual)
                open_orders = await self.exchange.fetch_open_orders(self.symbol)
                buy_orders = [o for o in open_orders if o['side'] == 'buy']
                sell_orders = [o for o in open_orders if o['side'] == 'sell']
                num_buy_orders = len(buy_orders)
                num_sell_orders = len(sell_orders)
                total_open = num_buy_orders + num_sell_orders

                if num_buy_orders > buy_target:
                    # Cancelar las más lejanas (o a tu criterio)
                    current_price = executed_order['price']
                    buy_orders_sorted = sorted(
                        buy_orders, 
                        key=lambda o: abs(o['price'] - current_price), 
                        reverse=True
                    )
                    excess_buys = num_buy_orders - buy_target
                    for i in range(excess_buys):
                        order_to_cancel = buy_orders_sorted[i]
                        try:
                            await self.exchange.cancel_order(order_to_cancel['id'], self.symbol)
                            logging.info(f"[Rebalance] Cancelada BUY {order_to_cancel['id']} @ {order_to_cancel['price']} (exceso).")
                        except Exception as e:
                            logging.error(f"Error cancelando BUY {order_to_cancel['id']}: {e}")

                elif num_buy_orders < buy_target:
                    # Crear las que faltan en BUY
                    current_price = executed_order['price']
                    missing = buy_target - num_buy_orders
                    for i in range(missing):
                        # Escalonar hacia abajo
                        price_for_buy = current_price * (1 - self.percentage_spread*(i+1))
                        amount = executed_order['amount']  # por ejemplo
                        created = await self.create_order('buy', amount, price_for_buy)
                        if created:
                            logging.info(f"[Rebalance] BUY adicional creada @ {price_for_buy} para completar {buy_target}.")

                # Al final de esto, deberías tener:
                # num_buy_orders = buy_target
                # num_sell_orders = sell_target
                # total_open = self.num_orders
                logging.info("[Rebalance] Proceso de rebalance completado.")
            except Exception as e:
                logging.error(f"Error en el rebalanceo de la grid: {e}")
