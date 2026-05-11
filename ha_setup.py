#!/usr/bin/env python3
"""
Setup no interactivo para HA Add-on.

Lee usuario y contraseña de UTE desde variables de entorno,
autentica contra la API y guarda los tokens/credenciales cifrados.
Solo se ejecuta en la primera corrida (cuando no hay oauth_config.enc).
"""

import logging
import os
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

sys.path.insert(0, str(Path(__file__).parent))

from ute.auth import UTEAuthenticator
from ute.credentials import CredentialsManager


def main():
    username = os.environ.get("UTE_USERNAME", "").strip()
    password = os.environ.get("UTE_PASSWORD", "").strip()
    credentials_path = os.environ.get("CREDENTIALS_PATH", "/data/credentials")

    if not username or not password:
        logger.error(
            "Configurá 'ute_username' y 'ute_password' en la configuración del add-on antes de iniciarlo."
        )
        sys.exit(1)

    creds_manager = CredentialsManager(credentials_path)

    logger.info("Obteniendo configuración OAuth de UTE...")
    config = UTEAuthenticator.fetch_setup_config()
    if not config:
        logger.error("No se pudo obtener la configuración OAuth de UTE. Verificá la conexión a internet.")
        sys.exit(1)

    creds_manager.set_oauth_config(
        unique_id=config["unique_id"],
        client_id=config["client_id"],
        client_secret=config["client_secret"],
        scope=config["scope"],
    )

    logger.info("Autenticando con UTE (cédula: %s)...", username)
    auth = UTEAuthenticator(username, password, oauth_config=config)
    if not auth.authenticate():
        logger.error(
            "Autenticación fallida. Verificá el usuario (cédula) y contraseña en la configuración del add-on."
        )
        sys.exit(1)

    creds_manager.set_user_credentials(username, password)
    creds_manager.set_tokens(auth.access_token, auth.refresh_token, auth.expires_in)

    logger.info("Setup completado exitosamente. El add-on iniciará normalmente.")


if __name__ == "__main__":
    main()
