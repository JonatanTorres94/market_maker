# 🤖 Crypto Market Maker Bot (v2.0)

Sistema de **Market Making de alta fidelidad para Binance**, desarrollado en Python con arquitectura desacoplada y orientada a eventos.

Diseñado para ejecutar estrategias de **micro-spread**, con:
- Gestión de inventario
- Control de volatilidad (Drift Gate)
- Ejecución robusta con fallback a REST

---

## 🧱 Arquitectura del Sistema

El bot implementa una arquitectura basada en **capas de decisión**, donde cada acción es trazable:

- **Engine**  
  Orquestador del loop principal. Construye el `CycleState` y ejecuta el `ExecutionPlan`.

- **Coordinator**  
  Ejecuta operaciones atómicas contra el exchange (placement/cancel).  
  Incluye fallback a REST para validación de estado.

- **StateStore**  
  Persistencia de corto plazo para tracking de órdenes activas (BUY/SELL).

- **Maintenance**  
  Servicio de background para:
  - Reconciliación de órdenes
  - Reconciliación de ejecuciones (fills)
  - Limpieza de estado vía REST

---

## 🚀 Ejecución de Sesiones

El sistema utiliza variables de entorno para aislar sesiones, permitiendo correr múltiples estrategias sin colisiones.

---

### 1. Inicializar sesión


```bash
RUN_SESSION_ID=paper_017 \
DRIFT_GATE_LOOKBACK_SECONDS=3 \
DRIFT_GATE_THRESHOLD_BPS=1.5 \
python -m src.scripts.create_paper_session

RUN_SESSION_ID=paper_016 \
DRIFT_GATE_LOOKBACK_SECONDS=3 \
DRIFT_GATE_THRESHOLD_BPS=1.5 \
python -m src.scripts.run_market_maker \
> logs/paper_005.log 2>&1 &

RUN_SESSION_ID=paper_052 \
python -m src.scripts.reconcile_orders

RUN_SESSION_ID=paper_005 \
python -m src.scripts.reconcile_executions

RUN_SESSION_ID=paper_005 \
python -m src.scripts.analyze_journal

### Activar entorno virtual source venv/bin/activate

#Servicio de corrida MINT
systemctl --user stop market-maker-loop.service
pkill -f run_market_maker
systemctl --user start market-maker-loop.service
journalctl --user -u market-maker-loop.service -f