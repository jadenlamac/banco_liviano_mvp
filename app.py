from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import os
import uuid
from sqlalchemy import Numeric
import requests # ⬅️ IMPORTADO: Para comunicarnos con PayPhone

app = Flask(__name__)
CORS(app)

# =================================================================
# ⚙️ CONFIGURACIÓN DE LA BASE DE DATOS (SUPABASE)
# =================================================================

db_url = os.getenv("SUPABASE_DB_URL", "sqlite:///banco_liviano.db")

# ✅ Corrige formato antiguo postgres:// -> postgresql://
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

# ✅ Log de conexión
print("🧩 Conectando a base de datos:", db_url)

app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

# =================================================================
# 🔑 CONFIGURACIÓN DE PAYPHONE (LISTO)
# =================================================================
# Credenciales de la imagen (ajusta si usas variables de entorno)
PAYPHONE_TOKEN = os.getenv("PAYPHONE_TOKEN", "J8GXWQ6hPUdK0jSb938Q")
PAYPHONE_SECRET = os.getenv("PAYPHONE_SECRET", "cHDAJ4oikm6ZqSZXs5OYxA")
PAYPHONE_STORE_ID = os.getenv("PAYPHONE_STORE_ID", 12555) # ⬅️ STORE ID USADO
PAYPHONE_URL_PAGO = "https://pay.payphonetodo.com/api/v1/Deuda" 
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
    id = db.Column(db.Integer, primary_key=True)
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

# -------------------- PAGAR (P2P) --------------------
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
# 💸 RUTAS DE PAGOS (PAYPHONE) - RECARGA
# =================================================================

# -------------------- 1. INICIAR PAGO (Llamada desde Flutter) --------------------
@app.route("/iniciar_pago_payphone", methods=["POST"])
def iniciar_pago_payphone():
    data = request.get_json()
    cedula = data.get("nombre")
    monto_usd = data.get("monto", 0)
    
    try:
        monto_centavos = int(float(monto_usd) * 100)
    except ValueError:
        return jsonify({"error": "Monto inválido"}), 400

    if not cedula or monto_centavos <= 0:
        return jsonify({"error": "Faltan cédula o monto"}), 400

    usuario = Usuario.query.filter_by(cedula=cedula).first()
    if not usuario:
        return jsonify({"error": "Usuario de Banco Liviano no existe"}), 404

    callback_url = f"{request.url_root}payphone_callback?cedula={cedula}"

    headers = {
        'Authorization': f'Bearer {PAYPHONE_TOKEN}', 
        'Content-Type': 'application/json',
    }

    payload = {
        "amount": monto_centavos,
        "amountWithTax": monto_centavos, 
        "clientTransactionId": str(uuid.uuid4()),
        "responseUrl": callback_url, 
        "cancellationUrl": callback_url,
        "storeId": int(PAYPHONE_STORE_ID),
    }

    try:
        response = requests.post(PAYPHONE_URL_PAGO, headers=headers, json=payload)
        response.raise_for_status()

        payphone_data = response.json()
        payment_url = payphone_data.get("payment_url") 

        if payment_url:
            return jsonify({
                "ok": True,
                "payphone_url": payment_url 
            })
        else:
            return jsonify({"error": payphone_data.get("message", "Error desconocido de PayPhone")}), 500

    except requests.exceptions.RequestException as e:
        print(f"Error de PayPhone: {e}")
        return jsonify({"error": "Error al comunicar con PayPhone"}), 500

# -------------------- 2. CALLBACK DE CONFIRMACIÓN (Llamada desde PayPhone) --------------------
@app.route("/payphone_callback", methods=["GET", "POST"])
def payphone_callback():
    transaction_id = request.args.get("transactionId") or request.form.get("transactionId")
    cedula = request.args.get("cedula") 
    
    if not transaction_id or not cedula:
        return "Error en Callback: Faltan datos", 400

    # VERIFICAR EL ESTADO REAL de la transacción
    headers = {
        'Authorization': f'Bearer {PAYPHONE_TOKEN}',
        'Content-Type': 'application/json',
    }
    
    verification_url = f"https://pay.payphonetodo.com/api/v1/transaction/status/{transaction_id}" 

    try:
        status_response = requests.get(verification_url, headers=headers)
        status_data = status_response.json()
        
        # El código '3' significa Aprobado (Confirmar con la documentación de PayPhone)
        if status_data.get("statusCode") == 3: 
            
            usuario = Usuario.query.filter_by(cedula=cedula).first()
            monto = float(status_data.get("amount", 0)) / 100.0
            
            if usuario:
                usuario.saldo += monto
                movimiento = Movimiento(
                    usuario_id=usuario.id, 
                    titulo=f"Recarga PayPhone ID: {transaction_id}", 
                    tipo="ingreso", 
                    monto=monto
                )
                db.session.add(movimiento)
                db.session.commit()
                
                return "Recarga exitosa. Volviendo a la App...", 200 
            else:
                return "Error: Usuario no encontrado en Banco Liviano", 404
        else:
            return "Pago no aprobado/cancelado. Volviendo a la App...", 200
            
    except Exception as e:
        print(f"Error en verificación de callback: {e}")
        return "Error interno en la verificación final.", 500


# =================================================================
# 🚀 ARRANQUE DEL SERVIDOR
# =================================================================

with app.app_context():
    db.create_all()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)