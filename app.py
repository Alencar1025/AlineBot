# ---------- IMPORTS OBRIGATÓRIOS ----------
from flask import Flask, request, jsonify, g
import re
import os
import sqlite3
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
import time
import requests
import logging
import json
import messagebird  # Novo provider

# ---------- CONFIGURAÇÕES INICIAIS ----------
app = Flask(__name__)
app.config['DATABASE'] = 'states.db'

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("alinebot.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('AlineBot')

# Configuração MessageBird
MBIRD_API_KEY = os.environ.get('MBIRD_API_KEY')
MBIRD_NUMBER = os.environ.get('MBIRD_NUMBER')
client = messagebird.Client(MBIRD_API_KEY) if MBIRD_API_KEY else None

# Configuração Google Sheets
SCOPES = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
GOOGLE_CREDS = json.loads(os.environ.get('GOOGLE_CREDS_JSON')) if os.environ.get('GOOGLE_CREDS_JSON') else {}

# ---------- BANCO DE DADOS SQLITE ----------
def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(app.config['DATABASE'])
        db.row_factory = sqlite3.Row
    return db

def init_db():
    with app.app_context():
        db = get_db()
        cursor = db.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_states (
                phone TEXT PRIMARY KEY,
                state TEXT,
                last_interaction TEXT,
                primeira_vez BOOLEAN DEFAULT 1,
                dados_reserva TEXT
            )
        ''')
        db.commit()

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

# ---------- SISTEMA DE INTENÇÕES ----------
INTENTOES = {
    "saudacao": ["oi", "olá", "ola", "bom dia", "boa tarde", "boa noite", "aline", "alô"],
    "ajuda": ["ajuda", "socorro", "opções", "comandos", "menu", "help"],
    "reserva": ["reserva", "reservar", "agendar", "viagem", "passagem"],
    "pagar": ["pagar", "pagamento", "pague", "comprar"],
    "status": ["status", "situação", "verificar", "consulta"],
    "cancelar": ["cancelar", "desmarcar", "anular", "remover"],
    "suporte": ["suporte", "atendente", "humano", "operador"]
}

# ---------- FUNÇÕES AUXILIARES ----------
def obter_periodo_dia():
    hora_atual = datetime.now().hour
    if 5 <= hora_atual < 12:
        return "Bom dia"
    elif 12 <= hora_atual < 18:
        return "Boa tarde"
    return "Boa noite"

def detectar_intencao(mensagem):
    mensagem = mensagem.lower().strip()
    for palavra in mensagem.split():
        for intencao, palavras_chave in INTENTOES.items():
            if palavra in palavras_chave:
                return intencao
    return None

def conectar_google_sheets():
    try:
        if not GOOGLE_CREDS:
            return None
            
        fixed_creds = GOOGLE_CREDS.copy()
        if 'private_key' in fixed_creds:
            fixed_creds['private_key'] = fixed_creds['private_key'].replace('\\\\n', '\n').replace('\\n', '\n')
        
        creds = Credentials.from_service_account_info(fixed_creds, scopes=SCOPES)
        return gspread.authorize(creds)
    except Exception as e:
        logger.error(f"Erro Google Sheets: {str(e)}")
        return None

def enviar_resposta(telefone, mensagem):
    """Envia mensagem via MessageBird"""
    try:
        if client:
            msg = client.message_create(
                MBIRD_NUMBER,
                f"+55{telefone}",  # Formato internacional para Brasil
                mensagem
            )
            logger.info(f"Mensagem enviada para {telefone}: {mensagem[:50]}...")
            return True
        return False
    except Exception as e:
        logger.error(f"Erro MessageBird: {str(e)}")
        return False

# ---------- ROTA PRINCIPAL ----------
@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    logger.info(f"Dados recebidos: {json.dumps(data, indent=2)}")
    
    # Extrair informações do MessageBird
    if data.get('type') == 'message':
        telefone = data['source']['number']
        mensagem = data['content']['text']
    else:
        return jsonify({"status": "ignorado"}), 200
    
    telefone = re.sub(r'\D', '', telefone)[-11:]  # Normalizar telefone
    
    db = get_db()
    cursor = db.cursor()
    
    # Recuperar ou criar estado do usuário
    cursor.execute("SELECT * FROM user_states WHERE phone = ?", (telefone,))
    estado_usuario = cursor.fetchone()
    
    if not estado_usuario:
        cursor.execute(
            "INSERT INTO user_states (phone, state, last_interaction, primeira_vez) VALUES (?, ?, ?, ?)",
            (telefone, "INICIO", datetime.now().isoformat(), True)
        )
        db.commit()
        estado_atual = "INICIO"
        primeira_vez = True
    else:
        estado_atual = estado_usuario["state"]
        primeira_vez = estado_usuario["primeira_vez"]
    
    # Processar mensagem
    intencao = detectar_intencao(mensagem)
    resposta = processar_mensagem(estado_atual, intencao, mensagem, telefone, primeira_vez)
    
    # Atualizar estado
    novo_estado = resposta.get("novo_estado", estado_atual)
    cursor.execute(
        "UPDATE user_states SET state = ?, last_interaction = ?, primeira_vez = ? WHERE phone = ?",
        (novo_estado, datetime.now().isoformat(), False, telefone)
    )
    db.commit()
    
    # Enviar resposta
    enviar_resposta(telefone, resposta["mensagem"])
    return jsonify({"status": "sucesso"}), 200

def processar_mensagem(estado_atual, intencao, mensagem, telefone, primeira_vez):
    periodo = obter_periodo_dia()
    resposta = {"mensagem": "", "novo_estado": estado_atual}
    
    if estado_atual == "INICIO":
        if intencao in ["saudacao", "ajuda"] or primeira_vez:
            saudacao = f"{periodo}! Eu sou a Aline, assistente da JCM Viagens 🧳✨\n\n" if primeira_vez else f"{periodo}! "
            resposta["mensagem"] = (
                saudacao +
                "*Comandos disponíveis:*\n"
                "- RESERVA: Nova reserva\n"
                "- STATUS: Verificar reserva\n"
                "- PAGAR: Pagamento\n"
                "- CANCELAR: Cancelamento\n"
                "- SUPORTE: Atendente humano\n\n"
                "Digite o comando desejado!"
            )
            resposta["novo_estado"] = "AGUARDANDO_ACAO"
        
        elif intencao == "continuar":
            resposta["mensagem"] = "Vamos continuar de onde paramos! Qual era a última ação?"
            resposta["novo_estado"] = "AGUARDANDO_ACAO"
        
        else:
            resposta["mensagem"] = "Não entendi. Digite *OI* para começar ou *AJUDA* para ver opções"
    
    elif estado_atual == "AGUARDANDO_ACAO":
        if intencao == "reserva":
            resposta["mensagem"] = (
                "✈️ Para reservar, envie:\n\n"
                "RESERVA [origem] para [destino] - [pessoas] pessoas - [data]\n\n"
                "*Exemplos válidos:*\n"
                "RESERVA Aeroporto GRU para Hotel Campinas - 4 pessoas - 25/07/2025\n"
                "reserva São Paulo para Rio - 2 pessoas - 30/07/2025"
            )
            resposta["novo_estado"] = "AGUARDANDO_RESERVA"
        
        # Outros estados (similar ao anterior, adaptado para novo fluxo)
    
    elif estado_atual == "AGUARDANDO_RESERVA":
        # Regex robusto que aceita variações
        padrao = r'(?i)(?:reserva|reservar)\s+(.+?)\s+(?:para|pra|->)\s+(.+?)\s+[-\—]\s+(\d+)\s+(?:pessoas?|pess?|pax)\s+[-\—]\s+(\d{1,2}/\d{1,2}/\d{2,4})'
        match = re.search(padrao, mensagem)
        
        if match:
            origem = match.group(1).strip()
            destino = match.group(2).strip()
            pessoas = int(match.group(3))
            data_reserva = match.group(4)
            
            # Processar reserva (similar ao código anterior)
            resposta["mensagem"] = f"✅ Reserva confirmada! Detalhes:\n- Origem: {origem}\n- Destino: {destino}\n- Data: {data_reserva}"
            resposta["novo_estado"] = "INICIO"
        else:
            resposta["mensagem"] = (
                "❌ Formato incorreto! Por favor use:\n"
                "RESERVA [origem] para [destino] - [pessoas] pessoas - [data]\n\n"
                "*Exemplos:*\n"
                "RESERVA Aeroporto GRU para Hotel Campinas - 4 pessoas - 25/07/2025\n"
                "reserva São Paulo para Rio - 2 pessoas - 30/07/2025"
            )
    
    return resposta

# ... (rotas de teste, warmup, etc) ...

if __name__ == '__main__':
    init_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
