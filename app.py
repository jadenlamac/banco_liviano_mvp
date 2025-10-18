from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import os
import uuid # Para generar el QR_KEY_ID
from sqlalchemy import Numeric # Importar el tipo de dato decimal/numeric

app = Flask(__name__)
CORS(app)

# =================================================================
#                         CONFIGURACIÓN DE DB
# =================================================================

# ✅ Configuración dinámica para Railway
# Si Railway da una URL de PostgreSQL, úsala. Si no, usa SQLite local.
db_url = os.getenv("DATABASE_URL", "sqlite:///banco_liviano.db")

# Railway a veces agrega "postgres://" y SQLAlchemy necesita "postgresql://"
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

# =================================================================
#                         MODELOS ACTUALIZADOS
# =================================================================

class Usuario(db.Model):
    __tablename__ = 'usuarios' # Coincide con el nombre de tu tabla en PostgreSQL
    
    id = db.Column(db.Integer, primary_key=True)
    
    # 🔑 CAMPOS NUEVOS/MODIFICADOS DEL REGISTRO DE 3 PASOS
    # La cédula es el campo de login principal (en lugar de 'nombre')
    cedula = db.Column(db.String(10), unique=True, nullable=False) 
    telefono = db.Column(db.String(15), unique=True, nullable=False)
    
    # La clave en el modelo SQL se llama password_hash
    password_hash = db.Column(db.String(200), nullable=False) 
    
    # 💰 USAMOS NUMERIC/DECIMAL PARA MÁXIMA PRECISIÓN (Finanzas)
    saldo = db.Column(Numeric(10, 2), default=0.00) 
    
    # 🔑 CAMPO QR: LA LLAVE QUE SE CODIFICA
    qr_key_id = db.Column(db.String(36), unique=True, nullable=False) # Usamos UUID estándar de 36 caracteres
    
    movimientos = db.relationship("Movimiento", backref="usuario", lazy=True)

class Movimiento(db.Model):
    __tablename__ = 'transacciones' # Coincide con el nombre de tu tabla en PostgreSQL
    
    id = db.Column(db.Integer, primary_key=True)
    
    # El usuario_id se relaciona con el 'id' de la tabla 'usuarios'
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=False) 
    
    titulo = db.Column(db.String(100), nullable=False)
    tipo = db.Column(db.String(20))  # ingreso o gasto
    
    # 💰 USAMOS NUMERIC/DECIMAL PARA MÁXIMA PRECISIÓN
    monto = db.Column(Numeric(10, 2), nullable=False) 
    fecha = db.Column(db.DateTime, default=datetime.utcnow)

# =================================================================
#                            RUTAS ACTUALIZADAS
# =================================================================

@app.route("/")
def index():
    return jsonify({"ok": True, "service": "Banco Liviano API conectada"})

# 1. Crear usuario (Registro Final - Paso 3)
@app.route("/crear_usuario", methods=["POST"])
def crear_usuario():
    data = request.get_json()
    # 🔑 Ahora esperamos cédula, teléfono y password del Flutter
    cedula = data.get("nombre") # 'nombre' del Flutter ahora es 'cedula'
    password = data.get("password")
    telefono = data.get("telefono")

    if not cedula or not password or not telefono:
        return jsonify({"error": "Faltan datos de registro (Cédula, Teléfono o Clave)"}), 400

    if Usuario.query.filter_by(cedula=cedula).first():
        return jsonify({"error": "Esta cédula ya está registrada"}), 400
    
    if Usuario.query.filter_by(telefono=telefono).first():
        return jsonify({"error": "Este teléfono ya está registrado"}), 400

    # Procesamiento de seguridad y claves
    hashed = generate_password_hash(password)
    # Generamos un ID único para el QR
    qr_id = str(uuid.uuid4()) 
    
    # Creamos el nuevo usuario con la nueva estructura de campos
    nuevo = Usuario(
        cedula=cedula, 
        telefono=telefono,
        password_hash=hashed,
        qr_key_id=qr_id # Guardamos la clave QR
    )
    
    db.session.add(nuevo)
    db.session.commit()

    return jsonify({
        "ok": True, 
        "mensaje": "Usuario creado", 
        "cedula": cedula, 
        "saldo": str(nuevo.saldo), # Convertir Numeric a string para JSON
        "qr_key": qr_id
    })

# 2. Login
@app.route("/login", methods=["POST"])
def login():
    data = request.get_json()
    # 🔑 El login ahora usa la cédula como identificador principal
    cedula = data.get("nombre") 
    password = data.get("password")

    usuario = Usuario.query.filter_by(cedula=cedula).first()
    if not usuario:
        return jsonify({"error": "Cédula o Clave incorrecta"}), 404

    # Comparamos con el campo password_hash
    if not check_password_hash(usuario.password_hash, password):
        return jsonify({"error": "Cédula o Clave incorrecta"}), 401

    return jsonify({"ok": True, "mensaje": "Inicio de sesión exitoso", "cedula": usuario.cedula})

# 3. Consultar usuario
@app.route("/usuario/<cedula>", methods=["GET"])
def usuario_info(cedula):
    # 🔑 Consultamos por cédula
    usuario = Usuario.query.filter_by(cedula=cedula).first()
    if not usuario:
        return jsonify({"error": "Usuario no encontrado"}), 404

    return jsonify({
        "cedula": usuario.cedula, 
        "saldo": str(usuario.saldo) # Importante: Convertir a string para JSON
    })

# 4. Movimientos
@app.route("/movimientos/<cedula>", methods=["GET"])
def movimientos(cedula):
    # 🔑 Consultamos por cédula
    usuario = Usuario.query.filter_by(cedula=cedula).first()
    if not usuario:
        return jsonify({"error": "Usuario no encontrado"}), 404

    # Usamos Movimiento.usuario_id que es la FK al id de Usuario
    movs = Movimiento.query.filter_by(usuario_id=usuario.id).order_by(Movimiento.fecha.desc()).all()
    lista = [
        {
            "titulo": m.titulo,
            "tipo": m.tipo,
            "monto": str(m.monto), # Importante: Convertir a string
            "fecha": m.fecha.strftime("%Y-%m-%d %H:%M"),
        }
        for m in movs
    ]

    return jsonify({"ok": True, "movimientos": lista})

# Las rutas de recargar y pagar no cambian mucho, solo se aseguran de usar 'cedula' y 'saldo' como Numeric.

# 5. Recargar saldo
@app.route("/recargar", methods=["POST"])
def recargar():
    data = request.get_json()
    cedula = data.get("nombre") # 'nombre' del Flutter ahora es 'cedula'
    monto = float(data.get("monto", 0))

    usuario = Usuario.query.filter_by(cedula=cedula).first()
    if not usuario:
        return jsonify({"error": "Usuario no encontrado"}), 404

    usuario.saldo += monto
    # Usamos el campo usuario_id en lugar de usuario.nombre
    movimiento = Movimiento(usuario_id=usuario.id, titulo="Recarga de saldo", tipo="ingreso", monto=monto)

    db.session.add(movimiento)
    db.session.commit()

    return jsonify({"ok": True, "mensaje": f"Se recargaron {monto} USD", "saldo_actual": str(usuario.saldo)})

# 6. Pagar (Ruta de Transacción)
@app.route("/pagar", methods=["POST"])
def pagar():
    data = request.get_json()
    de = data.get("de")
    para = data.get("para")
    monto = float(data.get("monto", 0))

    remitente = Usuario.query.filter_by(cedula=de).first() # Buscar por cédula
    receptor = Usuario.query.filter_by(cedula=para).first() # Buscar por cédula

    if not remitente or not receptor:
        return jsonify({"error": "Cédula del remitente o receptor no existe"}), 404

    if remitente.saldo < monto:
        return jsonify({"error": "Saldo insuficiente"}), 400

    # Transacción de saldos (Decimal/Numeric)
    remitente.saldo -= monto
    receptor.saldo += monto

    # Registros de movimientos
    mov1 = Movimiento(usuario_id=remitente.id, titulo=f"Pago a {para}", tipo="gasto", monto=monto)
    mov2 = Movimiento(usuario_id=receptor.id, titulo=f"Recibido de {de}", tipo="ingreso", monto=monto)

    db.session.add_all([mov1, mov2])
    db.session.commit()

    return jsonify({"ok": True, "mensaje": f"{de} pagó {monto} USD a {para}"})

# =================================================================
#                             ARRANQUE
# =================================================================

with app.app_context():
    # Nota: Si ya creaste las tablas en PostgreSQL manualmente, 
    # db.create_all() no las recreará, pero sí las usará.
    db.create_all()

if __name__ == "__main__":
    # Railway expone el puerto en la variable de entorno PORT
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)