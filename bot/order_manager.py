import datetime
import motor.motor_asyncio
import asyncio
import logging
from bot.helpers import (
    calculate_order_prices_buy,
    calculate_order_prices_sell,
    format_quantity
)

class OrderManager:
    """
    Bot de 'grid alcista' estático:
      - Coloca inicialmente únicamente órdenes de compra escalonadas por debajo de un precio.
      - Cuando se llena una orden de compra, crea la orden de venta contraria (y viceversa).
      - Lleva contadores de órdenes llenas (match) y un profit estimado.
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
        self.account = config.get('account')
        self.exchange_name = config.get('exchange_name')

        self.percentage_spread = float(config['percentage_spread'])
        self.amount = float(config['amount'])
        self.num_orders = int(config['num_orders'])
        self.price_format = config.get('price_format')
        self.amount_format = config.get('amount_format')
        self.contract_size = config.get('contract_size')

        self.total_buys_filled = 46963 + 354

        self.total_sells_filled = 46963

        self.match_profit = 6903.5470
        

    async def check_orders(self):
        """
        Escucha actualizaciones de órdenes a través de watch_orders y procesa cada una.
        """
        reconnect_attempts = 0
        while True:
            try:
                self.print_stats()
                orders = await self.exchange.watch_orders(self.symbol)
                open_orders = [o for o in orders if o['info'].get('posSide') == 'long']
                if not open_orders:
                    continue
                for o in open_orders:
                    await self.process_order(o)
                reconnect_attempts = 0
            except Exception as e:
                reconnect_attempts += 1
                wait_time = min(2 ** reconnect_attempts, 60)
                logging.error(f"Error en check_orders (intento {reconnect_attempts}): {e}")
                logging.info(f"Reintentando en {wait_time} seg...")
                await asyncio.sleep(wait_time)

    async def process_order(self, order: dict):
        """
        Si la orden se llenó completamente (status en ('filled','closed') y filled == amount),
        actualiza los contadores y crea la orden contraria.
        """
        try:
            oid = order.get('id')
            if not oid:
                return
            side = order.get('side')
            price = order.get('price', None)
            amount = float(order.get('amount', 0.0))
            filled = float(order.get('filled', 0.0))
            status = order.get('status')
            if status in ('filled', 'closed') and filled == amount and amount > 0.0:
                if side == 'buy':
                    self.total_buys_filled += 1
                    if price is not None:
                        sell_price = price * (1 + self.percentage_spread)
                        await self.create_order('sell', filled, sell_price)
                    else:
                        logging.warning(f"Omitida venta para la orden buy {oid} por falta de price.")
                else:
                    self.total_sells_filled += 1
                    self.match_profit += (self.amount * self.percentage_spread)
                    if price is not None:
                        buy_price = price * (1 - self.percentage_spread)
                        await self.create_order('buy', filled, buy_price)
                    else:
                        logging.warning(f"Omitida compra para la orden sell {oid} por falta de price.")
        except Exception as e:
            logging.error(f"Error en process_order: {e}")

    async def create_order(self, side: str, amount: float, price: float):
        """
        Crea una orden limit usando create_order del exchange.
        """
        try:
            params = {'posSide': 'long'}
            resp = await self.exchange.create_order(
                self.symbol,
                'limit',
                side,
                amount,
                price,
                params=params
            )
            if resp:
                oid = resp['id']
                logging.info(f"Orden creada: {side.upper()} {amount} @ {price}, ID={oid}")
            else:
                logging.warning(f"No se recibió respuesta en create_order: {side} {amount} @ {price}")
        except Exception as e:
            logging.error(f"Error creando orden: {e}")


    async def place_orders(self, initial_price: float):
        """
        Coloca la grid inicial de órdenes de compra por debajo de initial_price.
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
        Imprime un resumen de la actividad del grid: volumen, contadores, net position, profit y fee aproximado.
        """
        net_pos = self.total_buys_filled - self.total_sells_filled
        total_volume = (self.total_buys_filled + self.total_sells_filled) * self.amount
        fee_approx = total_volume * 0.00002  # 0.002% = 0.00002

        print("\n=== Grid Alcista Stats ===")
        print(f"  Volumen Total: {total_volume}")
        print(f"  Total de Compras: {self.total_buys_filled}")
        print(f"  Número de Matchs (Ventas llenas): {self.total_sells_filled}")
        print(f"  Net Position: {net_pos}")
        print(f"  Match Profit: {self.match_profit:.4f}")
        print(f"  Fee Aproximado: {fee_approx:.4f}")
        print("=== Fin de Stats ===\n")

    async def rebalance(self):
        """
        Rebalancea el grid de órdenes. Primero obtiene las órdenes abiertas y calcula
        la diferencia entre compras y ventas, y el net_pos. Luego:
          1) Si hay demasiadas ventas (sells > buys * 1.1), cancela algunas ventas y crea compras.
          2) Si hay demasiadas compras (buys > sells * 1.1) y el net_pos permite más ventas, cancela algunas compras y crea ventas.
          3) Finalmente, se asegura de tener exactamente self.num_orders órdenes abiertas, creando órdenes extra si es necesario.
        """
        fetchorders = await self.exchange.fetch_open_orders(self.symbol)
        open_orders = [o for o in fetchorders if o['info'].get('posSide') == 'long']
        net_pos = self.total_buys_filled - self.total_sells_filled

        buy_orders = [o for o in open_orders if o['side'] == 'buy']
        sell_orders = [o for o in open_orders if o['side'] == 'sell']

        total_open = len(open_orders)
        num_buys = len(buy_orders)
        num_sells = len(sell_orders)
        logging.info(f"[Rebalance] total_open={total_open}, buy_orders={num_buys}, sell_orders={num_sells}, net_pos={net_pos}")

        # Limite máximo de órdenes a modificar en un ciclo: 25% del total
        max_diff = max(1, self.num_orders // 5)

        # --------------------------------------------------------------------
        # 1) Rebalancear COMPRAS: Si hay más SELL que BUY (más de 10% de diferencia)
        # --------------------------------------------------------------------
        if num_sells > num_buys * 1.1:
            logging.info("[Rebalance] Necesitamos cancelar ventas y poner compras")
            sorted_sells = sorted(sell_orders, key=lambda o: o['price'], reverse=True)
            raw_diff = num_sells - num_buys
            diff = min(raw_diff, max_diff)
            if diff <= 0:
                logging.info("[Rebalance] diff <= 0, nada que cancelar ni crear en compras.")
            else:
                logging.info(f"[Rebalance] Cancelaremos {diff} sell-orders y crearemos {diff} buy-orders.")
                sells_to_cancel = sorted_sells[:diff]
                for s in sells_to_cancel:
                    try:
                        await self.exchange.cancel_order(s['id'], self.symbol)
                        logging.info(f"Cancelada venta ID={s['id']} precio={s['price']}")
                    except Exception as e:
                        logging.error(f"Error cancelando venta {s['id']}: {e}")

                if len(buy_orders) == 0:
                    logging.warning("[Rebalance] No hay buy_orders para referencia, usando fallback=0.0")
                    ref_price = 0.0  # Podrías usar un mid_price
                else:
                    sorted_buys_asc = sorted(buy_orders, key=lambda o: o['price'])
                    ref_price = sorted_buys_asc[0]['price'] * (1 - self.percentage_spread)
                
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
                    logging.error(f"[Rebalance] Error al generar precios buy: {e}")

        # --------------------------------------------------------------------
        # 2) Rebalancear VENTAS: Si hay más BUY que SELL (más de 10% de diferencia) y hay margen (net_pos > num_sells)
        # --------------------------------------------------------------------
        if num_buys > num_sells * 1.1 and net_pos > num_sells:
            logging.info("[Rebalance] Puede que necesitemos más ventas.")
            logging.info(f"net_pos={net_pos}, sells={num_sells}, buy_orders={num_buys}")
            
            await asyncio.sleep(0.1)
            if net_pos == num_sells:
                logging.info("[Rebalance] net_pos == sells. No hay margen para más ventas.")
            else:
                raw_diff = num_buys - num_sells 
                capacidad_ventas = net_pos - num_sells
                diff = min(raw_diff, capacidad_ventas, max_diff)
                if diff <= 0:
                    logging.info("[Rebalance] diff <= 0, no hay nada que cancelar ni crear en ventas.")
                else:
                    logging.info(f"[Rebalance] Cancelaremos {diff} buy-orders y crearemos {diff} sell-orders.")
                    sorted_buys_asc = sorted(buy_orders, key=lambda o: o['price'])
                    buys_to_cancel = sorted_buys_asc[:diff]
                    for b in buys_to_cancel:
                        try:
                            await self.exchange.cancel_order(b['id'], self.symbol)
                            logging.info(f"Cancelada compra ID={b['id']} precio={b['price']}")
                        except Exception as e:
                            logging.error(f"Error cancelando compra {b['id']}: {e}")
                    
                    if len(sell_orders) > 0:
                        sorted_sells_desc = sorted(sell_orders, key=lambda o: o['price'], reverse=True)
                        ref_price = sorted_sells_desc[0]['price'] * (1 + self.percentage_spread)
                    else:
                        logging.warning("[Rebalance] No hay sells para referencia, usando fallback=0.0")
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
                        logging.error(f"[Rebalance] Error al generar precios sell: {e}")
        else:
            logging.info("[Rebalance] No hay condición para re-balancear ventas en este momento.")

        # --------------------------------------------------------------------
        # 3) Paso final: Asegurar que el total de órdenes sea exactamente self.num_orders
        # --------------------------------------------------------------------
        await asyncio.sleep(0.02)
        fetch_open_orders_final = await self.exchange.fetch_open_orders(self.symbol)
        open_orders_final = [o for o in fetch_open_orders_final if o['info'].get('posSide') == 'long']
        total_final = len(open_orders_final)
        if total_final < self.num_orders:
            faltan = self.num_orders - total_final
            logging.info(f"[Rebalance] Quedaron {total_final} órdenes; faltan {faltan} para llegar a {self.num_orders}. Crearemos buys extra.")
            
            buy_orders_final = [o for o in open_orders_final if o['side'] == 'buy']
            if buy_orders_final:
                sorted_buys_final = sorted(buy_orders_final, key=lambda o: o['price'])
                ref_price = sorted_buys_final[0]['price'] * (1 - self.percentage_spread)
            else:
                logging.warning("[Rebalance] No hay buy_orders para referencia, fallback=0.0")
                ref_price = 0.0
            
            try:
                prices = calculate_order_prices_buy(
                    ref_price,
                    self.percentage_spread,
                    faltan,
                    self.price_format
                )
                count = 0
                for p in prices:
                    if count >= faltan:
                        break
                    amt = format_quantity(
                        self.amount / p / self.contract_size,
                        self.amount_format
                    )
                    await self.create_order('buy', amt, p)
                    logging.info(f"Creada compra extra {amt} @ {p}")
                    count += 1
            except Exception as e:
                logging.error(f"[Rebalance] Error creando las {faltan} compras extra: {e}")
        elif total_final > self.num_orders:
            extra = total_final - self.num_orders
            logging.info(f"[Rebalance] Existen {total_final} órdenes; se cancelarán {extra} para ajustar a {self.num_orders}.")
            sorted_orders = sorted(open_orders_final, key=lambda o: o['price'])
            orders_to_cancel = sorted_orders[-extra:]
            for o in orders_to_cancel:
                try:
                    await self.exchange.cancel_order(o['id'], self.symbol)
                    logging.info(f"Cancelada orden extra ID={o['id']} precio={o['price']}")
                except Exception as e:
                    logging.error(f"Error cancelando orden extra {o['id']}: {e}")

        logging.info("[Rebalance] Finalizó la ejecución.")


    async def data_send(self):
        # Cadena de conexión a MongoDB Atlas (ajústala si es necesario)
        mongo_uri = "mongodb+srv://trademate:n4iTxStjWPyPSDHl@cluster0.uxsok.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"
        client = motor.motor_asyncio.AsyncIOMotorClient(mongo_uri)
        db = client["Grid"]
        collection = db["Match Profit"]

        # Definir el filtro único para identificar el documento (por ejemplo, por exchange, account y crypto_pair)
        filter_doc = {
            "exchange": self.exchange_name,
            "account": self.account,
            "crypto_pair": self.symbol,
        }

        # Datos a actualizar (o insertar si no existe)
        data = {
            "timestamp": datetime.datetime.utcnow(),
            "match_profit": self.match_profit,
            "number_of_matches": self.total_sells_filled,
            "net_position": self.total_buys_filled - self.total_sells_filled,
            "total_volume": (self.total_buys_filled + self.total_sells_filled) * self.amount,
        }

        update_doc = {"$set": data}

        try:
            result = await collection.update_one(filter_doc, update_doc, upsert=True)
            logging.info(f"Datos actualizados en MongoDB, resultado: {result.raw_result}")
        except Exception as e:
            logging.error(f"Error actualizando datos en MongoDB: {e}")






#DM00014
#f76999e1-492a-4076-8ec9-d708fc4824e1
#07531DF9F47BFD06C2FC8333B26150B5

#DM0013
#2f1cb002-ede2-4083-a049-262281a041d9
#9D4E9E1882E6B0DF1478598B824C7887