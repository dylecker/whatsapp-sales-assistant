# Guía: probar el asistente con un modelo real y gratuito

## Opción A — NVIDIA en la nube (recomendada)
1. Crear cuenta en https://build.nvidia.com y generar una API key (`nvapi-...`). No subir la key al repositorio.
2. Modelo probado por el equipo: `nvidia/nemotron-3.5-lightning-30b-a3b`. Es un modelo que razona antes de responder: necesita `WSA_LLM_MAX_TOKENS=4000` y `WSA_LLM_TIMEOUT=180`. (`meta/llama-3.1-70b-instruct` no funcionó en nuestra prueba.) Verificar en esa página el nombre vigente del modelo y sus límites.
3. Windows (PowerShell), arquitectura híbrida (la recomendada):
```
$env:WSA_LLM_PROVIDER="hibrido:nvidia"
$env:WSA_LLM_API_KEY="nvapi-..."
$env:WSA_LLM_MODEL="nvidia/nemotron-3.5-lightning-30b-a3b"
$env:WSA_LLM_MAX_TOKENS="4000"
$env:WSA_LLM_TIMEOUT="180"
python scripts/evaluar_llm.py --salida docs/resultados_hibrido_nvidia
```
Para el modelo solo, usar `WSA_LLM_PROVIDER="nvidia"` y `--salida docs/resultados_solo_nvidia`. Con Ollama, `hibrido:ollama` o `ollama`.
Privacidad: el endpoint gratuito advierte no enviar datos personales o confidenciales y registra el uso; usarlo solo con datos ficticios.

## Opción B — Ollama local (respaldo; funciona sin internet)
1. Instalar Ollama (https://ollama.com) y descargar un modelo pequeño: `ollama pull qwen2.5:3b`
2. `$env:WSA_LLM_PROVIDER="hibrido:ollama"; $env:WSA_LLM_MODEL="qwen2.5:3b"`
3. `python scripts/evaluar_llm.py --salida docs/resultados_hibrido_ollama`
Con 8 GB de RAM y una RTX 3050 conviene un modelo de 3B; uno de 7-8B puede ir lento.

## Qué entregar al profesor (Avance 5/6)
- `docs/resultados_*.md` y `.json` (exactitud, precios inventados enviados = 0, latencia p95, tokens, costo de referencia).
- Ejecutar el servidor con el mismo proveedor: `python -m app.main` y escribirle por el webhook simulado (`scripts/demo.py`; con un modelo lento, el límite de espera de la demo es `WSA_DEMO_TIMEOUT`, 180 s por defecto; cada respuesta indica `origen=modelo` o `origen=reglas`).
