#!/usr/bin/env python3
"""
Descubrimiento de cuenta UTE para el Add-on de HA.

Se ejecuta automáticamente cuando UTE_ACCOUNT_ID no está configurado.
Lee usuario/contraseña del options.json, autentica con UTE y loguea
los IDs necesarios para completar la configuración del add-on.
"""

import logging
import os
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

sys.path.insert(0, str(Path(__file__).parent))

from ute.auth import UTEAuthenticator
from ute.client import UTEClient
from ute.credentials import CredentialsManager
from ute.session import UTESession
from ute.tariffs import TariffProcessor


def main():
    username = os.environ.get("UTE_USERNAME", "").strip()
    password = os.environ.get("UTE_PASSWORD", "").strip()
    encryption_key = os.environ.get("ENCRYPTION_KEY", "").strip()
    credentials_path = os.environ.get("CREDENTIALS_PATH", "/data/credentials")

    if not username or not password:
        logger.error("Configurá 'ute_username' y 'ute_password' en el add-on antes de iniciar.")
        sys.exit(1)

    logger.info("=" * 55)
    logger.info("  DESCUBRIMIENTO DE CUENTA UTE")
    logger.info("=" * 55)

    creds_manager = CredentialsManager(credentials_path, encryption_key=encryption_key)

    logger.info("Obteniendo configuración OAuth...")
    oauth_config = UTEAuthenticator.fetch_setup_config()
    if not oauth_config:
        logger.error("No se pudo obtener la configuración OAuth. Verificá la conexión a internet.")
        sys.exit(1)

    creds_manager.set_oauth_config(
        unique_id=oauth_config["unique_id"],
        client_id=oauth_config["client_id"],
        client_secret=oauth_config["client_secret"],
        scope=oauth_config["scope"],
    )

    logger.info("Autenticando con UTE...")
    auth = UTEAuthenticator(username, password, oauth_config=oauth_config)
    if not auth.authenticate():
        logger.error("Autenticación fallida. Verificá usuario (cédula) y contraseña.")
        sys.exit(1)

    creds_manager.set_user_credentials(username, password)
    creds_manager.set_tokens(auth.access_token, auth.refresh_token, auth.expires_in)

    session = UTESession(creds_manager)
    client = UTEClient(session)

    logger.info("Obteniendo cuentas...")
    accounts = client.get_accounts()
    if not accounts:
        logger.error("No se encontraron cuentas asociadas al usuario.")
        sys.exit(1)

    logger.info("=" * 55)
    logger.info("  COPIA ESTOS VALORES EN LA CONFIGURACIÓN DEL ADD-ON")
    logger.info("=" * 55)

    for account in accounts:
        account_id = account.get("accountId", "")
        address = account.get("address", "")
        logger.info(f"  Dirección  : {address}")
        logger.info(f"  ute_account_id     = {account_id}")

        services = client.get_services(account_id) or []
        for svc in services:
            service_id = svc.get("serviceAgreementId", "")
            service_point_id = svc.get("servicePointId", "")
            tariff = svc.get("tariff", "").upper()

            logger.info(f"  ute_service_id     = {service_id}")
            logger.info(f"  ute_service_point_id = {service_point_id}")
            logger.info(f"  ute_tariff         = {tariff}")

            if tariff in ("TRT", "TRD"):
                try:
                    peak = client.get_peak_config(account_id, service_id)
                    if peak:
                        peak_start = peak.get("selectedPeakStart") or peak.get("meterPeakStart")
                        code = TariffProcessor.get_schedule_code_from_id(peak_start)
                        logger.info(f"  ute_schedule_code  = {code or 'TRIPLERES19 (valor por defecto)'}")
                except Exception:
                    logger.info("  ute_schedule_code  = TRIPLERES19 (valor por defecto)")

        logger.info("-" * 55)

    logger.info("Copiá los valores anteriores en la pestaña Configuration del add-on,")
    logger.info("luego reiniciá el add-on para comenzar la publicación de datos.")
    logger.info("=" * 55)


if __name__ == "__main__":
    main()
