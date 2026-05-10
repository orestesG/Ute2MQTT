#!/usr/bin/env python3
"""
Ute2MQTT - Punto de Entrada Principal.

Obtiene datos de consumo eléctrico del Proveedor de Energía y los publica vía MQTT.
"""

import os
import sys
import logging
import signal
from datetime import datetime, date
from typing import Optional

from ute.session import UTESession
from ute.mqtt import MQTTPublisher
from scheduler import DailyScheduler
from ute.credentials import CredentialsManager
from ute.tariffs import TariffProcessor

# Configuración de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class Ute2MQTT:
    """Clase principal que orquesta la recolección de datos del Proveedor y publicación MQTT."""
    
    def __init__(self):
        """Inicializa el cliente con la configuración del entorno."""
        # Configuración de cuenta
        self.account_id = os.environ.get("UTE_ACCOUNT_ID")
        
        # Configuración de almacenamiento de credenciales
        storage_path = os.environ.get("CREDENTIALS_PATH", "./credentials")
        self.creds_manager = CredentialsManager(storage_path)
        
        # Configuración del servicio (Optimizacion)
        self.service_id = os.environ.get("UTE_SERVICE_ID")
        self.service_point_id = os.environ.get("UTE_SERVICE_POINT_ID")
        self.tariff = os.environ.get("UTE_TARIFF")
        self.schedule_code = os.environ.get("UTE_SCHEDULE_CODE")
        
        if not all([self.service_id, self.service_point_id, self.tariff]):
            logger.error("Faltan variables de entorno del servicio (UTE_SERVICE_ID, etc). Ejecuta setup.py.")
            sys.exit(1)
            
        self.tariff = self.tariff.upper()
        
        # Configuración MQTT
        self.mqtt_broker = os.environ.get("MQTT_BROKER", "localhost")
        self.mqtt_port = int(os.environ.get("MQTT_PORT", "1883"))
        self.mqtt_username = os.environ.get("MQTT_USERNAME")
        self.mqtt_password = os.environ.get("MQTT_PASSWORD")
        self.mqtt_topic_prefix = os.environ.get("MQTT_TOPIC_PREFIX", "energy")
        self.mqtt_client_id = os.environ.get("MQTT_CLIENT_ID")
        self.mqtt_discovery_prefix = os.environ.get("MQTT_DISCOVERY_PREFIX", "discovery")
        
        # Configuración del planificador
        self.time_window = os.environ.get("SCHEDULE_TIME", "AM").upper()
        
        # Inicializar Sesión
        try:
            self.session = UTESession(self.creds_manager)
        except ValueError as e:
            logger.error(str(e))
            logger.error("Ejecutar setup.py primero para configurar")
            sys.exit(1)
        
        # Validar configuración requerida
        if not self.account_id:
            logger.error("Falta variable de entorno UTE_ACCOUNT_ID")
            sys.exit(1)
            
        if self.tariff in ("TRT", "TRD") and not self.schedule_code:
            logger.error(f"Para tarifa {self.tariff} se requiere UTE_SCHEDULE_CODE en el .env (ej. TRIPLERES19)")
            sys.exit(1)
            
        # Inicializar componentes
        self.mqtt: Optional[MQTTPublisher] = None
        self.scheduler: Optional[DailyScheduler] = None
        
        # Caché para información del servicio
        # self.schedule_code ya se carga del entorno
    
    
    
    def fetch_and_publish(self):
        """Tarea principal: obtener datos y publicar a MQTT."""
        logger.info("Iniciando obtención de datos...")
        
        # Obtener cliente autenticado desde la sesión
        client = self.session.get_client()
        if not client:
            logger.error("No se pudo establecer sesión con el Proveedor (Credenciales inválidas o error de red)")
            return
        
        
        
        # Obtener consumo actual
        consumption = client.get_current_consumption(self.account_id)
        if not consumption:
            logger.error("Falló al obtener consumo")
            return
        
        # Obtener deuda total
        debt = client.get_total_debt(self.account_id)
        
        # Registrar error de simulation si la API lo indica
        if consumption.get("errorMessage"):
            logger.warning(f"Simulation API: {consumption['errorMessage']}")

        # Preparar datos base
        period_start = consumption.get("initialDate")
        period_end   = consumption.get("finalDate")

        # Fallback: si la API no retorna fechas, usar el mes calendario actual
        if not period_start or not period_end:
            today = date.today()
            period_start = today.replace(day=1).strftime("%Y-%m-%d")
            period_end   = today.strftime("%Y-%m-%d")
            logger.info(f"Fechas de período no disponibles desde simulation; usando mes actual: {period_start} → {period_end}")

        state = {
            "current_consumption": consumption.get("currentConsumption", 0),
            "current_spending": consumption.get("currentSpending", 0),
            "total_debt": debt or 0,
            "tariff": self.tariff,
            "period_start": period_start,
            "period_end": period_end,
        }

        # Obtener y procesar bandas si corresponde
        if self.schedule_code:
            band_data = client.get_consumption_by_band(
                self.service_point_id,
                self.schedule_code,
                period_start,
                period_end
            )

            if band_data:
                processed_bands = TariffProcessor.process_bands(self.tariff, band_data)
                state.update(processed_bands)
                # Calcular consumo total desde las bandas si simulation no lo dio
                if not consumption.get("currentConsumption"):
                    state["current_consumption"] = sum(processed_bands.values())
        
        logger.info(f"Datos recolectados: {state}")
        
        # Publicar a MQTT
        try:
            self.mqtt = MQTTPublisher(
                broker=self.mqtt_broker,
                port=self.mqtt_port,
                username=self.mqtt_username,
                password=self.mqtt_password,
                topic_prefix=self.mqtt_topic_prefix,
                client_id=self.mqtt_client_id,
                discovery_prefix=self.mqtt_discovery_prefix
            )
            
            if self.mqtt.connect():
                 self.mqtt.publish_discovery(self.service_id, self.account_id, self.tariff)
                 self.mqtt.publish_state(self.service_id, state)
                 self.mqtt.disconnect()
            else:
                 logger.error("No se pudo conectar al broker MQTT para publicar")
                 
        except Exception as e:
            logger.error(f"Error durante la publicación MQTT: {e}")
        finally:
            self.mqtt = None
    
    def run(self):
        """Ejecuta el cliente con planificador."""
        logger.info("Iniciando Ute2MQTT...")
        logger.info(f"Cuenta: {self.account_id}")
        
        # Manejar señales
        def signal_handler(sig, frame):
            logger.info("Apagado solicitado...")
            if self.scheduler:
                self.scheduler.stop()
            if self.mqtt:
                self.mqtt.disconnect()
            sys.exit(0)
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        self.scheduler = DailyScheduler(
            task=self.fetch_and_publish,
            time_window=self.time_window,
            run_on_start=True
        )
        self.scheduler.start()


def main():
    app = Ute2MQTT()
    app.run()


if __name__ == "__main__":
    main()

