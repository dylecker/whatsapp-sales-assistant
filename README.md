# WhatsApp Sales Assistant

Proyecto de Ingeniería I · Ingeniería de Sistemas · UTB. Asistente conversacional para ventas por
WhatsApp de mipymes: responde con el catálogo del negocio, registra pedidos preliminares, mueve al
cliente por el embudo y pasa la conversación a una persona cuando hace falta.

Repositorio: https://github.com/dylecker/whatsapp-sales-assistant · Prototipo navegable (diseño del panel): https://whapp-salesassistant-7e1299.netlify.app

Autores: Dylan Andres Ecker Lopez y Hasmet Gonzalez Perez · Docente: Aisner Marrugo.

## Cómo ejecutarlo

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python -m pytest -q            # 27 pruebas de extremo a extremo (todas pasan)
python scripts/demo.py         # demostración completa en consola
python -m app.main             # servidor en http://127.0.0.1:8000 con datos de ejemplo
```

Usuarios de ejemplo (negocio ficticio «Moda Caribe»): `dueno@modacaribe.test` y
`vendedor@modacaribe.test`, contraseña `demo1234`.

## Estructura

| Archivo | Responsabilidad |
| --- | --- |
| `app/api.py` | Webhook de WhatsApp (GET de verificación y POST firmado) y API REST del panel |
| `app/service.py` | **Flujo 1** y traspaso a humano: orquesta contexto, modelo, embudo, pedidos y envío |
| `app/llm.py` | Capa de abstracción del modelo: `RuleBasedProvider` (local) y `AnthropicProvider` (API) |
| `app/retrieval.py` | Recuperación de contexto (catálogo y preguntas frecuentes) |
| `app/whatsapp.py` | Lectura del webhook y envío (`SimulatedSender` / `CloudApiSender`) |
| `app/security.py` | Firma HMAC del webhook, hash scrypt de contraseñas, JWT |
| `app/schema.sql` | Modelo de datos (10 entidades, restricciones y disparadores de trazabilidad) |
| `tests/` | Pruebas contra un servidor real: webhook firmado → base de datos → API del panel |
| `prototipo/index.html` | Prototipo navegable del panel (HTML con datos de ejemplo; no está conectado a la API) |
| `scripts/demo.py` | Recorrido completo; su salida está en `docs/evidencia_demo.txt` |

## Variables de entorno

`WSA_DB_PATH`, `WSA_APP_SECRET`, `WSA_VERIFY_TOKEN`, `WSA_JWT_SECRET`, `WSA_LLM_PROVIDER`
(`reglas` | `anthropic`), `WSA_SENDER` (`simulado` | `cloud_api`), `ANTHROPIC_API_KEY`, `WHATSAPP_TOKEN`.
Los valores por defecto son solo para desarrollo.

## Qué NO está probado todavía

- `AnthropicProvider` y `CloudApiSender` están escritos pero no se han ejecutado contra los servicios reales.
- La demo y las pruebas usan el proveedor local por reglas y un envío simulado.
- La base es SQLite; el diseño en PostgreSQL + pgvector y la migración a FastAPI/SQLAlchemy quedan para Proyecto de Ingeniería II.
- Pendientes de requerimientos: RF-14 (recordatorios), RF-15 (exportar CSV), eliminación de datos de un cliente (RNF-04) y documentación OpenAPI (RNF-09).
