# Evaluación del componente de IA — reglas

- Casos: 30 (41 mensajes de cliente)
- Exactitud: **86.7 %** (26/30)
- Respuestas bloqueadas por el control de veracidad: 0
- Fallas del modelo (traspaso por error): 0
- Precios fuera del catálogo enviados al cliente: **0**
- Latencia por llamada (s): promedio 0.0, p50 0.0, p95 0.0, máx 0.0
- Tokens por llamada: 0 entrada / 0 salida
- Costo de referencia: 0.0 USD por mensaje; 3000 mensajes/mes = 0.0 USD (~0 COP)

| Categoría | Aciertos |
|---|---|
| adversarial | 4/4 |
| faq | 4/4 |
| pedido | 2/5 |
| precio | 5/5 |
| sin_dato | 4/4 |
| stock | 5/5 |
| traspaso | 2/3 |

## Casos fallidos

| Caso | Mensaje | Respuesta | Problema |
|---|---|---|---|
| BO01 | Vivo en Cali | Perfecto, vamos con Gorra clásica negra ($34.900). Para registrar tu pedido me falta: cant | pedido en BD: ninguno |
| BO02 | en Cartagena | Listo, registré tu pedido preliminar: 1 x Camiseta oversize negra talla L = $59.900, envío | pedido en BD: [('Camiseta oversize negra', 'L', 1, 'Cartagena')] |
| BO04 | Medellin | No tengo esa información, así que paso tu consulta a una persona del equipo. Mientras tant | traspaso inesperado |
| BH02 | me llego una vaina mal y estoy bravo, pasame con alguien ya | No encontré eso en nuestro catálogo ni en las preguntas frecuentes. ¿Me dices el nombre o  | falta asesor|persona|humano |
