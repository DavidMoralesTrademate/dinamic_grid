import asyncio
import logging
from sortedcontainers import SortedDict
from bot.helpers import calculate_order_prices, format_quantity

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
                self.print_stats()  # Imprime contadores y estado
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
            prices = calculate_order_prices(
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

        num_orders = self.exchange.open_orders(self.symbol)

        print(num_orders)

