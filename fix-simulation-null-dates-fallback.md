# PR: fix/simulation-null-dates-fallback

## Problema

El endpoint `/accounts/consumption/simulation` retorna `initialDate: null`, `finalDate: null` y `currentConsumption: 0` con el error:

> "No se encontraron segmentos de factura para el AS {serviceAgreementId}"

Esto ocurre aunque la cuenta tenga consumo registrado. La causa exacta por parte de la API de UTE no está clara (puede ser un tema del ciclo de facturación o del estado del segmento).

El código anterior dependía de las fechas de ese endpoint para consultar las bandas por franja horaria (PUNTA / LLANO / VALLE). Como las fechas eran `null`, la condición `if period_start and period_end` fallaba y **las bandas nunca se consultaban**, resultando en todos los valores en cero publicados por MQTT.

## Solución aplicada

### `main.py`
- Se registra el `errorMessage` de simulation como `WARNING` en lugar de ignorarlo.
- Cuando `initialDate` o `finalDate` son `null`, se calcula un **fallback al mes calendario actual** (primer día del mes → hoy).
- La consulta de bandas ya no depende de las fechas del simulation; siempre se ejecuta si hay `schedule_code` configurado.
- Si `currentConsumption` viene en 0 desde simulation, se calcula el total sumando las bandas procesadas.

### `ute/client.py`
- Se agrega logging de la respuesta cruda en `get_current_consumption`, `get_total_debt` y `get_consumption_by_band` para facilitar el diagnóstico futuro.

## Verificación

El endpoint de bandas `/accounts/{servicePointId}/calculateConsumptionForPlan/{scheduleCode}/{start}/{end}` funciona correctamente con el `servicePointId` y fechas explícitas, retornando datos reales:

```
PUNTA: 11.0 kWh
LLANO: 45.0 kWh
VALLE: 24.0 kWh
Total: 80.0 kWh
```

## Notas para el PR

- Investigar por qué `/accounts/consumption/simulation` falla para este `serviceAgreementId`. Puede ser un problema de configuración en el backend de UTE o un cambio en la API.
- El `currentSpending` sigue en 0 ya que proviene del simulation. Evaluar si hay otro endpoint que provea el gasto estimado del período.
- Las bandas retornan `"errorCode": "1"` — verificar si ese campo tiene documentación o impacto.
