# ==============================================================
# 🏦 BANCO LIVIANO API — PRODUCCIÓN (Supabase + PayPhone)
# ==============================================================

from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
from sqlalchemy import Numeric
from decimal import Decimal
import os
import uuid
import base64
import requests

# --------------------------------------------------------------
# 🌐 CONFIGURACIÓN BASE
# --------------------------------------------------------------
app = Flask(__name__)
CORS(app)

db_url = os.getenv("SUPABASE_DB_URL", "sqlite:///banco_liviano.db")
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)
if "?sslmode=require" not in db_url:
    db_url += "?sslmode=require"

print("🧩 Conectando a base de datos:", db_url)
app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)

# --------------------------------------------------------------
# 🔑 CREDENCIALES PAYPHONE PRODUCCIÓN
# --------------------------------------------------------------
PAYPHONE_CLIENT_ID = os.getenv("PAYPHONE_CLIENT_ID", "J8GXWq6hPUdK0jSb93BQ")
PAYPHONE_SECRET    = os.getenv("PAYPHONE_SECRET",    "cHD4J4oikm6zqxs5OyA")
PAYPHONE_STORE_ID  = int(os.getenv("PAYPHONE_STORE_ID", "125555"))

# Endpoints de producción
PAYPHONE_URL_AUTH     = "https://pay.payphonetodoesposible.com/api/Authentication"
PAYPHONE_URL_SALE     = "https://pay.payphonetodoesposible.com/api/Sale"
PAYPHONE_URL_CALLBACK = os.getenv(
    "PAYPHONE_CALLBACK_URL",
    "https://banco-liviano-mvp.onrender.com/payphone_callback"
)

# Cache simple del token (memoria del proceso)
_TOKEN_CACHE = {"token": None, "exp": datetime.utcnow()}

def _get_payphone_token():
    """
    Obtiene y cachea el access token de PayPhone.
    - Se autentica con BASIC (client_id:secret) contra /api/Authentication
    - Devuelve el token (string) para usar como Bearer en /api/Sale
    """
    global _TOKEN_CACHE

    # Si el token existe y no ha expirado, úsalo
    if _TOKEN_CACHE["token"] and datetime.utcnow() < _TOKEN_CACHE["exp"]:
        return _TOKEN_CACHE["token"]

    basic = base64.b64encode(f"{PAYPHONE_CLIENT_ID}:{PAYPHONE_SECRET}".encode()).decode()
    headers = {"Authorization": f"Basic {basic}"}
    try:
        r = requests.post(PAYPHONE_URL_AUTH, headers=headers, timeout=20)
        # La API devuelve el token como string JSON (ej: "xxxxx")
        if r.status_code == 200:
            token = r.text.strip().strip('"')
            # Cache por ~55 minutos (el token suele durar 1h)
            _TOKEN_CACHE = {"token": token, "exp": datetime.utcnow() + timedelta(minutes=55)}
            print("✅ TOKEN PayPhone obtenido.")
            return token
        else:
            print("❌ Error AUTH PayPhone:", r.status_code, r.text)
            return None
    except Exception as e:
        print("❌ Excepción AUTH PayPhone:", e)
        return None

# --------------------------------------------------------------
# 🧱 MODELOS DE BASE DE DATOS
# --------------------------------------------------------------
class Usuario(db.Model):
    __tablename__ = "usuarios"
    id = db.Column(db.Integer, primary_key=True)
    cedula = db.Column(db.String(10), unique=True, nullable=False)
    telefono = db.Column(db.String(15), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    saldo = db.Column(Numeric(10, 2), default=Decimal("0.00"))
    qr_key_id = db.Column(db.String(36), unique=True, nullable=False)
    movimientos = db.relationship("Movimiento", backref="usuario", lazy=True)


class Movimiento(db.Model):
    __tablename__ = "transacciones"
    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=False)
    titulo = db.Column(db.String(100), nullable=False)
    tipo = db.Column(db.String(20))
    monto = db.Column(Numeric(10, 2), nullable=False)
    fecha = db.Column(db.DateTime, default=datetime.utcnow)


# --------------------------------------------------------------
# 🌐 RUTAS PRINCIPALES
# --------------------------------------------------------------
@app.route("/health")
def health():
    return jsonify({"ok": True})

@app.route("/")
def index():
    return jsonify({"ok": True, "service": "Banco Liviano API conectada a Supabase"})


# -------------------- CREAR USUARIO --------------------
@app.route("/crear_usuario", methods=["POST"])
def crear_usuario():
    data = request.get_json()
    cedula = data.get("nombre")
    password = data.get("password")
    telefono = data.get("telefono")

    if not cedula or not password or not telefono:
        return jsonify({"error": "Faltan datos de registro"}), 400

    if Usuario.query.filter_by(cedula=cedula).first():
        return jsonify({"error": "Esta cédula ya está registrada"}), 400

    if Usuario.query.filter_by(telefono=telefono).first():
        return jsonify({"error": "Este teléfono ya está registrado"}), 400

    hashed = generate_password_hash(password)
    qr_id = str(uuid.uuid4())

    nuevo = Usuario(
        cedula=cedula,
        telefono=telefono,
        password_hash=hashed,
        qr_key_id=qr_id,
    )

    db.session.add(nuevo)
    db.session.commit()

    return jsonify({
        "ok": True,
        "mensaje": "Usuario creado correctamente",
        "cedula": cedula,
        "saldo": str(nuevo.saldo),
        "qr_key": qr_id
    })


# -------------------- LOGIN --------------------
@app.route("/login", methods=["POST"])
def login():
    data = request.get_json()
    cedula = data.get("nombre")
    password = data.get("password")

    usuario = Usuario.query.filter_by(cedula=cedula).first()
    if not usuario or not check_password_hash(usuario.password_hash, password):
        return jsonify({"error": "Cédula o Clave incorrecta"}), 401

    return jsonify({
        "ok": True,
        "mensaje": "Inicio de sesión exitoso",
        "cedula": usuario.cedula
    })


# -------------------- CONSULTAR USUARIO --------------------
@app.route("/usuario/<cedula>", methods=["GET"])
def usuario_info(cedula):
    usuario = Usuario.query.filter_by(cedula=cedula).first()
    if not usuario:
        return jsonify({"error": "Usuario no encontrado"}), 404

    return jsonify({
        "cedula": usuario.cedula,
        "saldo": str(usuario.saldo)
    })


# -------------------- MOVIMIENTOS --------------------
@app.route("/movimientos/<cedula>", methods=["GET"])
def movimientos(cedula):
    usuario = Usuario.query.filter_by(cedula=cedula).first()
    if not usuario:
        return jsonify({"error": "Usuario no encontrado"}), 404

    movs = Movimiento.query.filter_by(usuario_id=usuario.id).order_by(Movimiento.fecha.desc()).all()
    lista = [
        {
            "titulo": m.titulo,
            "tipo": m.tipo,
            "monto": str(m.monto),
            "fecha": m.fecha.strftime("%Y-%m-%d %H:%M"),
        }
        for m in movs
    ]
    return jsonify({"ok": True, "movimientos": lista})


# --------------------------------------------------------------
# 💳 INICIAR PAGO PAYPHONE (PRODUCCIÓN)
#   - Crea un movimiento PENDIENTE
#   - Pide token a /api/Authentication (Basic)
#   - Llama a /api/Sale con Authorization: Bearer <token>
#   - Devuelve URL de checkout
# --------------------------------------------------------------
@app.route("/iniciar_pago_payphone", methods=["POST"])
def iniciar_pago_payphone():
    data = request.get_json()
    cedula = data.get("nombre")

    try:
        monto = Decimal(str(data.get("monto", 0)))
    except Exception:
        monto = Decimal("0")

    if monto <= 0:
        return jsonify({"error": "Monto inválido"}), 400

    usuario = Usuario.query.filter_by(cedula=cedula).first()
    if not usuario:
        return jsonify({"error": "Usuario no encontrado"}), 404

    # Normalizar teléfono (ej. 099... -> 99... con country 593)
    phone = ''.join(ch for ch in usuario.telefono if ch.isdigit())
    if phone.startswith("0"):
        phone = phone[1:]

    monto_centavos = int((monto * 100).quantize(Decimal("1")))
    reference = f"TX-{uuid.uuid4().hex[:10]}"

    # 1) Registrar movimiento PENDIENTE (no sumamos al saldo aún)
    mov = Movimiento(
        usuario_id=usuario.id,
        titulo=f"[PENDIENTE] Recarga {reference}",
        tipo="ingreso",
        monto=monto
    )
    db.session.add(mov)
    db.session.commit()

    # 2) Obtener token
    token = _get_payphone_token()
    if not token:
        return jsonify({"error": "No se pudo obtener el token de PayPhone"}), 500

    # 3) Preparar payload
    payload = {
        "phoneNumber": phone,          # para web checkout puedes enviarlo o dejar que el usuario ingrese
        "countryCode": "593",
        "clientUserId": usuario.cedula,
        "reference": reference,
        "amount": monto_centavos,
        "amountWithTax": monto_centavos,
        "amountWithoutTax": 0,
        "tax": 0,
        "storeId": PAYPHONE_STORE_ID,
        "currency": "USD",
        "callbackURL": PAYPHONE_URL_CALLBACK,
    }

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    try:
        r = requests.post(PAYPHONE_URL_SALE, json=payload, headers=headers, timeout=30)
        print("📤 Enviado a PayPhone /Sale:", r.status_code, r.text)
        if r.status_code == 200:
            response = r.json()
            if "payWithPayPhoneUrl" in response:
                return jsonify({"ok": True, "payphone_url": response["payWithPayPhoneUrl"]})
            return jsonify({"error": "Respuesta inesperada de PayPhone", "detalle": response}), 500
        else:
            return jsonify({"error": "Error en PayPhone", "detalle": r.text}), 500
    except Exception as e:
        return jsonify({"error": f"Error al conectar con PayPhone: {e}"}), 500


# --------------------------------------------------------------
# 🔁 CALLBACK PAYPHONE
#   - Marca movimiento COMPLETADO y acredita saldo si fue aprobado
# --------------------------------------------------------------
@app.route("/payphone_callback", methods=["GET", "POST"])
def payphone_callback():
    data = request.values.to_dict()
    print("📥 Callback recibido:", data)

    # PayPhone suele enviar 'reference'. Si no, intenta alternativas por si cambian nombres.
    reference = data.get("reference") or data.get("clientTransactionId") or data.get("clientUserId")
    transaction_status = data.get("transactionStatus") or data.get("status")

    if not reference:
        return "Sin referencia", 400

    mov = Movimiento.query.filter(Movimiento.titulo.contains(reference)).first()
    if not mov:
        return "Transacción no encontrada", 404

    titulo_original = mov.titulo or ""
    aprobado = str(transaction_status).lower() in ("approved", "aprobada", "success", "ok", "true", "1", "aprobado")

    if titulo_original.startswith("[PENDIENTE]"):
        if aprobado:
            usuario = mov.usuario
            # Sumar con Decimal para evitar conflictos (Numeric devuelve Decimal)
            usuario.saldo = (usuario.saldo or Decimal("0")) + (mov.monto or Decimal("0"))
            mov.titulo = titulo_original.replace("[PENDIENTE] ", "").strip()
            db.session.commit()
            return "<h3>✅ Recarga completada correctamente. Puedes cerrar esta ventana.</h3>"
        else:
            mov.titulo = titulo_original.replace("[PENDIENTE]", "[FALLIDA]").strip()
            db.session.commit()
            return "<h3>❌ Pago rechazado o cancelado.</h3>"

    return "<h3>ℹ️ Recarga ya procesada.</h3>"


# --------------------------------------------------------------
# 🚀 ARRANQUE SERVIDOR
# --------------------------------------------------------------
with app.app_context():
    db.create_all()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
