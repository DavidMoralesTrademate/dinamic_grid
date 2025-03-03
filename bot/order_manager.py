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
        self.order_limit = 100  # Límite de órdenes abiertas permitidas
        
        self.buy_orders = []  # Órdenes de compra activas
        self.sell_orders = []  # Órdenes de venta activas
        self.last_grid_price = None  # Último precio de referencia del grid

    async def track_market(self):
        """Monitorea el mercado en tiempo real y ajusta las órdenes dinámicamente."""
        while True:
            try:
                ticker = await self.exchange.fetch_ticker(self.symbol)
                current_price = ticker['last']
                await self.adjust_orders(current_price)
                await asyncio.sleep(1)  # Ajustar cada segundo
            except Exception as e:
                logging.error(f"Error en track_market: {e}")
                await asyncio.sleep(5)  # Esperar más si hay error

    async def adjust_orders(self, current_price):
        """Ajusta las órdenes si el precio se ha movido."""
        if self.last_grid_price is None:
            self.last_grid_price = current_price
            await self.place_initial_orders(current_price)
            return
        
        price_difference = current_price - self.last_grid_price
        if abs(price_difference) >= (self.percentage_spread * self.last_grid_price):
            if price_difference > 0:
                await self.shift_grid_up()
            else:
                await self.shift_grid_down()
            self.last_grid_price = current_price

    async def place_initial_orders(self, price):
        """Coloca las órdenes iniciales en el grid."""
        try:
            prices = calculate_order_prices(price, self.percentage_spread, self.num_orders, self.price_format)
            
            for p in prices[:self.num_orders // 2]:
                order = await self.create_order('buy', self.amount, p)
                self.buy_orders.append(order)
                
            for p in prices[self.num_orders // 2:]:
                order = await self.create_order('sell', self.amount, p)
                self.sell_orders.append(order)
            
            logging.info(f"Grid inicial colocado desde {prices[0]} hasta {prices[-1]}")
        except Exception as e:
            logging.error(f"Error colocando órdenes iniciales: {e}")
    
    async def shift_grid_up(self):
        """Si el precio sube, eliminamos la compra más baja y agregamos una venta más alta."""
        if self.buy_orders:
            buy_order = self.buy_orders.pop(0)  # Quitamos la compra más baja
            await self.cancel_order(buy_order)
            new_sell_price = format_price(self.sell_orders[-1]['price'] * (1 + self.percentage_spread), self.price_format)
            new_sell_order = await self.create_order('sell', self.amount, new_sell_price)
            self.sell_orders.append(new_sell_order)
            logging.info(f"Precio subió: Quitada compra y agregada venta en {new_sell_price}")
    
    async def shift_grid_down(self):
        """Si el precio baja, eliminamos la venta más alta y agregamos una compra más baja."""
        if self.sell_orders:
            sell_order = self.sell_orders.pop()  # Quitamos la venta más alta
            await self.cancel_order(sell_order)
            new_buy_price = format_price(self.buy_orders[0]['price'] * (1 - self.percentage_spread), self.price_format)
            new_buy_order = await self.create_order('buy', self.amount, new_buy_price)
            self.buy_orders.insert(0, new_buy_order)
            logging.info(f"Precio bajó: Quitada venta y agregada compra en {new_buy_price}")
    
    async def create_order(self, side, amount, price):
        """Crea una nueva orden de compra o venta."""
        try:
            formatted_amount = format_quantity(amount / price / self.contract_size, self.amount_format)
            order = await self.exchange.create_order(self.symbol, 'limit', side, formatted_amount, price, params={'posSide': 'long'})
            logging.info(f"Orden creada: {side.upper()} {formatted_amount} @ {price}")
            return order
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