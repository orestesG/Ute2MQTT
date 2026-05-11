import logging
import random
import threading
from datetime import datetime, timedelta, time, date
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class DailyScheduler:
    """
    Planificador que ejecuta una tarea periódicamente.

    Modos:
    - interval_hours: ejecuta cada N horas (ej. cada 6 h).
    - time_window (AM/PM): ejecuta una vez al día en horario aleatorio dentro de la ventana.
    """

    def __init__(
        self,
        task: Callable,
        time_window: str = "AM",
        run_on_start: bool = True,
        interval_hours: Optional[float] = None,
        on_next_run_scheduled: Optional[Callable[["datetime"], None]] = None,
    ):
        self.task = task
        self.time_window = time_window.upper()
        self.run_on_start = run_on_start
        self.interval_hours = interval_hours
        self.on_next_run_scheduled = on_next_run_scheduled
        self._stop_event = threading.Event()
        self._last_run_date: Optional[date] = None

    def _window_bounds(self):
        if self.time_window == "AM":
            return 6, 12   # 06:00 inclusive, 12:00 exclusivo
        return 12, 18      # 12:00 inclusive, 18:00 exclusivo

    def _random_time_in_window(self) -> time:
        start_hour, end_hour = self._window_bounds()
        hour = random.randint(start_hour, end_hour - 1)
        minute = random.randint(0, 59)
        return time(hour=hour, minute=minute, second=0, microsecond=0)

    def _get_next_run_time(self) -> datetime:
        """Calcula la próxima fecha y hora de ejecución."""
        now = datetime.now()

        if self.interval_hours is not None:
            return now + timedelta(hours=self.interval_hours)

        # Modo ventana diaria
        today = now.date()

        if self._last_run_date == today:
            target_date = today + timedelta(days=1)
        else:
            target_date = today

        t = self._random_time_in_window()
        next_run = datetime.combine(target_date, t)

        if next_run <= now:
            target_date = today + timedelta(days=1)
            t = self._random_time_in_window()
            next_run = datetime.combine(target_date, t)

        return next_run

    def _run_task(self):
        try:
            self.task()
        except Exception as e:
            logger.exception("Ejecución de tarea fallida: %s", e)
        finally:
            self._last_run_date = datetime.now().date()

    def start(self):
        self._stop_event.clear()

        if self.run_on_start:
            logger.info("Ejecutando tarea inicial...")
            self._run_task()

        while not self._stop_event.is_set():
            next_run = self._get_next_run_time()
            wait_seconds = (next_run - datetime.now()).total_seconds()

            logger.info("Próxima ejecución programada para: %s", next_run.strftime('%Y-%m-%d %H:%M:%S'))
            logger.info("Esperando %.1f horas...", max(0, wait_seconds) / 3600)

            if self.on_next_run_scheduled:
                try:
                    self.on_next_run_scheduled(next_run)
                except Exception as e:
                    logger.warning("Error en callback on_next_run_scheduled: %s", e)

            if self._stop_event.wait(timeout=max(0, wait_seconds)):
                break

            logger.info("Ejecutando tarea programada...")
            self._run_task()

    def stop(self):
        logger.info("Deteniendo planificador...")
        self._stop_event.set()
