# Análisis de corridas

Un caso cuenta como aprobado si acierta en más de la mitad de las corridas. «Precios fuera del catálogo» es el máximo entre corridas (debe ser 0).

| Grupo | Corridas | Exactitud media ± desv. (puntos) | Por mayoría (IC Wilson 95 %) | Casos inestables | Bloqueadas (media) | Precios fuera del catálogo | Latencia p50 / p95 (s) |
|-------|----------|----------------------------------|------------------------------|------------------|--------------------|----------------------------|------------------------|
| B0    | 1        | 86.7 ± 0.0                       | 86.7 % (26/30; 70.3–94.7)    | 0/30             | 0.0                | 0                          | 0.0 / 0.0              |
| C1    | 3        | 55.6 ± 2.0                       | 53.3 % (16/30; 36.1–69.8)    | 4/30             | 2.7                | 0                          | 13.1 / 15.8            |
| B1    | 3        | 43.3 ± 3.4                       | 43.3 % (13/30; 27.4–60.8)    | 2/30             | 1.3                | 0                          | 10.5 / 12.7            |

## McNemar: C1 contra B1

- Casos comparados: 30
- Acierta C1 y falla B1: 5; acierta B1 y falla C1: 2
- Diferencia de exactitud (C1 menos B1): +10.0 puntos
- p (exacto, dos colas): 0.4531

## Exactitud por categoría (por mayoría)

| Categoría   | B0  | C1  | B1  |
|-------------|-----|-----|-----|
| adversarial | 4/4 | 3/4 | 3/4 |
| faq         | 4/4 | 1/4 | 0/4 |
| pedido      | 2/5 | 1/5 | 3/5 |
| precio      | 5/5 | 4/5 | 0/5 |
| sin_dato    | 4/4 | 4/4 | 4/4 |
| stock       | 5/5 | 1/5 | 1/5 |
| traspaso    | 2/3 | 2/3 | 2/3 |

## Exactitud por variante lingüística (por mayoría)

| Variante   | B0          | C1         | B1         |
|------------|-------------|------------|------------|
| abreviado  | 6/7 (86 %)  | 4/7 (57 %) | 4/7 (57 %) |
| formal     | 8/9 (89 %)  | 5/9 (56 %) | 4/9 (44 %) |
| modismos   | 6/8 (75 %)  | 3/8 (38 %) | 2/8 (25 %) |
| sin_tildes | 6/6 (100 %) | 4/6 (67 %) | 3/6 (50 %) |
