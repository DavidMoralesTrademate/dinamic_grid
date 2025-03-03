import asyncio
import logging
import math
from bot.helpers import calculate_order_prices_buy,calculate_order_prices_sell,  format_quantity

class OrderManager:
    """
    Bot de 'grid alcista' estático:
      - Al iniciar, coloca únicamente órdenes de compra escalonadas por debajo de un precio inicial.
      - Cuando se llena una orden de compra, crea la orden de venta contraria (y viceversa).
      - Guarda contadores de compras/ventas llenas y un profit estimado por cada venta completada.
    """
    def __init__(self, exchange, symbol, config):
        """
        Parámetros:
          - exchange: instancia ccxt.pro con métodos watch_orders, create_order, etc.
          - symbol: str, par de trading (ej: 'BTC/USDT').
          - config: dict con:
              'percentage_spread': float,
              'amount': float,
              'num_orders': int,
              'price_format': int (opcional),
              'amount_format': int (opcional),
              'contract_size': float (opcional).
        """
        self.exchange = exchange
        self.symbol = symbol

        # Extrae configuración
        self.percentage_spread = float(config['percentage_spread'])
        self.amount = float(config['amount'])
        self.num_orders = int(config['num_orders'])
        self.price_format = config.get('price_format')
        self.amount_format = config.get('amount_format')
        self.contract_size = config.get('contract_size')

        # Contadores de órdenes llenas
        self.total_buys_filled = 0
        self.total_sells_filled = 0

        # Ganancia estimada, asumiendo que cada venta produce spread * amount
        self.match_profit = 0.0

    async def check_orders(self):
        """
        Bucle principal que escucha las actualizaciones de órdenes vía watch_orders.
        Cada vez que detecta una orden 'filled' o 'closed' con amount == filled,
        llama a process_order para manejar la lógica de compra/venta contraria.
        """
        reconnect_attempts = 0
        while True:
            try:
                #self.print_stats()  # Imprime contadores y estado
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
                logging.info(f"Reintentando en {wait_time} seg...")
                await asyncio.sleep(wait_time)

    async def process_order(self, order: dict):
        """
        Procesa cada actualización de orden.
        Si la orden se llenó por completo (status in ('filled','closed') y filled == amount),
        incrementa el contador correspondiente y crea la orden contraria.
        """
        try:
            oid = order.get('id')
            if not oid:
                return  # No hay ID => no podemos procesar

            side = order.get('side')          # 'buy' o 'sell'
            price = order.get('price', None)  # precio al que se ejecutó la orden
            amount = float(order.get('amount', 0.0))
            filled = float(order.get('filled', 0.0))
            status = order.get('status')      # 'open', 'closed', 'filled', etc.

            # Si la orden se llenó completamente
            if status in ('filled', 'closed') and filled == amount and amount > 0.0:
                # Actualizamos contadores
                if side == 'buy':
                    self.total_buys_filled += 1
                    # Crea la venta contraria
                    if price is not None:
                        sell_price = price * (1 + self.percentage_spread)
                        await self.create_order('sell', filled, sell_price)
                    else:
                        logging.warning(f"Omitida venta para la orden buy {oid} por falta de price.")
                else:  # side == 'sell'
                    self.total_sells_filled += 1
                    # Ganancia estimada
                    self.match_profit += (self.amount * self.percentage_spread)
                    # Crea la compra contraria
                    if price is not None:
                        buy_price = price * (1 - self.percentage_spread)
                        await self.create_order('buy', filled, buy_price)
                    else:
                        logging.warning(f"Omitida compra para la orden sell {oid} por falta de price.")

        except Exception as e:
            logging.error(f"Error en process_order: {e}")

    async def create_order(self, side: str, amount: float, price: float):
        """
        Crea una nueva orden limit. No se guarda en estructuras locales,
        pues la idea es un grid estático (se confía en watch_orders para updates).
        """
        try:
            params = {'posSide': 'long'}  # Hedge Mode (OKX), ajusta si deseas 'short'
            resp = await self.exchange.create_order(
                self.symbol, 
                'limit', 
                side, 
                amount, 
                price, 
                params=params
            )
            if resp:
                # Sólo logueamos
                oid = resp['id']
                logging.info(f"Orden creada: {side.upper()} {amount} @ {price}, ID={oid}")
            else:
                logging.warning(f"No se recibió respuesta en create_order: {side} {amount} @ {price}")

        except Exception as e:
            logging.error(f"Error creando orden: {e}")

    async def place_orders(self, initial_price: float):
        """
        Coloca un grid 'alcista' inicial: únicamente órdenes de compra escalonadas
        por debajo de initial_price. Posteriormente, cada vez que una compra se llene,
        se generará la venta correspondiente en process_order.
        """
        try:
            prices = calculate_order_prices_buy(
                initial_price, 
                self.percentage_spread, 
                self.num_orders, 
                self.price_format
            )
            count = 0
            for p in prices:
                if count >= self.num_orders:
                    break
                amt = format_quantity(
                    self.amount / p / self.contract_size, 
                    self.amount_format
                )
                await self.create_order('buy', amt, p)
                count += 1
        except Exception as e:
            logging.error(f"Error en place_orders: {e}")

    def print_stats(self):
        """
        Imprime un resumen de contadores cada vez que se llama (en check_orders).
        """
        print("\n=== Grid Alcista Stats ===")
        print(f"  Buys llenas: {self.total_buys_filled}")
        print(f"  Sells llenas: {self.total_sells_filled}")
        print(f"  Profit estimado (spread): {self.match_profit:.4f}")
        print("=== Fin de Stats ===\n")



async def rebalance(self):

    open_orders = await self.exchange.fetch_open_orders(self.symbol)
    net_pos = self.total_buys_filled - self.total_sells_filled

    buy_orders = [o for o in open_orders if o['side'] == 'buy']
    sell_orders = [o for o in open_orders if o['side'] == 'sell']

    total_open = len(open_orders)
    logging.info(f"[Rebalance] total_open={total_open}, "
                 f"buy_orders={len(buy_orders)}, sell_orders={len(sell_orders)}, net_pos={net_pos}")

    # --------------------------
    # Rebalancear compras
    # --------------------------
    if len(sell_orders) > len(buy_orders) + 1:
        logging.info("Necesitamos cancelar ventas y poner compras")

        sorted_sells = sorted(sell_orders, key=lambda o: o['price'], reverse=True)
        diff = (len(sell_orders) - len(buy_orders)) 
        if diff <= 0:
            logging.info("diff<=0, no hacemos nada.")
            return

        # Limitar un cambio muy brusco
        if diff > self.num_orders // 2:
            diff = self.num_orders // 2

        sells_to_cancel = sorted_sells[:diff]

        # Cancelar esas sells
        for s in sells_to_cancel:
            try:
                await self.exchange.cancel_order(s['id'], self.symbol)
                logging.info(f"Cancelada venta ID={s['id']} precio={s['price']}")
            except Exception as e:
                logging.error(f"Error cancelando venta {s['id']}: {e}")

        # Para crear buys, si no hay buy_orders, usar fallback
        sorted_buys_asc = sorted(buy_orders, key=lambda o: o['price'])
        if len(sorted_buys_asc) == 0:
            logging.warning("No hay buy_orders para referencia de precio, fallback=0.0.")
            ref_price = 0.0  # o mid_price
        else:
            ref_price = sorted_buys_asc[0]['price'] * (1 - self.percentage_spread)

        # Crear 'diff' compras
        try:
            prices = calculate_order_prices_buy(
                ref_price, 
                self.percentage_spread, 
                diff, 
                self.price_format
            )
            count = 0
            for p in prices:
                if count >= diff:
                    break
                amt = format_quantity(
                    self.amount / p / self.contract_size,
                    self.amount_format
                )
                try:
                    await self.create_order('buy', amt, p)
                    logging.info(f"Creada compra {amt} @ {p}")
                    count += 1
                except Exception as e:
                    logging.error(f"Error creando compra en {p}: {e}")
        except Exception as e:
            logging.error(f"Error al generar/cargar precios buy: {e}")

    # --------------------------
    # Rebalancear ventas
    # --------------------------
    # “necesitamos más ventas” si hay muchas compras y net_pos> ventas
    if len(buy_orders) > len(sell_orders) + 1 and net_pos > len(sell_orders):
        logging.info("Puede que necesitemos más ventas.")
        logging.info(f"net_pos={net_pos}, sells={len(sell_orders)}, buys={len(buy_orders)}")
        
        await asyncio.sleep(0.1)

        # si net_pos == len(sell_orders), nada que hacer
        if net_pos == len(sell_orders):
            logging.info("net_pos == sells, no hay margen para más ventas.")
            return

        diff = (len(buy_orders) - len(sell_orders))
        # no crear más ventas de las que net_pos respalda
        capacidad_venta = net_pos - len(sell_orders)
        if diff > capacidad_venta:
            diff = capacidad_venta

        if diff <= 0:
            logging.info("diff <= 0, no hacemos nada.")
            return

        if diff > self.num_orders // 2:
            diff = self.num_orders // 2

        sorted_buys_asc = sorted(buy_orders, key=lambda o: o['price'])
        buys_to_cancel = sorted_buys_asc[:diff]

        logging.info(f"Cancelaremos {diff} buy-orders y crearemos {diff} sell-orders.")
        
        # Cancelar buys
        for b in buys_to_cancel:
            try:
                await self.exchange.cancel_order(b['id'], self.symbol)
                logging.info(f"Cancelada compra ID={b['id']} precio={b['price']}")
            except Exception as e:
                logging.error(f"Error cancelando compra {b['id']}: {e}")

        # Crear sells
        sorted_sells_desc = sorted(sell_orders, key=lambda o: o['price'], reverse=True)
        if len(sorted_sells_desc) > 0:
            ref_price = sorted_sells_desc[0]['price'] * (1 + self.percentage_spread)
        else:
            logging.warning("No hay sells para referencia de precio, fallback=0.0.")
            ref_price = 0.0

        try:
            prices = calculate_order_prices_sell(
                ref_price,
                self.percentage_spread,
                diff,
                self.price_format
            )
            count = 0
            for p in prices:
                if count >= diff:
                    break
                amt = format_quantity(
                    (self.amount * (1 - self.percentage_spread)) / p / self.contract_size,
                    self.amount_format
                )
                try:
                    await self.create_order('sell', amt, p)
                    logging.info(f"Creada venta {amt} @ {p}")
                    count += 1
                except Exception as e:
                    logging.error(f"Error creando venta en {p}: {e}")
        except Exception as e:
            logging.error(f"Error al generar/cargar precios sell: {e}")

    # --------------------------
    # Ajuste final: asegurar total_open == self.num_orders
    # (opcional, para no “perder” un buy)
    # --------------------------
    # Tras las acciones anteriores, el total de órdenes pudo quedar < self.num_orders
    # Si en tu grid alcista, cuando net_pos=0, quieres tener TODO en buy,
    # o si net_pos>0, podrías decidir la proporción. Aquí lo hago simple:
    await asyncio.sleep(0.1)  # un breve delay para que las cancelaciones se reflejen
    open_orders = await self.exchange.fetch_open_orders(self.symbol)
    total_open = len(open_orders)
    if total_open < self.num_orders:
        # cuántas faltan
        missing = self.num_orders - total_open
        # supón que cuando net_pos==0 => pones TODO buy, si net_pos>0 => pones “some sells / some buys”,
        # para un grid neto. Para simplificar, aquí asumo: si net_pos==0 => all buy,
        # sino => pones todo en buy igual. Ajusta según tu preferencia
        logging.info(f"Tras rebalances quedamos con {total_open} open, faltan {missing} para {self.num_orders}. Crearemos buys.")
        
        # define un “ref_price” para las nuevas buys
        # si ya tienes buys, usa la de precio más bajo, de lo contrario fallback a 0?
        buy_orders = [o for o in open_orders if o['side'] == 'buy']
        if buy_orders:
            sorted_buys_asc = sorted(buy_orders, key=lambda o: o['price'])
            ref_price = sorted_buys_asc[0]['price'] * (1 - self.percentage_spread)
        else:
            logging.warning("No hay buys para ref, fallback=0.0.")
            ref_price = 0.0
        
        try:
            prices = calculate_order_prices_buy(
                ref_price,
                self.percentage_spread,
                missing,
                self.price_format
            )
            count = 0
            for p in prices:
                if count >= missing:
                    break
                amt = format_quantity(
                    self.amount / p / self.contract_size,
                    self.amount_format
                )
                await self.create_order('buy', amt, p)
                logging.info(f"Creada compra final {amt} @ {p}")
                count += 1
        except Exception as e:
            logging.error(f"Error completando {missing} buys finales: {e}")

    logging.info("[Rebalance] fin, total_final=?? revisa en el next cycle.")