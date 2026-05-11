"""
Módulo de Gestión de Credenciales y Tokens.

Maneja el almacenamiento seguro de tokens con cifrado AES.
Los tokens se almacenan cifrados en disco y se refrescan automáticamente cuando es necesario.
"""

import base64
import json
import logging
import os
import time
import secrets
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

logger = logging.getLogger(__name__)

# Archivo de salt para derivación de clave
SALT_FILE = "salt.bin"


def _derive_key(password: str, salt: bytes) -> bytes:
    """
    Deriva una clave compatible con Fernet desde una contraseña usando PBKDF2.
    
    Args:
        password: La clave/contraseña de cifrado
        salt: Salt aleatorio para derivación de clave
        
    Returns:
        Clave de 32 bytes codificada en base64 urlsafe
    """
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=480000,
    )
    return base64.urlsafe_b64encode(kdf.derive(password.encode()))


class CredentialsManager:
    """
    Gestiona el almacenamiento de tokens con cifrado AES.
    
    Solo se almacenan tokens (cifrados en disco).
    Las credenciales se solicitan una vez durante el setup para obtener tokens iniciales.
    El refresco de tokens es manejado por el planificador.
    """
    
    def __init__(self, storage_path: Optional[str] = None, encryption_key: Optional[str] = None):
        """
        Inicializa el gestor de credenciales.
        
        Args:
            storage_path: Ruta para almacenamiento en disco (por defecto: ./credentials/)
            encryption_key: Clave de cifrado explícita. Si no se provee, se busca en env ENCRYPTION_KEY.
        """
        self.storage_path = Path(storage_path) if storage_path else Path("./credentials")
        
        # Obtener clave de cifrado (prioridad: argumento > variable de entorno)
        self.encryption_key = encryption_key or os.environ.get("ENCRYPTION_KEY")
        
        if not self.encryption_key:
            raise ValueError(
                "ENCRYPTION_KEY es requerida. Generar con: openssl rand -hex 32"
            )
        
        # Almacenamiento de tokens en memoria
        self._tokens: Dict[str, Any] = {}
        
        # Cache de instancia Fernet (evita recalcular PBKDF2)
        self._fernet: Optional[Fernet] = None
        
        # Asegurar que existe el directorio de almacenamiento
        self.storage_path.mkdir(parents=True, exist_ok=True)
        
        # Cargar salt o generar uno nuevo
        self._salt = self._load_or_create_salt()
        
        # Cargar tokens desde disco
        self._load_from_disk()
    
    def _load_or_create_salt(self) -> bytes:
        """Carga el salt existente o crea uno nuevo."""
        salt_path = self.storage_path / SALT_FILE
        
        if salt_path.exists():
            with open(salt_path, "rb") as f:
                return f.read()
        else:
            salt = secrets.token_bytes(16)
            with open(salt_path, "wb") as f:
                f.write(salt)
            return salt
    
    def _get_fernet(self) -> Fernet:
        """
        Obtiene instancia de Fernet para cifrado/descifrado.
        
        La instancia se cachea para evitar recalcular PBKDF2 (480k iteraciones)
        en cada operación de cifrado/descifrado.
        """
        if self._fernet is None:
            key = _derive_key(self.encryption_key, self._salt)
            self._fernet = Fernet(key)
        return self._fernet
    
    def _encrypt(self, data: str) -> bytes:
        """Cifra datos usando AES (Fernet)."""
        fernet = self._get_fernet()
        return fernet.encrypt(data.encode())
    
    def _decrypt(self, data: bytes) -> str:
        """Descifra datos usando AES (Fernet)."""
        fernet = self._get_fernet()
        return fernet.decrypt(data).decode()
    
    def _load_from_disk(self):
        """Carga tokens desde disco."""
        tokens_file = self.storage_path / "tokens.enc"
        
        if tokens_file.exists():
            try:
                with open(tokens_file, "rb") as f:
                    encrypted = f.read()
                decrypted = self._decrypt(encrypted)
                self._tokens = json.loads(decrypted)
                logger.debug("Tokens cargados desde disco")
            except Exception as e:
                logger.warning(f"Error al cargar tokens: {e}")
                self._tokens = {}
    
    def _save_to_disk(self):
        """Guarda tokens en disco (cifrados)."""
        tokens_file = self.storage_path / "tokens.enc"
        
        try:
            if self._tokens:
                encrypted = self._encrypt(json.dumps(self._tokens))
                with open(tokens_file, "wb") as f:
                    f.write(encrypted)
                logger.debug("Tokens guardados en disco")
        except Exception as e:
            logger.error(f"Error al guardar tokens en disco: {e}")
    
    def set_tokens(self, access_token: str, refresh_token: str, expires_in: int):
        """
        Almacena tokens OAuth.
        
        Args:
            access_token: El token de acceso
            refresh_token: El token de refresco  
            expires_in: Validez del token en segundos
        """
        self._tokens = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_at": time.time() + expires_in - 300,  # 5 min de margen
            "stored_at": datetime.now().isoformat()
        }
        self._save_to_disk()
        logger.info("Tokens almacenados")
    
    def get_tokens(self) -> Optional[Dict[str, Any]]:
        """Obtiene los tokens almacenados si aún son válidos."""
        if not self._tokens:
            return None
        
        # Verificar si el token expiró
        expires_at = self._tokens.get("expires_at", 0)
        if time.time() >= expires_at:
            logger.info("Token expirado")
            return None
        
        return self._tokens.copy()
    
    def get_refresh_token(self) -> Optional[str]:
        """Obtiene el refresh token sin importar la expiración del access token."""
        if self._tokens:
            return self._tokens.get("refresh_token")
        return None
    
    def clear_tokens(self):
        """Limpia los tokens almacenados."""
        self._tokens = {}
        tokens_file = self.storage_path / "tokens.enc"
        if tokens_file.exists():
            tokens_file.unlink()
        logger.info("Tokens eliminados")
    
    def is_token_valid(self) -> bool:
        """Verifica si el token actual sigue siendo válido."""
        if not self._tokens:
            return False
        expires_at = self._tokens.get("expires_at", 0)
        return time.time() < expires_at
    
    def time_until_expiry(self) -> float:
        """Obtiene los segundos hasta que expire el token."""
        if not self._tokens:
            return 0
        expires_at = self._tokens.get("expires_at", 0)
        return max(0, expires_at - time.time())
    
    # =========================================================================
    # OAuth Config Management (from /customers/setup endpoint)
    # =========================================================================
    
    def set_oauth_config(self, unique_id: str, client_id: str, client_secret: str, scope: str):
        """
        Almacena la configuración OAuth obtenida del endpoint setup.
        
        Args:
            unique_id: Identificador único del dispositivo
            client_id: OAuth client ID
            client_secret: OAuth client secret
            scope: OAuth scope
        """
        config = {
            "unique_id": unique_id,
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": scope,
            "fetched_at": datetime.now().isoformat()
        }
        
        config_file = self.storage_path / "oauth_config.enc"
        try:
            encrypted = self._encrypt(json.dumps(config))
            with open(config_file, "wb") as f:
                f.write(encrypted)
            logger.info("OAuth config almacenada")
        except Exception as e:
            logger.error(f"Error al guardar OAuth config: {e}")
    
    def get_oauth_config(self) -> Optional[Dict[str, Any]]:
        """
        Obtiene la configuración OAuth almacenada.
        
        Returns:
            Diccionario con la config OAuth o None si no existe.
        """
        config_file = self.storage_path / "oauth_config.enc"
        
        if not config_file.exists():
            return None
        
        try:
            with open(config_file, "rb") as f:
                encrypted = f.read()
            decrypted = self._decrypt(encrypted)
            return json.loads(decrypted)
        except Exception as e:
            logger.warning(f"Error al cargar OAuth config: {e}")
            return None
    
    def has_oauth_config(self) -> bool:
        """Verifica si existe configuración OAuth almacenada."""
        config_file = self.storage_path / "oauth_config.enc"
        return config_file.exists()
    
    def clear_oauth_config(self):
        """Elimina la configuración OAuth almacenada."""
        config_file = self.storage_path / "oauth_config.enc"
        if config_file.exists():
            config_file.unlink()
        logger.info("OAuth config eliminada")
    
    # =========================================================================
    # User Credentials Management (for re-authentication)
    # =========================================================================
    
    def set_user_credentials(self, username: str, password: str):
        """
        Almacena las credenciales del usuario cifradas.
        
        Se usan para re-autenticación automática cuando el refresh token expira.
        
        Args:
            username: Cédula del usuario
            password: Contraseña del usuario
        """
        creds = {
            "username": username,
            "password": password,
            "stored_at": datetime.now().isoformat()
        }
        
        creds_file = self.storage_path / "user_credentials.enc"
        try:
            encrypted = self._encrypt(json.dumps(creds))
            with open(creds_file, "wb") as f:
                f.write(encrypted)
            logger.info("Credenciales de usuario almacenadas")
        except Exception as e:
            logger.error(f"Error al guardar credenciales: {e}")
    
    def get_user_credentials(self) -> Optional[Dict[str, str]]:
        """
        Obtiene las credenciales del usuario almacenadas.
        
        Returns:
            Dict con username y password, o None si no existen.
        """
        creds_file = self.storage_path / "user_credentials.enc"
        
        if not creds_file.exists():
            return None
        
        try:
            with open(creds_file, "rb") as f:
                encrypted = f.read()
            decrypted = self._decrypt(encrypted)
            return json.loads(decrypted)
        except Exception as e:
            logger.warning(f"Error al cargar credenciales: {e}")
            return None
    
    def has_user_credentials(self) -> bool:
        """Verifica si existen credenciales de usuario almacenadas."""
        creds_file = self.storage_path / "user_credentials.enc"
        return creds_file.exists()
    
    def clear_user_credentials(self):
        """Elimina las credenciales de usuario almacenadas."""
        creds_file = self.storage_path / "user_credentials.enc"
        if creds_file.exists():
            creds_file.unlink()
        logger.info("Credenciales de usuario eliminadas")
    
    def clear_all(self):
        """Elimina TODOS los datos almacenados (tokens, config, credenciales)."""
        self.clear_tokens()
        self.clear_oauth_config()
        self.clear_user_credentials()
        
        # También limpiar el salt para forzar una rotación completa de claves si se desea,
        # aunque eso invalidaría backups anteriores. Por ahora mantenemos el salt.
        
        logger.info("Todos los datos almacenados han sido eliminados")
