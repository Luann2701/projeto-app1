from flask import Flask, render_template, request, redirect, session, flash, url_for
from werkzeug.middleware.proxy_fix import ProxyFix
import psycopg2
from datetime import datetime, timedelta
import os
import secrets
import smtplib
from email.message import EmailMessage
from werkzeug.utils import secure_filename
from flask import abort
from urllib.parse import quote_plus
from datetime import datetime
import os
import requests
import pytz
import mercadopago


def get_db_connection():
    return psycopg2.connect(
        os.environ.get("DATABASE_URL"),
        sslmode="require"
    )



def get_conn():
    return psycopg2.connect(
        os.environ.get("DATABASE_URL"),
        sslmode="require"
    )



mp = mercadopago.SDK(os.getenv("MERCADOPAGO_ACCESS_TOKEN"))


WHATSAPP_ARENA = "5535998775023"
CHAVE_PIX = "59105896000116"
VALOR_HORARIO = 65

from dotenv import load_dotenv
from flask_dance.contrib.google import make_google_blueprint, google

# Carrega variáveis do .env
load_dotenv()

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
app.config.update(
    SESSION_COOKIE_SAMESITE="None",
    SESSION_COOKIE_SECURE=True
)


app.secret_key = os.getenv("SECRET_KEY")

# ======================
# CONFIGURAÇÃO DE UPLOAD DE EVENTOS  
# ======================

UPLOAD_FOLDER = "static/uploads/eventos"
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp'}

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# ======================
# LOGIN GOOGLE TAMBÉM
# ======================

google_bp = make_google_blueprint(
    client_id=os.getenv("GOOGLE_OAUTH_CLIENT_ID"),
    client_secret=os.getenv("GOOGLE_OAUTH_CLIENT_SECRET"),
    scope=[
        "openid",
        "https://www.googleapis.com/auth/userinfo.email",
        "https://www.googleapis.com/auth/userinfo.profile"
    ],
    
     redirect_to="login_google"   # 🔴 ESTA LINHA RESOLVE TUDO

)

app.register_blueprint(google_bp, url_prefix="/login")

# ======================
# BANCO DE DADOS - POSTGRESQL (NEON)
# ======================

DATABASE_URL = os.getenv("DATABASE_URL")

def conectar():
    try:
        return psycopg2.connect(DATABASE_URL)
    except Exception as e:
        print("❌ Erro ao conectar no banco:", e)
        return None

def criar_banco():
    conn = conectar()
    if not conn:
        print("⚠️ Banco indisponível. Tabelas não criadas.")
        return

    c = conn.cursor()
    
    # ======================
    # TABELA USUÁRIOS
    # ======================
    c.execute("""
    CREATE TABLE IF NOT EXISTS usuarios (
        id SERIAL PRIMARY KEY,
        usuario TEXT UNIQUE NOT NULL,
        senha TEXT,
        tipo TEXT NOT NULL,
        reset_token TEXT,
        reset_expira TIMESTAMP
    )
    """)

    # ======================
    # GARANTE COLUNA TELEFONE
    # ======================
    c.execute("""
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 
            FROM information_schema.columns 
            WHERE table_name='usuarios'
            AND column_name='telefone'
        ) THEN
            ALTER TABLE usuarios
            ADD COLUMN telefone TEXT;
        END IF;
    END$$;
    """)

    # ======================
    # TABELA RESERVAS
    # ======================
    c.execute("""
    CREATE TABLE IF NOT EXISTS reservas (
        id SERIAL PRIMARY KEY,
        usuario TEXT NOT NULL,
        esporte TEXT NOT NULL,
        quadra TEXT NOT NULL,
        data DATE NOT NULL,
        horario TEXT NOT NULL,
        pago BOOLEAN DEFAULT FALSE,
        criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # ======================
    # TABELA EVENTOS
    # ======================
    c.execute("""
    CREATE TABLE IF NOT EXISTS eventos (
        id SERIAL PRIMARY KEY,
        imagem TEXT NOT NULL,
        link TEXT,
        criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # ======================
    # TABELA HORÁRIOS (DONO)
    # ======================

    c.execute("""
    CREATE TABLE IF NOT EXISTS horarios (
        id SERIAL PRIMARY KEY,
        quadra TEXT NOT NULL,
        data DATE,
        hora TIME NOT NULL,
        tipo VARCHAR(20) NOT NULL,
        permanente BOOLEAN DEFAULT FALSE,
        criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # ======================
    # CRIA DONO PADRÃO
    # ======================
    c.execute(
        "SELECT 1 FROM usuarios WHERE tipo = %s",
        ("dono",)
    )
    
    if not c.fetchone():
        c.execute(
            "INSERT INTO usuarios (usuario, senha, tipo) VALUES (%s, %s, %s)",
            ("admin", "1234", "dono")
        )

    conn.commit()
    conn.close()


# CRIA AS TABELAS AO INICIAR O APP
criar_banco()

def enviar_email_recuperacao(destino, token):
    try:
        link = f"https://arenacorpoativo.onrender.com/reset_senha/{token}"

        url = "https://api.brevo.com/v3/smtp/email"

        api_key = os.getenv("BREVO_API_KEY")
        print("BREVO_API_KEY:", api_key)

        headers = {
            "api-key": api_key,
            "Content-Type": "application/json"
        }

        data = {
            "sender": {
                "name": "Arena Corpo Ativo",
                "email": "arenacorpoativo2026@gmail.com"
            },
            "to": [{"email": destino}],
            "subject": "Recuperação de senha",
            "htmlContent": f"""
            <p>Olá!</p>
            <p>Clique no link para redefinir sua senha:</p>
            <a href="{link}">{link}</a>
            """
        }

        r = requests.post(url, json=data, headers=headers)

        print("STATUS:", r.status_code)
        print("RESPOSTA:", r.text)

        return r.status_code == 201

    except Exception as e:
        print("ERRO AO ENVIAR EMAIL:", e)
        return False


# ======================
# HORÁRIO DE BRASILIA
# ======================

def agora_brasilia():
    tz = pytz.timezone("America/Sao_Paulo")
    return datetime.now(tz)

@app.route("/debug_sessao")
def debug_sessao():
    return {
        "usuario": session.get("usuario"),
        "tipo": session.get("tipo")
    }


# ======================
# TELA INICIAL
# ======================

@app.route("/teste_mp")
def teste_mp():
    preference_data = {
        "items": [
            {
                "title": "Teste Reserva Arena",
                "quantity": 1,
                "unit_price": 1.00
            }
        ]
    }

    preference = mp.preference().create(preference_data)

    return {
        "status": preference["status"],
        "init_point": preference["response"].get("init_point")
    }


@app.route("/")
def inicio():
    if "usuario" in session:
        return redirect("/telefone")  # já logado
    return render_template("escolha.html")


# ======================
# LOGIN CLIENTE
# ======================

from werkzeug.security import check_password_hash

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        usuario = request.form["usuario"]
        senha = request.form["senha"]

        conn = conectar()
        c = conn.cursor(dictionary=True)
        c.execute(
            "SELECT * FROM usuarios WHERE usuario=%s AND tipo='cliente'",
            (usuario,)
        )
        user = c.fetchone()
        conn.close()

        if user and check_password_hash(user["senha"], senha):
            session["usuario"] = usuario
            session["tipo"] = "cliente"
            return redirect("/telefone")

        return render_template("error.html", mensagem="Login inválido")

    return render_template("login.html")


# ======================
# LOGIN DONO
# ======================

@app.route("/login_dono", methods=["GET", "POST"])
def login_dono():
    if request.method == "POST":
        email = request.form["usuario"]
        senha = request.form["senha"]

        if email == "administrador@gmail.com" and senha == "arenaca2026":
            session.clear()
            session["usuario"] = email
            session["tipo"] = "dono"
            return redirect("/painel_dono")
        else:
            return render_template(
                "login_dono.html",
                erro="❌ Usuário ou senha inválidos"
            )

    return render_template("login_dono.html")


# ======================
# CADASTRO CLIENTE
# ======================
@app.route("/cadastro", methods=["GET", "POST"])
def cadastro():
    if request.method == "POST":
        usuario = request.form["usuario"]
        senha = request.form["senha"]

        try:
            conn = conectar()
            c = conn.cursor()
            c.execute(
                "INSERT INTO usuarios (usuario, senha, tipo) VALUES (%s, %s, 'cliente')",
                (usuario, senha),
            )
            conn.commit()
            conn.close()

            return render_template(
                "cadastro.html",
                sucesso="✅ Usuário cadastrado com sucesso!"
            )

        except:
            return render_template(
                "cadastro.html",
                erro="⚠️ Este usuário já existe."
            )

    return render_template("cadastro.html")


# ======================
# TELEFONE
# ======================

@app.route("/telefone", methods=["GET", "POST"])
def telefone():
    if "usuario" not in session:
        return redirect("/login")

    conn = conectar()
    c = conn.cursor()

    # busca telefone
    c.execute(
        "SELECT telefone FROM usuarios WHERE usuario=%s",
        (session["usuario"],)
    )
    telefone = c.fetchone()[0]

    # se já tiver telefone, pula etapa
    if telefone:
        conn.close()
        return redirect("/esporte")

    if request.method == "POST":
        tel = request.form["telefone"]

        c.execute(
            "UPDATE usuarios SET telefone=%s WHERE usuario=%s",
            (tel, session["usuario"])
        )
        conn.commit()
        conn.close()

        return redirect("/esporte")

    conn.close()
    return render_template("telefone.html")


# ======================
# ESPORTE
# ======================

@app.route("/esporte")
def esporte():
    if "usuario" not in session:
        return redirect("/")
    return render_template("esporte.html")

# ======================
# QUADRAS
# ======================
@app.route("/quadras/<esporte>")
def quadras(esporte):
    if "usuario" not in session:
        return redirect("/")

    if esporte == "Beach Tenis":
        quadras = ["Quadra 1", "Quadra 2", "Quadra 3"]
    elif esporte == "Futvolei":
        quadras = ["Quadra 3"]
    else:
        quadras = []

    return render_template(
        "quadras.html",
        quadras=quadras,
        esporte=esporte
    )


# ======================
# DATAS + HORÁRIOS
# ======================
@app.route("/datas/<esporte>/<quadra>", methods=["GET", "POST"])
def datas(esporte, quadra):
    if "usuario" not in session:
        return redirect("/")

    if request.method == "POST":
        data_escolhida = request.form["data"]
        return redirect(f"/horarios/{esporte}/{quadra}/{data_escolhida}")

    hoje = datetime.now().date()

    if session.get("tipo") == "dono":
        # 📅 DONO → mês inteiro (30 dias)
        dias = [hoje + timedelta(days=i) for i in range(30)]

    else: 
        # 👤 CLIENTE → hoje + 6 dias
        dias = [hoje + timedelta(days=i) for i in range(7)]

    return render_template(
        "datas.html",
        esporte=esporte,
        quadra=quadra,
        dias=dias
    )

# ======================
# HORÁRIOS
# ======================

@app.route("/horarios/<esporte>/<quadra>/<data>")
def horarios(esporte, quadra, data):

    if "usuario" not in session:
        return redirect("/")

    agora = agora_brasilia()
    hoje = agora.date()
    data_escolhida = datetime.strptime(data, "%Y-%m-%d").date()

    # ✅ CORRETO: Python e Postgres usam o mesmo padrão
    # 0 = segunda ... 6 = domingo
    dia_semana = data_escolhida.weekday()

    # ==================================================
    # 🔒 CLIENTE: HOJE + 6 DIAS
    # ==================================================
    if session.get("tipo") != "dono":
        if data_escolhida < hoje or data_escolhida > hoje + timedelta(days=6):
            return redirect(f"/datas/{esporte}/{quadra}")

    # ==================================================
    # ⏰ LISTA BASE DE HORÁRIOS
    # ==================================================
    lista_horarios = [f"{h:02d}:00" for h in range(6, 22)]

    if data_escolhida == hoje:
        hora_atual = agora.strftime("%H:%M")
        lista_horarios = [h for h in lista_horarios if h > hora_atual]

    conn = conectar()
    c = conn.cursor()

    # ==================================================
    # 🔥 LIMPA RESERVAS EXPIRADAS
    # ==================================================
    c.execute("""
        DELETE FROM reservas
        WHERE pago = FALSE
          AND criado_em < NOW() - INTERVAL '10 minutes'
    """)
    conn.commit()

    # ==================================================
    # ✅ RESERVAS PAGAS
    # ==================================================
    c.execute("""
        SELECT horario
        FROM reservas
        WHERE quadra = %s
          AND data = %s
          AND pago = TRUE
    """, (quadra, data))

    ocupados_reserva = [str(h[0])[:5] for h in c.fetchall()]

    # ==================================================
    # ⏳ RESERVAS PENDENTES
    # ==================================================
    c.execute("""
        SELECT horario, criado_em
        FROM reservas
        WHERE quadra = %s
          AND data = %s
          AND pago = FALSE
          AND criado_em >= NOW() - INTERVAL '10 minutes'
    """, (quadra, data))

    pendentes = []
    expiracao = {}

    for horario, criado_em in c.fetchall():
        hora_str = str(horario)[:5]
        pendentes.append(hora_str)
        expiracao[hora_str] = (criado_em + timedelta(minutes=10)).strftime("%H:%M")

    # ==================================================
    # MAPAS
    # ==================================================
    tipos_horarios = {}
    ocupados_dono = set()

    # ==================================================
    # 🔒 HORÁRIOS FIXOS (FUNCIONA NO DIA E NAS SEMANAS)
    # ==================================================
    c.execute("""
        SELECT h.hora
        FROM horarios h
        WHERE h.permanente = TRUE
          AND h.quadra = %s
          AND h.dia_semana = %s
          AND NOT EXISTS (
              SELECT 1
              FROM cancelamentos_fixos c
              WHERE c.quadra = h.quadra
                AND c.hora = h.hora
                AND c.data = %s
          )
    """, (quadra, dia_semana, data))

    for (hora,) in c.fetchall():
        hora_str = str(hora)[:5]
        tipos_horarios[hora_str] = "fixo"
        ocupados_dono.add(hora_str)

    # ==================================================
    # 🛠 HORÁRIOS DO DONO (DATA ESPECÍFICA)
    # ==================================================
    c.execute("""
        SELECT hora, tipo
        FROM horarios
        WHERE data = %s
          AND quadra = %s
          AND (permanente IS NULL OR permanente = FALSE)
    """, (data, quadra))

    for hora, tipo in c.fetchall():
        hora_str = str(hora)[:5]

        if hora_str in tipos_horarios:
            continue  # fixo nunca é sobrescrito

        tipo_normalizado = tipo.lower().replace(" ", "").replace("_", "")
        tipos_horarios[hora_str] = tipo_normalizado

        if tipo_normalizado in ["ocupado", "dayuse", "fechada"]:
            ocupados_dono.add(hora_str)

    conn.close()

    # ==================================================
    # 🚫 OCUPADOS FINAIS
    # ==================================================
    ocupados = list(set(ocupados_reserva) | ocupados_dono)

    return render_template(
        "horarios.html",
        esporte=esporte,
        quadra=quadra,
        data=data,
        horarios=lista_horarios,
        ocupados=ocupados,
        pendentes=pendentes,
        expiracao=expiracao,
        tipos_horarios=tipos_horarios,
        tipo_usuario=session.get("tipo")
    )

# ==========================
# HORÁRIOS FIXOS NOVA TELA
# ==========================

import calendar
from datetime import datetime
import psycopg2.extras

@app.route("/admin/horarios-fixos")
def admin_horarios_fixos():

    if "usuario" not in session or session.get("tipo") != "dono":
        return redirect("/login")

    conn = conectar()
    cur = conn.cursor()

    # ===============================
    # HORÁRIOS FIXOS ATIVOS
    # ===============================
    cur.execute("""
        SELECT
            id,
            cliente,
            telefone,
            email,
            quadra,
            hora,
            dia_semana
        FROM horarios
        WHERE tipo = 'fixo'
          AND permanente = TRUE
        ORDER BY quadra, hora
    """)
    dados = cur.fetchall()

    # ===============================
    # CANCELAMENTOS DE FIXOS
    # ===============================
    cur.execute("""
        SELECT quadra, hora, data
        FROM cancelamentos_fixos
    """)
    cancelados_db = cur.fetchall()

    cancelados_set = set(
        (q, str(h)[:5], d.strftime("%Y-%m-%d"))
        for q, h, d in cancelados_db
    )

    # ===============================
    # CALENDÁRIO DO MÊS ATUAL
    # ===============================
    hoje = datetime.now()
    ano = hoje.year
    mes = hoje.month
    ultimo_dia = calendar.monthrange(ano, mes)[1]

    fixos_dict = {}

    for id_fixo, cliente, telefone, email, quadra, hora, dia_semana in dados:

        if id_fixo not in fixos_dict:
            fixos_dict[id_fixo] = {
                "id": id_fixo,
                "cliente": cliente,
                "telefone": telefone,
                "email": email or "sem email",
                "quadra": quadra,
                "hora": str(hora)[:5],
                "datas": []
            }

        if dia_semana is None:
            continue

        for dia in range(1, ultimo_dia + 1):
            data = datetime(ano, mes, dia)

            if data.weekday() == dia_semana:
                data_str = data.strftime("%Y-%m-%d")

                cancelado = (
                    quadra,
                    str(hora)[:5],
                    data_str
                ) in cancelados_set

                fixos_dict[id_fixo]["datas"].append({
                    "data": data,
                    "data_str": data_str,
                    "cancelado": cancelado
                })

    fixos = list(fixos_dict.values())

    cur.close()
    conn.close()

    return render_template("horarios_fixos.html", fixos=fixos)


# ======================
# MEUS HORÁRIOS
# ======================

@app.route("/meus_horarios")
def meus_horarios():

    if "usuario" not in session:
        return redirect("/")

    usuario = session["usuario"]

    conn = conectar()
    c = conn.cursor()

    # ✅ BUSCA SOMENTE RESERVAS PAGAS
    c.execute("""
        SELECT esporte, quadra, data, horario, pago
        FROM reservas
        WHERE usuario = %s AND pago = TRUE
        ORDER BY data, horario
    """, (usuario,))

    reservas = c.fetchall()
    conn.close()

    return render_template(
        "meus_horarios.html",
        reservas=reservas
    )


# ======================
# CANCELAR / RESERVA / PAGAMENTO
# ======================

@app.route("/cancelar_pagamento/<int:reserva_id>", methods=["GET", "POST"])
def cancelar_pagamento(reserva_id):
    if "usuario" not in session:
        return redirect("/")

    conn = conectar()
    c = conn.cursor()

    # 🔎 Busca dados da reserva pendente
    c.execute("""
        SELECT esporte, quadra, data, horario
        FROM reservas
        WHERE id = %s AND pago = FALSE
    """, (reserva_id,))

    reserva = c.fetchone()

    if not reserva:
        conn.close()
        return redirect("/")

    esporte, quadra, data, horario = reserva

    # 🗑 Remove a reserva
    c.execute("""
        DELETE FROM reservas
        WHERE id = %s
    """, (reserva_id,))

    # 🔓 Remove o horário que foi marcado como ocupado
    c.execute("""
        DELETE FROM horarios
        WHERE quadra = %s
          AND data = %s
          AND hora = %s
          AND tipo = 'ocupado'
    """, (quadra, data, horario))

    conn.commit()
    conn.close()

    return redirect(url_for(
        "horarios",
        esporte=esporte,
        quadra=quadra,
        data=data
    ))



@app.route("/reservar", methods=["POST"])
def reservar():
    if "usuario" not in session:
        return redirect("/")

    usuario = session["usuario"]
    email = session.get("email", "cliente@arenacorpoativo.com")
    telefone = session.get("telefone", "")  # 🔥 agora salva telefone

    esporte = request.form["esporte"]
    quadra = request.form["quadra"]
    data = request.form["data"]
    horario = request.form["horario"]

    valor = 1  # teste

    conn = conectar()
    c = conn.cursor()

    # 🔒 1️⃣ TRAVA REAL
    c.execute("""
        SELECT 1 FROM reservas
        WHERE quadra = %s
          AND data = %s
          AND horario = %s
          AND (
              pago = TRUE OR
              criado_em >= NOW() - INTERVAL '10 minutes'
          )
        LIMIT 1
    """, (quadra, data, horario))

    if c.fetchone():
        conn.close()
        flash(
            "⏳ Outro cliente já reservou este horário.",
            "warning"
        )
        return redirect(url_for(
            "horarios",
            esporte=esporte,
            quadra=quadra,
            data=data
        ))

    # 🟡 2️⃣ CRIA RESERVA PENDENTE
    c.execute("""
        INSERT INTO reservas (
            usuario, telefone, esporte, quadra, data, horario,
            pago, status, criado_em
        )
        VALUES (%s, %s, %s, %s, %s, %s, FALSE, 'pendente', NOW())
        RETURNING id
    """, (
        usuario,
        telefone,
        esporte,
        quadra,
        data,
        horario
    ))

    reserva_id = c.fetchone()[0]

    # 🔥 3️⃣ MARCA HORÁRIO COMO OCUPADO IMEDIATAMENTE
    c.execute("""
        INSERT INTO horarios (
            data, hora, tipo, quadra
        )
        VALUES (%s, %s, 'ocupado', %s)
    """, (
        data,
        horario,
        quadra
    ))

    conn.commit()
    conn.close()

    # 💳 4️⃣ CRIA PAGAMENTO PIX
    payment_data = {
        "transaction_amount": float(valor),
        "description": f"Reserva Quadra {quadra} - {data} {horario}",
        "payment_method_id": "pix",
        "external_reference": str(reserva_id),
        "notification_url": "https://arenacorpoativo.onrender.com/webhook/mercadopago",
        "payer": {
            "email": email
        }
    }

    try:
        payment = mp.payment().create(payment_data)
        response = payment["response"]

        payment_id = response["id"]
        pix_data = response["point_of_interaction"]["transaction_data"]

        qr_code_base64 = pix_data["qr_code_base64"]
        qr_code_copia_cola = pix_data["qr_code"]

    except Exception as e:
        # ❌ rollback limpo
        conn = conectar()
        c = conn.cursor()

        c.execute("DELETE FROM reservas WHERE id = %s", (reserva_id,))
        c.execute("""
            DELETE FROM horarios
            WHERE quadra = %s
              AND data = %s
              AND hora = %s
        """, (quadra, data, horario))

        conn.commit()
        conn.close()

        print("ERRO MERCADO PAGO:", e)
        flash("Erro ao gerar pagamento.", "erro")
        return redirect(url_for(
            "horarios",
            esporte=esporte,
            quadra=quadra,
            data=data
        ))

    # 🔗 5️⃣ LINKA PAGAMENTO
    conn = conectar()
    c = conn.cursor()

    c.execute("""
        UPDATE reservas
        SET payment_id = %s,
            external_reference = %s
        WHERE id = %s
    """, (
        str(payment_id),
        str(reserva_id),
        reserva_id
    ))

    conn.commit()
    conn.close()

    return render_template(
        "pagamento.html",
        reserva_id=reserva_id,
        valor=valor,
        qr_code_base64=qr_code_base64,
        qr_code_copia_cola=qr_code_copia_cola
    )

# ======================
# EVENTOS DO DONO
# ======================

@app.route("/admin/eventos", methods=["GET", "POST"])
def admin_eventos():

    # 🔐 só dono
    if "usuario" not in session or session.get("tipo") != "dono":
        return redirect("/login")

    conn = conectar()
    c = conn.cursor()

    # PUBLICAR EVENTO
    if request.method == "POST":
        imagem = request.files.get("imagem")
        link = request.form.get("link")

        if imagem and imagem.filename != "":
            nome_arquivo = secrets.token_hex(8) + "_" + imagem.filename
            caminho = os.path.join(app.config["UPLOAD_FOLDER"], nome_arquivo)

            imagem.save(caminho)

            c.execute(
             "INSERT INTO eventos (imagem, link, criado_em) VALUES (%s, %s, %s)",
            (nome_arquivo, link, datetime.now())
             )

            conn.commit()
            flash("Evento publicado com sucesso!", "sucesso")

    # LISTAR EVENTOS
    c.execute("""
        SELECT id, imagem, link, criado_em
        FROM eventos
        ORDER BY criado_em DESC
    """)
    eventos = c.fetchall()

    conn.close()

    return render_template("admin_eventos.html", eventos=eventos)

# ======================
# EVENTOS EXCLUIR
# ======================

@app.route("/admin/eventos/excluir/<int:id_evento>", methods=["POST"])
def excluir_evento(id_evento):

    if "usuario" not in session or session.get("tipo") != "dono":
        return redirect("/login")

    conn = conectar()
    c = conn.cursor()

    # pega nome da imagem
    c.execute("SELECT imagem FROM eventos WHERE id=%s", (id_evento,))
    evento = c.fetchone()

    if evento:
        imagem = evento[0]
        caminho = os.path.join("static/uploads/eventos", imagem)

        if os.path.exists(caminho):
            os.remove(caminho)

        c.execute("DELETE FROM eventos WHERE id=%s", (id_evento,))
        conn.commit()

    conn.close()
    flash("Evento removido com sucesso!", "sucesso")

    return redirect("/admin/eventos")

# ======================
# PAINEL DO DONO 
# ======================

@app.route("/painel_dono")
def painel_dono():

    if "tipo" not in session or session["tipo"] != "dono":
        return redirect("/")

    data_filtro = request.args.get("data")
    quadra_filtro = request.args.get("quadra")

    conn = conectar()
    c = conn.cursor()

    query = """
    SELECT 
        COALESCE(r.nome, u.usuario, 'Não informado') AS cliente,
        COALESCE(u.telefone, '-') AS telefone,
        r.esporte,
        r.quadra,
        r.data,
        r.horario,
        COALESCE(r.pago, FALSE) AS pago
    FROM reservas r
    LEFT JOIN usuarios u
        ON u.usuario = r.usuario
    WHERE 1=1
"""

    params = []

    if data_filtro:
        query += " AND data = %s"
        params.append(data_filtro)

    if quadra_filtro:
        query += " AND quadra = %s"
        params.append(quadra_filtro)

    query += " ORDER BY data DESC, horario"

    c.execute(query, params)
    reservas_db = c.fetchall()

    conn.close()

    return render_template(
        "painel_dono.html",
        reservas=reservas_db,
        data_filtro=data_filtro,
        quadra_filtro=quadra_filtro
    )


# ======================
# RELATÓRIO MENSAL (DONO)
# ======================

@app.route("/relatorio_mensal")
def relatorio_mensal():
    if "tipo" not in session or session["tipo"] != "dono":
        return redirect("/")

    conn = conectar()
    c = conn.cursor()

    print("========== DIAGNÓSTICO RELATÓRIO ==========")

    # 🔍 TOTAL RESERVAS
    c.execute("SELECT COUNT(*) FROM reservas")
    print("TOTAL RESERVAS:", c.fetchone()[0])

    # 🔍 RESERVAS PAGAS
    c.execute("SELECT COUNT(*) FROM reservas WHERE pago = TRUE")
    print("RESERVAS PAGAS:", c.fetchone()[0])

    # 🔍 TOTAL HORARIOS
    c.execute("SELECT COUNT(*) FROM horarios")
    print("TOTAL HORARIOS:", c.fetchone()[0])

    # 🔍 DAY USE
    c.execute("SELECT COUNT(*) FROM horarios WHERE tipo = 'dayuse'")
    print("DAY USE:", c.fetchone()[0])

    # 🔍 FIXOS
    c.execute("SELECT COUNT(*) FROM horarios WHERE tipo = 'fixo' AND permanente = TRUE")
    print("FIXOS:", c.fetchone()[0])

    print("===========================================")

    # 🔵 Reservas pagas por mês
    c.execute("""
        SELECT 
            to_char(data, 'YYYY-MM') AS mes,
            COUNT(*) 
        FROM reservas
        WHERE pago = TRUE
        GROUP BY mes
        ORDER BY mes
    """)
    reservas = {row[0]: row[1] for row in c.fetchall()}

    # 🟠 Day Uses por mês
    c.execute("""
        SELECT 
            to_char(data, 'YYYY-MM') AS mes,
            COUNT(*) 
        FROM horarios
        WHERE tipo = 'dayuse'
        GROUP BY mes
        ORDER BY mes
    """)
    day_uses = {row[0]: row[1] for row in c.fetchall()}

    # 🟢 Fixos por mês
    c.execute("""
        SELECT 
            to_char(data, 'YYYY-MM') AS mes,
            COUNT(*) 
        FROM horarios
        WHERE tipo = 'fixo'
          AND permanente = TRUE
        GROUP BY mes
        ORDER BY mes
    """)
    fixos = {row[0]: row[1] for row in c.fetchall()}

    conn.close()

    meses = sorted(set(reservas) | set(day_uses) | set(fixos))

    dados = []

    for mes in meses:
        dados.append({
            "mes": mes,
            "reservas": reservas.get(mes, 0),
            "day_uses": day_uses.get(mes, 0),
            "fixos": fixos.get(mes, 0)
        })

    return render_template("relatorio_mensal.html", dados=dados)


# ======================
# GERENCIAR HORÁRIOS (DONO)
# ======================

@app.route("/admin/definir_horario", methods=["POST"])
def definir_horario():

    if "tipo" not in session or session["tipo"] != "dono":
        abort(403)

    data = request.form.get("data")
    hora = request.form.get("hora")
    quadra = request.form.get("quadra")

    tipo = request.form.get("tipo")
    if tipo:
        tipo = tipo.lower().replace(" ", "").replace("_", "")

    conn = conectar()
    c = conn.cursor()

    # 🔥 Remove qualquer regra anterior do dono (agenda diária)
    c.execute("""
        DELETE FROM horarios
        WHERE data = %s AND hora = %s AND quadra = %s
    """, (data, hora, quadra))

    # ======================
    # LIVRE → REMOVE FIXO E SUBTRAI DO RELATÓRIO
    # ======================
    if tipo == "livre" or not tipo:

        # 🔑 REMOVE HORÁRIO FIXO PERMANENTE (ESSA ERA A FALTA)
        c.execute("""
            DELETE FROM horarios
            WHERE hora = %s
              AND quadra = %s
              AND tipo = 'fixo'
              AND permanente = TRUE
        """, (hora, quadra))

        # Remove reservas (se existirem)
        c.execute("""
            DELETE FROM reservas
            WHERE data = %s AND horario = %s AND quadra = %s
        """, (data, hora, quadra))

        # DESATIVA HISTÓRICO ATIVO
        c.execute("""
            UPDATE historico_horarios
            SET ativo = FALSE
            WHERE id = (
                SELECT id
                FROM historico_horarios
                WHERE data = %s
                  AND hora = %s
                  AND quadra = %s
                  AND ativo = TRUE
                ORDER BY criado_em DESC
                LIMIT 1
            )
            AND ativo = TRUE
        """, (data, hora, quadra))

    # ======================
    # OCUPADO / FIXO / DAY USE → SOMA NO RELATÓRIO
    # ======================
    else:
        # 🔑 REGRA EXISTENTE (mantida)
        permanente = True if tipo == "fixo" else False

        c.execute("""
            INSERT INTO horarios (data, hora, quadra, tipo, permanente)
            VALUES (%s, %s, %s, %s, %s)
        """, (data, hora, quadra, tipo, permanente))

        # REGISTRA HISTÓRICO (continua igual)
        c.execute("""
            INSERT INTO historico_horarios (data, hora, quadra, origem)
            VALUES (%s, %s, %s, %s)
        """, (data, hora, quadra, tipo))

    conn.commit()
    conn.close()

    return redirect(request.referrer)


# ==================================================================
# RESERVA MANUAL DO DONO
# ==================================================================

@app.route("/admin/reserva_manual", methods=["POST"])
def reserva_manual():

    if session.get("tipo") != "dono":
        abort(403)

    nome = request.form.get("nome")
    telefone = request.form.get("telefone")
    email = request.form.get("email")

    quadra = request.form.get("quadra")
    esporte = request.form.get("esporte")
    data = request.form.get("data")
    horario = request.form.get("horario")

    tipo = request.form.get("tipo", "ocupado").lower().strip()
    pago = request.form.get("pago") == "true"

    # 🔧 Correção Python ↔ Postgres
    dia_semana = datetime.strptime(data, "%Y-%m-%d").weekday()

    conn = conectar()
    c = conn.cursor()

    # ================= REMOVE CONFLITOS =================
    if tipo == "fixo":
        c.execute("""
            DELETE FROM horarios
            WHERE quadra = %s
              AND hora = %s
              AND permanente = TRUE
        """, (quadra, horario))
    else:
        c.execute("""
            DELETE FROM horarios
            WHERE quadra = %s
              AND hora = %s
              AND data = %s
        """, (quadra, horario, data))

    # ================= HORÁRIO FIXO =================
    if tipo == "fixo":

        c.execute("""
            INSERT INTO horarios
            (quadra, data, hora, tipo, permanente, dia_semana, cliente, telefone, email)
            VALUES (%s, NULL, %s, 'fixo', TRUE, %s, %s, %s, %s)
        """, (
            quadra,
            horario,
            dia_semana,
            nome,
            telefone,
            email
        ))

        conn.commit()
        conn.close()
        return redirect(request.referrer)

    # ================= OCUPADO NORMAL =================
    c.execute("""
        DELETE FROM reservas
        WHERE quadra = %s AND data = %s AND horario = %s
    """, (quadra, data, horario))

    c.execute("""
        INSERT INTO reservas
        (nome, telefone, email, esporte, quadra, data, horario, pago, origem)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'dono')
    """, (
        nome,
        telefone,
        email,
        esporte,
        quadra,
        data,
        horario,
        pago
    ))

    c.execute("""
        INSERT INTO horarios
        (quadra, data, hora, tipo, permanente)
        VALUES (%s,%s,%s,'ocupado',FALSE)
    """, (quadra, data, horario))

    conn.commit()
    conn.close()

    return redirect(f"/horarios/{esporte}/{quadra}/{data}")


# ==================================================================
# ROTA PARA IR PARA TELA QUADRAS APÓS CLICAR EM GERENCIAR HORARIOS
# ==================================================================

@app.route("/admin/quadras")
def admin_quadras():
    if "usuario" not in session or session.get("tipo") != "dono":
        return redirect("/login")

    quadras = ["Quadra 1", "Quadra 2", "Quadra 3"]

    return render_template(
        "quadras.html",
        esporte="Gerenciamento de Horários",
        quadras=quadras
    )

# ==================================================================
# GERENCIAR HORARIOS
# ==================================================================

@app.route("/admin/horarios")
def admin_horarios():

    # 🔐 só dono
    if "usuario" not in session or session.get("tipo") != "dono":
        return redirect("/login")

    quadras = ["Quadra 1", "Quadra 2", "Quadra 3"]

    # texto só para o título da página
    esporte = "Gerenciar Horários"

    return render_template(
        "quadras.html",
        esporte=esporte,
        quadras=quadras
    )

# ==========================================
# MERCADO PAGO RESPONDE PARA O SITE
# ==========================================

@app.route("/status_reserva/<int:reserva_id>")
def status_reserva(reserva_id):
    conn = conectar()
    c = conn.cursor()

    c.execute("SELECT pago FROM reservas WHERE id = %s", (reserva_id,))
    r = c.fetchone()

    conn.close()

    if r and r[0]:
        return {"status": "confirmado"}
    return {"status": "pendente"}


@app.route("/webhook/mercadopago", methods=["POST"])
def webhook_mercadopago():
    # 1️⃣ pegar payment_id
    payment_id = (
        request.args.get("data.id")
        or request.args.get("id")
    )

    if not payment_id:
        return "ok", 200

    # 2️⃣ buscar pagamento no Mercado Pago
    headers = {
        "Authorization": f"Bearer {os.getenv('MERCADOPAGO_ACCESS_TOKEN')}"
    }

    r = requests.get(
        f"https://api.mercadopago.com/v1/payments/{payment_id}",
        headers=headers
    )

    if r.status_code != 200:
        return "ok", 200

    pagamento = r.json()
    status = pagamento.get("status")
    reserva_id = pagamento.get("external_reference")

    # só processa se realmente aprovado
    if status != "approved" or not reserva_id:
        return "ok", 200

    conn = conectar()
    c = conn.cursor()

    # 3️⃣ buscar dados da reserva (somente se ainda não estiver paga)
    c.execute("""
        SELECT data, horario, quadra
        FROM reservas
        WHERE id = %s AND pago = FALSE
    """, (reserva_id,))

    reserva = c.fetchone()
    if not reserva:
        conn.close()
        return "ok", 200

    data_reserva, horario_reserva, quadra_reserva = reserva

    # 4️⃣ confirmar reserva
    c.execute("""
        UPDATE reservas
        SET pago = TRUE,
            status = 'pago',
            payment_id = %s
        WHERE id = %s
    """, (payment_id, reserva_id))

    # 5️⃣ converte horário reservado → ocupado (SEM duplicar)
    c.execute("""
        UPDATE horarios
        SET tipo = 'ocupado'
        WHERE data = %s
          AND hora = %s::time
          AND quadra = %s
          AND tipo = 'reservado'
    """, (data_reserva, horario_reserva, quadra_reserva))

    # se nada foi atualizado, não continua (webhook duplicado, por ex.)
    if c.rowcount == 0:
        conn.commit()
        conn.close()
        return "ok", 200

    # 🔒 6️⃣ desativa qualquer histórico ativo anterior (EVITA DUPLICIDADE)
    c.execute("""
        UPDATE historico_horarios
        SET ativo = FALSE
        WHERE data = %s
          AND hora = %s::time
          AND quadra = %s
          AND ativo = TRUE
    """, (data_reserva, horario_reserva, quadra_reserva))

    # 📊 7️⃣ registra UM único histórico válido (entra no relatório mensal)
    c.execute("""
        INSERT INTO historico_horarios (data, hora, quadra, origem, ativo)
        VALUES (%s, %s::time, %s, 'ocupado', TRUE)
    """, (data_reserva, horario_reserva, quadra_reserva))

    conn.commit()
    conn.close()

    print(f"✅ Reserva {reserva_id} confirmada com sucesso")
    return "ok", 200

# ======================
# EVENTOS
# ======================

@app.route("/eventos")
def eventos():
    conn = conectar()
    c = conn.cursor()

    c.execute("""
        SELECT imagem, link, criado_em
        FROM eventos
        ORDER BY criado_em DESC
    """)
    eventos = c.fetchall()
    conn.close()

    return render_template("eventos.html", eventos=eventos)


# ======================
# LIMPAR SESSÃO
# ======================

@app.route("/limpar_sessao")
def limpar_sessao():
    session.clear()
    return "Sessão limpa. Pode fechar esta aba e tentar login novamente."

# ======================
# LOGOUT
# ======================

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

# ======================
# CANCELAR RESERVAS
# ======================

from datetime import datetime

@app.route("/cancelar_reserva", methods=["POST"])
def cancelar_reserva():
    if "tipo" not in session or session["tipo"] != "dono":
        return redirect("/")

    quadra = request.form.get("quadra")
    data = request.form.get("data")
    horario = request.form.get("horario")

    # 🔥 Converte string para TIME (corrige erro 500)
    horario_time = datetime.strptime(horario, "%H:%M").time()

    conn = conectar()
    c = conn.cursor()

    # 1️⃣ Remove a reserva
    c.execute("""
        DELETE FROM reservas
        WHERE quadra = %s
          AND data = %s
          AND horario = %s
    """, (quadra, data, horario))

    # 2️⃣ Libera o horário
    c.execute("""
        DELETE FROM horarios
        WHERE quadra = %s
          AND data = %s
          AND hora = %s
          AND tipo = 'ocupado'
    """, (quadra, data, horario_time))

    # 3️⃣ Ajusta relatório (só se a tabela existir)
    c.execute("""
        UPDATE historico_horarios
        SET ativo = FALSE
        WHERE id = (
            SELECT id
            FROM historico_horarios
            WHERE data = %s
              AND hora = %s
              AND quadra = %s
              AND ativo = TRUE
            ORDER BY criado_em DESC
            LIMIT 1
        )
    """, (data, horario_time, quadra))

    conn.commit()
    conn.close()

    flash("Reserva cancelada com sucesso!", "sucesso")
    return redirect("/painel_dono")

# ======================
# LOGIN GOOGLE
# ======================

@app.route("/login_google")
def login_google():
    if not google.authorized:
        return redirect(url_for("google.login"))

    resp = google.get("/oauth2/v2/userinfo")
    if not resp.ok:
        return redirect("/login")

    info = resp.json()
    email = info["email"]

    conn = conectar()
    c = conn.cursor()

    c.execute("SELECT * FROM usuarios WHERE usuario=%s", (email,))
    user = c.fetchone()

    if not user:
        c.execute(
            "INSERT INTO usuarios (usuario, senha, tipo) VALUES (%s, %s, 'cliente')",
            (email, "")
        )
        conn.commit()

    conn.close()

    # ❌ NÃO usar session.clear()
    session["usuario"] = email
    session["tipo"] = "cliente"

    return redirect("/telefone")

# ======================
# ESQUECI MINHA SENHA
# ======================

@app.route("/esqueci_senha", methods=["GET", "POST"])
def esqueci_senha():
    if request.method == "POST":
        email = request.form["email"]

        conn = conectar()
        c = conn.cursor()

        # só permite reset para quem NÃO usa Google
        c.execute("""
            SELECT * FROM usuarios 
            WHERE usuario=%s AND senha != ''
        """, (email,))
        user = c.fetchone()

        if not user:
            conn.close()
            return render_template(
                "esqueci_senha.html",
                mensagem="E-mail inválido."
            )

        token = secrets.token_urlsafe(32)
        expira = (datetime.now() + timedelta(minutes=15))

        c.execute("""
            UPDATE usuarios
            SET reset_token=%s, reset_expira=%s
            WHERE usuario=%s
        """, (token, expira, email))

        conn.commit()
        conn.close()

        sucesso = enviar_email_recuperacao(email, token)

        if sucesso:
            mensagem = "Verifique seu email para redefinir a senha."
        else:
            mensagem = "Erro ao enviar email. Tente novamente mais tarde."

        return render_template("esqueci_senha.html", mensagem=mensagem)

    return render_template("esqueci_senha.html")

# ======================
# CANCELA FIXO SEMPRE
# ======================

@app.route("/admin/cancelar_fixo_definitivo", methods=["POST"])
def cancelar_fixo_definitivo():
    id_fixo = request.form.get("id_fixo")

    if not id_fixo:
        flash("Erro: ID não recebido.", "erro")
        return redirect("/admin/horarios-fixos")

    conn = conectar()
    cur = conn.cursor()

    cur.execute("""
        UPDATE horarios
        SET permanente = FALSE
        WHERE id = %s
    """, (id_fixo,))

    conn.commit()
    cur.close()
    conn.close()

    flash("Horário fixo cancelado definitivamente.", "sucesso")
    return redirect("/admin/horarios-fixos")


# ======================
# CANCELA FIXO NO DIA 1
# ======================

@app.route("/admin/cancelar_fixo_dia", methods=["POST"])
def cancelar_fixo_dia():
    quadra = request.form["quadra"]
    hora = request.form["hora"]
    data = request.form["data"]

    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO cancelamentos_fixo (quadra, hora, data)
        VALUES (%s, %s, %s)
        ON CONFLICT DO NOTHING
    """, (quadra, hora, data))

    conn.commit()
    cur.close()
    conn.close()

    flash("Horário cancelado apenas neste dia.", "sucesso")
    return redirect("/admin/horarios-fixos")

# ======================
# CANCELA FIXO NO DIA 2
# ======================

import logging

@app.route('/admin/toggle_fixo_dia', methods=['POST'])
def toggle_fixo_dia():
    app.logger.warning(f"POST RECEBIDO: {request.form}")
    quadra = request.form.get('quadra')
    hora = request.form.get('hora')
    data = request.form.get('data')
    cancelado = request.form.get('cancelado')  # "1" = estava cancelado

    if not quadra or not hora or not data:
        print("❌ DADOS INCOMPLETOS:", quadra, hora, data)
        return redirect(url_for('admin_horarios_fixos'))

    conn = conectar()
    cur = conn.cursor()

    try:
        if cancelado == "1":
            # 🔁 REATIVAR
            cur.execute("""
                DELETE FROM cancelamentos_fixos
                WHERE quadra = %s AND hora = %s AND data = %s
            """, (quadra, hora, data))
        else:
            # ⛔ CANCELAR
            cur.execute("""
                INSERT INTO cancelamentos_fixos (quadra, hora, data)
                VALUES (%s, %s, %s)
                ON CONFLICT (quadra, hora, data) DO NOTHING
            """, (quadra, hora, data))
        print("🔄 TOGGLE:", quadra, hora, data, "cancelado =", cancelado)
        conn.commit()
        print("✅ COMMIT REALIZADO")

    except Exception as e:
        conn.rollback()
        print("🔥 ERRO TOGGLE_FIXO_DIA:", e)

    finally:
        cur.close()
        conn.close()

    return redirect(url_for('admin_horarios_fixos'))



# ======================
# RESET MINHA SENHA
# ======================

@app.route("/reset_senha/<token>", methods=["GET", "POST"])
def reset_senha(token):
    conn = conectar()
    c = conn.cursor()

    c.execute("""
        SELECT reset_expira FROM usuarios
        WHERE reset_token=%s
    """, (token,))
    user = c.fetchone()

    if not user:
        conn.close()
        return "❌ Link inválido ou expirado"

    if datetime.now() > user[0]:
        conn.close()
        return "⏰ Token expirado"

    if request.method == "POST":
        nova = request.form["senha"]

        c.execute("""
            UPDATE usuarios
            SET senha=%s, reset_token=NULL, reset_expira=NULL
            WHERE reset_token=%s
        """, (nova, token))

        conn.commit()
        conn.close()
        return redirect("/login")

    conn.close()
    return render_template("reset_senha.html")

# -----------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)


