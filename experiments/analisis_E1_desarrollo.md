# Análisis de corridas

Un caso cuenta como aprobado si acierta en más de la mitad de las corridas. «Precios fuera del catálogo» es el máximo entre corridas (debe ser 0).

| Grupo | Corridas | Exactitud media ± desv. (puntos) | Por mayoría (IC Wilson 95 %) | Casos inestables | Bloqueadas (media) | Precios fuera del catálogo | Latencia p50 / p95 (s) |
|-------|----------|----------------------------------|------------------------------|------------------|--------------------|----------------------------|------------------------|
| B0    | 1        | 100.0 ± 0.0                      | 100.0 % (50/50; 92.9–100.0)  | 0/50             | 0.0                | 0                          | 0.0 / 0.0              |
| C1    | 3        | 80.7 ± 1.2                       | 80.0 % (40/50; 67.0–88.8)    | 3/50             | 2.0                | 0                          | 11.7 / 15.1            |
| B1    | 3        | 41.3 ± 1.2                       | 42.0 % (21/50; 29.4–55.8)    | 1/50             | 2.0                | 0                          | 8.8 / 10.9             |

## McNemar: C1 contra B1

- Casos comparados: 50
- Acierta C1 y falla B1: 19; acierta B1 y falla C1: 0
- Diferencia de exactitud (C1 menos B1): +38.0 puntos
- p (exacto, dos colas): 0.0000

## Exactitud por categoría (por mayoría)

| Categoría   | B0    | C1    | B1   |
|-------------|-------|-------|------|
| adversarial | 4/4   | 3/4   | 1/4  |
| faq         | 8/8   | 6/8   | 0/8  |
| pedido      | 7/7   | 7/7   | 7/7  |
| precio      | 10/10 | 10/10 | 0/10 |
| sin_dato    | 6/6   | 4/6   | 4/6  |
| stock       | 10/10 | 5/10  | 4/10 |
| traspaso    | 5/5   | 5/5   | 5/5  |
