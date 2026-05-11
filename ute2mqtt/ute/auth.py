"""
Módulo de Autenticación para el Proveedor de Energía.
"""

import logging
import requests
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class UTEAuthenticator:
    """Maneja la autenticación y tokens para la API del Proveedor."""

    AUTH_URL = "https://identityserver.ute.com.uy/connect/token"
    SETUP_URL = "https://rocme.ute.com.uy/customersapp/customers/setup"
    USER_AGENT = "Dart/3.7 (dart:io)"

    @staticmethod
    def fetch_setup_config() -> Optional[Dict[str, Any]]:
        """
        Obtiene la configuración OAuth desde el endpoint /customers/setup.
        """
        logger.info("Obteniendo configuración OAuth desde setup endpoint...")
        
        try:
            response = requests.post(
                UTEAuthenticator.SETUP_URL,
                headers={
                    "User-Agent": UTEAuthenticator.USER_AGENT,
                    "Content-Type": "application/json; charset=utf-8",
                    "Accept-Encoding": "gzip",
                },
                json={"registrationId": None, "deviceInfo": []},
                timeout=30
            )
            
            if response.status_code != 200:
                logger.error(f"Error en setup endpoint: {response.status_code}")
                return None
            
            data = response.json()
            oauth_config = data.get("oAuthConfiguration", {})
            
            return {
                "unique_id": data.get("uniqueId"),
                "client_id": oauth_config.get("client"),
                "client_secret": oauth_config.get("secret"),
                "scope": oauth_config.get("scope"),
            }
            
        except requests.RequestException as e:
            logger.error(f"Error al obtener setup config: {e}")
            return None
        except ValueError as e:
            logger.error(f"Error al decodificar respuesta JSON en setup: {e}")
            return None


    def __init__(
        self,
        username: Optional[str] = None,
        password: Optional[str] = None,
        oauth_config: Optional[Dict[str, Any]] = None
    ):
        """
        Inicializa el autenticador.
        """
        self.username = username
        self.password = password
        
        # Configuración OAuth
        if oauth_config:
            self.client_id = oauth_config.get("client_id", "customers_mobile_app")
            self.client_secret = oauth_config.get("client_secret")
            self.unique_id = oauth_config.get("unique_id")
        else:
            self.client_id = "customers_mobile_app"
            self.client_secret = None
            self.unique_id = None
        
        self.access_token: Optional[str] = None
        self.refresh_token: Optional[str] = None
        self.expires_in: int = 0
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": self.USER_AGENT})

    def set_tokens(self, access_token: str, refresh_token: str = None, expires_in: int = 3600):
        """Establece tokens desde una fuente externa."""
        self.access_token = access_token
        if refresh_token:
            self.refresh_token = refresh_token
        self.expires_in = expires_in

    def authenticate(self) -> bool:
        """Autentica con el servidor OAuth2."""
        if not self.username or not self.password:
            logger.error("Se requiere usuario y contraseña para autenticar")
            return False
            
        logger.info("Autenticando con el Proveedor de Energía...")
        
        headers = {
            "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
        }
        
        data = {
            "grant_type": "password",
            "username": self.username,
            "password": self.password,
        }
        
        try:
            response = self.session.post(
                self.AUTH_URL,
                headers=headers,
                data=data,
                auth=(self.client_id, self.client_secret),
                timeout=30
            )
            
            if response.status_code != 200:
                logger.error(f"Autenticación fallida: {response.status_code} - {response.text}")
                return False
            
            token_data = response.json()
            self.access_token = token_data.get("access_token")
            self.refresh_token = token_data.get("refresh_token")
            self.expires_in = token_data.get("expires_in", 3600)
            
            logger.info("Autenticación exitosa")
            return True
            
        except requests.RequestException as e:
            logger.error(f"Error en la solicitud de autenticación: {e}")
            return False
        except ValueError as e:
            logger.error(f"Error al decodificar respuesta JSON en autenticación: {e}")
            return False


    def refresh_access_token(self) -> bool:
        """Refresca el token de acceso."""
        if not self.refresh_token:
            logger.error("No hay refresh token disponible")
            return False
        
        logger.info("Refrescando token de acceso...")
        
        headers = {
            "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
        }
        
        data = {
            "grant_type": "refresh_token",
            "refresh_token": self.refresh_token,
        }
        
        try:
            response = self.session.post(
                self.AUTH_URL,
                headers=headers,
                data=data,
                auth=(self.client_id, self.client_secret),
                timeout=30
            )
            
            if response.status_code != 200:
                logger.warning(f"Refresco de token fallido: {response.status_code}")
                return False
            
            token_data = response.json()
            self.access_token = token_data.get("access_token")
            self.refresh_token = token_data.get("refresh_token", self.refresh_token)
            self.expires_in = token_data.get("expires_in", 3600)
            
            logger.info("Refresco de token exitoso")
            return True
            
        except requests.RequestException as e:
            logger.error(f"Error en la solicitud de refresco de token: {e}")
            return False
        except ValueError as e:
            logger.error(f"Error al decodificar respuesta JSON en refresco: {e}")
            return False


    def get_auth_headers(self) -> Dict[str, str]:
        """Obtiene los headers con el token de autorización."""
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json; charset=utf-8",
        }
