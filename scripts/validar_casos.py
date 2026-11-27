"""Revision estructural de un archivo de casos (NO ejecuta el sistema ni el modelo).

Uso:  python scripts/validar_casos.py data/casos_prueba_ciega.json
Comprueba: estructura, ids unicos y prefijos, conteos por categoria/variante/autor, consistencia con el catalogo
(nombres exactos, tallas, stock, precios), validez de las expresiones regulares y criterios de espera demasiado debiles.
"""
import collections
import json
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.seed import PRODUCTOS  # noqa: E402

PREFIJOS = {"BP": "precio", "BS": "stock", "BF": "faq", "BN": "sin_dato", "BO": "pedido", "BH": "traspaso", "BA": "adversarial"}
VARIANTES = {"formal", "modismos", "sin_tildes", "abreviado"}
CLAVES = {"id", "categoria", "variante", "autor", "mensajes", "espera", "prohibe", "traspaso", "pedido"}
CATALOGO = {p[0]: p for p in PRODUCTOS}
PALABRAS = {"oversize": "Camiseta oversize negra", "basica": "Camiseta básica blanca", "jean": "Jean slim azul",
            "floral": "Vestido floral", "lino": "Vestido lino beige", "gorra": "Gorra clásica negra", "sudadera": "Sudadera gris con capota"}
errores, avisos = [], []


def err(i, t):
    errores.append("[%s] %s" % (i, t))


def avi(i, t):
    avisos.append("[%s] %s" % (i, t))


def sin_tilde(t):
    return "".join(c for c in unicodedata.normalize("NFD", str(t)) if unicodedata.category(c) != "Mn").lower()


def revisar_criterios(cid, campo, lista, categoria):
    if not isinstance(lista, list) or not all(isinstance(x, str) for x in lista):
        err(cid, campo + " debe ser una lista de textos")
        return
    for patron in lista:
        if patron.startswith("re:"):
            try:
                re.compile(patron[3:])
            except re.error as e:
                err(cid, "%s: expresion regular invalida (%s): %s" % (campo, e, patron))
            continue
        for alt in patron.split("|"):
            n = alt.strip()
            if not n:
                err(cid, "%s: alternativa vacia en '%s' (una cadena vacia coincide con todo)" % (campo, patron))
            elif len(n) <= 2 and not n.isdigit():
                avi(cid, "%s: '%s' es muy corto: se busca como subcadena y coincide dentro de otras palabras. Usa re:\\b%s\\b" % (campo, n, re.escape(n)))
            elif len(n) <= 3 and n.isalpha():
                avi(cid, "%s: '%s' es muy corto y puede aparecer dentro de otras palabras" % (campo, n))
            if campo == "espera" and alt != sin_tilde(alt) and "|" not in patron:
                avi(cid, "espera '%s' lleva tilde y no tiene alternativa sin tilde (si el modelo la omite, falla)" % alt)


def main(ruta):
    datos = json.loads(Path(ruta).read_text(encoding="utf-8"))
    if not isinstance(datos, list):
        raise SystemExit("El archivo debe ser una lista JSON de casos")
    ids = [d.get("id") for d in datos]
    for rep in sorted({i for i in ids if ids.count(i) > 1}):
        err(rep, "id repetido")
    for d in datos:
        cid = d.get("id", "?")
        faltan, sobran = CLAVES - set(d), set(d) - CLAVES
        if faltan:
            err(cid, "faltan claves: %s" % sorted(faltan))
        if sobran:
            avi(cid, "claves no previstas: %s" % sorted(sobran))
        cat = d.get("categoria")
        pref = str(cid)[:2]
        if PREFIJOS.get(pref) != cat:
            err(cid, "el prefijo '%s' no corresponde a la categoria '%s'" % (pref, cat))
        if d.get("variante") not in VARIANTES:
            err(cid, "variante invalida: %r" % d.get("variante"))
        msgs = d.get("mensajes")
        if not isinstance(msgs, list) or not msgs or not all(isinstance(m, str) and m.strip() for m in msgs):
            err(cid, "mensajes debe ser una lista de textos no vacios")
        elif cat != "pedido" and len(msgs) > 1:
            avi(cid, "tiene %d mensajes; solo los pedidos suelen llevar varios" % len(msgs))
        revisar_criterios(cid, "espera", d.get("espera", []), cat)
        revisar_criterios(cid, "prohibe", d.get("prohibe", []), cat)
        if d.get("traspaso") not in (True, False):
            err(cid, "traspaso debe ser true o false")
        elif (cat == "traspaso") != bool(d.get("traspaso")):
            err(cid, "traspaso=%s no es coherente con la categoria '%s'" % (d.get("traspaso"), cat))
        ped = d.get("pedido")
        if cat == "pedido" and ped is None:
            err(cid, "un caso de pedido debe tener pedido='ninguno' o [producto, talla, cantidad, ciudad]")
        if cat != "pedido" and ped is not None:
            avi(cid, "no es de la categoria pedido pero trae el campo pedido")
        if isinstance(ped, list):
            if len(ped) != 4:
                err(cid, "pedido debe tener 4 elementos [producto, talla, cantidad, ciudad]")
            else:
                prod, talla, cant, ciudad = ped
                p = CATALOGO.get(prod)
                if not p:
                    err(cid, "producto '%s' no existe con ese nombre exacto (revisa tildes y mayusculas)" % prod)
                else:
                    tallas = p[4]
                    if talla is None and tallas != ["unica"]:
                        err(cid, "talla null pero '%s' tiene tallas %s" % (prod, tallas))
                    if talla is not None and talla not in tallas:
                        err(cid, "talla '%s' no existe en '%s' (%s): ese caso deberia ser pedido='ninguno'" % (talla, prod, tallas))
                    if not isinstance(cant, int) or cant < 1:
                        err(cid, "cantidad invalida: %r" % (cant,))
                    elif cant > p[5]:
                        err(cid, "cantidad %d supera el stock (%d) de '%s': deberia ser pedido='ninguno'" % (cant, p[5], prod))
                    if p[5] == 0:
                        err(cid, "'%s' esta agotado: deberia ser pedido='ninguno'" % prod)
                if not isinstance(ciudad, str) or not ciudad.strip():
                    err(cid, "ciudad vacia")
        elif ped not in (None, "ninguno"):
            err(cid, "pedido invalido: %r" % (ped,))
        if cat == "precio" and isinstance(msgs, list) and msgs:
            texto = sin_tilde(" ".join(msgs))
            hallados = {PALABRAS[k] for k in PALABRAS if k in texto}
            esperados = {p[3] for n, p in CATALOGO.items() if n in hallados}
            fmt = {"{:,}".format(v).replace(",", ".") for v in esperados}
            esp = " ".join(d.get("espera", []))
            precios = set(re.findall(r"\d{2,3}[.,]\d{3}", esp))
            if precios and fmt and not ({x.replace(",", ".") for x in precios} & fmt):
                err(cid, "el mensaje habla de %s (precio %s) pero espera %s" % (sorted(hallados), sorted(fmt), sorted(precios)))
            if not precios:
                avi(cid, "caso de precio sin una cifra en espera")
        if cat in ("stock", "precio", "faq") and not d.get("espera"):
            avi(cid, "categoria '%s' sin criterio en espera: nunca podria fallar por falta de dato" % cat)
    print("Casos:", len(datos))
    print("Por categoria:", dict(collections.Counter(d.get("categoria") for d in datos)))
    print("Por variante:", dict(collections.Counter(d.get("variante") for d in datos)))
    print("Por autor:", dict(collections.Counter(d.get("autor") for d in datos)))
    for v in VARIANTES:
        if sum(1 for d in datos if d.get("variante") == v) < 6:
            err("variantes", "hay menos de 6 casos de la variante '%s'" % v)
    print("\nERRORES (%d):" % len(errores))
    print("\n".join(errores) or "  ninguno")
    print("\nAVISOS (%d):" % len(avisos))
    print("\n".join(avisos) or "  ninguno")
    return 1 if errores else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "data/casos_prueba_ciega.json"))