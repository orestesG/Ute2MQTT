"""
Ute2MQTT - Publicador MQTT.

Publica datos de energía del Proveedor de Energía a MQTT con auto-descubrimiento.
"""

import json
import logging
import time
from typing import Dict, Any, Optional
from datetime import datetime
import paho.mqtt.client as mqtt

logger = logging.getLogger(__name__)


class MQTTPublisher:
    """Publica datos del Proveedor de Energía a MQTT con auto-descubrimiento."""
    
    def __init__(
        self,
        broker: str,
        port: int = 1883,
        username: Optional[str] = None,
        password: Optional[str] = None,
        discovery_prefix: str = "discovery",
        topic_prefix: str = "ute",
        client_id: Optional[str] = None
    ):

        """
        Inicializa el publicador MQTT.
        
        Args:
            broker: Hostname/IP del broker MQTT
            port: Puerto del broker MQTT
            username: Usuario MQTT (opcional)
            password: Contraseña MQTT (opcional)
            discovery_prefix: Prefijo de descubrimiento (auto-discovery)
            topic_prefix: Prefijo para topics de estado
        """
        self.broker = broker
        self.port = port
        self.username = username
        self.password = password
        self.discovery_prefix = discovery_prefix
        self.topic_prefix = topic_prefix
        self.client_id = client_id
        self.client: Optional[mqtt.Client] = None
        self.connected = False
    
    def connect(self) -> bool:
        """Conecta al broker MQTT."""
        try:
            # Usar client_id proporcionado o generar uno con sufijo aleatorio para evitar desconexiones
            cid = self.client_id if self.client_id else f"ute2mqtt-{int(time.time())}"
            self.client = mqtt.Client(client_id=cid, protocol=mqtt.MQTTv311)
            
            if self.username and self.password:
                self.client.username_pw_set(self.username, self.password)
            
            self.client.on_connect = self._on_connect
            self.client.on_disconnect = self._on_disconnect
            
            logger.info(f"Conectando al broker MQTT en {self.broker}:{self.port}")
            self.client.connect(self.broker, self.port, keepalive=60)
            self.client.loop_start()
            
            # Esperar la conexión
            for _ in range(10):
                if self.connected:
                    return True
                time.sleep(0.5)
            
            logger.error("Error al conectar al broker MQTT")
            return False
            
        except Exception as e:
            logger.error(f"Error de conexión MQTT: {e}")
            return False
    
    def disconnect(self):
        """Desconecta del broker MQTT."""
        if self.client:
            self.client.loop_stop()
            self.client.disconnect()
            self.connected = False
    
    def _on_connect(self, client, userdata, flags, rc):
        """Callback de conexión MQTT."""
        if rc == 0:
            logger.info("Conectado al broker MQTT")
            self.connected = True
        else:
            logger.error(f"Conexión MQTT fallida con código {rc}")
    
    def _on_disconnect(self, client, userdata, rc):
        """Callback de desconexión MQTT."""
        logger.info("Desconectado del broker MQTT")
        self.connected = False
    
    def publish_discovery(self, service_id: str, account_id: str, tariff: str):
        """
        Publica mensajes de auto-descubrimiento.
        
        Args:
            service_id: El ID del servicio (identificador único del medidor)
            account_id: El ID de cuenta del Proveedor de Energía (para info)
            tariff: Tipo de tarifa (TRT=triple, TRD=doble, TRS=simple, TGS=simple)
        """
        device_info = {
            "identifiers": [f"ute_{service_id}"],
            "name": f"UTE {service_id}",
            "manufacturer": "Proveedor de Energía",
            "model": "Medidor Inteligente"
        }
        
        if not self.client or not self.connected:
            logger.error("Intento de publicación sin conexión MQTT activa")
            return
        
        base_topic = f"{self.topic_prefix}/{service_id}"
        
        # Sensores base (aplican a todas las tarifas)
        sensors = [
            {
                "name": "Consumo Actual",
                "unique_id": f"ute_{service_id}_consumption",
                "state_topic": f"{base_topic}/state",
                "value_template": "{{ value_json.current_consumption }}",
                "unit_of_measurement": "kWh",
                "device_class": "energy",
                "state_class": "total_increasing",
                "icon": "mdi:lightning-bolt",
            },
            {
                "name": "Gasto Actual",
                "unique_id": f"ute_{service_id}_spending",
                "state_topic": f"{base_topic}/state",
                "value_template": "{{ value_json.current_spending }}",
                "unit_of_measurement": "$",
                "device_class": "monetary",
                "state_class": "total",
                "icon": "mdi:currency-usd",
            },
            {
                "name": "Deuda Total",
                "unique_id": f"ute_{service_id}_debt",
                "state_topic": f"{base_topic}/state",
                "value_template": "{{ value_json.total_debt }}",
                "unit_of_measurement": "$",
                "device_class": "monetary",
                "state_class": "total",
                "icon": "mdi:cash-clock",
            },
            {
                "name": "Última Actualización",
                "unique_id": f"ute_{service_id}_updated",
                "state_topic": f"{base_topic}/state",
                "value_template": "{{ value_json.updated_at }}",
                "device_class": "timestamp",
                "icon": "mdi:clock-outline",
            },
            {
                "name": "Próxima Actualización",
                "unique_id": f"ute_{service_id}_next_update",
                "state_topic": f"{base_topic}/scheduler",
                "value_template": "{{ value_json.next_run_at }}",
                "device_class": "timestamp",
                "icon": "mdi:clock-fast",
            },
        ]
        
        # Agregar sensores de banda según tipo de tarifa
        if tariff == "TRT":
            # Tarifa Triple: PUNTA/LLANO/VALLE
            sensors.extend([
                {
                    "name": "Consumo Punta",
                    "unique_id": f"ute_{service_id}_punta",
                    "state_topic": f"{base_topic}/state",
                    "value_template": "{{ value_json.consumption_punta }}",
                    "unit_of_measurement": "kWh",
                    "device_class": "energy",
                    "state_class": "total_increasing",
                    "icon": "mdi:flash-alert",
                },
                {
                    "name": "Consumo Llano",
                    "unique_id": f"ute_{service_id}_llano",
                    "state_topic": f"{base_topic}/state",
                    "value_template": "{{ value_json.consumption_llano }}",
                    "unit_of_measurement": "kWh",
                    "device_class": "energy",
                    "state_class": "total_increasing",
                    "icon": "mdi:flash",
                },
                {
                    "name": "Consumo Valle",
                    "unique_id": f"ute_{service_id}_valle",
                    "state_topic": f"{base_topic}/state",
                    "value_template": "{{ value_json.consumption_valle }}",
                    "unit_of_measurement": "kWh",
                    "device_class": "energy",
                    "state_class": "total_increasing",
                    "icon": "mdi:flash-outline",
                },
            ])
        elif tariff == "TRD":
            # Tarifa Doble: PUNTA/FUERA_PUNTA
            sensors.extend([
                {
                    "name": "Consumo Punta",
                    "unique_id": f"ute_{service_id}_punta",
                    "state_topic": f"{base_topic}/state",
                    "value_template": "{{ value_json.consumption_punta }}",
                    "unit_of_measurement": "kWh",
                    "device_class": "energy",
                    "state_class": "total_increasing",
                    "icon": "mdi:flash-alert",
                },
                {
                    "name": "Consumo Fuera Punta",
                    "unique_id": f"ute_{service_id}_fuera_punta",
                    "state_topic": f"{base_topic}/state",
                    "value_template": "{{ value_json.consumption_fuera_punta }}",
                    "unit_of_measurement": "kWh",
                    "device_class": "energy",
                    "state_class": "total_increasing",
                    "icon": "mdi:flash-outline",
                },
            ])
        # TRS y otras tarifas: solo sensores base, sin bandas
        
        for sensor in sensors:
            sensor["device"] = device_info
            discovery_topic = f"{self.discovery_prefix}/sensor/{sensor['unique_id']}/config"
            
            self.client.publish(
                discovery_topic,
                json.dumps(sensor),
                retain=True
            )
            logger.debug(f"Publicado descubrimiento para {sensor['name']}")
        
        logger.info(f"Publicado descubrimiento para servicio {service_id} (tarifa: {tariff})")
    
    def publish_state(self, service_id: str, data: Dict[str, Any]):
        """
        Publica datos de estado actuales.
        
        Args:
        Args:
            service_id: El ID del servicio (identificador único del medidor)
            data: Diccionario con valores de sensores
        """
        if not self.client or not self.connected:
            logger.error("Intento de publicación sin conexión MQTT activa")
            return

        # Agregar marca de tiempo con timezone (requerido para device_class: timestamp)
        data["updated_at"] = datetime.now().astimezone().isoformat()
        
        topic = f"{self.topic_prefix}/{service_id}/state"
        payload = json.dumps(data)
        
        result = self.client.publish(topic, payload, retain=True)
        
        if result.rc == mqtt.MQTT_ERR_SUCCESS:
            logger.info(f"Publicado estado para servicio {service_id}")
        else:
            logger.error(f"Error al publicar estado: {result.rc}")

    def publish_scheduler_info(self, service_id: str, next_run_at: datetime):
        """Publica la próxima fecha de ejecución al tópico de scheduler."""
        if not self.client or not self.connected:
            logger.error("Intento de publicación sin conexión MQTT activa")
            return

        topic = f"{self.topic_prefix}/{service_id}/scheduler"
        payload = json.dumps({"next_run_at": next_run_at.astimezone().isoformat()})

        result = self.client.publish(topic, payload, retain=True)
        if result.rc == mqtt.MQTT_ERR_SUCCESS:
            logger.info(f"Publicada próxima ejecución para servicio {service_id}: {next_run_at.strftime('%Y-%m-%d %H:%M:%S')}")
        else:
            logger.error(f"Error al publicar info de scheduler: {result.rc}")
