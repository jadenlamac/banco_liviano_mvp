from flask import Flask, request, jsonify, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import os
import uuid
from sqlalchemy import Numeric
import requests # ⬅️ IMPORTADO: Necesario para PayPhone

app = Flask(__name__)
CORS(app)

# =================================================================
# ⚙️ CONFIGURACIÓN DE LA BASE DE DATOS (SUPABASE)
# =================================================================

db_url = os.getenv("SUPABASE_DB_URL", "sqlite:///banco_liviano.db")

# ✅ Corrige formato antiguo postgres:// -> postgresql://
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

# ✅ Asegura que use SSL (requerido por Supabase)
# NOTA: Si usas el Pooler de Supabase (puerto 6543) DEBES ELIMINAR O COMENTAR la siguiente línea.
if "?sslmode=require" not in db_url:
    db_url += "?sslmode=require"

# ✅ Log de conexión
print("🧩 Conectando a base de datos:", db_url)

app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

# =================================================================
# 🔑 CONFIGURACIÓN DE PAYPHONE (USANDO TUS CREDENCIALES)
# =================================================================
# Credenciales obtenidas de tu captura anterior
PAYPHONE_TOKEN = os.getenv("PAYPHONE_TOKEN", "J8GXWQ6hPUdK0jSb938Q")
PAYPHONE_SECRET = os.getenv("PAYPHONE_SECRET", "cHDAJ4oikm6ZqSZXs5OYxA") 
PAYPHONE_STORE_ID = os.getenv("PAYPHONE_STORE_ID", 12555) 
PAYPHONE_URL_PAGO = "https://pay.payphonetodo.com/api/v1/Deuda" 
PAYPHONE_URL_CALLBACK = "https://banco-liviano-mvp.onrender.com/payphone_callback"
# =================================================================

# =================================================================
# 🧱 MODELOS DE BASE DE DATOS
# =================================================================

class Usuario(db.Model):
    __tablename__ = 'usuarios'
    id = db.Column(db.Integer, primary_key=True)
    cedula = db.Column(db.String(10), unique=True, nullable=False)
    telefono = db.Column(db.String(15), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    saldo = db.Column(Numeric(10, 2), default=0.00)
    qr_key_id = db.Column(db.String(36), unique=True, nullable=False)
    movimientos = db.relationship("Movimiento", backref="usuario", lazy=True)


class Movimiento(db.Model):
    __tablename__ = 'transacciones'
    # ⚠️ CAMBIADO: Debe ser String (UUID) para usarlo como referencia de PayPhone
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4())) 
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=False)
    titulo = db.Column(db.String(100), nullable=False)
    tipo = db.Column(db.String(20))
    monto = db.Column(Numeric(10, 2), nullable=False)
    fecha = db.Column(db.DateTime, default=datetime.utcnow)

# =================================================================
# 🌐 RUTAS DEL API
# =================================================================

@app.route("/")
def index():
    return jsonify({"ok": True, "service": "Banco Liviano API"})

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
        qr_key_id=qr_id
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

    movs = Movimiento.query.filter(Movimiento.usuario_id == usuario.id).order_by(Movimiento.fecha.desc()).all()
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

# -------------------- PAGAR (Transferencia P2P) --------------------
@app.route("/pagar", methods=["POST"])
def pagar():
    data = request.get_json()
    de = data.get("de")
    para = data.get("para")
    monto = float(data.get("monto", 0))

    remitente = Usuario.query.filter_by(cedula=de).first()
    receptor = Usuario.query.filter_by(cedula=para).first()

    if not remitente or not receptor:
        return jsonify({"error": "Cédula del remitente o receptor no existe"}), 404

    if remitente.saldo < monto:
        return jsonify({"error": "Saldo insuficiente"}), 400

    remitente.saldo -= monto
    receptor.saldo += monto

    mov1 = Movimiento(usuario_id=remitente.id, titulo=f"Pago a {para}", tipo="gasto", monto=monto)
    mov2 = Movimiento(usuario_id=receptor.id, titulo=f"Recibido de {de}", tipo="ingreso", monto=monto)

    db.session.add_all([mov1, mov2])
    db.session.commit()

    return jsonify({
        "ok": True,
        "mensaje": f"{de} pagó {monto} USD a {para}"
    })


# =================================================================
# 🚀 RUTAS DE PAYPHONE (IMPLEMENTACIÓN COMPLETA)
# =================================================================

# -------------------- 1. INICIAR PAGO --------------------
@app.route("/iniciar_pago_payphone", methods=["POST"])
def iniciar_pago_payphone():
    data = request.get_json()
    cedula = data.get("nombre")
    monto = data.get("monto")

    usuario = Usuario.query.filter_by(cedula=cedula).first()
    if not usuario:
        return jsonify({"ok": False, "error": "Usuario no encontrado"}), 404

    if not monto or float(monto) <= 0:
        return jsonify({"ok": False, "error": "Monto inválido"}), 400

    try:
        monto_centavos = int(float(monto) * 100)
        tx_id = str(uuid.uuid4())

        # Crear un movimiento temporal (Pendiente) antes de llamar a PayPhone
        movimiento = Movimiento(
            id=tx_id, 
            usuario_id=usuario.id, 
            titulo="Recarga - Pendiente PayPhone", 
            tipo="ingreso", 
            monto=float(monto)
        )
        db.session.add(movimiento)
        db.session.commit()

        headers = {
            "Authorization": f"Bearer {PAYPHONE_TOKEN}",
            "Content-Type": "application/json",
        }

        payload = {
            "phoneNumber": usuario.telefono,
            "countryCode": "593",
            "clientUserId": usuario.cedula,
            "reference": tx_id,
            "amount": monto_centavos,
            "amountWithTax": monto_centavos,
            "amountWithoutTax": 0,
            "tax": 0,
            "storeId": PAYPHONE_STORE_ID,
            "currency": "USD",
            "callbackURL": PAYPHONE_URL_CALLBACK,
        }

        res = requests.post(PAYPHONE_URL_PAGO, json=payload, headers=headers)
        res.raise_for_status() 
        
        payphone_data = res.json()
        
        if payphone_data.get('payphoneUrl'):
            return jsonify({
                "ok": True,
                "mensaje": "Pago iniciado, redirigiendo a PayPhone",
                "payphone_url": payphone_data['payphoneUrl']
            })
        else:
            return jsonify({"ok": False, "error": "Error de PayPhone: URL no recibida", "detail": payphone_data}), 500

    except requests.exceptions.HTTPError as e:
        Movimiento.query.filter_by(id=tx_id).delete()
        db.session.commit()
        return jsonify({"ok": False, "error": f"Error HTTP de PayPhone: {e.response.status_code}", "detail": str(e.response.text)}), 500
    except Exception as e:
        Movimiento.query.filter_by(id=tx_id).delete()
        db.session.commit()
        return jsonify({"ok": False, "error": f"Error interno: {str(e)}"}), 500

# -------------------- 2. CALLBACK DE PAYPHONE --------------------
@app.route("/payphone_callback", methods=["GET", "POST"])
def payphone_callback():
    transaction_id = request.args.get('transactionId') or request.form.get('transactionId')

    if not transaction_id:
        return "ID de transacción no recibido", 400

    headers = {
        "Authorization": f"Bearer {PAYPHONE_TOKEN}",
        "Content-Type": "application/json",
    }
    
    url_consulta = f"https://pay.payphonetodo.com/api/v1/Deuda/Transaccion/{transaction_id}"
    
    try:
        res = requests.get(url_consulta, headers=headers)
        res.raise_for_status()
        tx_data = res.json()
    except Exception:
        return "Error al consultar estado de pago.", 500

    tx_status = tx_data.get('transactionStatus') 
    tx_reference = tx_data.get('clientTransactionId')

    if tx_status == 1:
        # Pago APROBADO: Actualizar saldo y movimiento
        movimiento = Movimiento.query.filter_by(id=tx_reference).first()
        
        if movimiento and movimiento.titulo == "Recarga - Pendiente PayPhone":
            usuario = Usuario.query.get(movimiento.usuario_id)
            monto_usd = float(movimiento.monto)

            usuario.saldo += monto_usd
            movimiento.titulo = f"Recarga PayPhone ID: {transaction_id}"
            
            db.session.commit()
            
            return "<html><body><h1>✅ Recarga exitosa</h1><p>Tu saldo ha sido actualizado. Regresa a la app.</p></body></html>", 200
        
        return "Error: Transacción ya procesada o movimiento no encontrado.", 400


    elif tx_status == 3:
        # Pago RECHAZADO: Eliminar movimiento pendiente
        movimiento = Movimiento.query.filter_by(id=tx_reference).first()
        if movimiento:
            db.session.delete(movimiento)
            db.session.commit()
        
        return "<html><body><h1>❌ Pago rechazado</h1><p>Intenta recargar nuevamente.</p></body></html>", 200

    else:
        # Otro estado (Pendiente)
        return "<html><body><h1>⏳ Pago Pendiente</h1><p>Vuelve a la app para verificar tu saldo.</p></body></html>", 200


# =================================================================
# 🚀 ARRANQUE DEL SERVIDOR
# =================================================================

with app.app_context():
    # ⚠️ IMPORTANTE: Si ya creaste tablas con id=Integer, deberás eliminarlas o renombrarlas 
    # en Supabase para que SQLAlchemy pueda crear el nuevo esquema con id=String(36)
    db.create_all()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)