import asyncio
import logging
from sortedcontainers import SortedDict
from bot.helpers import calculate_order_prices, format_quantity

class OrderManager:
    def __init__(self, exchange, symbol, config):
        self.exchange = exchange
        self.symbol = symbol

        # Parámetros de configuración básicos de la estrategia
        self.percentage_spread = float(config['percentage_spread'])
        self.amount = float(config['amount'])
        self.num_orders = int(config['num_orders'])
        self.price_format = config.get('price_format')
        self.amount_format = config.get('amount_format')
        self.contract_size = config.get('contract_size')

        # Contadores de órdenes llenas
        self.total_buys_filled = 0
        self.total_sells_filled = 0
        self.total_profit_matches = 0.0  # profit estimado

        # Lock (para cuando quieras hacer rebalances futuros)
        self._rebalance_lock = asyncio.Lock()

        # Estructuras de datos
        # - Diccionario principal: id => info de orden
        # - SortedDict: key=price => set de order_ids
        self.orders_by_id = {}
        self.orders_by_price = SortedDict()

    ### ------------------- Estructuras Locales de Órdenes -------------------
    def _add_order_local(self, order):
        """
        Inserta la orden en nuestras estructuras (orders_by_id, orders_by_price).
        order debe tener: 'id', 'side', 'price', 'amount', 'filled', 'status', ...
        """
        oid = order['id']
        price = order['price']

        # Guardamos la orden en el diccionario principal
        self.orders_by_id[oid] = order

        # Insertamos en el SortedDict por precio
        if price not in self.orders_by_price:
            self.orders_by_price[price] = set()
        self.orders_by_price[price].add(oid)

    def _remove_order_local(self, order):
        """
        Elimina la orden de nuestras estructuras, usando order['id'] y order['price'].
        """
        oid = order['id']
        price = order['price']

        # Borramos del diccionario principal
        if oid in self.orders_by_id:
            del self.orders_by_id[oid]

        # Borramos del SortedDict
        if price in self.orders_by_price:
            s = self.orders_by_price[price]
            if oid in s:
                s.remove(oid)
                if not s:  # Si se queda vacío
                    del self.orders_by_price[price]

    def _update_local_order(self, order):
        """
        Actualiza (o inserta) la orden en estructuras, según su estado.
        """
        oid = order.get('id')
        price = order.get('price')
        status = order.get('status', 'open')

        if not oid or price is None:
            return  # orden sin ID o sin precio => no insertamos en orders_by_price

        # Si la tenemos, vemos si cambió de precio => la sacamos del old_price
        existing = self.orders_by_id.get(oid)
        if existing:
            old_price = existing['price']
            if old_price != price:
                # remover del old_price
                if old_price in self.orders_by_price:
                    s = self.orders_by_price[old_price]
                    if oid in s:
                        s.remove(oid)
                        if not s:
                            del self.orders_by_price[old_price]
                # actualizar
                existing.update(order)
                # reinsertar en la nueva price
                if price not in self.orders_by_price:
                    self.orders_by_price[price] = set()
                self.orders_by_price[price].add(oid)
            else:
                # precio igual => solo actualizar campos
                existing.update(order)
        else:
            # No existía => add
            self._add_order_local(order)

        self.orders_by_id[oid]['status'] = status

    ### ------------------- Procesamiento de Updates del Exchange -------------------
    async def check_orders(self):
        """
        Bucle principal que escucha watch_orders y llama process_order
        para cada actualización.
        """
        reconnect_attempts = 0
        while True:
            try:
                self.print_active_orders()  # imprime un resumen
                orders = await self.exchange.watch_orders(self.symbol)
                if not orders:
                    continue
                for o in orders:
                    await self.process_order(o)
                reconnect_attempts = 0
            except Exception as e:
                reconnect_attempts += 1
                wait_time = min(2**reconnect_attempts, 60)
                logging.error(f"Error en check_orders (intento {reconnect_attempts}): {e}")
                logging.info(f"Reintentando en {wait_time} segundos...")
                await asyncio.sleep(wait_time)

    async def process_order(self, order):
        """
        process_order es llamado para cada update de 'watch_orders'.
        Aquí decidimos si la orden se llenó, se canceló, etc., y
        actualizamos nuestras estructuras + creamos la orden contraria si se llenó.
        """
        try:
            oid = order.get('id')
            if not oid:
                return

            side = order.get('side')
            price = order.get('price')
            amount = order.get('amount', 0.0)
            filled = order.get('filled', 0.0)
            status = order.get('status')

            if status in ('open', 'partially_filled'):
                # Actualizamos en nuestras estructuras
                self._update_local_order(order)

            elif status in ('filled', 'closed'):
                # Llenada completamente o cerrada
                # chequeamos si (filled == amount), es la referencia para un fill total
                if filled == amount and amount > 0.0:
                    await self.on_order_filled(order)
                # en ambos casos la removemos
                self._remove_order_local(order)

            elif status in ('canceled', 'expired', 'rejected'):
                # Orden finalizada sin llenarse
                self._remove_order_local(order)
            else:
                # Otros estados (ej. 'new', 'pending'), actualizamos
                self._update_local_order(order)

        except Exception as e:
            logging.error(f"Error procesando orden: {e}")

    async def on_order_filled(self, order):
        """
        Maneja la lógica cuando una orden se llena completamente.
        """
        side = order['side']
        amount_filled = order['amount']
        price_filled = order.get('price', None)

        if side == 'buy':
            self.total_buys_filled += 1
        else:
            self.total_sells_filled += 1
            # Ganancia hipotética si asumes que cada venta produce un spread * self.amount
            profit = self.amount * self.percentage_spread
            self.total_profit_matches += profit

        # Crear la orden contraria
        if price_filled is not None:
            side_counter = 'sell' if side == 'buy' else 'buy'
            spread_multiplier = 1 + self.percentage_spread if side_counter == 'sell' else 1 - self.percentage_spread
            new_price = price_filled * spread_multiplier
            await self.create_order(side_counter, amount_filled, new_price)
        else:
            logging.warning(f"Orden {order['id']} se llenó sin price. No se crea la contraria.")

    ### ------------------- Creación de Órdenes -------------------
    async def create_order(self, side, amount, price):
        """
        Crea una nueva orden 'limit' y la registra en nuestras estructuras
        si el exchange la confirma.
        """
        try:
            params = {'posSide': 'long'}  # si estás en hedge mode
            resp = await self.exchange.create_order(self.symbol, 'limit', side, amount, price, params=params)
            if resp:
                oid = resp['id']
                logging.info(f"Orden creada: {side.upper()} {amount} @ {price}, ID={oid}")
                # Agregar a structures
                # Llamamos un "skeleton" de order para guardarla
                new_order_dict = {
                    'id': oid,
                    'side': side,
                    'price': price,
                    'amount': amount,
                    'filled': 0.0,
                    'status': 'open'
                }
                self._add_order_local(new_order_dict)
                return resp
            else:
                logging.warning(f"No se recibió respuesta en create_order: {side.upper()} {amount} @ {price}")
        except Exception as e:
            logging.error(f"Error creando orden: {e}")

    async def place_orders(self, price):
        """
        Método para colocar la grid estática inicial (todas ordenes de 'buy', p.ej.).
        """
        try:
            prices = calculate_order_prices(price, self.percentage_spread, self.num_orders, self.price_format)
            created = 0
            for p in prices:
                if created >= self.num_orders:
                    break
                formatted_amount = format_quantity(self.amount / p / self.contract_size, self.amount_format)
                await self.create_order('buy', formatted_amount, p)
                created += 1
        except Exception as e:
            logging.error(f"Error al place_orders: {e}")

    ### ------------------- Reporte en Pantalla -------------------
    def print_active_orders(self):
        """
        Imprime contadores y un breve listado de las órdenes activas,
        ordenadas por precio ascendente (gracias a sortedcontainers).
        """
        print("\n=== ESTADÍSTICAS DE MATCH ===")
        print(f"  Buys llenas: {self.total_buys_filled}")
        print(f"  Sells llenas: {self.total_sells_filled}")
        print(f"  Profit estimado (spread): {self.total_profit_matches:.2f}")
        print("=== Órdenes Activas ===")

        if not self.orders_by_id:
            print("  No hay órdenes activas registradas.")
        else:
            # Recorremos la estructura sorted por price
            for price in self.orders_by_price.keys():
                ids_con_ese_precio = self.orders_by_price[price]
                for oid in ids_con_ese_precio:
                    od = self.orders_by_id.get(oid, {})
                    side = od.get('side','?')
                    st = od.get('status','?')
                    filled = od.get('filled',0.0)
                    amt = od.get('amount',0.0)
                    print(f"    Price={price}, ID={oid}, side={side}, status={st}, amount={amt}, filled={filled}")
        print("=== FIN ===\n")
