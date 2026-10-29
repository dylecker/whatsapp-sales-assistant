"""Punto de entrada: `python -m app.main` crea la base, carga datos de ejemplo y levanta el servidor."""
from __future__ import annotations

import os

import uvicorn

from .api import create_app
from .config import Settings
from .db import connect, init_db
from .seed import seed

settings = Settings()
init_db(settings.db_path)
_c = connect(settings.db_path)
seed(_c)
_c.close()
app = create_app(settings)

if __name__ == "__main__":
    uvicorn.run(app, host=os.getenv("HOST", "127.0.0.1"), port=int(os.getenv("PORT", "8000")))
