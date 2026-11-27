# WhatsApp Sales Assistant

Proyecto de Ingeniería I · Ingeniería de Sistemas · UTB, continuado como proyecto final de Inteligencia Artificial.
Asistente conversacional para ventas por WhatsApp de mipymes: responde con el catálogo del negocio, registra pedidos
preliminares, mueve al cliente por el embudo y pasa la conversación a una persona cuando hace falta.

Repositorio: https://github.com/dylecker/whatsapp-sales-assistant · Prototipo navegable (diseño del panel): https://whapp-salesassistant-7e1299.netlify.app

Autores (Proyecto de Ingeniería I): Dylan Andres Ecker Lopez y Hasmet Gonzalez Perez · Docente: Aisner Marrugo.

Proyecto final de Inteligencia Artificial: Hasmet Gonzalez Perez, Dylan Andres Ecker Lopez y Jesus Nicanor Gutierrez Grau.

## Cómo ejecutarlo

Linux o macOS:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

Windows (PowerShell):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Después, en cualquiera de los dos:

```bash
python -m pytest -q            # 59 pruebas automatizadas (todas pasan en la validación realizada)
python scripts/demo.py         # demostración completa en consola
python -m app.main             # servidor en http://127.0.0.1:8000 con datos de ejemplo
```

Usuarios de ejemplo (negocio ficticio «Moda Caribe»): `dueno@modacaribe.test` y
`vendedor@modacaribe.test`, contraseña `demo1234`.

## Evaluación del componente de IA

`scripts/evaluar_llm.py` ejecuta 50 casos fijos (65 mensajes) contra el servicio real y mide exactitud, precios fuera del
catálogo, latencia y costo. Para el proyecto final de IA (ruta D: lenguaje natural y LLM) se compara la línea base sin
recuperación contra el modelo con recuperación del catálogo. Requiere Ollama con el modelo descargado (`ollama pull qwen2.5:3b`).

En PowerShell:

```powershell
# B0: reglas sin LLM
python scripts/evaluar_llm.py --salida experiments/B0_reglas

# C1: Qwen2.5-3B (Ollama), arquitectura híbrida, con recuperación léxica
$env:WSA_LLM_PROVIDER = "hibrido:ollama"; $env:WSA_LLM_MODEL = "qwen2.5:3b"
python scripts/evaluar_llm.py --salida experiments/C1_qwen_hibrido

# B1: igual que C1 pero sin catálogo ni preguntas frecuentes para el modelo
$env:WSA_SIN_RECUPERACION = "1"
python scripts/evaluar_llm.py --salida experiments/B1_qwen_hibrido_sin_rag
Remove-Item Env:WSA_SIN_RECUPERACION, Env:WSA_LLM_PROVIDER, Env:WSA_LLM_MODEL
```

Resultados del hito 2 (50 casos de desarrollo, una corrida, temperatura 0):

| Configuración | Exactitud | Precios fuera del catálogo enviados | Latencia p50 / p95 |
| --- | --- | --- | --- |
| B0: reglas sin LLM | 100 % (50/50) | 0 | 0 s |
| C1: Qwen2.5-3B híbrido + recuperación léxica | 82 % (41/50) | 0 | 11,7 / 15,7 s |
| B1: Qwen2.5-3B híbrido, sin recuperación | 40 % (20/50) | 0 | 9,0 / 10,9 s |

Los archivos completos están en `experiments/`; los del Avance 6 (Qwen y Nemotron, modelo solo e híbrido) están en
`docs/resultados_*`. El 100 % de B0 no mide calidad porque las reglas se escribieron viendo esos mismos casos. Siguen
pendientes la prueba ciega, la recuperación vectorial, las corridas repetidas y Nemotron en esta evaluación. El uso de IA
generativa en el trabajo se registra en `docs/bitacora_ia.md`.

## Estructura

La carpeta `app/` equivale conceptualmente a `src/` y contiene el código fuente principal de la aplicación.

| Archivo | Responsabilidad |
| --- | --- |
| `app/api.py` | Webhook de WhatsApp (GET de verificación y POST firmado) y API REST del panel |
| `app/service.py` | **Flujo 1** y traspaso a humano: orquesta contexto, modelo, embudo, pedidos y envío |
| `app/llm.py` | Capa de abstracción del modelo: `RuleBasedProvider` (local), `OpenAICompatProvider` (Ollama y NVIDIA), `AnthropicProvider` (API), `HybridProvider` (reglas para lo crítico y modelo para el resto) y `MeteredProvider` (medición) |
| `app/retrieval.py` | Recuperación léxica de contexto (catálogo y preguntas frecuentes) |
| `app/veracidad.py` | Control de veracidad: bloquea respuestas con precios, stock o tallas que no están en el catálogo |
| `app/whatsapp.py` | Lectura del webhook y envío (`SimulatedSender` / `CloudApiSender`) |
| `app/security.py` | Firma HMAC del webhook, hash scrypt de contraseñas, JWT |
| `app/schema.sql` | Modelo de datos (10 entidades, restricciones y disparadores de trazabilidad) |
| `tests/` | Pruebas contra un servidor real (webhook firmado, base de datos, API del panel), del proveedor compatible y de la línea base sin recuperación |
| `prototipo/index.html` | Prototipo navegable del panel (HTML con datos de ejemplo; no está conectado a la API) |
| `scripts/demo.py` | Recorrido completo; su salida está en `docs/evidencia_demo.txt` |
| `scripts/evaluar_llm.py` | Evaluación del componente de IA; escribe `.json` y `.md` |
| `experiments/` | Resultados del proyecto final de IA (B0, C1 y B1) con sus registros |
| `docs/` | Evidencia de la demo, guía del modelo real, resultados del Avance 6, diagramas y bitácora de uso de IA |

## Variables de entorno

`WSA_DB_PATH`, `WSA_APP_SECRET`, `WSA_VERIFY_TOKEN`, `WSA_JWT_SECRET`, `WSA_SENDER` (`simulado` | `cloud_api`),
`WHATSAPP_TOKEN`. Los valores por defecto son solo para desarrollo.

Modelo de lenguaje: `WSA_LLM_PROVIDER` (`reglas` | `ollama` | `nvidia` | `openai` | `anthropic` | `hibrido:ollama` |
`hibrido:nvidia`), `WSA_LLM_MODEL`, `WSA_LLM_BASE_URL`, `WSA_LLM_API_KEY`, `WSA_LLM_TIMEOUT`, `WSA_LLM_MAX_TOKENS`,
`ANTHROPIC_API_KEY` y `WSA_SIN_RECUPERACION` (con valor `1`, el modelo no recibe catálogo ni preguntas frecuentes).

## Qué NO está probado todavía

- `AnthropicProvider` y `CloudApiSender` están escritos pero no se han ejecutado contra los servicios reales.
- La demo y las pruebas automáticas usan el proveedor local por reglas y un envío simulado. Los modelos reales (Ollama y NVIDIA) se evaluaron con `scripts/evaluar_llm.py`, con casos escritos por el equipo y una corrida por configuración.
- La base es SQLite; el diseño en PostgreSQL + pgvector y la migración a FastAPI/SQLAlchemy quedan para Proyecto de Ingeniería II.
- Pendientes de requerimientos: RF-14 (recordatorios), RF-15 (exportar CSV), eliminación de datos de un cliente (RNF-04) y documentación OpenAPI (RNF-09).


## Reproducción desde una instalación limpia

Los siguientes pasos permiten clonar, instalar y evaluar el proyecto desde un entorno nuevo.

1. **Clonar el repositorio y entrar en la carpeta:**

   ```powershell
   git clone https://github.com/dylecker/whatsapp-sales-assistant.git; cd whatsapp-sales-assistant
   ```

2. **Crear y activar el entorno virtual:**

   ```powershell
   python -m venv .venv; .\.venv\Scripts\Activate.ps1
   ```

3. **Instalar las dependencias:**

   ```powershell
   pip install -r requirements.txt
   ```

4. **Ejecutar las pruebas automatizadas:**

   ```powershell
   python -m pytest -q
   ```

5. **Ejecutar la evaluación B0 de los 50 casos:**

   ```powershell
   python scripts/evaluar_llm.py --salida experiments/B0_reglas
   ```
