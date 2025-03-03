import asyncio
import logging
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

        # Contadores de órdenes llenas y un profit simple
        self.total_buys_filled = 0
        self.total_sells_filled = 0
        self.match_profit = 0.0  # Ganancia estimada cada vez que se llena una venta

    async def check_orders(self):
        """
        Bucle principal: escucha con watch_orders.
        Si una orden se llena (status in ('filled','closed')), dispara process_order.
        """
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
                wait_time = min(2**reconnect_attempts, 60)
                logging.error(f"Error en check_orders (intento {reconnect_attempts}): {e}")
                logging.info(f"Reintentando en {wait_time} s...")
                await asyncio.sleep(wait_time)

    async def process_order(self, order):
        """
        Si la orden se llenó completamente (status in ('filled','closed')) y filled == amount,
        crea la orden contraria y sube los contadores.
        """
        try:
            side = order.get('side')  # 'buy' o 'sell'
            filled = order.get('filled', 0.0)
            price = order.get('price')

            # Revisar si se llenó (muchos exchanges usan 'closed' para fill total)
            if order.get('filled') == order.get('amount'):
                if side == 'buy':
                    self.total_buys_filled += 1
                    # Crear la venta
                    if price is not None:
                        side_counter = 'sell'
                        new_price = price * (1 + self.percentage_spread)
                        await self.create_order(side_counter, filled, new_price)
                    else:
                        logging.warning(f"La orden buy se llenó sin price. No se crea venta.")
                else:
                    self.total_sells_filled += 1
                    # Sumar profit estimado
                    self.match_profit += (self.amount * self.percentage_spread)
                    # Crear la compra
                    if price is not None:
                        side_counter = 'buy'
                        new_price = price * (1 - self.percentage_spread)
                        await self.create_order(side_counter, filled, new_price)
                    else:
                        logging.warning(f"La orden sell se llenó sin price. No se crea compra.")

        except Exception as e:
            logging.error(f"Error procesando orden: {e}")

    async def create_order(self, side, amount, price):
        """
        Crea una nueva orden limit sin almacenar estructuras.
        """
        try:
            params = {'posSide': 'long'}  # Para hedge mode en OKX, p.ej
            resp = await self.exchange.create_order(
                self.symbol, 'limit', side, amount, price, params=params
            )
            if resp:
                oid = resp['id']
                logging.info(f"Orden creada: {side.upper()} {amount} @ {price}, ID={oid}")
            else:
                logging.warning(f"No se recibió respuesta create_order: {side} {amount} @ {price}")
        except Exception as e:
            logging.error(f"Error creando orden: {e}")

    async def place_orders(self, current_price):
        """
        Coloca únicamente órdenes de compra (grid alcista) por debajo del precio actual
        usando calculate_order_prices. No pone ventas inicialmente.
        """
        try:
            prices = calculate_order_prices(
                current_price,
                self.percentage_spread,
                self.num_orders,
                self.price_format
            )
            created = 0
            for p in prices:
                if created >= self.num_orders:
                    break
                formatted_amount = format_quantity(self.amount / p / self.contract_size, self.amount_format)
                await self.create_order('buy', formatted_amount, p)
                created += 1
        except Exception as e:
            logging.error(f"Error al place_orders: {e}")

    def print_stats(self):
        """
        Imprime contadores de buys, sells y profit estimado.
        """
        print("\n=== Grid Alcista Stats ===")
        print(f"  Buys llenas: {self.total_buys_filled}")
        print(f"  Sells llenas: {self.total_sells_filled}")
        print(f"  Profit estimado (spread): {self.match_profit:.2f}")
        print("=== Fin de Stats ===\n")
