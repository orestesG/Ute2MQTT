#!/usr/bin/env python3
"""
Ute2MQTT - Punto de Entrada Principal.

Obtiene datos de consumo eléctrico del Proveedor de Energía y los publica vía MQTT.
"""

import os
import sys
import logging
import signal
import time
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
        _interval_env = os.environ.get("SCHEDULE_INTERVAL_HOURS", "").strip()
        self.schedule_interval_hours: Optional[float] = float(_interval_env) if _interval_env else None
        
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
            self.schedule_code = "TRIPLERES19"
            logger.warning(f"UTE_SCHEDULE_CODE no configurado para tarifa {self.tariff}; usando default: TRIPLERES19 (horario punta 19-23h)")
            
        # Inicializar componentes
        self.mqtt: Optional[MQTTPublisher] = None
        self.scheduler: Optional[DailyScheduler] = None
        self.next_run_at: Optional[datetime] = None
        
        # Caché para información del servicio
        # self.schedule_code ya se carga del entorno
    
    
    
    def _fetch_with_retry(self, func, retries: int = 2, base_delay: int = 30):
        """Ejecuta func con hasta `retries` reintentos y backoff exponencial."""
        for attempt in range(retries + 1):
            result = func()
            if result is not None:
                return result
            if attempt < retries:
                delay = base_delay * (2 ** attempt)
                logger.warning(f"Intento {attempt + 1} fallido, reintentando en {delay}s...")
                time.sleep(delay)
        return None

    def _publish_availability(self, online: bool):
        """Abre una conexión MQTT efímera para publicar el estado de availability."""
        try:
            publisher = MQTTPublisher(
                broker=self.mqtt_broker,
                port=self.mqtt_port,
                username=self.mqtt_username,
                password=self.mqtt_password,
                topic_prefix=self.mqtt_topic_prefix,
                client_id=self.mqtt_client_id,
                discovery_prefix=self.mqtt_discovery_prefix,
            )
            if publisher.connect():
                publisher.publish_availability(self.service_id, online)
                publisher.disconnect()
        except Exception as e:
            logger.error(f"Error publicando availability: {e}")

    def fetch_and_publish(self):
        """Tarea principal: obtener datos y publicar a MQTT."""
        logger.info("Iniciando obtención de datos...")
        
        # Obtener cliente autenticado desde la sesión
        client = self.session.get_client()
        if not client:
            logger.error("No se pudo establecer sesión con el Proveedor (Credenciales inválidas o error de red)")
            self._publish_availability(False)
            return
        
        
        
        # Obtener consumo actual (con reintentos)
        consumption = self._fetch_with_retry(lambda: client.get_current_consumption(self.account_id))
        if not consumption:
            logger.error("Falló al obtener consumo tras reintentos")
            self._publish_availability(False)
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

            # Franja horaria activa según schedule_code y hora local
            state["current_band"] = TariffProcessor.get_current_band(self.schedule_code)

            # Historial de los últimos 6 meses
            today = date.today()
            history = []
            for i in range(6):
                m = today.month - i
                y = today.year
                while m <= 0:
                    m += 12
                    y -= 1
                kwh = client.get_monthly_consumption(self.service_point_id, self.schedule_code, y, m)
                history.append({"month": f"{y}-{m:02d}", "kwh": round(kwh, 2) if kwh is not None else None})
            state["monthly_history"] = history

            # Historial de facturación (montos reales facturados, a mes vencido).
            # UTE cierra el día 26 y factura ~1 mes después → el ciclo de consumo
            # de cada factura es el mes anterior al vencimiento.
            invoices = client.get_invoices(self.account_id)
            if invoices:
                billing = []
                for inv in invoices:
                    exp_raw = inv.get("expirationDate")
                    if not exp_raw:
                        continue
                    try:
                        exp = datetime.fromisoformat(exp_raw)
                    except ValueError:
                        continue
                    # ciclo = mes anterior al vencimiento (cierre día 26, a mes vencido)
                    cy, cm = exp.year, exp.month - 1
                    if cm == 0:
                        cm, cy = 12, cy - 1
                    amount = inv.get("monthCharges")
                    if amount is None:
                        amount = inv.get("totalAmount", 0)
                    # Solo cycle + amount: el estado de un sensor HA está limitado a
                    # 255 caracteres, así que se publica el payload mínimo que consume
                    # el dashboard (no vto/doc/kwh, que excederían el límite).
                    billing.append({"cycle": f"{cy}-{cm:02d}", "amount": amount})
                # Orden cronológico ascendente, últimos 6 ciclos cerrados
                billing.sort(key=lambda b: b["cycle"])
                state["billing_history"] = billing[-6:]

        # Fallback: estimar gasto desde bandas cuando simulation no provee currentSpending
        if not state["current_spending"] and consumption.get("errorMessage") and self.tariff == "TRT":
            punta = state.get("consumption_punta", 0)
            llano = state.get("consumption_llano", 0)
            valle = state.get("consumption_valle", 0)
            if punta or llano or valle:
                estimated = TariffProcessor.estimate_spending_trt(punta, llano, valle)
                state["current_spending"] = estimated
                logger.info(
                    f"current_spending estimado por tarifas TRT 2026 (sin IVA/cargo fijo): "
                    f"${estimated:.2f} "
                    f"(punta={punta}kWh × $12.034 + llano={llano}kWh × $5.172 + valle={valle}kWh × $2.443)"
                )

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
                 self.mqtt.publish_availability(self.service_id, True)
                 self.mqtt.disconnect()
            else:
                 logger.error("No se pudo conectar al broker MQTT para publicar")
                 
        except Exception as e:
            logger.error(f"Error durante la publicación MQTT: {e}")
        finally:
            self.mqtt = None
    
    def _on_next_run_scheduled(self, next_run: datetime):
        """Publica la próxima fecha de ejecución a MQTT."""
        self.next_run_at = next_run
        try:
            publisher = MQTTPublisher(
                broker=self.mqtt_broker,
                port=self.mqtt_port,
                username=self.mqtt_username,
                password=self.mqtt_password,
                topic_prefix=self.mqtt_topic_prefix,
                client_id=self.mqtt_client_id,
                discovery_prefix=self.mqtt_discovery_prefix,
            )
            if publisher.connect():
                publisher.publish_scheduler_info(self.service_id, next_run)
                publisher.disconnect()
            else:
                logger.error("No se pudo conectar al broker MQTT para publicar próxima ejecución")
        except Exception as e:
            logger.error(f"Error publicando próxima ejecución: {e}")

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
        
        if self.schedule_interval_hours:
            logger.info(f"Modo intervalo: ejecutando cada {self.schedule_interval_hours} horas")
        else:
            logger.info(f"Modo ventana diaria: ejecutando en franja {self.time_window}")

        self.scheduler = DailyScheduler(
            task=self.fetch_and_publish,
            time_window=self.time_window,
            run_on_start=True,
            interval_hours=self.schedule_interval_hours,
            on_next_run_scheduled=self._on_next_run_scheduled,
        )
        self.scheduler.start()


def main():
    app = Ute2MQTT()
    app.run()


if __name__ == "__main__":
    main()

