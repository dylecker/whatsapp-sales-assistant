-- WhatsApp Sales Assistant - esquema consolidado (prototipo en SQLite).
-- Diez entidades. En PostgreSQL 16 las columnas embedding pasan a VECTOR(n) con pgvector.

CREATE TABLE IF NOT EXISTS negocio (
  id INTEGER PRIMARY KEY,
  nombre TEXT NOT NULL,
  whatsapp_phone_number_id TEXT NOT NULL UNIQUE,
  tono TEXT NOT NULL DEFAULT 'cercano' CHECK (tono IN ('cercano','formal')),
  horario_inicio TEXT NOT NULL DEFAULT '08:00',
  horario_fin TEXT NOT NULL DEFAULT '18:00',
  ia_activa INTEGER NOT NULL DEFAULT 1 CHECK (ia_activa IN (0,1)),
  espera_asesor_min INTEGER NOT NULL DEFAULT 10,
  creado_en TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS usuario (
  id INTEGER PRIMARY KEY,
  negocio_id INTEGER NOT NULL REFERENCES negocio(id),
  nombre TEXT NOT NULL,
  correo TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  rol TEXT NOT NULL CHECK (rol IN ('propietario','vendedor')),
  activo INTEGER NOT NULL DEFAULT 1 CHECK (activo IN (0,1)),
  creado_en TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cliente (
  id INTEGER PRIMARY KEY,
  negocio_id INTEGER NOT NULL REFERENCES negocio(id),
  telefono TEXT NOT NULL,
  nombre TEXT,
  consentimiento_datos INTEGER NOT NULL DEFAULT 0 CHECK (consentimiento_datos IN (0,1)),
  consentimiento_en TEXT,
  creado_en TEXT NOT NULL,
  UNIQUE (negocio_id, telefono)
);

CREATE TABLE IF NOT EXISTS conversacion (
  id INTEGER PRIMARY KEY,
  negocio_id INTEGER NOT NULL REFERENCES negocio(id),
  cliente_id INTEGER NOT NULL REFERENCES cliente(id),
  etapa TEXT NOT NULL DEFAULT 'nuevo'
        CHECK (etapa IN ('nuevo','interesado','negociando','cerrado','perdido')),
  modo TEXT NOT NULL DEFAULT 'ia' CHECK (modo IN ('ia','humano')),
  abierta INTEGER NOT NULL DEFAULT 1 CHECK (abierta IN (0,1)),
  asignado_a INTEGER REFERENCES usuario(id),
  requiere_atencion INTEGER NOT NULL DEFAULT 0 CHECK (requiere_atencion IN (0,1)),
  motivo_traspaso TEXT,
  handoff_en TEXT,
  espera_notificada INTEGER NOT NULL DEFAULT 0 CHECK (espera_notificada IN (0,1)),
  borrador_pedido TEXT,               -- JSON con producto/talla/cantidad/ciudad en curso
  fallos_consecutivos INTEGER NOT NULL DEFAULT 0,
  ultimo_mensaje_en TEXT,
  creada_en TEXT NOT NULL
);
-- Solo una conversacion abierta por cliente
CREATE UNIQUE INDEX IF NOT EXISTS ux_conversacion_abierta
  ON conversacion(cliente_id) WHERE abierta = 1;
CREATE INDEX IF NOT EXISTS ix_conversacion_negocio_etapa ON conversacion(negocio_id, etapa);

CREATE TABLE IF NOT EXISTS mensaje (
  id INTEGER PRIMARY KEY,
  conversacion_id INTEGER NOT NULL REFERENCES conversacion(id),
  negocio_id INTEGER NOT NULL REFERENCES negocio(id),
  remitente TEXT NOT NULL CHECK (remitente IN ('cliente','ia','humano')),
  usuario_id INTEGER REFERENCES usuario(id),
  texto TEXT NOT NULL,
  intencion TEXT,
  wa_message_id TEXT,
  creado_en TEXT NOT NULL,
  CHECK ((remitente = 'humano') = (usuario_id IS NOT NULL))
);
-- Idempotencia del webhook: un mensaje de WhatsApp no se guarda dos veces
CREATE UNIQUE INDEX IF NOT EXISTS ux_mensaje_wa ON mensaje(wa_message_id) WHERE wa_message_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_mensaje_conversacion ON mensaje(conversacion_id, id);

-- Trazabilidad (RNF-11): el registro no se modifica ni se borra.
-- Unica excepcion: completar una sola vez la intencion detectada.
CREATE TRIGGER IF NOT EXISTS mensaje_no_update BEFORE UPDATE ON mensaje
WHEN NOT (OLD.intencion IS NULL AND NEW.intencion IS NOT NULL
          AND OLD.texto = NEW.texto AND OLD.remitente = NEW.remitente
          AND OLD.conversacion_id = NEW.conversacion_id AND OLD.creado_en = NEW.creado_en
          AND OLD.negocio_id = NEW.negocio_id
          AND OLD.wa_message_id IS NEW.wa_message_id AND OLD.usuario_id IS NEW.usuario_id)
BEGIN SELECT RAISE(ABORT, 'mensaje inmutable'); END;

CREATE TRIGGER IF NOT EXISTS mensaje_no_delete BEFORE DELETE ON mensaje
BEGIN SELECT RAISE(ABORT, 'mensaje inmutable'); END;

CREATE TABLE IF NOT EXISTS evento_embudo (
  id INTEGER PRIMARY KEY,
  conversacion_id INTEGER NOT NULL REFERENCES conversacion(id),
  etapa_anterior TEXT NOT NULL,
  etapa_nueva TEXT NOT NULL,
  origen TEXT NOT NULL CHECK (origen IN ('ia','manual')),
  usuario_id INTEGER REFERENCES usuario(id),
  creado_en TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS producto (
  id INTEGER PRIMARY KEY,
  negocio_id INTEGER NOT NULL REFERENCES negocio(id),
  nombre TEXT NOT NULL,
  descripcion TEXT,
  categoria TEXT NOT NULL,
  precio_cop INTEGER NOT NULL CHECK (precio_cop >= 0),
  tallas TEXT NOT NULL DEFAULT '[]',      -- JSON: ["S","M","L"]
  stock INTEGER NOT NULL DEFAULT 0 CHECK (stock >= 0),
  activo INTEGER NOT NULL DEFAULT 1 CHECK (activo IN (0,1)),
  embedding BLOB,                          -- reservada (pgvector); el prototipo usa busqueda lexica
  creado_en TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_producto_negocio ON producto(negocio_id, activo);

CREATE TABLE IF NOT EXISTS pregunta_frecuente (
  id INTEGER PRIMARY KEY,
  negocio_id INTEGER NOT NULL REFERENCES negocio(id),
  tema TEXT NOT NULL,
  pregunta TEXT NOT NULL,
  respuesta TEXT NOT NULL,
  palabras_clave TEXT NOT NULL DEFAULT '',
  activo INTEGER NOT NULL DEFAULT 1 CHECK (activo IN (0,1)),
  embedding BLOB
);

CREATE TABLE IF NOT EXISTS pedido (
  id INTEGER PRIMARY KEY,
  negocio_id INTEGER NOT NULL REFERENCES negocio(id),
  conversacion_id INTEGER NOT NULL REFERENCES conversacion(id),
  cliente_id INTEGER NOT NULL REFERENCES cliente(id),
  ciudad TEXT,
  estado TEXT NOT NULL DEFAULT 'preliminar' CHECK (estado IN ('preliminar','confirmado','cancelado')),
  creado_en TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS item_pedido (
  id INTEGER PRIMARY KEY,
  pedido_id INTEGER NOT NULL REFERENCES pedido(id),
  producto_id INTEGER NOT NULL REFERENCES producto(id),
  talla TEXT,
  cantidad INTEGER NOT NULL CHECK (cantidad > 0),
  precio_unitario_cop INTEGER NOT NULL CHECK (precio_unitario_cop >= 0)
);
