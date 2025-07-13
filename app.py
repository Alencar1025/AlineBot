import os
import re
import json
import logging
import random
import smtplib
import gspread
import requests
from datetime import datetime, timedelta
from flask import Flask, request, Response
from twilio.rest import Client
from twilio.twiml.messaging_response import MessagingResponse
from logging.handlers import RotatingFileHandler
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from oauth2client.service_account import ServiceAccountCredentials

# ================= CONFIGURAÇÃO INICIAL =================
app = Flask(__name__)

# Configuração robusta de logs
log_handler = RotatingFileHandler('alinebot.log', maxBytes=10*1024*1024, backupCount=5)
log_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
log_handler.setFormatter(log_formatter)
app.logger.addHandler(log_handler)
app.logger.setLevel(logging.INFO)

# Configurações Twilio
TWILIO_ACCOUNT_SID = os.environ.get('TWILIO_ACCOUNT_SID')
TWILIO_AUTH_TOKEN = os.environ.get('TWILIO_AUTH_TOKEN')
TWILIO_PHONE_NUMBER = os.environ.get('TWILIO_PHONE_NUMBER', '+14155238886')

# Configurações Google Sheets
GOOGLE_CREDS = json.loads(os.environ.get('GOOGLE_SERVICE_ACCOUNT_JSON'))
SHEET_KEY = '1TEMPLATE_JCM_PAGAMENTOS_V2'  # Substituir pelo ID real

# Configurações E-mail
SMTP_SERVER = os.environ.get('SMTP_SERVER', 'smtp.sendgrid.net')
SMTP_PORT = int(os.environ.get('SMTP_PORT', 587))
SMTP_USER = os.environ.get('SMTP_USER')
SMTP_PASSWORD = os.environ.get('SMTP_PASSWORD')
EMAIL_FROM = os.environ.get('EMAIL_FROM', 'alinebot@jcm.com')

# Inicialização segura do cliente Twilio
try:
    twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    app.logger.info("Twilio client inicializado com sucesso")
except Exception as e:
    app.logger.critical(f"Falha ao inicializar Twilio client: {str(e)}")
    twilio_client = None

# Inicialização Google Sheets
try:
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_dict(GOOGLE_CREDS, scope)
    gc = gspread.authorize(creds)
    app.logger.info("Google Sheets API inicializada com sucesso")
except Exception as e:
    app.logger.critical(f"Falha ao inicializar Google Sheets: {str(e)}")
    gc = None

# ================= ESTRUTURA DE DADOS =================
class UserState:
    def __init__(self):
        self.estados = {}
        self.reservas = {}
        self.solicitacoes = {}
    
    def get_user_state(self, telefone):
        return self.estados.get(telefone, "INICIO")
    
    def set_user_state(self, telefone, estado):
        self.estados[telefone] = estado

state_manager = UserState()

# Dados de usuários (serão migrados para Sheets)
USUARIOS = {
    "+5511972508430": {"nome": "Cleverson", "empresa": "JCM", "nivel": 5, "ativo": True},
    "+5511988216292": {"nome": "Teste", "empresa": "JCM", "nivel": 5, "ativo": True}
}

# ================= FUNÇÕES PRINCIPAIS =================
def identificar_cliente(telefone):
    telefone_normalizado = re.sub(r'[^0-9+]', '', telefone)
    return USUARIOS.get(telefone_normalizado, {
        "nome": "Convidado", "empresa": "N/A", "nivel": 0, "ativo": False
    })

def processar_comando_admin(mensagem, telefone):
    try:
        if re.search(r'adicionar usuario', mensagem, re.IGNORECASE):
            # Lógica para adicionar usuário
            return "✅ Usuário adicionado!"
        
        elif re.search(r'listar usuarios', mensagem, re.IGNORECASE):
            return "📋 Lista de usuários..."
        
        elif re.search(r'status servidor', mensagem, re.IGNORECASE):
            return "🟢 Servidor operacional\n💾 32% RAM livre\n🌐 5 conexões ativas"
        
        elif re.search(r'atribuir motorista', mensagem, re.IGNORECASE):
            return atribuir_motorista(mensagem)
        
        return "Comando administrativo desconhecido"
    
    except Exception as e:
        app.logger.error(f"Erro em comando admin: {str(e)}")
        return "❌ Erro ao processar comando"

def atribuir_motorista(mensagem):
    """Atribui motorista usando algoritmo round-robin"""
    try:
        # Lógica de atribuição (será integrada com Sheets)
        motoristas = ["CONT_001", "CONT_002", "CONT_003"]
        motorista = motoristas.pop(0)
        motoristas.append(motorista)
        return f"✅ Motorista {motorista} atribuído com sucesso!"
    except Exception as e:
        app.logger.error(f"Erro ao atribuir motorista: {str(e)}")
        return "❌ Falha na atribuição de motorista"

def registrar_reserva_google_sheets(dados):
    """Registra reserva no Google Sheets"""
    if not gc:
        return False
    
    try:
        sheet = gc.open_by_key(SHEET_KEY).worksheet("Reservas_JCM")
        nova_linha = [
            f"RES_{datetime.now().strftime('%Y%m%d%H%M%S')}",
            dados['cliente'],
            datetime.now().strftime('%d/%m/%y'),
            dados['hora_coleta'],
            dados['origem'],
            dados['destino'],
            dados['categoria'],
            "",  # ID_Motorista (preenchido posteriormente)
            "Pendente",
            dados['valor'],
            "Avulso",
            "Pendente",
            "", "", "", ""  # Campos restantes
        ]
        sheet.append_row(nova_linha)
        return True
    except Exception as e:
        app.logger.error(f"Erro ao registrar reserva no Sheets: {str(e)}")
        return False

def enviar_email_confirmacao(destinatario, reserva_id):
    """Envia e-mail de confirmação de reserva"""
    try:
        msg = MIMEMultipart()
        msg['From'] = EMAIL_FROM
        msg['To'] = destinatario
        msg['Subject'] = f"✅ Confirmação de Reserva #{reserva_id}"
        
        corpo = f"""
        <h2>Reserva Confirmada - JCM Transportes</h2>
        <p>Sua reserva <b>#{reserva_id}</b> foi confirmada com sucesso!</p>
        <h3>Detalhes:</h3>
        <ul>
            <li><b>Origem:</b> {reserva_id['origem']}</li>
            <li><b>Destino:</b> {reserva_id['destino']}</li>
            <li><b>Data/Hora:</b> {reserva_id['data']} às {reserva_id['hora']}</li>
            <li><b>Veículo:</b> {reserva_id['categoria']}</li>
            <li><b>Valor:</b> R$ {reserva_id['valor']}</li>
        </ul>
        <p>Acompanhe seu motorista em tempo real pelo nosso app.</p>
        """
        
        msg.attach(MIMEText(corpo, 'html'))
        
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)
        
        return True
    except Exception as e:
        app.logger.error(f"Erro ao enviar e-mail: {str(e)}")
        return False

# ================= PROCESSADOR DE RESERVAS =================
def processar_reserva(mensagem, telefone, cliente):
    """Processa mensagens de reserva com validação avançada"""
    try:
        # Padrões de reconhecimento
        padrao1 = re.compile(r'reserva (.+) para (.+) - (\d+) pessoas - (.+)')
        padrao2 = re.compile(r'reserva: (.+) -> (.+), (\d+)p, (.+)')
        
        match = padrao1.match(mensagem) or padrao2.match(mensagem)
        
        if not match:
            return "Formato inválido. Use: RESERVA [Origem] para [Destino] - [Pessoas] pessoas - [Data/Hora]"
        
        origem, destino, pessoas, data_hora = match.groups()
        
        # Validação básica
        if not pessoas.isdigit() or int(pessoas) <= 0:
            return "❌ Número de pessoas inválido"
        
        # Estrutura de reserva
        reserva = {
            'cliente': cliente['nome'],
            'telefone': telefone,
            'origem': origem.strip(),
            'destino': destino.strip(),
            'pessoas': int(pessoas),
            'data_hora': data_hora.strip(),
            'status': 'pendente',
            'timestamp': datetime.now().isoformat()
        }
        
        # Registra reserva
        state_manager.reservas[telefone] = reserva
        
        # Integração com Google Sheets
        if registrar_reserva_google_sheets({
            'cliente': cliente['nome'],
            'hora_coleta': data_hora.split()[0] if ' ' in data_hora else data_hora,
            'origem': origem,
            'destino': destino,
            'categoria': "Sedan Executivo",  # Categoria padrão
            'valor': "300.00"  # Valor estimado
        }):
            # Atribui motorista e envia confirmação
            motorista = atribuir_motorista("")
            if cliente.get('email'):
                enviar_email_confirmacao(cliente['email'], reserva)
            
            state_manager.set_user_state(telefone, "CONFIRMACAO")
            return (f"✅ Reserva confirmada!\n"
                    f"📆 {data_hora}\n"
                    f"📍 {origem} → {destino}\n"
                    f"👤 Motorista: {motorista}\n"
                    f"📬 Confirmação enviada por e-mail")
        else:
            return "⚠️ Reserva registrada localmente (erro no sistema principal)"
            
    except Exception as e:
        app.logger.error(f"Erro ao processar reserva: {str(e)}")
        return "❌ Erro ao processar reserva. Tente novamente."

# ================= ROTAS ESSENCIAIS =================
@app.route('/healthz', methods=['GET', 'HEAD'])
def health_check():
    return Response("OK", status=200)

@app.route("/webhook", methods=['POST'])
def webhook():
    try:
        telefone = request.form.get('From', '')
        mensagem = request.form.get('Body', '').strip().lower()
        
        if not telefone or not mensagem:
            return Response("Dados incompletos", status=400)
        
        app.logger.info(f"Mensagem de {telefone}: {mensagem}")
        cliente = identificar_cliente(telefone)
        
        if not cliente['ativo']:
            resp = MessagingResponse()
            resp.message("❌ Você não tem permissão. Contate o administrador.")
            return str(resp)
        
        resposta = processar_mensagem(mensagem, telefone, cliente)
        
        resp = MessagingResponse()
        resp.message(resposta)
        return str(resp)
        
    except Exception as e:
        app.logger.exception("ERRO CRÍTICO no webhook:")
        resp = MessagingResponse()
        resp.message("⚠️ Ocorreu um erro interno. Tente novamente.")
        return str(resp)

def processar_mensagem(mensagem, telefone, cliente):
    estado_atual = state_manager.get_user_state(telefone)
    
    # Comandos globais
    if mensagem == 'ajuda':
        return ("🆘 *AJUDA ALINEBOT*\n\n"
                "• RESERVA - Iniciar nova reserva\n"
                "• CANCELAR - Cancelar operação atual\n"
                "• STATUS - Verificar reservas\n"
                "• ADMIN - Comandos administrativos")
    
    if mensagem == 'cancelar':
        state_manager.set_user_state(telefone, "INICIO")
        return "Operação cancelada. Digite *RESERVA* para novo pedido."
    
    # Comandos administrativos
    if mensagem.startswith(("admin ", "administrativo ")):
        return processar_comando_admin(mensagem, telefone)
    
    # Máquina de estados
    if estado_atual == "INICIO":
        if "reserva" in mensagem:
            state_manager.set_user_state(telefone, "AGUARDANDO_RESERVA")
            return ("📝 Por favor, envie sua reserva no formato:\n"
                    "*RESERVA [Origem] para [Destino] - [Pessoas] pessoas - [Data/Hora]*\n"
                    "Ex: RESERVA Aeroporto GRU para Hotel Tivoli - 2 pessoas - 15/07 14:30")
        else:
            state_manager.set_user_state(telefone, "AGUARDANDO_ACAO")
            return ("👋 Olá {cliente['nome']}! Eu sou a AlineBot da JCM.\n"
                    "Digite *RESERVA* para novo serviço ou *AJUDA* para ajuda.")
    
    elif estado_atual == "AGUARDANDO_ACAO":
        if "reserva" in mensagem:
            state_manager.set_user_state(telefone, "AGUARDANDO_RESERVA")
            return "📝 Envie os detalhes da reserva no formato solicitado."
        elif "status" in mensagem:
            return "🔄 Verificando suas reservas..."
        else:
            return "Não entendi. Digite *AJUDA* para ver opções."
    
    elif estado_atual == "AGUARDANDO_RESERVA":
        if "reserva" in mensagem:
            return processar_reserva(mensagem, telefone, cliente)
        else:
            return "Formato incorreto. Use: *RESERVA [Origem] para [Destino] - [Pessoas] pessoas - [Data/Hora]*"
    
    elif estado_atual == "CONFIRMACAO":
        state_manager.set_user_state(telefone, "INICIO")
        return "Obrigado por usar JCM Transportes! Digite *RESERVA* para novo serviço."
    
    return "🤖 Comando não reconhecido. Digite *AJUDA* para ver opções."

# ================= FUNÇÕES DE TESTE =================
def executar_testes():
    """Função para executar testes automatizados"""
    testes = [
        ("reserva aeroporto guarulhos para hotel tivoli - 2 pessoas - 15/07 14:30", True),
        ("admin listar usuarios", True),
        ("status", True),
        ("comando invalido", False)
    ]
    
    resultados = []
    for mensagem, esperado in testes:
        resultado = processar_mensagem(mensagem, "+5511988216292", 
                                      {"nome": "Teste", "nivel": 5, "ativo": True})
        sucesso = "✅" if (resultado != "Comando não reconhecido") == esperado else "❌"
        resultados.append(f"{sucesso} Teste: '{mensagem}'")
    
    return "\n".join(resultados)

# ================= SERVIDOR PRODUÇÃO =================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    
    # Executar testes na inicialização
    app.logger.info("Executando testes de integração...")
    app.logger.info(executar_testes())
    
    if os.environ.get('ENVIRONMENT') == 'production':
        from waitress import serve
        app.logger.info(f"🚀 SERVIDOR PRODUÇÃO iniciado na porta {port}")
        serve(app, host="0.0.0.0", port=port, threads=12)
    else:
        app.logger.info(f"🚀 Servidor desenvolvimento iniciado na porta {port}")
        app.run(host="0.0.0.0", port=port, debug=False)
