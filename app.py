import os
import re
import json
import logging
import random
from datetime import datetime, timedelta
from flask import Flask, request
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
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
SERVICE_ACCOUNT_FILE = json.loads(os.environ.get('GOOGLE_CREDS_JSON'))
SPREADSHEET_ID = os.environ.get('SPREADSHEET_ID')

# Estado da conversa por usuário
estado_usuario = {}
contexto_reserva = {}
dados_clientes = {}
primeira_interacao = {}

# ========== CONSTANTES ATUALIZADAS ==========
TIPOS_VEICULOS = [
    "Sedan Executivo", "SUV Executivo", "Mini Van 7L", "Mini Van 7L Luxo",
    "Blindado Sedan", "Blindado SUV", "Blindado Mini Van 7L", 
    "Van 15L", "Van 15L Blindado", "Microônibus 25L", "Ônibus 46L"
]

# ========== SISTEMA DE PRECIFICAÇÃO ==========
def buscar_preco_corporativo(empresa, origem, destino, veiculo):
    """Busca preço na tabela corporativa específica"""
    try:
        creds = service_account.Credentials.from_service_account_info(
            SERVICE_ACCOUNT_FILE, scopes=SCOPES
        )
        service = build('sheets', 'v4', credentials=creds)
        
        # Buscar na planilha de tabelas corporativas
        range_name = "Tabelas_Corporativas_JCM!A:G"
        result = service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=range_name
        ).execute()
        
        rows = result.get('values', [])
        for row in rows[1:]:  # Pular cabeçalho
            if (row[0] == empresa and 
                (row[1] == origem or row[1] == "Qualquer hotel na cidade de São Paulo") and 
                (row[2] == destino or row[2] == "Qualquer local") and 
                row[3] == veiculo):
                return float(row[4].replace('R$', '').replace('.', '').replace(',', '.').strip())
        
        return None
    except Exception as e:
        logger.error(f"Erro ao buscar preço corporativo: {str(e)}")
        return None

def buscar_preco_geral(origem, destino, veiculo):
    """Busca preço na tabela geral de preços"""
    try:
        creds = service_account.Credentials.from_service_account_info(
            SERVICE_ACCOUNT_FILE, scopes=SCOPES
        )
        service = build('sheets', 'v4', credentials=creds)
        
        # Buscar na planilha geral
        range_name = "Tabela_Precos_Geral_JCM!A:S"
        result = service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=range_name
        ).execute()
        
        rows = result.get('values', [])
        header = rows[0] if rows else []
        
        # Encontrar índice do veículo
        try:
            col_index = header.index(veiculo)
        except ValueError:
            return None
            
        for row in rows[1:]:
            if row[0] == origem and row[1] == destino and len(row) > col_index:
                return float(row[col_index].replace('R$', '').replace('.', '').replace(',', '.').strip())
        
        return None
    except Exception as e:
        logger.error(f"Erro ao buscar preço geral: {str(e)}")
        return None

def calcular_preco(telefone, origem, destino, veiculo):
    """Calcula preço com base no tipo de cliente"""
    cliente = dados_clientes.get(telefone, {})
    
    # Verificar se é cliente corporativo
    if cliente.get('tipo') == 'Corporativo':
        empresa = cliente.get('empresa', '')
        preco = buscar_preco_corporativo(empresa, origem, destino, veiculo)
        if preco is not None:
            return preco
    
    # Buscar na tabela geral
    preco = buscar_preco_geral(origem, destino, veiculo)
    if preco is not None:
        return preco
    
    # Valor padrão se não encontrar
    return 300.00

# ========== IDENTIFICAÇÃO DE CLIENTES ==========
def identificar_cliente(telefone):
    """Identifica cliente e carrega seus dados"""
    try:
        if telefone in dados_clientes:
            return dados_clientes[telefone]
            
        creds = service_account.Credentials.from_service_account_info(
            SERVICE_ACCOUNT_FILE, scopes=SCOPES
        )
        service = build('sheets', 'v4', credentials=creds)
        
        # Buscar na planilha de clientes
        range_name = "Clientes_Especiais_JCM!A:K"
        result = service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=range_name
        ).execute()
        
        rows = result.get('values', [])
        for row in rows[1:]:  # Pular cabeçalho
            telefones = row[2].split(';') if len(row) > 2 else []
            if telefone in telefones:
                cliente = {
                    'tipo': row[0],
                    'empresa': row[1],
                    'telefones': telefones,
                    'email': row[3] if len(row) > 3 else '',
                    'cnpj': row[4] if len(row) > 4 else '',
                    'rotas': row[5].split(';') if len(row) > 5 else [],
                    'tabela': row[6] if len(row) > 6 else '',
                    'idioma': row[7] if len(row) > 7 else 'PT',
                    'locais': row[8].split(';') if len(row) > 8 else [],
                    'pagamento_antecipado': row[9] if len(row) > 9 else 'Não'
                }
                dados_clientes[telefone] = cliente
                return cliente
        
        # Se não encontrou, é cliente avulso
        cliente = {'tipo': 'Avulso', 'pagamento_antecipado': 'Sim'}
        dados_clientes[telefone] = cliente
        return cliente
        
    except Exception as e:
        logger.error(f"Erro ao identificar cliente: {str(e)}")
        return {'tipo': 'Avulso', 'pagamento_antecipado': 'Sim'}

# ========== FUNÇÕES ATUALIZADAS ==========
def extrair_dados_reserva(mensagem):
    """Extrai dados da reserva com novos padrões"""
    mensagem = mensagem.lower()
    
    # Padrão 1: RESERVA [origem] para [destino] - [pessoas]pax [veículo]
    match = re.search(r'reserva (.+) para (.+) - (\d+)pax (.+)', mensagem)
    if match:
        return {
            'origem': match.group(1).strip(),
            'destino': match.group(2).strip(),
            'pessoas': int(match.group(3)),
            'veiculo': match.group(4).strip()
        }
    
    # Padrão 2: RESERVA [origem]-[destino] - [pessoas] pessoas [veículo]
    match = re.search(r'reserva (.+)-(.+) - (\d+) pessoas (.+)', mensagem)
    if match:
        return {
            'origem': match.group(1).strip(),
            'destino': match.group(2).strip(),
            'pessoas': int(match.group(3)),
            'veiculo': match.group(4).strip()
        }
    
    # Padrão 3: DIARIA [horário] - [pessoas]pax [veículo] - [requisitos]
    match = re.search(r'diaria (\d+:\d+)-(\d+:\d+) - (\d+)pax (.+) - (.+)', mensagem)
    if match:
        return {
            'tipo': 'diaria',
            'inicio': match.group(1).strip(),
            'fim': match.group(2).strip(),
            'pessoas': int(match.group(3)),
            'veiculo': match.group(4).strip(),
            'requisitos': match.group(5).strip()
        }
    
    return None

def formatar_resposta(reserva, telefone):
    """Formata resposta com base no tipo de cliente"""
    cliente = identificar_cliente(telefone)
    
    if cliente['tipo'] == 'Corporativo':
        return (
            f"✅ *RESERVA CORPORATIVA CONFIRMADA!*\n\n"
            f"• Origem: {reserva['origem']}\n"
            f"• Destino: {reserva['destino']}\n"
            f"• Veículo: {reserva['veiculo']}\n"
            f"• Passageiros: {reserva['pessoas']}\n"
            f"• Valor: R${reserva['valor']:.2f}\n"
            f"• Tipo: Faturamento Mensal\n"
            f"• ID: {reserva['id']}\n\n"
            f"_Detalhes serão incluídos na fatura {datetime.now().strftime('%m/%Y')}_"
        )
    else:
        entrada = reserva['valor'] * 0.5
        return (
            f"✅ *RESERVA CONFIRMADA!*\n\n"
            f"• Origem: {reserva['origem']}\n"
            f"• Destino: {reserva['destino']}\n"
            f"• Veículo: {reserva['veiculo']}\n"
            f"• Passageiros: {reserva['pessoas']}\n"
            f"• Valor Total: R${reserva['valor']:.2f}\n"
            f"• Entrada (50%): R${entrada:.2f}\n"
            f"• ID: {reserva['id']}\n\n"
            f"⚠️ *PAGAMENTO OBRIGATÓRIO:*\n"
            f"Use o comando: PAGAR {reserva['id']}\n"
            f"_Sua reserva será confirmada após o pagamento_"
        )

def gerar_link_pagamento(reserva_id, valor):
    """Gera link de pagamento simulado"""
    return f"https://jcm-pagamentos.com/pagar/{reserva_id}?valor={valor}"

# ========== ROTAS PRINCIPAIS ATUALIZADAS ==========
@app.route("/")
def home():
    return "AlineBot JCM - Sistema de Reservas Corporativas v4.0"

@app.route("/webhook", methods=['POST'])
def webhook():
    telefone = request.form.get('From', '')
    mensagem = request.form.get('Body', '').strip()
    
    # Log detalhado
    logger.info(f"\n{'='*40} NOVA MENSAGEM {'='*40}")
    logger.info(f"📞 Origem: {telefone}")
    logger.info(f"💬 Conteúdo: '{mensagem}'")
    
    # Identificar cliente
    cliente = identificar_cliente(telefone)
    logger.info(f"👤 Cliente: {cliente['tipo']} - {cliente.get('empresa', '')}")
    
    # Estado da conversa
    estado_atual = estado_usuario.get(telefone, "INICIO")
    logger.info(f"🔍 Estado Atual: {estado_atual}")
    
    # Gerenciamento de estado
    if telefone not in estado_usuario:
        estado_usuario[telefone] = "INICIO"
        contexto_reserva[telefone] = {}
        primeira_interacao[telefone] = True
    
    # Processamento central
    resp = MessagingResponse()
    msg = resp.message()
    
    # Comandos especiais
    if mensagem.lower().startswith("pagar ") and estado_atual != "AGUARDANDO_RESERVA":
        reserva_id = mensagem[6:].strip()
        if reserva_id in contexto_reserva.get(telefone, {}):
            entrada = contexto_reserva[telefone][reserva_id]['valor'] * 0.5
            link = gerer_link_pagamento(reserva_id, entrada)
            msg.body(
                f"🔗 *LINK DE PAGAMENTO* 🔗\n\n"
                f"ID Reserva: {reserva_id}\n"
                f"Valor: R${entrada:.2f}\n\n"
                f"Acesse: {link}\n\n"
                "Após o pagamento, sua reserva será confirmada automaticamente."
            )
        else:
            msg.body("❌ Reserva não encontrada. Verifique o ID e tente novamente.")
        return str(resp)
    
    # Fluxo de conversação
    if estado_atual == "INICIO":
        if cliente['tipo'] == 'Corporativo':
            msg.body(
                f"👋 Olá! Eu sou a Aline da JCM Transportes.\n\n"
                f"Bem-vindo(a) da *{cliente['empresa']}*!\n"
                "Como posso ajudar com sua reserva corporativa hoje?"
            )
        else:
            msg.body(
                "👋 Olá! Eu sou a Aline da JCM Transportes.\n\n"
                "Para começar, preciso fazer seu cadastro rápido:\n"
                "1. Qual seu nome completo?\n"
                "2. Qual empresa você representa? (Digite 'Particular' se for caso)"
            )
            estado_usuario[telefone] = "CADASTRO_NOME"
    
    elif estado_atual == "CADASTRO_NOME":
        contexto_reserva[telefone]['nome'] = mensagem
        msg.body(
            f"Ótimo, {mensagem}! Agora preciso saber:\n"
            "Qual empresa você representa?\n"
            "(Digite 'Particular' se for caso)"
        )
        estado_usuario[telefone] = "CADASTRO_EMPRESA"
    
    elif estado_atual == "CADASTRO_EMPRESA":
        contexto_reserva[telefone]['empresa'] = mensagem
        msg.body(
            "Cadastro completo! ✅\n\n"
            "Agora você pode fazer reservas. Envie:\n\n"
            "RESERVA [Origem] para [Destino] - [Nº]pax [Veículo]\n\n"
            "Exemplo:\n"
            "RESERVA Aeroporto GRU para Hotel Tivoli - 3pax SUV Executivo"
        )
        estado_usuario[telefone] = "AGUARDANDO_ACAO"
        dados_clientes[telefone] = {
            'tipo': 'Corporativo' if mensagem != 'Particular' else 'Avulso',
            'empresa': mensagem
        }
    
    elif estado_atual == "AGUARDANDO_ACAO":
        if "reserva" in mensagem.lower():
            dados = extrair_dados_reserva(mensagem)
            if dados:
                # Calcular preço
                valor = calcular_preco(telefone, dados['origem'], dados['destino'], dados['veiculo'])
                
                # Gerar ID de reserva
                reserva_id = f"RES_{datetime.now().strftime('%H%M%S')}"
                
                # Armazenar reserva
                reserva = {
                    'id': reserva_id,
                    'origem': dados['origem'],
                    'destino': dados['destino'],
                    'veiculo': dados['veiculo'],
                    'pessoas': dados['pessoas'],
                    'valor': valor,
                    'hora': datetime.now().strftime("%d/%m/%Y %H:%M")
                }
                
                contexto_reserva[telefone][reserva_id] = reserva
                msg.body(formatar_resposta(reserva, telefone))
                
                # Atualizar estado
                if dados_clientes[telefone]['pagamento_antecipado'] == 'Sim':
                    estado_usuario[telefone] = "AGUARDANDO_PAGAMENTO"
                else:
                    estado_usuario[telefone] = "AGUARDANDO_ACAO"
            else:
                msg.body(
                    "❌ Formato inválido. Use:\n\n"
                    "RESERVA [Origem] para [Destino] - [Nº]pax [Veículo]\n\n"
                    "Exemplo:\n"
                    "RESERVA Aeroporto GRU para Morumbi - 2pax Sedan Executivo"
                )
        else:
            msg.body(
                "📋 *COMANDOS DISPONÍVEIS*\n\n"
                "• RESERVA [detalhes] - Fazer nova reserva\n"
                "• PAGAR [ID] - Gerar link de pagamento\n"
                "• DIARIA [detalhes] - Solicitar serviço de diária\n"
                "• SUPORTE - Falar com atendente\n\n"
                "Exemplos:\n"
                "RESERVA GRU para Campinas - 3pax Van\n"
                "PAGAR RES_12345\n"
                "DIARIA 9:00-18:00 - 4pax SUV - Inglês"
            )
    
    elif estado_atual == "AGUARDANDO_PAGAMENTO":
        if "pagar" in mensagem.lower():
            reserva_id = mensagem.split()[-1]
            if reserva_id in contexto_reserva[telefone]:
                entrada = contexto_reserva[telefone][reserva_id]['valor'] * 0.5
                link = gerer_link_pagamento(reserva_id, entrada)
                msg.body(
                    f"🔗 *LINK DE PAGAMENTO* 🔗\n\n"
                    f"ID Reserva: {reserva_id}\n"
                    f"Valor: R${entrada:.2f}\n\n"
                    f"Acesse: {link}\n\n"
                    "Após o pagamento, sua reserva será confirmada automaticamente."
                )
                estado_usuario[telefone] = "AGUARDANDO_ACAO"
            else:
                msg.body("❌ Reserva não encontrada. Verifique o ID e tente novamente.")
        else:
            msg.body(
                "⚠️ *PAGAMENTO PENDENTE!*\n\n"
                "Para confirmar sua reserva, você precisa pagar 50% de entrada.\n\n"
                "Use o comando: PAGAR [ID_RESERVA]\n\n"
                "Exemplo: PAGAR RES_12345"
            )
    
    # Envio da resposta via Twilio
    try:
        client.messages.create(
            body=str(msg),
            from_=f"whatsapp:{TWILIO_PHONE_NUMBER}",
            to=f"whatsapp:{telefone}"
        )
        logger.info(f"✅ Mensagem enviada para {telefone}")
    except Exception as e:
        logger.error(f"❌ Erro ao enviar mensagem: {str(e)}")
    
    return str(resp)

# Inicialização do sistema
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    logger.info(f"🚀 AlineBot iniciado na porta {port}")
    app.run(host="0.0.0.0", port=port)
