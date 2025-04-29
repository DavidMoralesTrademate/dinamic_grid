import asyncio
import ccxt.pro as ccxtpro
import logging
import uvloop
import aiorun
from inverse.order_manager import OrderManagerBearish

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
        
        self.exchange = ccxtpro.cryptocom({
            "apiKey": self.config["exchange_options"]["apiKey"],
            "secret": self.config["exchange_options"]["secret"],
            'enableRateLimit': False,
        })
        
        self.order_manager = OrderManagerBearish(self.exchange, self.symbol, self.config)
        logging.info("Exchange initialized with given API keys.")
    
    async def check_prices(self):
        """Obtiene los precios del mercado en tiempo real con reconexión inteligente."""
        await self.exchange.load_markets()
        reconnect_attempts = 0
        while True:
            try:
                if not self.all_ok and self.price > 0:
                    await self.order_manager.place_orders(87300)
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
    
    async def rebalance_loop(self):
        await asyncio.sleep(10)
        while True:
            await asyncio.sleep(1)
            await self.order_manager.rebalance()

    async def send_data(self):
        await asyncio.sleep(300)
        while True:
            await asyncio.sleep(300)
            await self.order_manager.data_send()

    async def async_run(self):
        """Ejecución principal del bot."""
        try:
            await asyncio.gather(
                asyncio.create_task(self.check_prices()),
                asyncio.create_task(self.order_manager.check_orders()),
                asyncio.create_task(self.rebalance_loop()),
                asyncio.create_task(self.send_data()),
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
