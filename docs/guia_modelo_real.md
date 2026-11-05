# Guía: probar el asistente con un modelo real y gratuito

## Opción A — NVIDIA en la nube (recomendada)
1. Crear cuenta en https://build.nvidia.com, elegir un modelo (por ejemplo un Llama instruct) y generar una API key (`nvapi-...`).
2. Verificar en esa página el nombre exacto del modelo y los límites vigentes del plan gratuito.
3. Windows (PowerShell):
```
$env:WSA_LLM_PROVIDER="nvidia"
$env:WSA_LLM_API_KEY="nvapi-..."
$env:WSA_LLM_MODEL="meta/llama-3.1-70b-instruct"   # ajustar al nombre que muestre build.nvidia.com
python scripts/evaluar_llm.py --salida docs/resultados_nvidia
```

## Opción B — Ollama local (respaldo; funciona sin internet)
1. Instalar Ollama (https://ollama.com) y descargar un modelo pequeño: `ollama pull qwen2.5:3b`
2. `$env:WSA_LLM_PROVIDER="ollama"; $env:WSA_LLM_MODEL="qwen2.5:3b"`
3. `python scripts/evaluar_llm.py --salida docs/resultados_ollama`
Con 8 GB de RAM y una RTX 3050 conviene un modelo de 3B; uno de 7-8B puede ir lento.

## Qué entregar al profesor (Avance 5/6)
- `docs/resultados_*.md` y `.json` (exactitud, precios inventados enviados = 0, latencia p95, tokens, costo de referencia).
- Ejecutar el servidor con el mismo proveedor: `python -m app.main` y escribirle por el webhook simulado (`scripts/demo.py`).
