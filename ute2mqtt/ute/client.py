"""
Módulo Cliente API para el Proveedor de Energía.
"""

import calendar
import logging
import requests
from typing import Optional, Dict, Any, List, TYPE_CHECKING

if TYPE_CHECKING:
    from .session import UTESession

logger = logging.getLogger(__name__)


class UTEClient:
    """Cliente para interactuar con la API del Proveedor de Energía."""
    
    API_BASE = "https://rocme.ute.com.uy/customersapp"
    
    def __init__(self, session_manager: 'UTESession'):
        """
        Inicializa el cliente API.
        
        Args:
            session_manager: Instancia de UTESession para manejar tokens y refresh.
        """
        self.session_manager = session_manager
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Dart/3.7 (dart:io)",
            "Accept-Encoding": "gzip"
        })

    def _get_headers(self) -> Dict[str, str]:
        return self.session_manager.get_auth_headers()

    def _request(self, method: str, endpoint: str, **kwargs) -> Optional[requests.Response]:
        """Wrapper para solicitudes con manejo de reintentos por auth."""
        url = f"{self.API_BASE}{endpoint}"
        
        # Inyectar headers de auth
        headers = kwargs.pop("headers", {})
        try:
            # logger.info(f"Obteniendo headers para {endpoint}...") 
            auth_headers = self._get_headers()
            headers.update(auth_headers)
        except Exception as e:
            logger.error(f"Error al obtener headers de autenticación: {e}")
            return None
            
        try:
            logger.info(f"Enviando solicitud {method} a {endpoint}")
            response = self.session.request(method, url, headers=headers, **kwargs)
            logger.info(f"Respuesta recibida: {response.status_code}")
            
            # Si falla por auth (401 o 403), intentar refresh y reintentar
            # A veces la API retorna 403 o 500 para tokens inválidos/corruptos
            if response.status_code in (401, 403, 500):
                logger.warning(f"Token rechazado ({response.status_code}). Intentando renovar...")
                if self.session_manager.refresh_or_reauthenticate():
                    # Actualizar headers con nuevo token
                    headers.update(self._get_headers())
                    logger.info("Reintentando solicitud con nuevo token...")
                    response = self.session.request(method, url, headers=headers, **kwargs)
                    logger.info(f"Respuesta reintento: {response.status_code}")
                else:
                    logger.error(f"No se pudo renovar la sesión tras {response.status_code}.")
                    return None
            
            return response
            
        except requests.RequestException as e:
            logger.error(f"Error de conexión en {endpoint}: {e}")
            return None

    def get_accounts(self) -> Optional[List[Dict[str, Any]]]:
        """Obtiene la lista de cuentas asociadas al usuario."""
        response = self._request("GET", "/accounts", timeout=30)
        
        if response is not None and response.status_code == 200:
            return response.json()
            
        code = response.status_code if response is not None else 'Error'
        logger.error(f"Error al obtener cuentas: {code}")
        return None

    def get_services(self, account_id: str) -> Optional[List[Dict[str, Any]]]:
        """Obtiene los servicios de una cuenta."""
        response = self._request("GET", f"/accounts/{account_id}/services", timeout=30)
        
        if response is not None and response.status_code == 200:
            return response.json()
            
        code = response.status_code if response is not None else 'Error'
        logger.error(f"Error al obtener servicios: {code}")
        return None

    def get_current_consumption(self, account_id: str) -> Optional[Dict[str, Any]]:
        """Obtiene la simulación de consumo actual."""
        response = self._request(
            "POST",
            "/accounts/consumption/simulation",
            json={"accountId": account_id},
            timeout=30
        )

        if response is not None and response.status_code == 200:
            data = response.json()
            logger.info(f"[simulation] {data}")
            return data

        code = response.status_code if response is not None else 'Error'
        logger.error(f"Error al obtener consumo: {code}")
        return None

    def get_total_debt(self, account_id: str) -> Optional[float]:
        """Obtiene la deuda total de una cuenta."""
        response = self._request("GET", f"/invoices/totalDebt/{account_id}", timeout=30)

        if response is not None and response.status_code == 200:
            try:
                value = float(response.text)
                logger.info(f"[totalDebt] {value}")
                return value
            except ValueError:
                return 0.0

        code = response.status_code if response is not None else 'Error'
        logger.error(f"Error al obtener deuda: {code}")
        return None

    def get_invoices(self, account_id: str) -> Optional[List[Dict[str, Any]]]:
        """Obtiene el historial de facturas emitidas (montos reales facturados).

        Cada factura incluye `monthCharges`/`totalAmount` (con IVA + cargo fijo)
        y `expirationDate`. Los campos `month`/`year` vienen en 0 (inservibles);
        el período se deriva de la fecha de vencimiento.
        """
        response = self._request("GET", f"/invoices/{account_id}", timeout=30)

        if response is not None and response.status_code == 200:
            data = response.json()
            logger.info(f"[invoices] {len(data) if isinstance(data, list) else 0} facturas")
            return data if isinstance(data, list) else None

        code = response.status_code if response is not None else 'Error'
        logger.error(f"Error al obtener facturas: {code}")
        return None

    def get_consumption_by_band(
        self,
        service_point_id: str,
        schedule_code: str,
        start_date: str,
        end_date: str
    ) -> Optional[List[Dict[str, Any]]]:
        """Obtiene el consumo desglosado por franja horaria."""
        endpoint = f"/accounts/{service_point_id}/calculateConsumptionForPlan/{schedule_code}/{start_date}/{end_date}"
        response = self._request("GET", endpoint, timeout=30)

        if response is not None and response.status_code == 200:
            data = response.json()
            logger.info(f"[bands] {data}")
            return data

        code = response.status_code if response is not None else 'Error'
        logger.error(f"Error al obtener consumo por franja: {code}")
        return None

    def get_monthly_consumption(
        self,
        service_point_id: str,
        schedule_code: str,
        year: int,
        month: int
    ) -> Optional[float]:
        """Retorna el consumo total (kWh) de un mes específico sumando todas las bandas."""
        first_day = f"{year}-{month:02d}-01"
        last_day = f"{year}-{month:02d}-{calendar.monthrange(year, month)[1]:02d}"
        band_data = self.get_consumption_by_band(service_point_id, schedule_code, first_day, last_day)
        if not band_data:
            return None
        return round(sum(b.get("consumption", 0) for b in band_data), 3)

    def get_peak_config(self, account_id: str, service_id: str) -> Optional[Dict[str, Any]]:
        """Obtiene la configuración de horario punta del servicio."""
        response = self._request("GET", f"/accounts/{account_id}/services/{service_id}/peak", timeout=30)
        
        if response is not None and response.status_code == 200:
            return response.json()
        
        # 404 es común si no tiene configuración plancha/inteligente?
        if response is not None and response.status_code == 404:
            return None
            
        code = response.status_code if response is not None else 'Error'
        logger.error(f"Error al obtener configuración de punta: {code}")
        return None
