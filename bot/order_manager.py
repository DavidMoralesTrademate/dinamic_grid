import asyncio
import logging
from sortedcontainers import SortedDict
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

        # Contadores
        self.total_buys_filled = 0
        self.total_sells_filled = 0
        self.match_profit = 0.0  # Ganancia estimada en cada venta


    ### -------------------------------------------------
    ###       Lógica Principal de watch_orders
    ### -------------------------------------------------
    async def check_orders(self):
        reconnect_attempts = 0
        while True:
            try:
                self.print_stats()  # cada iter, imprime
                orders = await self.exchange.watch_orders(self.symbol)
                if not orders:
                    continue

                for o in orders:
                    await self.process_order(o)

                reconnect_attempts = 0
            except Exception as e:
                reconnect_attempts += 1
                wt = min(2**reconnect_attempts, 60)
                logging.error(f"Error en check_orders (int {reconnect_attempts}): {e}")
                logging.info(f"Reintentando en {wt} segundos...")
                await asyncio.sleep(wt)

    async def process_order(self, order):
        """
        Actualiza nuestras estructuras. Si la orden se llenó -> crea la contraria.
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

            # Revisar si se llenó: 
            if status in ('filled','closed') and filled == amount and amount > 0.0:

                # Actualizar contadores
                if side == 'buy':
                    self.total_buys_filled += 1
                    # Crear la venta
                    if price is not None:
                        sell_price = price * (1 + self.percentage_spread)
                        await self.create_order('sell', filled, sell_price)
                    else:
                        logging.warning(f"Orden buy {oid} sin precio, no creo venta.")
                else:  # side == 'sell'
                    self.total_sells_filled += 1
                    # Profit estimado
                    self.match_profit += (self.amount * self.percentage_spread)

                    # Crear la compra
                    if price is not None:
                        buy_price = price * (1 - self.percentage_spread)
                        await self.create_order('buy', filled, buy_price)
                    else:
                        logging.warning(f"Orden sell {oid} sin precio, no creo compra.")

        except Exception as e:
            logging.error(f"Error en process_order: {e}")

    ### -------------------------------------------------
    ###       Creación de órdenes
    ### -------------------------------------------------
    async def create_order(self, side, amount, price):
        """
        Crea nueva orden limit, la almacena en orders_by_id / orders_by_price
        """
        try:
            params = {'posSide': 'long'}  # Hedge Mode (OKX), ajústalo si requieres 'short'
            await self.exchange.create_order(
                self.symbol, 
                'limit', 
                side, 
                amount, 
                price, 
                params=params
            )
            
        except Exception as e:
            logging.error(f"Error creando orden: {e}")
        return None

    async def place_orders(self, initial_price):
        """
        Coloca un grid alcista: solo órdenes de compra por debajo del precio
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
                amt = format_quantity(self.amount / p / self.contract_size, self.amount_format)
                await self.create_order('buy', amt, p)
                count += 1
        except Exception as e:
            logging.error(f"Error al place_orders: {e}")

    ### -------------------------------------------------
    ###       Impresión de Resultados
    ### -------------------------------------------------
    def print_stats(self):
        """
        Imprime contadores y un listado de órdenes activas (opcional).
        """
        print("\n=== Grid Alcista Stats ===")
        print(f"  Buys llenas: {self.total_buys_filled}")
        print(f"  Sells llenas: {self.total_sells_filled}")
        print(f"  Profit estimado: {self.match_profit:.4f}")
        print("=== Órdenes Activas (resumen) ===")

        print("=== Fin ===\n")
