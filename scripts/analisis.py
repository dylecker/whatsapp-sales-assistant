"""Analisis estadistico de varias corridas de scripts/evaluar_llm.py (solo biblioteca estandar).

Uso (cada grupo es NOMBRE=patron de archivos .json; --comparar A B hace la prueba de McNemar entre dos grupos):
    python scripts/analisis.py B0="experiments/B0_reglas*.json" C1="experiments/C1_qwen_hibrido*.json" \\
        B1="experiments/B1_qwen_hibrido_sin_rag*.json" --comparar C1 B1 --salida experiments/analisis_E1

Un caso cuenta como aprobado si acierta en MAS de la mitad de las corridas del grupo.
Intervalo de confianza: Wilson al 95 %. Comparacion de dos grupos: McNemar exacto (binomial, dos colas) sobre los mismos casos.
"""
import argparse
import glob
import json
import math
import statistics
from pathlib import Path


def wilson(k: int, n: int, z: float = 1.96):
    if n == 0:
        return 0.0, 0.0
    p = k / n
    den = 1 + z * z / n
    centro = (p + z * z / (2 * n)) / den
    margen = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return centro - margen, centro + margen


def mcnemar_exacto(b: int, c: int) -> float:
    n = b + c
    if n == 0:
        return 1.0
    cola = sum(math.comb(n, i) for i in range(0, min(b, c) + 1)) / 2 ** n
    return min(1.0, 2 * cola)


def cargar(patron: str):
    archivos = sorted(glob.glob(patron))
    if not archivos:
        raise SystemExit("No hay archivos para el patron: " + patron)
    return [(f, json.loads(Path(f).read_text(encoding="utf-8"))) for f in archivos]


def por_mayoria(corridas):
    ids = None
    for _, d in corridas:
        s = {c["id"] for c in d["casos"]}
        ids = s if ids is None else ids & s
    votos, meta = {}, {}
    for _, d in corridas:
        for c in d["casos"]:
            if c["id"] in ids:
                votos.setdefault(c["id"], []).append(bool(c["acierto"]))
                meta[c["id"]] = (c.get("categoria", ""), c.get("variante", "") or "")
    aprobado = {i: sum(v) > len(v) / 2 for i, v in votos.items()}
    inestable = {i: 0 < sum(v) < len(v) for i, v in votos.items()}
    return aprobado, inestable, meta


def media_desv(valores):
    return statistics.mean(valores), (statistics.stdev(valores) if len(valores) > 1 else 0.0)


def tabla(filas):
    ancho = [max(len(str(f[i])) for f in filas) for i in range(len(filas[0]))]
    lineas = ["| " + " | ".join(str(c).ljust(ancho[i]) for i, c in enumerate(f)) + " |" for f in filas]
    lineas.insert(1, "|" + "|".join("-" * (a + 2) for a in ancho) + "|")
    return "\n".join(lineas)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("grupos", nargs="+", help="NOMBRE=patron")
    ap.add_argument("--comparar", nargs=2, action="append", metavar=("A", "B"), default=[])
    ap.add_argument("--salida", help="prefijo del archivo .md de salida")
    a = ap.parse_args()

    grupos = {}
    for g in a.grupos:
        nombre, patron = g.split("=", 1)
        grupos[nombre] = cargar(patron)

    datos = {}
    filas = [["Grupo", "Corridas", "Exactitud media ± desv. (puntos)", "Por mayoría (IC Wilson 95 %)", "Casos inestables",
              "Bloqueadas (media)", "Precios fuera del catálogo", "Latencia p50 / p95 (s)"]]
    for nombre, corridas in grupos.items():
        ex = [d["resumen"]["exactitud_pct"] for _, d in corridas]
        m, s = media_desv(ex)
        aprobado, inestable, meta = por_mayoria(corridas)
        k, n = sum(aprobado.values()), len(aprobado)
        lo, hi = wilson(k, n)
        bloq = statistics.mean(d["resumen"]["bloqueadas_por_veracidad"] for _, d in corridas)
        precios = max(d["resumen"]["precios_inventados_enviados"] for _, d in corridas)
        lat = [d["resumen"]["latencia_s"] for _, d in corridas if "latencia_s" in d["resumen"]]
        lat_txt = "{:.1f} / {:.1f}".format(statistics.mean(x["p50"] for x in lat), statistics.mean(x["p95"] for x in lat)) if lat else "-"
        datos[nombre] = (aprobado, meta)
        filas.append([nombre, len(corridas), "{:.1f} ± {:.1f}".format(m, s),
                      "{:.1f} % ({}/{}; {:.1f}–{:.1f})".format(100 * k / n, k, n, 100 * lo, 100 * hi),
                      "{}/{}".format(sum(inestable.values()), n), "{:.1f}".format(bloq), precios, lat_txt])
    out = ["# Análisis de corridas", "", "Un caso cuenta como aprobado si acierta en más de la mitad de las corridas. "
           "«Precios fuera del catálogo» es el máximo entre corridas (debe ser 0).", "", tabla(filas)]

    for x, y in a.comparar:
        ax, _ = datos[x]
        ay, _ = datos[y]
        ids = sorted(set(ax) & set(ay))
        b = sum(ax[i] and not ay[i] for i in ids)
        c = sum(ay[i] and not ax[i] for i in ids)
        dif = 100 * (sum(ax[i] for i in ids) - sum(ay[i] for i in ids)) / len(ids)
        out += ["", "## McNemar: {} contra {}".format(x, y), "",
                "- Casos comparados: {}".format(len(ids)),
                "- Acierta {} y falla {}: {}; acierta {} y falla {}: {}".format(x, y, b, y, x, c),
                "- Diferencia de exactitud ({} menos {}): {:+.1f} puntos".format(x, y, dif),
                "- p (exacto, dos colas): {:.4f}".format(mcnemar_exacto(b, c))]

    categorias = sorted({m[0] for _, (_, meta) in datos.items() for m in meta.values()})
    out += ["", "## Exactitud por categoría (por mayoría)", ""]
    filas = [["Categoría"] + list(datos)]
    for cat in categorias:
        fila = [cat]
        for nombre, (aprobado, meta) in datos.items():
            ids = [i for i in aprobado if meta[i][0] == cat]
            fila.append("{}/{}".format(sum(aprobado[i] for i in ids), len(ids)))
        filas.append(fila)
    out.append(tabla(filas))

    variantes = sorted({m[1] for _, (_, meta) in datos.items() for m in meta.values() if m[1]})
    if variantes:
        out += ["", "## Exactitud por variante lingüística (por mayoría)", ""]
        filas = [["Variante"] + list(datos)]
        for v in variantes:
            fila = [v]
            for nombre, (aprobado, meta) in datos.items():
                ids = [i for i in aprobado if meta[i][1] == v]
                fila.append("{}/{} ({:.0f} %)".format(sum(aprobado[i] for i in ids), len(ids), 100 * sum(aprobado[i] for i in ids) / max(len(ids), 1)))
            filas.append(fila)
        out.append(tabla(filas))

    texto = "\n".join(out) + "\n"
    print(texto)
    if a.salida:
        Path(a.salida + ".md").write_text(texto, encoding="utf-8")
        print("Escrito: " + a.salida + ".md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())