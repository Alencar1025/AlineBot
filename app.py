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

app = Flask(__name__)

# ================= CONFIGURAÇÃO INICIAL =================
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
ultimo_id_reserva = {}

# ================= FUNÇÕES AUXILIARES =================
def calcular_tempo_espera(reserva_id):
    """Calcula tempo restante para pagamento"""
    return "59 minutos"

def detectar_intencao(mensagem):
    """Detecção robusta de intenções com regex melhorado"""
    mensagem = mensagem.lower().strip()
    
    # 1. Detecção de pagamento com variações
    if re.search(r'pagar\s*\w+', mensagem) or re.search(r'pagamento\s*\w+', mensagem):
        return "pagar"
    
    # 2. Lista expandida de saudações
    saudações = [
        "oi", "olá", "ola", "bom dia", "boa tarde", "boa noite", 
        "aline", "alô", "oi!", "ola!", "olá!", "ei", "e aí", "hello", 
        "hi", "saudações", "saudacoes", "iniciar", "começar", "bom dia!", 
        "boa tarde!", "olá boa tarde", "oi boa tarde", "olá bom dia", "oi bom dia",
        "ola boa tarde", "ola bom dia"
    ]
    
    if mensagem in saudações:
        return "saudacao"
    
    # 3. Verificar por palavras-chave
    mapeamento = {
        "ajuda": ["ajuda", "socorro", "opções", "comandos", "menu", "help", "ajude", "socorro!", "sos", "como usar", "o que fazer"],
        "reserva": ["reserva", "reservar", "agendar", "viagem", "passagem", "voo", "roteiro", "pacote", "agendamento", "marcar", "fazer reserva"],
        "pagar": ["pagar", "pagamento", "pague", "comprar", "pagto", "débito", "crédito", "boleto", "comprar", "pix", "pagamento reserva"],
        "status": ["status", "situação", "verificar", "consulta", "onde está", "localizar", "acompanhar", "situacao", "ver meu", "consulta reserva", "estado reserva"],
        "cancelar": ["cancelar", "desmarcar", "anular", "remover", "desistir", "estornar", "cancelamento", "cancelar reserva"],
        "suporte": ["suporte", "atendente", "humano", "pessoa", "falar com alguém", "operador", "atendimento", "falar humano", "atendente humano"]
    }
    
    for palavra in mensagem.split():
        for intencao, palavras_chave in mapeamento.items():
            if palavra in palavras_chave:
                return intencao
                
    return None

def identificar_cliente(telefone):
    """Identificação simulada de cliente (implementar com Google Sheets depois)"""
    # Exemplo: Cliente corporativo conhecido
    if telefone.endswith('8430'):  # Ambev
        return {'tipo': 'Corporativo', 'empresa': 'Ambev', 'pagamento_antecipado': 'Não'}
    return {'tipo': 'Avulso', 'pagamento_antecipado': 'Sim'}

def extrair_dados_reserva(mensagem):
    """Extrai dados da reserva com padrões robustos"""
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
    
    # Padrão 3: RESERVA [origem] para [destino] - [pessoas] pessoas - [veículo]
    match = re.search(r'reserva (.+) para (.+) - (\d+) pessoas - (.+)', mensagem)
    if match:
        return {
            'origem': match.group(1).strip(),
            'destino': match.group(2).strip(),
            'pessoas': int(match.group(3)),
            'veiculo': match.group(4).strip()
        }
    
    # Padrão 4: RESERVA [origem] para [destino] - [pessoas] pessoas [veículo] (sem hífen)
    match = re.search(r'reserva (.+) para (.+) (\d+) pessoas (.+)', mensagem)
    if match:
        return {
            'origem': match.group(1).strip(),
            'destino': match.group(2).strip(),
            'pessoas': int(match.group(3)),
            'veiculo': match.group(4).strip()
        }
    
    return None

def calcular_preco_simulado(origem, destino, veiculo):
    """Cálculo de preço simulado (implementar com Google Sheets depois)"""
    return random.randint(200, 500)

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
            f"Use o comando: *PAGAR {reserva['id']}*"
        )

def gerar_link_pagamento(reserva_id, valor):
    """Gera link de pagamento simulado"""
    return f"https://jcm-pagamentos.com/pagar/{reserva_id}?valor={valor}"

# ================= ROTA PRINCIPAL =================
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
    
    # Inicializar contexto se necessário
    if telefone not in estado_usuario:
        estado_usuario[telefone] = "INICIO"
        contexto_reserva[telefone] = {}
        ultimo_id_reserva[telefone] = None
    
    # Detectar intenção
    intencao = detectar_intencao(mensagem)
    logger.info(f"🧠 Intenção Detectada: {intencao}")
    
    # Processamento central
    resp = MessagingResponse()
    msg = resp.message()
    
    # FLUXO PRINCIPAL DE PAGAMENTO (prioritário)
    if intencao == "pagar":
        # Extrair ID mesmo com variações de texto
        match = re.search(r'pagar\s+(\w+)', mensagem, re.IGNORECASE)
        if match:
            reserva_id = match.group(1).upper()
            # Verificar se reserva existe
            if telefone in contexto_reserva and reserva_id in contexto_reserva[telefone]:
                reserva = contexto_reserva[telefone][reserva_id]
                entrada = reserva['valor'] * 0.5
                link = gerar_link_pagamento(reserva_id, entrada)
                
                msg.body(
                    f"🔗 *LINK DE PAGAMENTO* 🔗\n\n"
                    f"ID Reserva: {reserva_id}\n"
                    f"Valor Entrada: R${entrada:.2f}\n\n"
                    f"Clique para pagar:\n{link}\n\n"
                    "⚠️ Reserva válida por 1 hora após pagamento"
                )
                estado_usuario[telefone] = "AGUARDANDO_ACAO"
            else:
                msg.body("❌ Reserva não encontrada. Verifique o ID e tente novamente.")
        else:
            msg.body("Por favor, informe o ID da reserva no formato:\n\n*PAGAR [ID_RESERVA]*\n\nExemplo: PAGAR RES_211326")
        
        return str(resp)
    
    # FLUXOS POR ESTADO
    if estado_atual == "INICIO":
        if intencao == "saudacao" or intencao is None:
            if cliente['tipo'] == 'Corporativo':
                msg.body(
                    f"👋 Olá! Eu sou a Aline da JCM Transportes.\n\n"
                    f"Bem-vindo(a) da *{cliente['empresa']}*!\n"
                    "Como posso ajudar com sua reserva corporativa hoje?\n\n"
                    "Digite *RESERVA* para iniciar ou *AJUDA* para ver opções."
                )
            else:
                msg.body(
                    "👋 Olá! Eu sou a Aline da JCM Transportes.\n\n"
                    "Para começar, preciso fazer seu cadastro rápido:\n"
                    "1. Qual seu nome completo?\n"
                    "2. Qual empresa você representa? (Digite 'Particular' se for caso)"
                )
                estado_usuario[telefone] = "CADASTRO_NOME"
        elif intencao == "reserva":
            msg.body(
                "Por favor, envie sua reserva no formato:\n\n"
                "*RESERVA [Origem] para [Destino] - [Nº Pessoas] pessoas - [Veículo]*\n\n"
                "Exemplo:\n"
                "RESERVA Aeroporto GRU para Hotel Tivoli - 3 pessoas - SUV Executivo"
            )
            estado_usuario[telefone] = "AGUARDANDO_RESERVA"
        else:
            msg.body(
                "👋 Olá! Eu sou a Aline da JCM Transportes.\n\n"
                "Digite *RESERVA* para iniciar uma nova reserva ou *AJUDA* para ver opções."
            )
    
    elif estado_atual == "CADASTRO_NOME":
        contexto_reserva[telefone] = {'nome': mensagem}
        msg.body(
            f"Ótimo, {mensagem}! Agora preciso saber:\n"
            "Qual empresa você representa?\n"
            "(Digite 'Particular' se for caso)"
        )
        estado_usuario[telefone] = "CADASTRO_EMPRESA"
    
    elif estado_atual == "CADASTRO_EMPRESA":
        contexto_reserva[telefone]['empresa'] = mensagem
        tipo_cliente = 'Corporativo' if mensagem.lower() != 'particular' else 'Avulso'
        dados_clientes[telefone] = {'tipo': tipo_cliente, 'empresa': mensagem}
        
        msg.body(
            "Cadastro completo! ✅\n\n"
            "Agora você pode fazer reservas. Envie:\n\n"
            "*RESERVA [Origem] para [Destino] - [Nº Pessoas] pessoas - [Veículo]*\n\n"
            "Exemplo:\n"
            "RESERVA Aeroporto GRU para Hotel Tivoli - 3 pessoas - SUV Executivo"
        )
        estado_usuario[telefone] = "AGUARDANDO_ACAO"
    
    elif estado_atual == "AGUARDANDO_ACAO":
        if intencao == "reserva":
            msg.body(
                "Por favor, envie sua reserva no formato:\n\n"
                "*RESERVA [Origem] para [Destino] - [Nº Pessoas] pessoas - [Veículo]*\n\n"
                "Exemplo:\n"
                "RESERVA Shopping Morumbi para Aeroporto CGH - 2 pessoas - Sedan Executivo"
            )
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
                "RESERVA Av. Paulista para Morumbi - 4 pessoas - SUV\n"
                "PAGAR RES_12345\n"
                "STATUS RES_12345"
            )
        else:
            # Se o usuário tem reserva pendente, mostrar lembrete
            if telefone in ultimo_id_reserva and ultimo_id_reserva[telefone]:
                reserva_id = ultimo_id_reserva[telefone]
                if telefone in contexto_reserva and reserva_id in contexto_reserva[telefone]:
                    reserva = contexto_reserva[telefone][reserva_id]
                    entrada = reserva['valor'] * 0.5
                    
                    msg.body(
                        f"⚠️ *PAGAMENTO PENDENTE!*\n\n"
                        f"ID Reserva: {reserva_id}\n"
                        f"Valor Entrada: R${entrada:.2f}\n\n"
                        "Use: *PAGAR {reserva_id}*\n"
                        "Exemplo: PAGAR {reserva_id}\n\n"
                        "Ou digite *AJUDA* para ver todas opções."
                    )
                else:
                    msg.body("Desculpe, não entendi. Digite *AJUDA* para ver as opções disponíveis.")
            else:
                msg.body("Desculpe, não entendi. Digite *AJUDA* para ver as opções disponíveis.")
    
    elif estado_atual == "AGUARDANDO_RESERVA":
        dados = extrair_dados_reserva(mensagem)
        if dados:
            # Calcular preço
            valor = calcular_preco_simulado(dados['origem'], dados['destino'], dados['veiculo'])
            
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
            
            # Salvar no contexto
            if telefone not in contexto_reserva:
                contexto_reserva[telefone] = {}
            contexto_reserva[telefone][reserva_id] = reserva
            ultimo_id_reserva[telefone] = reserva_id
            
            # Responder
            msg.body(formatar_resposta(reserva, telefone))
            
            # Atualizar estado
            estado_usuario[telefone] = "AGUARDANDO_PAGAMENTO"
        else:
            msg.body(
                "❌ Formato inválido. Por favor, use:\n\n"
                "*RESERVA [Origem] para [Destino] - [Nº Pessoas] pessoas - [Veículo]*\n\n"
                "Exemplo:\n"
                "RESERVA Aeroporto GRU para Morumbi - 2 pessoas - Sedan Executivo"
            )
    
    elif estado_atual == "AGUARDANDO_PAGAMENTO":
        # Se o usuário enviar qualquer coisa que não seja pagamento, lembrar do pagamento
        ultima_reserva = ultimo_id_reserva.get(telefone)
        
        if ultima_reserva and telefone in contexto_reserva and ultima_reserva in contexto_reserva[telefone]:
            reserva = contexto_reserva[telefone][ultima_reserva]
            entrada = reserva['valor'] * 0.5
            
            msg.body(
                f"⚠️ *PAGAMENTO PENDENTE!*\n\n"
                f"ID Reserva: {ultima_reserva}\n"
                f"Valor Entrada: R${entrada:.2f}\n\n"
                "Use o comando: *PAGAR {ultima_reserva}*\n\n"
                "Exemplo: PAGAR {ultima_reserva}"
            )
        else:
            msg.body("❌ Nenhuma reserva pendente encontrada. Digite *RESERVA* para iniciar uma nova.")
            estado_usuario[telefone] = "AGUARDANDO_ACAO"
    
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

# ================= ROTAS ADICIONAIS =================
@app.route("/")
def home():
    return "AlineBot JCM - Sistema de Reservas Corporativas v5.0"

@app.route("/health")
def health_check():
    return "OK", 200

# ================= INICIALIZAÇÃO =================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    logger.info(f"🚀 AlineBot iniciado na porta {port}")
    app.run(host="0.0.0.0", port=port)
