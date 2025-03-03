# import asyncio
# import logging
# from bot.helpers import calculate_order_prices, format_quantity, format_price

# class OrderManager:
#     def __init__(self, exchange, symbol, config):
#         self.exchange = exchange
#         self.symbol = symbol
#         self.percentage_spread = float(config['percentage_spread'])
#         self.amount = float(config['amount'])
#         self.num_orders = int(config['num_orders'])
#         self.price_format = config.get('price_format')
#         self.amount_format = config.get('amount_format')
#         self.contract_size = config.get('contract_size')
#         self.order_limit = 10  # Límite de órdenes abiertas permitidas

#     async def check_orders(self):
#         """Monitorea el estado de las órdenes en tiempo real con reconexión inteligente."""
#         reconnect_attempts = 0
#         while True:
#             try:
#                 orders = await self.exchange.watch_orders(self.symbol)
#                 if not orders:
#                     continue
#                 for order in orders:
#                     await self.process_order(order)
#                 reconnect_attempts = 0  # Resetear intentos si hay éxito
#             except Exception as e:
#                 reconnect_attempts += 1
#                 wait_time = min(2 ** reconnect_attempts, 60)  # Backoff exponencial
#                 logging.error(f"Error en check_orders ({reconnect_attempts} intento): {e}")
#                 logging.info(f"Reintentando en {wait_time} segundos...")
#                 await asyncio.sleep(wait_time)
    
#     async def process_order(self, order):
#         """Procesa una orden ejecutada y coloca una orden contraria."""
#         try:
#             if order['filled'] == order['amount']:
#                 side = 'sell' if order['side'] == 'buy' else 'buy'
#                 target_price = order['price'] * (1 + self.percentage_spread if side == 'sell' else 1 - self.percentage_spread)
#                 await self.create_order(side, order['amount'], target_price)
#         except Exception as e:
#             logging.error(f"Error procesando orden: {e}")
    
#     async def create_order(self, side, amount, price):
#         """Crea una nueva orden de compra o venta."""
#         try:
#             formatted_amount = format_quantity(amount / price / self.contract_size, self.amount_format)
#             await self.exchange.create_order(self.symbol, 'limit', side, formatted_amount, price, params={'posSide': 'long'})
#             logging.info(f"Orden creada: {side.upper()} {formatted_amount} @ {price}")
#         except Exception as e:
#             logging.error(f"Error creando orden: {e}")


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
        self.order_limit = 10  # Límite de órdenes abiertas permitidas
        self.buy_orders = []  # Lista de órdenes de compra activas
        self.sell_orders = []  # Lista de órdenes de venta activas

    async def check_orders(self):
        """Monitorea el estado de las órdenes en tiempo real con reconexión inteligente."""
        reconnect_attempts = 0
        while True:
            try:
                orders = await self.exchange.watch_orders(self.symbol)
                if not orders:
                    continue
                for order in orders:
                    await self.process_order(order)
                reconnect_attempts = 0  # Resetear intentos si hay éxito
            except Exception as e:
                reconnect_attempts += 1
                wait_time = min(2 ** reconnect_attempts, 60)  # Backoff exponencial
                logging.error(f"Error en check_orders ({reconnect_attempts} intento): {e}")
                logging.info(f"Reintentando en {wait_time} segundos...")
                await asyncio.sleep(wait_time)
    
    async def process_order(self, order):
        """Procesa una orden ejecutada y ajusta el grid dinámicamente."""
        try:
            if order['filled'] == order['amount']:
                side = 'sell' if order['side'] == 'buy' else 'buy'
                target_price = order['price'] * (1 + self.percentage_spread if side == 'sell' else 1 - self.percentage_spread)
                new_order = await self.create_order(side, order['amount'], target_price)
                
                if new_order:
                    if side == 'buy':
                        self.buy_orders.append(new_order)
                        if len(self.buy_orders) > self.num_orders // 2:
                            removed_order = self.sell_orders.pop(0)
                            await self.cancel_order(removed_order)
                    else:
                        self.sell_orders.append(new_order)
                        if len(self.sell_orders) > self.num_orders // 2:
                            removed_order = self.buy_orders.pop(0)
                            await self.cancel_order(removed_order)
        except Exception as e:
            logging.error(f"Error procesando orden: {e}")
    
    async def create_order(self, side, amount, price):
        """Crea una nueva orden de compra o venta."""
        try:
            formatted_amount = format_quantity(amount / price / self.contract_size, self.amount_format)
            order = await self.exchange.create_order(self.symbol, 'limit', side, formatted_amount, price, params={'posSide': 'long'})
            logging.info(f"Orden creada: {side.upper()} {formatted_amount} @ {price}")
            return {'id': order['id'], 'price': price, 'amount': formatted_amount}
        except Exception as e:
            logging.error(f"Error creando orden: {e}")
            return None
    
    async def cancel_order(self, order):
        """Cancela una orden específica."""
        try:
            await self.exchange.cancel_order(order['id'], self.symbol)
            logging.info(f"Orden cancelada: {order['id']} @ {order['price']}")
        except Exception as e:
            logging.error(f"Error cancelando orden: {e}")
    
    async def place_orders(self, price):
        """Coloca órdenes de compra o venta en el grid."""
        try:
            prices = calculate_order_prices(price, self.percentage_spread, self.num_orders, self.price_format)
            tasks = [self.create_order('buy', self.amount, p) for p in prices]
            await asyncio.gather(*tasks, return_exceptions=True)
        except Exception as e:
            logging.error(f"Error colocando órdenes: {e}")