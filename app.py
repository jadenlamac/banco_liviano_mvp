from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

app = Flask(__name__)
CORS(app)

# Base de datos SQLite local
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///banco_liviano.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# ---------------- MODELOS ----------------
class Usuario(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    saldo = db.Column(db.Float, default=0.0)
    movimientos = db.relationship('Movimiento', backref='usuario', lazy=True)

class Movimiento(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuario.id'), nullable=False)
    titulo = db.Column(db.String(100), nullable=False)
    tipo = db.Column(db.String(20))  # ingreso o gasto
    monto = db.Column(db.Float, nullable=False)
    fecha = db.Column(db.DateTime, default=datetime.utcnow)

# ---------------- RUTAS ----------------
@app.route('/')
def index():
    return jsonify({'ok': True, 'service': 'Banco Liviano API conectada'})

# Crear usuario
@app.route('/crear_usuario', methods=['POST'])
def crear_usuario():
    data = request.get_json()
    nombre = data.get('nombre')
    password = data.get('password')

    if not nombre or not password:
        return jsonify({'error': 'Faltan datos'}), 400

    if Usuario.query.filter_by(nombre=nombre).first():
        return jsonify({'error': 'El usuario ya existe'}), 400

    hashed = generate_password_hash(password)
    nuevo = Usuario(nombre=nombre, password=hashed)
    db.session.add(nuevo)
    db.session.commit()

    return jsonify({'ok': True, 'mensaje': 'Usuario creado', 'usuario': nombre, 'saldo': nuevo.saldo})

# Login
@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    nombre = data.get('nombre')
    password = data.get('password')

    usuario = Usuario.query.filter_by(nombre=nombre).first()
    if not usuario:
        return jsonify({'error': 'Usuario no encontrado'}), 404

    if not check_password_hash(usuario.password, password):
        return jsonify({'error': 'Contraseña incorrecta'}), 401

    return jsonify({'ok': True, 'mensaje': 'Inicio de sesión exitoso', 'usuario': usuario.nombre})

# Consultar usuario
@app.route('/usuario/<nombre>', methods=['GET'])
def usuario_info(nombre):
    usuario = Usuario.query.filter_by(nombre=nombre).first()
    if not usuario:
        return jsonify({'error': 'Usuario no encontrado'}), 404

    return jsonify({'nombre': usuario.nombre, 'saldo': usuario.saldo})

# Movimientos
@app.route('/movimientos/<nombre>', methods=['GET'])
def movimientos(nombre):
    usuario = Usuario.query.filter_by(nombre=nombre).first()
    if not usuario:
        return jsonify({'error': 'Usuario no encontrado'}), 404

    movs = Movimiento.query.filter_by(usuario_id=usuario.id).order_by(Movimiento.fecha.desc()).all()
    lista = [
        {
            'titulo': m.titulo,
            'tipo': m.tipo,
            'monto': m.monto,
            'fecha': m.fecha.strftime('%Y-%m-%d %H:%M')
        } for m in movs
    ]

    return jsonify({'ok': True, 'movimientos': lista})

# Recargar saldo
@app.route('/recargar', methods=['POST'])
def recargar():
    data = request.get_json()
    nombre = data.get('nombre')
    monto = float(data.get('monto', 0))

    usuario = Usuario.query.filter_by(nombre=nombre).first()
    if not usuario:
        return jsonify({'error': 'Usuario no encontrado'}), 404

    usuario.saldo += monto
    movimiento = Movimiento(
        usuario_id=usuario.id,
        titulo='Recarga de saldo',
        tipo='ingreso',
        monto=monto
    )

    db.session.add(movimiento)
    db.session.commit()

    return jsonify({'ok': True, 'mensaje': f'Se recargaron {monto} USD', 'saldo_actual': usuario.saldo})

# Pagar (envía dinero a otro usuario)
@app.route('/pagar', methods=['POST'])
def pagar():
    data = request.get_json()
    de = data.get('de')
    para = data.get('para')
    monto = float(data.get('monto', 0))

    remitente = Usuario.query.filter_by(nombre=de).first()
    receptor = Usuario.query.filter_by(nombre=para).first()

    if not remitente or not receptor:
        return jsonify({'error': 'Usuario remitente o receptor no existe'}), 404

    if remitente.saldo < monto:
        return jsonify({'error': 'Saldo insuficiente'}), 400

    remitente.saldo -= monto
    receptor.saldo += monto

    mov1 = Movimiento(usuario_id=remitente.id, titulo=f'Pago a {para}', tipo='gasto', monto=monto)
    mov2 = Movimiento(usuario_id=receptor.id, titulo=f'Recibido de {de}', tipo='ingreso', monto=monto)

    db.session.add_all([mov1, mov2])
    db.session.commit()

    return jsonify({'ok': True, 'mensaje': f'{de} pagó {monto} USD a {para}'})

# Inicializar BD
with app.app_context():
    db.create_all()

if __name__ == '__main__':
    app.run(debug=True)
