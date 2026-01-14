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
    SESSION_COOKIE_SAMESITE="Lax",
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


# ======================
# TELA INICIAL
# ======================

@app.route("/")
def inicio():
    if "usuario" in session:
        return redirect("/telefone")  # já logado
    return render_template("escolha.html")


# ======================
# LOGIN CLIENTE
# ======================
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        usuario = request.form["usuario"]
        senha = request.form["senha"]

        conn = conectar()
        c = conn.cursor()
        c.execute(
            "SELECT * FROM usuarios WHERE usuario=%s AND senha=%s AND tipo='cliente'",
            (usuario, senha),
        )
        user = c.fetchone()
        conn.close()

        if user:
            session["usuario"] = usuario
            session["tipo"] = "cliente"
            return redirect("/telefone")
        else:
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

    # ==================================================
    # 🔒 CLIENTE: HOJE + 6 DIAS
    # ==================================================
    if session.get("tipo") != "dono":
     if data_escolhida < hoje or data_escolhida > hoje + timedelta(days=6):
        return redirect(f"/datas/{esporte}/{quadra}")


    lista_horarios = [f"{h:02d}:00" for h in range(6, 22)]

    if data_escolhida == hoje:
        hora_atual = agora.strftime("%H:%M")
        lista_horarios = [h for h in lista_horarios if h > hora_atual]

    conn = conectar()
    c = conn.cursor()

    # ======================
    # RESERVAS PAGAS
    # ======================
    c.execute("""
        SELECT horario FROM reservas
        WHERE quadra = %s AND data = %s AND pago = TRUE
    """, (quadra, data))
    ocupados_reserva = [h[0] for h in c.fetchall()]

    # ======================
    # HORÁRIOS DEFINIDOS PELO DONO
    # ======================
    c.execute("""
        SELECT hora, tipo FROM horarios
        WHERE data = %s AND quadra = %s
    """, (data, quadra))
    dia = c.fetchall()

    tipos_horarios = {}
    ocupados_dono = []

    for hora, tipo in dia:
        hora_str = hora.strftime("%H:%M")
        tipos_horarios[hora_str] = tipo
        if tipo == "ocupado":
            ocupados_dono.append(hora_str)

    # ======================
    # HORÁRIOS FIXOS
    # ======================
    c.execute("""
        SELECT hora, tipo FROM horarios
        WHERE permanente = TRUE AND quadra = %s
    """, (quadra,))
    fixos = c.fetchall()

    for hora, tipo in fixos:
        tipos_horarios[hora.strftime("%H:%M")] = tipo

    conn.close()

    # ======================
    # OCUPADOS = RESERVA OU DONO
    # ======================
    ocupados = list(set(ocupados_reserva + ocupados_dono))

    return render_template(
        "horarios.html",
        esporte=esporte,
        quadra=quadra,
        data=data,
        horarios=lista_horarios,
        ocupados=ocupados,
        tipos_horarios=tipos_horarios,
        tipo_usuario=session.get("tipo")
    )

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

    # 🧹 Remove reservas com mais de 2 dias de atraso
    c.execute("""
    DELETE FROM reservas
    WHERE data < CURRENT_DATE - INTERVAL '2 days'
             """)
    conn.commit()


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
# RESERVA / PAGAMENTO
# ======================

@app.route("/reservar", methods=["POST"])
def reservar():
    if "usuario" not in session:
        return redirect("/")

    usuario = session["usuario"]
    esporte = request.form["esporte"]
    quadra = request.form["quadra"]
    data = request.form["data"]
    horario = request.form["horario"]

    conn = conectar()
    c = conn.cursor()

    # salva como PENDENTE
    c.execute("""
        INSERT INTO reservas (usuario, esporte, quadra, data, horario, pago, status, criado_em)
        VALUES (%s, %s, %s, %s, %s, FALSE, 'pendente', %s)
        RETURNING id
    """, (
        usuario,
        esporte,
        quadra,
        data,
        horario,
        datetime.now()
    ))

    reserva_id = c.fetchone()[0]

    conn.commit()
    conn.close()

    # 📲 dados da arena (POR ENQUANTO FIXOS)
    whatsapp_arena = WHATSAPP_ARENA  # seu WhatsApp com DDI
    chave_pix = CHAVE_PIX

    mensagem = (
        f"*ARENA CORPO ATIVO!* \n\n"
        f"Olá! 👋\n\n"
        f"Você solicitou a reserva:\n"
        f"🏟 Quadra: {quadra}\n"
        f"📅 Data: {data}\n"
        f"⏰ Horário: {horario}\n\n"
        f"💰 Valor: R$ 65,00\n"
        f"🔑 Pix: {chave_pix}\n\n"
        f"⏳ Você tem até *10 minutos* para realizar o pagamento.\n"
        f"Após o pagamento por favor *envie* o comprovante logo abaixo."
        f"Após o envio do comprovante, volte ao app e clique em *Já paguei* será direcionado novamente para o whatsapp e será confirmado seu horário."
    )

    link_whatsapp = f"https://wa.me/{whatsapp_arena}?text={quote_plus(mensagem)}"

    return render_template(
        "pagamento.html",
        esporte=esporte,
        quadra=quadra,
        data=data,
        horario=horario,
        valor=65,
        whatsapp_link=link_whatsapp,
        reserva_id=reserva_id
    )


# ======================
# CONFIRMAR PAGAMENTO
# ======================

@app.route("/confirmar_pagamento", methods=["POST"])
def confirmar_pagamento():
    if "usuario" not in session:
        return redirect("/")

    usuario = session["usuario"]
    esporte = request.form["esporte"]
    quadra = request.form["quadra"]
    data = request.form["data"]
    horario = request.form["horario"]

    conn = conectar()
    c = conn.cursor()

    # 🔎 Verifica se já está pago
    c.execute("""
        SELECT pago FROM reservas
        WHERE usuario = %s
          AND esporte = %s
          AND quadra = %s
          AND data = %s
          AND horario = %s
    """, (usuario, esporte, quadra, data, horario))

    resultado = c.fetchone()

    # Se já estiver pago, não faz nada
    if resultado and resultado[0] == True:
        conn.close()
        return redirect("/meus_horarios")

    # ✅ Marca como pago
    c.execute("""
        UPDATE reservas 
        SET pago = TRUE
        WHERE usuario = %s
          AND esporte = %s
          AND quadra = %s
          AND data = %s
          AND horario = %s
    """, (usuario, esporte, quadra, data, horario))

    # 📊 Registra como "ocupado" no relatório mensal
    c.execute("""
        INSERT INTO horarios (data, hora, quadra, tipo, permanente)
        VALUES (%s, %s, %s, 'ocupado', FALSE)
    """, (data, horario, quadra))

    conn.commit()
    conn.close()

    # 📲 WhatsApp
    whatsapp_arena = WHATSAPP_ARENA

    mensagem = (
        f"✅ PAGAMENTO CONFIRMADO!\n\n"
        f"Reserva confirmada:\n"
        f"🏟 Quadra: {quadra}\n"
        f"📅 Data: {data}\n"
        f"⏰ Horário: {horario}\n\n"
        f"Obrigado! Nos vemos na arena 💪🔥"
    )

    link_whatsapp = f"https://wa.me/{whatsapp_arena}?text={quote_plus(mensagem)}"

    return redirect(link_whatsapp)


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
            r.usuario,
            u.telefone,
            r.esporte,
            r.quadra,
            r.data,
            r.horario,
            r.pago
        FROM reservas r
        LEFT JOIN usuarios u ON u.usuario = r.usuario
        WHERE r.pago = TRUE
    """
    params = []

    if data_filtro:
        query += " AND r.data = %s"
        params.append(data_filtro)

    if quadra_filtro:
        query += " AND r.quadra = %s"
        params.append(quadra_filtro)

    query += " ORDER BY r.data, r.horario"

    c.execute(query, params)
    reservas = c.fetchall()
    conn.close()

    return render_template(
        "painel_dono.html",
        reservas=reservas,
        data_filtro=data_filtro,
        quadra_filtro=quadra_filtro
    )

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
        tipo = tipo.lower().replace(" ", "")  # "Day Use" -> "dayuse"

    conn = conectar()
    c = conn.cursor()

    # Remove regra anterior
    c.execute("""
        DELETE FROM horarios
        WHERE data = %s AND hora = %s AND quadra = %s
    """, (data, hora, quadra))

    # LIVRE
    if tipo == "livre" or not tipo:

        c.execute("""
            DELETE FROM reservas
            WHERE data = %s AND horario = %s AND quadra = %s
        """, (data, hora, quadra))

    # OCUPADO, FIXO, DAYUSE
    else:

        c.execute("""
            INSERT INTO horarios (data, hora, quadra, tipo, permanente)
            VALUES (%s, %s, %s, %s, FALSE)
        """, (data, hora, quadra, tipo))

    conn.commit()
    conn.close()

    return redirect(request.referrer)



# ==================================================================
# GERENCIAMENTO MENSAL (RELATÓRIO)
# ==================================================================

@app.route("/admin/relatorio_mensal")
def relatorio_mensal():

    if "tipo" not in session or session["tipo"] != "dono":
        return redirect("/")

    conn = conectar()
    c = conn.cursor()

    c.execute("""
        SELECT 
            TO_CHAR(data, 'MM/YYYY') AS mes,
            COUNT(*) FILTER (WHERE tipo = 'ocupado' OR tipo = 'fixo') AS horarios,
            COUNT(*) FILTER (WHERE tipo = 'dayuse') AS dayuses
        FROM horarios
        WHERE data IS NOT NULL
        GROUP BY mes
        ORDER BY mes;
    """)

    dados = c.fetchall()
    conn.close()

    return render_template("relatorio_mensal.html", dados=dados)


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

@app.route("/cancelar_reserva", methods=["POST"])
def cancelar_reserva():
    if "tipo" not in session or session["tipo"] != "dono":
        return redirect("/")

    usuario = request.form.get("usuario")
    esporte = request.form.get("esporte")
    quadra = request.form.get("quadra")
    data = request.form.get("data")
    horario = request.form.get("horario")

    conn = conectar()
    c = conn.cursor()

    c.execute("""
        DELETE FROM reservas
        WHERE usuario = %s
          AND esporte = %s
          AND quadra = %s
          AND data = %s
          AND horario = %s
    """, (usuario, esporte, quadra, data, horario))

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


