import datetime
import motor.motor_asyncio
import asyncio
import logging
from bot_crypto.helpers import (
    calculate_order_prices_sell,
    calculate_order_prices_buy,
    format_quantity
)

class OrderManager:
    """
    Bot de 'grid bajista' estático:
      - Coloca inicialmente órdenes de venta escalonadas por encima de un precio.
      - Cuando se llena una orden de venta, crea la orden de compra contraria (y viceversa).
      - Lleva contadores de órdenes llenas (match) y un profit estimado.
    """
    def __init__(self, exchange, symbol, config):
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

        self.total_sells_filled = 0
        self.total_buys_filled = 0
        self.match_profit = 0

    async def check_orders(self):
        reconnect_attempts = 0
        while True:
            try:
                self.print_stats()
                orders = await self.exchange.watch_orders(self.symbol)
                if not orders:
                    continue
                for o in orders:
                    await self.process_order(o)
                reconnect_attempts = 0
            except Exception as e:
                reconnect_attempts += 1
                wait_time = min(2 ** reconnect_attempts, 60)
                logging.error(f"Error en check_orders (intento {reconnect_attempts}): {e}")
                logging.info(f"Reintentando en {wait_time} seg...")
                await asyncio.sleep(wait_time)

    async def process_order(self, order: dict):
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
                if side == 'sell':
                    self.total_sells_filled += 1
                    if price is not None:
                        buy_price = price * (1 - self.percentage_spread)
                        await self.create_order('buy', filled, buy_price)
                    else:
                        logging.warning(f"Omitida compra para la orden sell {oid} por falta de price.")
                else:
                    self.total_buys_filled += 1
                    self.match_profit += (self.amount * self.percentage_spread)
                    if price is not None:
                        sell_price = price * (1 + self.percentage_spread)
                        await self.create_order('sell', filled, sell_price)
                    else:
                        logging.warning(f"Omitida venta para la orden buy {oid} por falta de price.")
        except Exception as e:
            logging.error(f"Error en process_order: {e}")

    async def create_order(self, side: str, amount: float, price: float):
        try:
            resp = await self.exchange.create_order(
                self.symbol,
                'limit',
                side,
                amount,
                price,
            )
            if resp:
                oid = resp['id']
                logging.info(f"Orden creada: {side.upper()} {amount} @ {price}, ID={oid}")
            else:
                logging.warning(f"No se recibió respuesta en create_order: {side} {amount} @ {price}")
        except Exception as e:
            logging.error(f"Error creando orden: {e}")

    async def place_orders(self, initial_price: float):
        try:
            prices = calculate_order_prices_sell(
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
                    (self.amount * (1 - self.percentage_spread)) / p,
                    self.amount_format
                )
                await self.create_order('sell', amt, p)
                count += 1
        except Exception as e:
            logging.error(f"Error en place_orders: {e}")

    def print_stats(self):
        net_pos = self.total_sells_filled - self.total_buys_filled
        total_volume = (self.total_buys_filled + self.total_sells_filled) * self.amount
        fee_approx = total_volume * 0.00002

        print("\n=== Grid Bajista Stats ===")
        print(f"  Volumen Total: {total_volume}")
        print(f"  Total de Ventas: {self.total_sells_filled}")
        print(f"  Número de Matchs (Compras llenas): {self.total_buys_filled}")
        print(f"  Net Position: {net_pos}")
        print(f"  Match Profit: {self.match_profit:.4f}")
        print(f"  Fee Aproximado: {fee_approx:.4f}")
        print("=== Fin de Stats ===\n")

    async def rebalance(self):
        open_orders = await self.exchange.fetch_open_orders(self.symbol)
        net_pos = self.total_sells_filled - self.total_buys_filled

        buy_orders = [o for o in open_orders if o['side'] == 'buy']
        sell_orders = [o for o in open_orders if o['side'] == 'sell']

        total_open = len(open_orders)
        num_buys = len(buy_orders)
        num_sells = len(sell_orders)

        logging.info(f"[Rebalance] total_open={total_open}, sell_orders={num_sells}, buy_orders={num_buys}, net_pos={net_pos}")

        max_diff = max(1, self.num_orders // 5)

        # 1) Si hay más compras que ventas
        if num_buys > num_sells * 1.1:
            logging.info("[Rebalance] Demasiadas compras, cancelando y colocando ventas")
            sorted_buys = sorted(buy_orders, key=lambda o: o['price'])
            diff = min(num_buys - num_sells, max_diff)
            buys_to_cancel = sorted_buys[:diff]
            for b in buys_to_cancel:
                try:
                    await self.exchange.cancel_order(b['id'], self.symbol)
                    logging.info(f"Cancelada compra ID={b['id']} precio={b['price']}")
                except Exception as e:
                    logging.error(f"Error cancelando compra {b['id']}: {e}")

            if sell_orders:
                ref_price = max(o['price'] for o in sell_orders) * (1 + self.percentage_spread)
            else:
                ref_price = 0.0

            try:
                prices = calculate_order_prices_sell(ref_price, self.percentage_spread, diff, self.price_format)
                for p in prices:
                    amt = format_quantity((self.amount * (1 - self.percentage_spread)) / p, self.amount_format)
                    await self.create_order('sell', amt, p)
                    logging.info(f"Creada venta {amt} @ {p}")
            except Exception as e:
                logging.error(f"[Rebalance] Error creando ventas: {e}")

        # 2) Si hay más ventas que compras y net_pos permite comprar
        if num_sells > num_buys * 1.1 and net_pos > num_buys:
            logging.info("[Rebalance] Demasiadas ventas, cancelando y colocando compras")
            sorted_sells = sorted(sell_orders, key=lambda o: o['price'], reverse=True)
            diff = min(num_sells - num_buys, net_pos - num_buys, max_diff)
            sells_to_cancel = sorted_sells[:diff]
            for s in sells_to_cancel:
                try:
                    await self.exchange.cancel_order(s['id'], self.symbol)
                    logging.info(f"Cancelada venta ID={s['id']} precio={s['price']}")
                except Exception as e:
                    logging.error(f"Error cancelando venta {s['id']}: {e}")

            if buy_orders:
                ref_price = min(o['price'] for o in buy_orders) * (1 - self.percentage_spread)
            else:
                ref_price = 0.0

            try:
                prices = calculate_order_prices_buy(ref_price, self.percentage_spread, diff, self.price_format)
                for p in prices:
                    amt = format_quantity(self.amount / p, self.amount_format)
                    await self.create_order('buy', amt, p)
                    logging.info(f"Creada compra {amt} @ {p}")
            except Exception as e:
                logging.error(f"[Rebalance] Error creando compras: {e}")

        # 3) Ajustar a self.num_orders
        await asyncio.sleep(0.05)
        open_orders_final = await self.exchange.fetch_open_orders(self.symbol)
        total_final = len(open_orders_final)
        if total_final < self.num_orders:
            faltan = self.num_orders - total_final
            logging.info(f"[Rebalance] Faltan {faltan} órdenes para completar la grid")
            if sell_orders:
                ref_price = max(o['price'] for o in sell_orders) * (1 + self.percentage_spread)
            else:
                ref_price = 0.0
            try:
                prices = calculate_order_prices_sell(ref_price, self.percentage_spread, faltan, self.price_format)
                for p in prices:
                    amt = format_quantity((self.amount * (1 - self.percentage_spread)) / p, self.amount_format)
                    await self.create_order('sell', amt, p)
                    logging.info(f"Creada venta extra {amt} @ {p}")
            except Exception as e:
                logging.error(f"[Rebalance] Error creando ventas extra: {e}")
        elif total_final > self.num_orders:
            extra = total_final - self.num_orders
            logging.info(f"[Rebalance] Hay {extra} órdenes extra, se eliminarán")
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
        mongo_uri = "mongodb+srv://trademate:n4iTxStjWPyPSDHl@cluster0.uxsok.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"
        client = motor.motor_asyncio.AsyncIOMotorClient(mongo_uri)
        db = client["Grid"]
        collection = db["Match Profit"]

        filter_doc = {
            "exchange": self.exchange_name,
            "account": self.account,
            "crypto_pair": self.symbol,
        }

        data = {
            "timestamp": datetime.datetime.utcnow(),
            "match_profit": self.match_profit,
            "number_of_matches": self.total_buys_filled,
            "net_position": self.total_sells_filled - self.total_buys_filled,
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