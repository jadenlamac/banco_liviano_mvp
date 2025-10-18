from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import os
import uuid
from sqlalchemy import Numeric

app = Flask(__name__)
CORS(app)

# =================================================================
#                      ⚙️ CONFIGURACIÓN DB (SUPABASE)
# =================================================================

# Lee tu URL de Supabase desde variable de entorno
db_url = os.getenv("SUPABASE_DB_URL", "sqlite:///banco_liviano.db")

# Corrige formato si viene como postgres://
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

# Conexión con SSL requerida para Supabase
app.config["SQLALCHEMY_DATABASE_URI"] = db_url + "?sslmode=require"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

# =================================================================
#                      🧱 MODELOS DE BASE DE DATOS
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
#                      🌐 RUTAS DEL API
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

# -------------------- RECARGAR SALDO --------------------
@app.route("/recargar", methods=["POST"])
def recargar():
    data = request.get_json()
    cedula = data.get("nombre")
    monto = float(data.get("monto", 0))

    usuario = Usuario.query.filter_by(cedula=cedula).first()
    if not usuario:
        return jsonify({"error": "Usuario no encontrado"}), 404

    usuario.saldo += monto
    movimiento = Movimiento(usuario_id=usuario.id, titulo="Recarga de saldo", tipo="ingreso", monto=monto)

    db.session.add(movimiento)
    db.session.commit()

    return jsonify({
        "ok": True,
        "mensaje": f"Se recargaron {monto} USD",
        "saldo_actual": str(usuario.saldo)
    })

# -------------------- PAGAR --------------------
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
#                      🚀 ARRANQUE DEL SERVIDOR
# =================================================================

with app.app_context():
    db.create_all()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
