# Changelog

## 1.3.14

- **Fix**: el sensor "Historial Facturación" quedaba en `unknown` porque el JSON
  superaba el límite de 255 caracteres del estado de un sensor en HA. Ahora se
  publica el payload mínimo (`cycle` + `amount`), que es lo que consume el dashboard.

## 1.3.13

- **Nuevo sensor "Historial Facturación"**: publica los montos reales facturados
  por UTE (con IVA y cargo fijo) tomados de `/invoices`. Cada factura se ancla a su
  ciclo de cierre (mes anterior al vencimiento, ya que UTE cierra el día 26 y factura
  a mes vencido). Se exponen los últimos 6 ciclos vía MQTT (`billing_history`).
- Solo aplica a tarifas TRT y TRD (junto al "Historial Mensual" de kWh).
