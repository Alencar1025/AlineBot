# ---------- IMPORTS OBRIGATÓRIOS ----------
from flask import Flask, request, jsonify, g
from twilio.twiml.messaging_response import MessagingResponse
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

# Autenticação Twilio
twilio_account_sid = os.environ.get('TWILIO_ACCOUNT_SID')
twilio_auth_token = os.environ.get('TWILIO_AUTH_TOKEN')

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
    "suporte": ["suporte", "atendente", "humano", "operador"],
    "continuar": ["continuar", "seguir", "voltar", "retomar"]
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

# ---------- ROTA PRINCIPAL ----------
@app.route('/webhook', methods=['POST'])
def webhook():
    from_number = request.values.get('From', '')
    mensagem = request.values.get('Body', '').strip()
    logger.info(f"Mensagem recebida de {from_number}: {mensagem}")
    
    telefone = re.sub(r'\D', '', from_number)[-11:]  # Normalizar telefone
    
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
    resp = MessagingResponse()
    msg = resp.message()
    resultado = processar_mensagem(estado_atual, mensagem, telefone, primeira_vez)
    
    # Atualizar estado
    novo_estado = resultado.get("novo_estado", estado_atual)
    cursor.execute(
        "UPDATE user_states SET state = ?, last_interaction = ?, primeira_vez = ? WHERE phone = ?",
        (novo_estado, datetime.now().isoformat(), False, telefone)
    )
    db.commit()
    
    msg.body(resultado["mensagem"])
    return str(resp)

def processar_mensagem(estado_atual, mensagem, telefone, primeira_vez):
    periodo = obter_periodo_dia()
    intencao = detectar_intencao(mensagem)
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
        
        elif intencao == "pagar":
            resposta["mensagem"] = "💳 Link para pagamento: https://jcmviagens.com/pagar\n\nEnvie o número da reserva para pagamento específico"
            resposta["novo_estado"] = "AGUARDANDO_PAGAMENTO"
        
        elif intencao == "status":
            resposta["mensagem"] = "🔍 Digite o número completo da reserva (ex: RES_123456) para verificar o status:"
            resposta["novo_estado"] = "AGUARDANDO_NUMERO_RESERVA"
        
        elif intencao == "cancelar":
            resposta["mensagem"] = "❌ Digite o número completo da reserva que deseja cancelar (ex: RES_123456):"
            resposta["novo_estado"] = "AGUARDANDO_CANCELAMENTO"
        
        elif intencao == "suporte":
            resposta["mensagem"] = "⏳ Redirecionando para atendente humano..."
            resposta["novo_estado"] = "SUPORTE_ATIVO"
        
        else:
            resposta["mensagem"] = "⚠️ Opção não reconhecida. Digite *AJUDA* para ver opções"
    
    elif estado_atual == "AGUARDANDO_RESERVA":
        # Regex robusto que aceita variações
        padrao = r'(?i)(?:reserva|reservar)\s+(.+?)\s+(?:para|pra|->)\s+(.+?)\s+[-\—]\s+(\d+)\s+(?:pessoas?|pess?|pax)\s+[-\—]\s+(\d{1,2}/\d{1,2}/\d{2,4})'
        match = re.search(padrao, mensagem)
        
        if match:
            origem = match.group(1).strip()
            destino = match.group(2).strip()
            pessoas = int(match.group(3))
            data_reserva = match.group(4)
            
            # Determinar veículo e valor
            if pessoas <= 4:
                veiculo = "Sedan"
                valor = 600.00
            elif pessoas <= 7:
                veiculo = "SUV"
                valor = 750.00
            else:
                veiculo = "Van"
                valor = 900.00
            
            id_reserva = f"RES_{int(time.time())}"
            
            # Salvar na planilha
            gc = conectar_google_sheets()
            if gc:
                try:
                    planilha_reservas = gc.open("Reservas_JCM").sheet1
                    reserva_data = [
                        id_reserva, telefone, data_reserva, "08:00", 
                        "LOC_005", "LOC_001", veiculo, "MOT_001", 
                        "Confirmado", valor
                    ]
                    planilha_reservas.append_row(reserva_data)
                    
                    # Registrar pagamento
                    planilha_pagamentos = gc.open("Pagamentos_Motoristas_JCM").sheet1
                    pagamento_data = [
                        id_reserva, "Alencar", valor * 0.8, 0.00,
                        valor * 0.2, "Producao", "Pendente"
                    ]
                    planilha_pagamentos.append_row(pagamento_data)
                    
                    resposta["mensagem"] = (
                        f"✅ Reserva {id_reserva} confirmada!\n\n" 
                        f"*Detalhes:*\n"
                        f"- Origem: {origem}\n"
                        f"- Destino: {destino}\n"
                        f"- Data: {data_reserva}\n"
                        f"- Veículo: {veiculo}\n"
                        f"- Valor: R$ {valor:.2f}\n\n"
                        f"Pagamento motorista registrado ✅"
                    )
                except Exception as e:
                    logger.error(f"Erro ao salvar reserva: {str(e)}")
                    resposta["mensagem"] = "❌ Erro interno ao processar reserva. Tente novamente mais tarde."
            else:
                resposta["mensagem"] = "❌ Erro na conexão com o Google Sheets. Tente novamente mais tarde."
            
            resposta["novo_estado"] = "INICIO"
        else:
            resposta["mensagem"] = (
                "❌ Formato incorreto! Por favor use:\n"
                "RESERVA [origem] para [destino] - [pessoas] pessoas - [data]\n\n"
                "*Exemplos:*\n"
                "RESERVA Aeroporto GRU para Hotel Campinas - 4 pessoas - 25/07/2025\n"
                "reserva São Paulo para Rio - 2 pessoas - 30/07/2025"
            )
    
    elif estado_atual == "AGUARDANDO_NUMERO_RESERVA":
        try:
            # Normalizar o ID da reserva
            reserva_id = mensagem.strip().upper()
            if not reserva_id.startswith("RES_"):
                reserva_id = "RES_" + reserva_id
            
            gc = conectar_google_sheets()
            if gc:
                planilha = gc.open("Reservas_JCM").sheet1
                dados = planilha.get_all_records()
                
                reserva = None
                for linha in dados:
                    if str(linha["ID_Reserva"]).strip() == reserva_id:
                        reserva = linha
                        break
                
                if reserva:
                    # Buscar motorista
                    planilha_motoristas = gc.open("Motoristas_JCM").sheet1
                    motoristas = planilha_motoristas.get_all_records()
                    motorista = next((m for m in motoristas if m["ID_Contato"] == reserva["ID_Motorista"]), None)
                    
                    # Buscar locais
                    planilha_locais = gc.open("Locais_Especificos_JCM").sheet1
                    locais = planilha_locais.get_all_records()
                    origem = next((l for l in locais if l["ID_Local"] == reserva["ID_Local_Origem"]), None)
                    destino = next((l for l in locais if l["ID_Local"] == reserva["ID_Local_Destino"]), None)
                    
                    resposta["mensagem"] = (
                        f"✅ Reserva *{reserva_id}*\n"
                        f"Status: {reserva['Status']}\n"
                        f"Data: {reserva['Data']}\n"
                        f"Origem: {origem['Nome'] if origem else 'Desconhecido'}\n"
                        f"Destino: {destino['Nome'] if destino else 'Desconhecido'}\n"
                        f"Veículo: {reserva['Categoria_Veiculo']}\n"
                        f"Motorista: {motorista['Nome'] if motorista else 'Não atribuído'}\n"
                        f"Valor: R$ {reserva['Valor']:.2f}"
                    )
                else:
                    resposta["mensagem"] = f"❌ Reserva {reserva_id} não encontrada. Verifique o número."
            else:
                resposta["mensagem"] = "❌ Falha na conexão com Google Sheets"
        except Exception as e:
            resposta["mensagem"] = f"❌ Erro ao buscar reserva: {str(e)}"
        
        resposta["novo_estado"] = "INICIO"
    
    elif estado_atual == "AGUARDANDO_CANCELAMENTO":
        # Normalizar o ID da reserva
        reserva_id = mensagem.strip().upper()
        if not reserva_id.startswith("RES_"):
            reserva_id = "RES_" + reserva_id
        
        if len(reserva_id) > 4:
            resposta["mensagem"] = f"✅ Reserva #{reserva_id} cancelada com sucesso!\nValor será estornado em até 5 dias úteis."
        else:
            resposta["mensagem"] = "❌ Número inválido. Digite o ID completo da reserva (ex: RES_123456)"
        
        resposta["novo_estado"] = "INICIO"
    
    elif estado_atual == "AGUARDANDO_PAGAMENTO":
        # Normalizar o ID da reserva
        reserva_id = mensagem.strip().upper()
        if not reserva_id.startswith("RES_"):
            reserva_id = "RES_" + reserva_id
        
        if len(reserva_id) > 4:
            resposta["mensagem"] = f"💳 Pagamento para reserva #{reserva_id}:\n🔗 Link: https://jcmviagens.com/pagar?id={reserva_id}\n\nValidade: 24 horas"
        else:
            resposta["mensagem"] = "⚠️ Digite o número completo da reserva para pagamento (ex: RES_123456)"
        
        resposta["novo_estado"] = "INICIO"
    
    elif estado_atual == "SUPORTE_ATIVO":
        resposta["mensagem"] = "⌛ Um atendente humano já foi notificado e entrará em contato em breve!"
        resposta["novo_estado"] = "INICIO"
    
    else:
        resposta["mensagem"] = "🔄 Reiniciando conversa... Digite *OI* para começar"
        resposta["novo_estado"] = "INICIO"
    
    return resposta

# ========== ROTA DE TESTE DE PLANILHAS ==========
@app.route('/teste-sheets')
def teste_sheets():
    try:
        gc = conectar_google_sheets()
        if gc:
            planilha = gc.open("Reservas_JCM").sheet1
            primeira_linha = planilha.row_values(1)
            return f"Conexão OK! Cabeçalhos: {primeira_linha}"
        else:
            return "❌ Falha na conexão com Google Sheets"
    except Exception as e:
        return f"ERRO: {str(e)}"

# ========== ROTA DE DIAGNÓSTICO ==========
@app.route('/system-status')
def system_status():
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT COUNT(*) FROM user_states")
    user_count = cursor.fetchone()[0]
    
    return jsonify({
        "status": "operacional",
        "users": user_count,
        "twilio_configured": bool(twilio_account_sid and twilio_auth_token),
        "google_configured": bool(GOOGLE_CREDS)
    })

# ========== WARMUP ==========
@app.route('/warmup')
def warmup():
    return "Instance warmed up!", 200

# ========== HEALTH CHECK ==========
@app.route('/healthz')
def health_check():
    return "✅ AlineBot Online", 200

# ---------- INICIAR SERVIDOR ----------
if __name__ == '__main__':
    init_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
