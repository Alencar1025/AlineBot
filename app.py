import os
import logging
import re
import json
from datetime import datetime
from flask import Flask, request, jsonify
from twilio.rest import Client
from twilio.twiml.messaging_response import MessagingResponse
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

app = Flask(__name__)

# Configuração de logs
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configurações do Twilio
TWILIO_ACCOUNT_SID = os.environ.get('TWILIO_ACCOUNT_SID')
TWILIO_AUTH_TOKEN = os.environ.get('TWILIO_AUTH_TOKEN')
TWILIO_PHONE_NUMBER = os.environ.get('TWILIO_PHONE_NUMBER')
client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

# Configuração do Google Sheets
SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive'
]
SERVICE_ACCOUNT_FILE = json.loads(os.environ.get('GOOGLE_CREDS_JSON'))
PASTA_RAIZ_ID = os.environ.get('PASTA_RAIZ_ID')  # ID da pasta JCM_OPERACIONAL

# Estado da conversa por usuário
estado_usuario = {}
contexto_reserva = {}
primeira_interacao = {}

# Mapeamento global de planilhas
PLANILHAS = {
    'clientes': None,
    'motoristas': None,
    'reservas': None,
    'pagamentos': None
}

# ========== SISTEMA DE INTENÇÕES ATUALIZADO ==========
INTENTOES = {
    "saudacao": ["oi", "olá", "ola", "bom dia", "boa tarde", "boa noite", "aline", "alô", "oi!", "ola!", "olá!", "ei", "e aí", "hello", "hi"],
    "ajuda": ["ajuda", "socorro", "opções", "comandos", "menu", "help", "ajude", "socorro!", "sos"],
    "reserva": ["reserva", "reservar", "agendar", "viagem", "passagem", "voo", "roteiro", "pacote", "agendamento"],
    "pagar": ["pagar", "pagamento", "pague", "comprar", "pagto", "débito", "crédito", "boleto", "comprar"],
    "status": ["status", "situação", "verificar", "consulta", "onde está", "localizar", "acompanhar", "situacao"],
    "cancelar": ["cancelar", "desmarcar", "anular", "remover", "desistir", "estornar", "cancelamento"],
    "suporte": ["suporte", "atendente", "humano", "pessoa", "falar com alguém", "operador", "atendimento"],
    "continuar": ["continuar", "seguir", "voltar", "retomar", "prosseguir", "voltei"]
}

# ========== FUNÇÃO DETECTAR INTENÇÃO CORRIGIDA ==========
def detectar_intencao(mensagem):
    mensagem = mensagem.lower().strip()
    
    # 1. Verificar saudações compostas
    for saudacao_composta in ["bom dia", "boa tarde", "boa noite"]:
        if saudacao_composta in mensagem:
            return "saudacao"
    
    # 2. Verificar palavras isoladas críticas
    if mensagem in ["oi", "ola", "olá", "oi!", "ola!", "olá!"]:
        return "saudacao"
    if mensagem in ["ajuda", "help", "ajude", "socorro"]:
        return "ajuda"
    
    # 3. Verificar por palavras-chave
    palavras = mensagem.split()
    for palavra in palavras:
        for intencao, palavras_chave in INTENTOES.items():
            if palavra in palavras_chave:
                return intencao
                
    return None

# ========== CONEXÃO COM GOOGLE SHEETS ==========
def conectar_google_sheets():
    try:
        creds = service_account.Credentials.from_service_account_info(
            SERVICE_ACCOUNT_FILE, 
            scopes=SCOPES
        )
        return creds
    except Exception as e:
        logger.error(f"Erro na conexão com Google Sheets: {str(e)}")
        return None

# ========== MAPEAR PLANILHAS ==========
def mapear_planilhas():
    global PLANILHAS
    
    creds = conectar_google_sheets()
    if not creds:
        return False
    
    try:
        drive_service = build('drive', 'v3', credentials=creds)
        
        # Mapear subpastas - versão resiliente a maiúsculas/minúsculas
        pastas = {
            'base': ['1_Dados_Base', '1_dados_base', '1_Dados_base'],  # Variações de nome
            'transacoes': ['2_Transacoes', '2_transacoes'],
            'financeiro': ['3_Financeiro', '3_financeiro']
        }
        
        # Obter ID da pasta raiz
        if not PASTA_RAIZ_ID:
            logger.critical("Variável PASTA_RAIZ_ID não configurada!")
            return False
        
        # Encontrar subpastas
        subpasta_ids = {}
        for tipo, nomes in pastas.items():
            encontrou = False
            for nome in nomes:
                query = f"name='{nome}' and '{PASTA_RAIZ_ID}' in parents and mimeType='application/vnd.google-apps.folder'"
                results = drive_service.files().list(q=query, fields="files(id)").execute()
                if results.get('files'):
                    subpasta_ids[tipo] = results['files'][0]['id']
                    logger.info(f"Subpasta encontrada: {nome} -> ID: {subpasta_ids[tipo]}")
                    encontrou = True
                    break
            if not encontrou:
                logger.error(f"Nenhuma subpasta encontrada para {tipo} com nomes: {nomes}")
        
        # Mapear planilhas em cada subpasta
        if subpasta_ids.get('base'):
            query = f"'{subpasta_ids['base']}' in parents and mimeType='application/vnd.google-apps.spreadsheet'"
            results = drive_service.files().list(q=query, fields="files(id, name)").execute()
            for file in results.get('files', []):
                if 'Clientes_Especiais_JCM' in file['name']:
                    PLANILHAS['clientes'] = file['id']
                elif 'Motoristas_JCM' in file['name']:
                    PLANILHAS['motoristas'] = file['id']
        
        if subpasta_ids.get('transacoes'):
            query = f"'{subpasta_ids['transacoes']}' in parents and mimeType='application/vnd.google-apps.spreadsheet'"
            results = drive_service.files().list(q=query, fields="files(id, name)").execute()
            for file in results.get('files', []):
                if 'Reservas_JCM' in file['name']:
                    PLANILHAS['reservas'] = file['id']
        
        if subpasta_ids.get('financeiro'):
            query = f"'{subpasta_ids['financeiro']}' in parents and mimeType='application/vnd.google-apps.spreadsheet'"
            results = drive_service.files().list(q=query, fields="files(id, name)").execute()
            for file in results.get('files', []):
                if 'Pagamentos_Motoristas_JCM' in file['name']:
                    PLANILHAS['pagamentos'] = file['id']
        
        logger.info(f"Planilhas mapeadas: {PLANILHAS}")
        return True
        
    except HttpError as e:
        logger.error(f"Erro do Google Drive: {str(e)}")
        return False
    except Exception as e:
        logger.error(f"Erro geral no mapeamento: {str(e)}")
        return False

# ========== FUNÇÕES AUXILIARES ==========
def extrair_dados_reserva(mensagem):
    padroes = [
        r'RESERVA (.+) para (.+) - (\d+) pessoas - (.+)',
        r'RESERVA (.+) para (.+) - (\d+)p - (.+)',
        r'RESERVA (.+) para (.+) (\d+)p (.+)'
    ]
    
    for padrao in padroes:
        match = re.search(padrao, mensagem, re.IGNORECASE)
        if match:
            return {
                'origem': match.group(1).strip(),
                'destino': match.group(2).strip(),
                'pessoas': int(match.group(3)),
                'data': match.group(4).strip()
            }
    return None

def formatar_resposta(reserva):
    return (
        f"🚕 *Reserva Confirmada!* 🚕\n\n"
        f"• Origem: {reserva['origem']}\n"
        f"• Destino: {reserva['destino']}\n"
        f"• Passageiros: {reserva['pessoas']}\n"
        f"• Data/Hora: {reserva['data']}\n"
        f"• Motorista: {reserva['motorista']}\n"
        f"• Valor: R${reserva['valor']:.2f}\n\n"
        f"ID da Reserva: *{reserva['id']}*\n\n"
        "Use `PAGAR {ID}` para gerar o link de pagamento."
    )

# ========== ROTAS PRINCIPAIS ==========
@app.route("/")
def home():
    return "AlineBot JCM Operacional - v3.2 (11/07/2025)"

@app.route("/teste-sheets")
def teste_sheets():
    if not PLANILHAS['reservas']:
        return "❌ Planilha de reservas não mapeada", 500
    
    try:
        creds = conectar_google_sheets()
        service = build('sheets', 'v4', credentials=creds)
        result = service.spreadsheets().values().get(
            spreadsheetId=PLANILHAS['reservas'],
            range="A1:A1"
        ).execute()
        return "✅ Conexão com Google Sheets bem-sucedida!"
    except Exception as e:
        return f"❌ Erro ao acessar planilha: {str(e)}", 500

@app.route("/debug-creds")
def debug_creds():
    if not SERVICE_ACCOUNT_FILE:
        return "❌ Credenciais não encontradas", 500
    
    debug_info = {
        "client_email": SERVICE_ACCOUNT_FILE.get('client_email', 'Não encontrado'),
        "private_key_length": len(SERVICE_ACCOUNT_FILE.get('private_key', ''))
    }
    return jsonify(debug_info)

@app.route("/map-sheets")
def map_sheets():
    return jsonify({
        "status": "success",
        "planilhas": PLANILHAS,
        "pasta_raiz": PASTA_RAIZ_ID
    })

@app.route("/debug-folders")
def debug_folders():
    try:
        creds = conectar_google_sheets()
        drive_service = build('drive', 'v3', credentials=creds)
        
        # Listar todas pastas na raiz
        query = f"'{PASTA_RAIZ_ID}' in parents and mimeType='application/vnd.google-apps.folder'"
        results = drive_service.files().list(q=query, fields="files(id, name)").execute()
        
        return jsonify({
            "status": "success",
            "folders": results.get('files', [])
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/webhook", methods=['POST'])
def webhook():
    telefone = request.form.get('From', '')
    mensagem = request.form.get('Body', '').strip()
    
    # Log detalhado
    logger.info(f"\n\n{'='*40} NOVA MENSAGEM {'='*40}")
    logger.info(f"📞 Origem: {telefone}")
    logger.info(f"💬 Conteúdo: '{mensagem}'")
    
    # Estado da conversa
    estado_atual = estado_usuario.get(telefone, "INICIO")
    primeira_vez = telefone not in estado_usuario
    logger.info(f"🔍 Estado Atual: {estado_atual}")
    logger.info(f"🎯 Primeira Vez: {primeira_vez}")
    
    # Detecção de intenção
    intencao = detectar_intencao(mensagem)
    logger.info(f"🧠 Intenção Detectada: {intencao}")
    
    # Gerenciamento de estado
    if primeira_vez:
        estado_usuario[telefone] = "INICIO"
        contexto_reserva[telefone] = {}
        primeira_interacao[telefone] = True
    
    # Processamento central
    resp = MessagingResponse()
    msg = resp.message()
    
    # Fluxo de conversação
    if estado_atual == "INICIO":
        if intencao == "saudacao" or primeira_vez:
            msg.body(
                "👋 Olá! Eu sou a Aline, assistente virtual da JCM Transportes.\n\n"
                "Posso ajudar com:\n"
                "• Reservas de transporte\n"
                "• Pagamentos\n"
                "• Consulta de status\n\n"
                "Digite *AJUDA* a qualquer momento para ver os comandos."
            )
            estado_usuario[telefone] = "AGUARDANDO_ACAO"
        
        elif intencao == "reserva":
            msg.body("Por favor, envie sua reserva no formato:\n\n"
                     "*RESERVA [Origem] para [Destino] - [Nº Pessoas] pessoas - [Data/Hora]*\n\n"
                     "Exemplo:\n"
                     "RESERVA Av. Paulista para Aeroporto GRU - 3 pessoas - 15/07 14:00")
            estado_usuario[telefone] = "AGUARDANDO_RESERVA"
    
    elif estado_atual == "AGUARDANDO_ACAO":
        if intencao == "reserva":
            msg.body("Por favor, envie sua reserva no formato:\n\n"
                     "*RESERVA [Origem] para [Destino] - [Nº Pessoas] pessoas - [Data/Hora]*\n\n"
                     "Exemplo:\n"
                     "RESERVA Av. Paulista para Aeroporto GRU - 3 pessoas - 15/07 14:00")
            estado_usuario[telefone] = "AGUARDANDO_RESERVA"
            
        elif intencao == "ajuda":
            msg.body(
                "📋 *COMANDOS DISPONÍVEIS*\n\n"
                "• *RESERVA*: Iniciar nova reserva\n"
                "• *PAGAR [ID]*: Gerar link pagamento\n"
                "• *STATUS [ID]*: Verificar reserva\n"
                "• *CANCELAR [ID]*: Cancelar reserva\n"
                "• *SUPORTE*: Falar com atendente\n\n"
                "Exemplos:\n"
                "RESERVA Av. Paulista para Morumbi - 4 pessoas - 12/07 09:00\n"
                "PAGAR RES_12345\n"
                "STATUS RES_12345"
            )
            
        elif intencao == "status":
            msg.body("Por favor, informe o ID da reserva no formato:\n\n*STATUS [ID_RESERVA]*\n\nExemplo: STATUS RES_12345")
            
        else:
            msg.body("Desculpe, não entendi. Digite *AJUDA* para ver as opções disponíveis.")
    
    elif estado_atual == "AGUARDANDO_RESERVA":
        dados = extrair_dados_reserva(mensagem)
        if dados:
            # Simulação de processamento
            reserva_id = f"RES_{datetime.now().strftime('%H%M%S')}"
            dados['id'] = reserva_id
            dados['motorista'] = "Alencar" if dados['origem'] == 'Ambev' else "Carlos"
            dados['valor'] = 55.00 * dados['pessoas']
            
            # Salvar no contexto
            contexto_reserva[telefone] = dados
            
            # Resposta formatada
            msg.body(formatar_resposta(dados))
            estado_usuario[telefone] = "AGUARDANDO_ACAO"
        else:
            msg.body("Formato inválido. Por favor, use:\n\n*RESERVA [Origem] para [Destino] - [Nº Pessoas] pessoas - [Data/Hora]*\n\nExemplo: RESERMA Shopping Morumbi para Aeroporto CGH - 2 pessoas - 18/07 16:30")
    
    # Envio da resposta via Twilio
    try:
        twilio_response = client.messages.create(
            body=str(msg),
            from_=f"whatsapp:{TWILIO_PHONE_NUMBER}",
            to=f"whatsapp:{telefone}"
        )
        logger.info(f"✅ Mensagem enviada - SID: {twilio_response.sid}")
    except Exception as e:
        logger.error(f"❌ Erro Twilio: {str(e)}")
    
    return str(resp)

# Inicialização do sistema
if __name__ == "__main__":
    # Mapear planilhas ao iniciar o app
    if mapear_planilhas():
        logger.info("✅ Sistema inicializado com sucesso!")
    else:
        logger.error("❌ Falha ao mapear planilhas")
    
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
