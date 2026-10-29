from __future__ import annotations

import re
import unicodedata

STOPWORDS = {
    "de", "la", "el", "los", "las", "un", "una", "unos", "unas", "y", "o", "en", "a", "con", "por",
    "para", "que", "es", "si", "me", "mi", "tu", "su", "lo", "al", "del", "se", "hay", "tiene",
    "tienen", "tengo", "quiero", "quisiera", "cuanto", "cuesta", "vale", "precio", "talla", "tallas",
    "hola", "buenas", "buenos", "dias", "tardes", "noches", "favor", "porfa", "gracias", "ese",
    "esa", "este", "esta", "son", "como", "cual", "cuales", "estan", "esta", "tienes", "puedo",
    "pueden", "van", "ver", "algo", "mas", "muy", "ya", "le", "les", "mis", "sus", "disponible",
    "disponibles", "disponibilidad", "stock", "queda", "quedan", "llevo", "comprar", "pedir",
}


def norm(texto: str) -> str:
    """Minusculas, sin tildes y con espacios simples."""
    t = unicodedata.normalize("NFKD", texto.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", t).strip()


def stem(palabra: str) -> str:
    if len(palabra) > 5 and palabra.endswith("es"):
        return palabra[:-2]
    if len(palabra) > 3 and palabra.endswith("s"):
        return palabra[:-1]
    return palabra


def tokens(texto: str, quitar_stop: bool = True) -> list[str]:
    out = []
    for w in re.findall(r"[a-z0-9]+", norm(texto)):
        if quitar_stop and w in STOPWORDS:
            continue
        out.append(stem(w))
    return out


def cop(valor: int) -> str:
    """Formato de pesos colombianos: 85000 -> $85.000"""
    return "$" + f"{int(valor):,}".replace(",", ".")


PRECIO_RE = re.compile(r"\$\s?(\d{1,3}(?:\.\d{3})+|\d+)")


def precios_en_texto(texto: str) -> list[int]:
    return [int(m.replace(".", "")) for m in PRECIO_RE.findall(texto)]
