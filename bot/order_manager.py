import asyncio
import logging
from bot.helpers import calculate_order_prices, format_quantity

class OrderManager:
    def __init__(self, exchange, symbol, config):
        self.exchange = exchange
        self.symbol = symbol

        # Parámetros básicos de la estrategia
        self.percentage_spread = float(config['percentage_spread'])
        self.amount = float(config['amount'])
        self.num_orders = int(config['num_orders'])
        self.price_format = config.get('price_format')
        self.amount_format = config.get('amount_format')
        self.contract_size = config.get('contract_size')

        # Contadores de compras/ventas llenas y profit estimado
        self.total_buys_filled = 0
        self.total_sells_filled = 0
        self.match_profit = 0.0

    async def check_orders(self):
        """
        Bucle principal que escucha `watch_orders` y procesa cada
        evento de orden sin guardar estructuras, salvo contadores.
        """
        reconnect_attempts = 0
        while True:
            try:
                self.print_match_stats()  # imprime cada cierto tiempo
                orders = await self.exchange.watch_orders(self.symbol)
                if not orders:
                    continue

                for o in orders:
                    # procesar cada actualización
                    await self.process_order(o)

                reconnect_attempts = 0
            except Exception as e:
                reconnect_attempts += 1
                wait_time = min(2 ** reconnect_attempts, 60)
                logging.error(f"Error en check_orders (intento {reconnect_attempts}): {e}")
                logging.info(f"Reintentando en {wait_time} segundos...")
                await asyncio.sleep(wait_time)

    async def process_order(self, order):
        """
        Procesa la orden en base a la info de 'watch_orders':
         - Si se llenó por completo, incrementa contadores
         - Crea la orden contraria
         - No guarda estructuras de órdenes.
        """
        try:
            # Verifica si se llenó completamente
            filled = order.get('filled', 0.0)
            amount = order.get('amount', 0.0)
            status = order.get('status')
            side = order.get('side')
            price = order.get('price')

            if status == 'filled' and filled == amount:
                # Orden llena completamente
                if side == 'buy':
                    self.total_buys_filled += 1
                else:
                    self.total_sells_filled += 1
                    # Ganancia estimada para un grid estático: amount * spread
                    self.match_profit += (self.amount * self.percentage_spread)

                # Crear orden contraria
                if price is not None:
                    side_counter = 'sell' if side == 'buy' else 'buy'
                    spread_multiplier = (1 + self.percentage_spread) if side_counter == 'sell' else (1 - self.percentage_spread)
                    new_price = price * spread_multiplier

                    await self.create_order(side_counter, filled, new_price)
                else:
                    logging.warning(f"La orden {order.get('id')} se llenó sin price. No se crea la contraria.")

        except Exception as e:
            logging.error(f"Error procesando orden: {e}")

    async def create_order(self, side, amount, price):
        """
        Crea una nueva orden 'limit'. No se guarda en estructuras locales,
        solo se ejecuta y confiamos en 'watch_orders' para updates.
        """
        try:
            params = {'posSide': 'long'}  # si usas Hedge Mode, por ejemplo
            resp = await self.exchange.create_order(
                self.symbol, 'limit', side, amount, price, params=params
            )
            if resp:
                oid = resp['id']
                logging.info(f"Orden creada: {side.upper()} {amount} @ {price}, ID={oid}")
            else:
                logging.warning(f"No se recibió respuesta en create_order: {side.upper()} {amount} @ {price}")
        except Exception as e:
            logging.error(f"Error creando orden: {e}")

    async def place_orders(self, price):
        """
        Coloca la grid inicial (estática). Por ejemplo, todas las órdenes de compra.
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

    def print_match_stats(self):
        """
        Imprime contadores de compras/ventas llenas y
        profit estimado sin almacenar órdenes localmente.
        """
        print("\n=== ESTADÍSTICAS DE MATCH ===")
        print(f"  Buys llenas: {self.total_buys_filled}")
        print(f"  Sells llenas: {self.total_sells_filled}")
        print(f"  Profit estimado: {self.match_profit:.2f}")
        print("=== FIN ===\n")
