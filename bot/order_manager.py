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

    async def check_orders(self):
        """Monitorea el estado de las órdenes en tiempo real con reconexión inteligente."""
        reconnect_attempts = 0
        while True:
            try:
                orders = await self.exchange.watch_orders(self.symbol)
                if not orders:
                    continue
                for order in orders:
                    # Procesa cada orden de forma concurrente
                    asyncio.create_task(self.process_order(order))
                reconnect_attempts = 0
            except Exception as e:
                reconnect_attempts += 1
                wait_time = min(2 ** reconnect_attempts, 60)
                logging.error(f"Error en check_orders ({reconnect_attempts} intento): {e}")
                logging.info(f"Reintentando en {wait_time} segundos...")
                await asyncio.sleep(wait_time)

    async def process_order(self, order):
        """
        Procesa una orden ejecutada, coloca la orden contraria y 
        invoca el rebalanceo dinámico de la grid.
        """
        try:
            if order['filled'] == order['amount']:
                # La orden se llenó completamente.
                # Colocar la orden contraria:
                side_counter = 'sell' if order['side'] == 'buy' else 'buy'
                spread_multiplier = 1 + self.percentage_spread if side_counter == 'sell' else 1 - self.percentage_spread
                target_price = order['price'] * spread_multiplier
                await self.create_order(side_counter, order['amount'], target_price)
                
                # Rebalancear la grid de forma dinámica.
                await self.rebalance_grid(order)
        except Exception as e:
            logging.error(f"Error procesando orden: {e}")

    async def create_order(self, side, amount, price):
        """Crea una nueva orden de compra o venta y asegura que no se duplique."""
        try:
            order = await self.exchange.create_order(
                self.symbol, 'limit', side, amount, price, params={'posSide': 'long'}
            )
            if order:
                logging.info(f"Orden creada exitosamente: {side.upper()} {amount} @ {price}, ID: {order['id']}")
                return {'id': order['id'], 'price': price, 'amount': amount}
            logging.warning(f"No se recibió respuesta de la orden {side.upper()} @ {price}")
        except Exception as e:
            logging.error(f"Error creando orden: {e}")
        return None  # Evitar contar órdenes fallidas

    async def place_orders(self, price):
        """Coloca órdenes de compra en la grid estática inicial."""
        try:
            prices = calculate_order_prices(price, self.percentage_spread, self.num_orders, self.price_format)
            created_orders = 0  # Contador de órdenes creadas
            for p in prices:
                if created_orders >= self.num_orders:
                    break
                formatted_amount = format_quantity(self.amount / p / self.contract_size, self.amount_format)
                await self.create_order('buy', formatted_amount, p)
                created_orders += 1
        except Exception as e:
            logging.error(f"Error colocando órdenes: {e}")

    async def rebalance_grid(self, executed_order):
        """
        Rebalancea la grid de órdenes de forma dinámica tras que una orden se ejecute por completo.
        
        - Si la orden ejecutada es de compra (mercado bajista):
            * Se recalcula la grid de compras a partir del precio de la orden ejecutada.
            * Se cancelan las órdenes de compra que estén por encima del máximo del nuevo grid.
            * Se colocan nuevas órdenes de compra para completar el número total deseado.
        
        - Si la orden ejecutada es de venta (mercado alcista):
            * Se genera una grid de ventas ascendente a partir del precio ejecutado.
            * Se cancelan las órdenes de venta que estén por debajo del mínimo del nuevo grid.
            * Se colocan nuevas órdenes de venta para reponer la grid.
        """
        try:
            # Obtener órdenes abiertas actuales.
            open_orders = await self.exchange.fetch_open_orders(self.symbol)
            # Separar órdenes por lado.
            buy_orders = [o for o in open_orders if o['side'] == 'buy']
            sell_orders = [o for o in open_orders if o['side'] == 'sell']
            
            if executed_order['side'] == 'buy':
                # Orden de compra ejecutada: el precio bajó.
                new_base = executed_order['price']
                # Calcula la nueva grid de compras a partir del nuevo precio base.
                new_buy_prices = calculate_order_prices(new_base, self.percentage_spread, self.num_orders, self.price_format)
                # Cancelar órdenes de compra que estén por encima del precio máximo permitido en la nueva grid.
                max_new_buy = new_buy_prices[0]
                for order in buy_orders:
                    if order['price'] > max_new_buy:
                        try:
                            await self.exchange.cancel_order(order['id'], self.symbol)
                            logging.info(f"Cancelada orden de compra en {order['price']} fuera del nuevo grid.")
                        except Exception as cancel_error:
                            logging.error(f"Error cancelando orden de compra {order['id']}: {cancel_error}")
                # Actualizar las órdenes abiertas tras las cancelaciones.
                open_orders = await self.exchange.fetch_open_orders(self.symbol)
                buy_orders = [o for o in open_orders if o['side'] == 'buy']
                existing_buy_prices = {o['price'] for o in buy_orders}
                # Colocar las órdenes de compra que faltan.
                for price in new_buy_prices:
                    if price not in existing_buy_prices:
                        formatted_amount = format_quantity(self.amount / price / self.contract_size, self.amount_format)
                        await self.create_order('buy', formatted_amount, price)
                        logging.info(f"Nueva orden de compra colocada en {price} para rebalancear grid.")
            
            elif executed_order['side'] == 'sell':
                # Orden de venta ejecutada: el precio subió.
                new_base = executed_order['price']
                # Generar una grid de ventas ascendente a partir del precio ejecutado.
                new_sell_prices = [
                    format_price(new_base * (1 + self.percentage_spread) ** i, self.price_format)
                    for i in range(self.num_orders)
                ]
                # Cancelar órdenes de venta que estén por debajo del mínimo del nuevo grid.
                min_new_sell = new_sell_prices[0]
                for order in sell_orders:
                    if order['price'] < min_new_sell:
                        try:
                            await self.exchange.cancel_order(order['id'], self.symbol)
                            logging.info(f"Cancelada orden de venta en {order['price']} fuera del nuevo grid.")
                        except Exception as cancel_error:
                            logging.error(f"Error cancelando orden de venta {order['id']}: {cancel_error}")
                # Actualizar las órdenes abiertas.
                open_orders = await self.exchange.fetch_open_orders(self.symbol)
                sell_orders = [o for o in open_orders if o['side'] == 'sell']
                existing_sell_prices = {o['price'] for o in sell_orders}
                # Colocar las órdenes de venta que falten.
                for price in new_sell_prices:
                    if price not in existing_sell_prices:
                        formatted_amount = format_quantity(self.amount / price / self.contract_size, self.amount_format)
                        await self.create_order('sell', formatted_amount, price)
                        logging.info(f"Nueva orden de venta colocada en {price} para rebalancear grid.")
                        
        except Exception as e:
            logging.error(f"Error en el rebalanceo de la grid: {e}")
