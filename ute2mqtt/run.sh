#!/usr/bin/env sh
set -e

# Detectar modo de ejecución: HA Add-on (tiene /data/options.json) o Docker puro (.env)
if [ -f /data/options.json ]; then
    echo "[ute2mqtt] Modo HA Add-on: leyendo configuración de /data/options.json"

    # Helper: leer campo del options.json
    _cfg() {
        python3 -c "
import json, sys
d = json.load(open('/data/options.json'))
v = d.get('$1', '')
print(v if v is not None else '')
"
    }

    export ENCRYPTION_KEY=$(_cfg encryption_key)
    export UTE_ACCOUNT_ID=$(_cfg ute_account_id)
    export UTE_SERVICE_ID=$(_cfg ute_service_id)
    export UTE_SERVICE_POINT_ID=$(_cfg ute_service_point_id)
    export UTE_TARIFF=$(_cfg ute_tariff)
    export UTE_SCHEDULE_CODE=$(_cfg ute_schedule_code)
    export MQTT_BROKER=$(_cfg mqtt_broker)
    export MQTT_PORT=$(_cfg mqtt_port)
    export MQTT_USERNAME=$(_cfg mqtt_username)
    export MQTT_PASSWORD=$(_cfg mqtt_password)
    export MQTT_TOPIC_PREFIX=$(_cfg mqtt_topic_prefix)
    export MQTT_DISCOVERY_PREFIX=$(_cfg mqtt_discovery_prefix)
    export MQTT_CLIENT_ID=$(_cfg mqtt_client_id)
    export SCHEDULE_TIME=$(_cfg schedule_time)
    export CREDENTIALS_PATH=/data/credentials

    # Intervalo de scheduler (0 = usar ventana diaria)
    _interval=$(_cfg schedule_interval_hours)
    if [ "$_interval" != "0" ] && [ "$_interval" != "0.0" ] && [ -n "$_interval" ]; then
        export SCHEDULE_INTERVAL_HOURS="$_interval"
    fi

    # Modo descubrimiento: si ute_account_id está vacío, mostrar IDs en el log y salir
    if [ -z "$UTE_ACCOUNT_ID" ]; then
        echo "[ute2mqtt] ute_account_id no configurado — iniciando modo descubrimiento..."
        UTE_USERNAME=$(_cfg ute_username) UTE_PASSWORD=$(_cfg ute_password) \
            python3 /app/discover.py
        exit 0
    fi

    # Setup inicial si no hay credenciales almacenadas
    if [ ! -f /data/credentials/oauth_config.enc ]; then
        echo "[ute2mqtt] Primera ejecución: realizando setup automático..."
        UTE_USERNAME=$(_cfg ute_username) UTE_PASSWORD=$(_cfg ute_password) \
            python3 /app/ha_setup.py || { echo "[ute2mqtt] Setup fallido. Verificá usuario y contraseña en la configuración del add-on."; exit 1; }
    fi
else
    echo "[ute2mqtt] Modo Docker: usando variables de entorno del archivo .env"
fi

exec python3 /app/main.py
