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

        print(len(open_orders))
        print(len(buy_orders))
        print(len(sell_orders))

        # rebalancear compras
        if len(sell_orders) > len(buy_orders) + 1*1: 
            print('necesitamos cancelar ventas y poner compras')

            sorted_sells = sorted(sell_orders, key=lambda o: o['price'], reverse=True)

            # Decide cuántas cancelar, ej: diff = len(sell_orders) - len(buy_orders)
            diff = (len(sell_orders) - len(buy_orders))  # o +1
            sells_to_cancel = sorted_sells[:diff]

            if diff > self.num_orders/2:
                diff = math.floor(open_orders / 2)

            # Cancelar esas sells
            for s in sells_to_cancel:
                await self.exchange.cancel_order(s['id'], self.symbol)

            sorted_buys = sorted(buy_orders, key=lambda o: o['price'])
            
            try:
                prices = calculate_order_prices_buy(
                    sorted_buys[0]['price'] * 1-self.percentage_spread, 
                    self.percentage_spread, 
                    diff, 
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


        # rebalancear ventas
        if len(buy_orders) > len(sell_orders) + 1*1 and net_pos > len(sell_orders):
            print('Puede que nececite mas ventas')
            print(f'net_pos: {net_pos} sell_orders: {len(sell_orders)}') 
            
            await asyncio.sleep(0.1)

            if net_pos == len(sell_orders):
                print('nos saliumos')
                return
            
            sorted_buys = sorted(buy_orders, key=lambda o: o['price'])

            diff = (len(buy_orders) - len(sell_orders))
            if diff >= net_pos:
                diff = net_pos

            if diff > self.num_orders/2:
                diff = math.floor(open_orders / 2)
                
            buys_to_cancel = sorted_buys[:diff]

            # Cancelar esas buys
            for s in buys_to_cancel:
                await self.exchange.cancel_order(s['id'], self.symbol)

            sorted_sells = sorted(sell_orders, key=lambda o: o['price'], reverse=True)

            try:
                prices = calculate_order_prices_sell(
                    sorted_sells[0]['price'] * 1+self.percentage_spread, 
                    self.percentage_spread, 
                    diff, 
                    self.price_format
                )
                count = 0
                for p in prices:
                    if count >= self.num_orders:
                        break
                    amt = format_quantity(
                        (self.amount * (1-self.percentage_spread)) / p / self.contract_size, 
                        self.amount_format 
                    )
                    await self.create_order('sell', amt, p)
                    count += 1
            except Exception as e:
                logging.error(f"Error en place_orders: {e}")