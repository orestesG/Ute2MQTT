"""
Módulo de Gestión de Sesión.

Orquesta la autenticación, renovación de tokens y persistencia.
"""

import logging
from typing import Optional, Dict

from .auth import UTEAuthenticator
from .credentials import CredentialsManager

logger = logging.getLogger(__name__)


class UTESession:
    """
    Gestiona el ciclo de vida de la sesión con el Proveedor de Energía.
    
    Se encarga de:
    1. Cargar tokens guardados.
    2. Verificar validez y refrescar si es necesario.
    3. Re-autenticar con credenciales si el refresh falla.
    4. Guardar tokens actualizados.
    """
    
    def __init__(self, creds_manager: CredentialsManager):
        self.creds_manager = creds_manager
        self.oauth_config = self.creds_manager.get_oauth_config()
        self.auth: Optional[UTEAuthenticator] = None
        
        # Validar que tenemos lo mínimo necesario
        if not self.oauth_config:
            raise ValueError("Configuración OAuth no encontrada")

    def get_client(self):
        """
        Obtiene un cliente autenticado, asegurando que la sesión sea válida.
        
        Returns:
            UTEClient listo para usar o None si no se pudo autenticar.
        """
        from .client import UTEClient
        if self._ensure_valid_session():
            return UTEClient(self)
        return None

    def _ensure_valid_session(self) -> bool:
        """Asegura que self.auth tenga una sesión válida (refresh/re-login)."""
        
        # 1. Inicializar Auth si no existe
        if not self.auth:
            self.auth = UTEAuthenticator(oauth_config=self.oauth_config)
            self._load_tokens_into_auth()

        # 2. Verificar si el token existe y sigue siendo válido
        if self.auth.access_token and self.creds_manager.is_token_valid():
            return True

        # 3. Intentar refresh si hay refresh token
        if self.auth.refresh_token:
            if self.auth.refresh_access_token():
                self._save_tokens()
                return True
            logger.warning("Falló el refresco del token, intentando re-autenticar...")
        
        # 4. Re-autenticación total
        return self._try_reauthenticate()

    def _load_tokens_into_auth(self):
        """Carga tokens del storage al autenticador."""
        tokens = self.creds_manager.get_tokens()
        if tokens:
            logger.info("Cargando tokens almacenados...")
            self.auth.set_tokens(
                tokens["access_token"],
                tokens.get("refresh_token"),
                expires_in=int(self.creds_manager.time_until_expiry())
            )
        else:
            # Intentar cargar solo refresh token si existe (caso token expirado pero refresh vivo)
            refresh = self.creds_manager.get_refresh_token()
            if refresh:
                self.auth.set_tokens("", refresh)

    def _try_reauthenticate(self) -> bool:
        """Intenta login completo con credenciales guardadas."""
        user_creds = self.creds_manager.get_user_credentials()
        if not user_creds:
            logger.error("No hay credenciales guardadas para re-autenticación automática.")
            return False
        
        logger.info("Intentando re-autenticar con credenciales guardadas...")
        
        # Reiniciar instancia auth con credenciales
        self.auth = UTEAuthenticator(
            username=user_creds["username"],
            password=user_creds["password"],
            oauth_config=self.oauth_config
        )
        
        if self.auth.authenticate():
            self._save_tokens()
            logger.info("Re-autenticación exitosa")
            return True
        
        logger.error("Re-autenticación falló. Credenciales pueden haber cambiado.")
        return False

    def refresh_or_reauthenticate(self) -> bool:
        """
        Intenta recuperar la sesión mediante refresh token o re-autenticación.
        
        Usado por el cliente cuando recibe un error 401.
        
        Returns:
            True si se logró recuperar la sesión, False en caso contrario.
        """
        logger.info("Intentando recuperar sesión (refresh o login)...")
        
        # 1. Intentar Refresh
        if self.auth.refresh_token:
            if self.auth.refresh_access_token():
                logger.info("Refresh exitoso")
                self._save_tokens()
                return True
            logger.warning("Refresh falló. Intentando re-login...")
        
        # 2. Intentar Login completo
        return self._try_reauthenticate()

    def get_auth_headers(self) -> Dict[str, str]:
        """Delega la obtención de headers al autenticador."""
        if not self.auth:
            self._ensure_valid_session()
        return self.auth.get_auth_headers()

    def _save_tokens(self):
        """Persiste los tokens actuales en disco."""
        if self.auth and self.auth.access_token:
            self.creds_manager.set_tokens(
                self.auth.access_token,
                self.auth.refresh_token,
                self.auth.expires_in
            )
