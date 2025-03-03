import asyncio
import ccxt.pro as ccxtpro
import logging
import uvloop
import aiorun
from bot.order_manager import OrderManager

# Configurar logging avanzado
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


# Mejor rendimiento con uvloop (solo para Linux/macOS)
asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

class BotMain:
    def __init__(self, config):
        self.config = config
        self.price = 0
        self.match = 0
        self.exchange = None
        self.all_ok = False
        self.symbol = config.get('symbols', [])[0] 
        self.percentage_spread = float(config['percentage_spread'])
        self.amount = float(config['amount'])
        self.num_orders = int(config['num_orders'])
        self.price_format = config.get('price_format')
        self.amount_format = config.get('amount_format')
        self.contract_size = config.get('contract_size')
        self.order_manager = None

    def initialize_params(self):
        if not self.symbol:
            raise ValueError("Symbol must be specified in config.")
        
        self.exchange = ccxtpro.okx({
            "apiKey": self.config["exchange_options"]["apiKey"],
            "secret": self.config["exchange_options"]["secret"],
            "password": self.config["exchange_options"]["password"],
            'enableRateLimit': False,
        })
        
        self.order_manager = OrderManager(self.exchange, self.symbol, self.config)
        logging.info("Exchange initialized with given API keys.")
    
    async def check_prices(self):
        """Obtiene los precios del mercado en tiempo real con reconexión inteligente."""
        await self.exchange.load_markets()
        reconnect_attempts = 0
        while True:
            try:
                if not self.all_ok and self.price > 0:
                    await self.order_manager.place_orders(self.price)
                    self.all_ok = True
                
                resp = await self.exchange.watch_bids_asks([self.symbol])
                self.price = float((resp[self.symbol]['bid'] + resp[self.symbol]['ask']) / 2)
                reconnect_attempts = 0 
            except Exception as e:
                reconnect_attempts += 1
                wait_time = min(2 ** reconnect_attempts, 60)  # Backoff exponencial
                logging.error(f"Error en check_prices ({reconnect_attempts} intento): {e}")
                logging.info(f"Reintentando en {wait_time} segundos...")
                await asyncio.sleep(wait_time)
    
    async def async_run(self):
        """Ejecución principal del bot."""
        try:
            await asyncio.gather(
                asyncio.create_task(self.check_prices()),
                asyncio.create_task(self.order_manager.check_orders()),
            )
        except Exception as e:
            logging.error(f"Error crítico en el bot: {e}")
        finally:
            await self.close()
    
    async def close(self):
        if self.exchange:
            await self.exchange.close()
            logging.info("Exchange connection closed.")

    def run(self):
        self.initialize_params()
        logging.info('-'*60)
        logging.info('Bot is running')
        logging.info('-'*60)
        try:
            aiorun.run(self.async_run())  # Usar aiorun para mejor manejo de señales
        except Exception as e:
            logging.critical(f'Bot stopped unexpectedly: {e}')





# import asyncio
# import ccxt.pro as ccxtpro
# import logging
# import uvloop
# import aiorun
# from bot.order_manager import OrderManager

# # Configurar logging
# logging.basicConfig(
#     level=logging.INFO, 
#     format='%(asctime)s - %(levelname)s - %(message)s'
# )

# # Configurar uvloop para mejorar rendimiento (si estás en Linux/macOS)
# asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

# class BotMain:
#     def __init__(self, config):
#         self.config = config
#         self.exchange = None
#         self.order_manager = None
#         self.symbol = config.get('symbols', [])[0]
#         self.price = 0

#     def initialize_params(self):
#         if not self.symbol:
#             raise ValueError("Symbol must be specified in config.")

#         # Inicializa el exchange ccxtpro
#         self.exchange = ccxtpro.okx({
#             "apiKey": self.config["exchange_options"]["apiKey"],
#             "secret": self.config["exchange_options"]["secret"],
#             "password": self.config["exchange_options"]["password"],
#             'enableRateLimit': False,
#         })

#         self.order_manager = OrderManager(self.exchange, self.symbol, self.config)
#         logging.info("Exchange initialized with given API keys.")

#     async def check_prices(self):
#         """
#         Obtiene los precios del mercado en tiempo real.
#         Usa watch_bids_asks (o watch_ticker) y actualiza self.price con el mid-price.
#         """
#         await self.exchange.load_markets()
#         reconnect_attempts = 0
#         while True:
#             try:
#                 resp = await self.exchange.watch_bids_asks([self.symbol])
#                 bid = resp[self.symbol]['bid']
#                 ask = resp[self.symbol]['ask']
#                 self.price = float((bid + ask) / 2)
#                 reconnect_attempts = 0
#             except Exception as e:
#                 reconnect_attempts += 1
#                 wait_time = min(2 ** reconnect_attempts, 60)
#                 logging.error(f"Error en check_prices ({reconnect_attempts} intento): {e}")
#                 logging.info(f"Reintentando en {wait_time} segundos...")
#                 await asyncio.sleep(wait_time)

#     async def async_run(self):
#         """
#         Ejecución principal del bot.
#         Se lanzan 3 tareas:
#          - Una para monitorear precios (check_prices).
#          - Una para colocar la grid inicial (place_orders) cuando tengamos el primer precio.
#          - Una para monitorear y procesar órdenes en tiempo real (check_orders).
#         """
#         # Primero esperamos a tener un precio inicial antes de colocar las órdenes
#         while self.price > 0:
#             # Esperar medio segundo, se actualiza cuando check_prices obtenga algo
#             await asyncio.sleep(0.5)

#         # Colocar grid inicial de compras
#         await self.order_manager.place_orders(self.price)

#         # Monitorear y procesar órdenes
#         await asyncio.gather(
#             self.check_prices(),
#             self.order_manager.check_orders()
#         )

#     async def close(self):
#         if self.exchange:
#             await self.exchange.close()
#             logging.info("Exchange connection closed.")

#     def run(self):
#         self.initialize_params()
#         logging.info('-'*60)
#         logging.info('Bot is running')
#         logging.info('-'*60)

#         try:
#             # Usar aiorun.run para un manejo de señales robusto (CTRL+C, etc.)
#             aiorun.run(self.async_run(), stop_on_unhandled_errors=True)
#         except Exception as e:
#             logging.critical(f'Bot stopped unexpectedly: {e}')
