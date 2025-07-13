import os
import re
import json
import logging
import random
import smtplib
import gspread
from datetime import datetime
from flask import Flask, request, Response
from twilio.rest import Client
from twilio.twiml.messaging_response import MessagingResponse
from logging.handlers import RotatingFileHandler
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from oauth2client.service_account import ServiceAccountCredentials
from dateutil.relativedelta import relativedelta

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
GOOGLE_CREDS_JSON = os.environ.get('GOOGLE_CREDS_JSON')
if GOOGLE_CREDS_JSON:
    try:
        GOOGLE_CREDS = json.loads(GOOGLE_CREDS_JSON)
    except json.JSONDecodeError:
        app.logger.error("Falha ao decodificar GOOGLE_CREDS_JSON. Verifique o formato.")
        GOOGLE_CREDS = None
else:
    GOOGLE_CREDS = None

SHEET_KEY = os.environ.get('PASTA_RAIZ_ID')  # ID da planilha

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
if GOOGLE_CREDS and SHEET_KEY:
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_dict(GOOGLE_CREDS, scope)
        gc = gspread.authorize(creds)
        app.logger.info("Google Sheets API inicializada com sucesso")
    except Exception as e:
        app.logger.critical(f"Falha ao inicializar Google Sheets: {str(e)}")
        gc = None
else:
    gc = None
    app.logger.warning("Credenciais do Google Sheets não fornecidas. Funcionalidades limitadas.")

# ================= ESTRUTURA DE DADOS =================
class UserState:
    def __init__(self):
        self.estados = {}
        self.reservas = {}
        self.solicitacoes = {}
        self.ultima_interacao = {}
    
    def get_user_state(self, telefone):
        return self.estados.get(telefone, "INICIO")
    
    def set_user_state(self, telefone, estado):
        self.estados[telefone] = estado
        self.ultima_interacao[telefone] = datetime.now()
    
    def tempo_desde_ultima_interacao(self, telefone):
        if telefone in self.ultima_interacao:
            return (datetime.now() - self.ultima_interacao[telefone]).total_seconds()
        return 9999  # Valor alto para novos usuários

state_manager = UserState()

# Dados de usuários (serão migrados para Sheets)
USUARIOS = {
    "+5511972508430": {"nome": "Cleverson", "empresa": "JCM", "nivel": 5, "ativo": True},
    "+5511988216292": {"nome": "Teste", "empresa": "JCM", "nivel": 5, "ativo": True}
}

# ================= FUNÇÕES DE HUMANIZAÇÃO =================
def saudacao():
    hora_atual = datetime.now().hour
    if 5 <= hora_atual < 12:
        return "Bom dia"
    elif 12 <= hora_atual < 18:
        return "Boa tarde"
    else:
        return "Boa noite"

def responder_saudacao():
    respostas = [
        "Estou ótima, obrigada! Como posso ajudar? 😊",
        "Tudo ótimo por aqui! E com você?",
        "Estou bem, pronta para te ajudar!",
        "Tudo bem sim! E aí, como vai você?"
    ]
    return random.choice(respostas)

def responder_aline():
    respostas = [
        "Sim, sou a Aline! Em que posso ajudar?",
        "Alô, Aline na área! Pronta para servir 😊",
        "Sim, estou aqui! Como posso te ajudar hoje?",
        "Oi! Aline no comando, diga aí!"
    ]
    return random.choice(respostas)

def responder_identificacao():
    respostas = [
        "Sou a Aline, assistente virtual da JCM Transportes!",
        "Prazer! Sou a Aline, sua assistente para reservas de transporte.",
        "Meu nome é Aline, e estou aqui para facilitar suas reservas!",
        "Sou a Aline, especialista em reservas da JCM 😊"
    ]
    return random.choice(respostas)

def responder_agradecimento():
    respostas = [
        "De nada! Estou sempre à disposição!",
        "Imagina! Fico feliz em ajudar 😊",
        "Por nada! Se precisar de mais algo, é só chamar!",
        "Foi um prazer! Conte comigo sempre que precisar"
    ]
    return random.choice(respostas)

# ================= FUNÇÕES PRINCIPAIS =================
def identificar_cliente(telefone):
    telefone_normalizado = re.sub(r'[^0-9+]', '', telefone)
    return USUARIOS.get(telefone_normalizado, {
        "nome": "Convidado", "empresa": "N/A", "nivel": 0, "ativo": False
    })

def processar_comando_admin(mensagem, telefone):
    try:
        if re.search(r'adicionar usuario', mensagem, re.IGNORECASE):
            return "✅ Usuário adicionado com sucesso!"
        
        elif re.search(r'listar usuarios', mensagem, re.IGNORECASE):
            lista = ["📋 Usuários cadastrados:"]
            for tel, user in USUARIOS.items():
                if tel == telefone: continue
                lista.append(f"- {user['nome']} ({tel}) | Nível {user['nivel']}")
            return "\n".join(lista)
        
        elif re.search(r'status servidor', mensagem, re.IGNORECASE):
            return "🟢 Servidor operacional\n💾 32% RAM livre\n🌐 5 conexões ativas"
        
        elif re.search(r'atribuir motorista', mensagem, re.IGNORECASE):
            return atribuir_motorista(mensagem)
        
        return "Comando administrativo desconhecido"
    
    except Exception as e:
        app.logger.error(f"Erro em comando admin: {str(e)}")
        return "❌ Erro ao processar comando"

def atribuir_motorista(mensagem):
    try:
        motoristas = ["CONT_001", "CONT_002", "CONT_003"]
        motorista = random.choice(motoristas)
        return f"✅ Motorista {motorista} atribuído com sucesso!"
    except Exception as e:
        app.logger.error(f"Erro ao atribuir motorista: {str(e)}")
        return "❌ Falha na atribuição de motorista"

def parse_data_relativa(data_str):
    """Converte expressões como 'amanhã' em datas reais"""
    hoje = datetime.now()
    
    if data_str.lower() in ['amanhã', 'amanha']:
        return (hoje + relativedelta(days=1)).strftime('%d/%m/%y')
    elif data_str.lower() == 'hoje':
        return hoje.strftime('%d/%m/%y')
    elif data_str.lower() == 'depois de amanhã':
        return (hoje + relativedelta(days=2)).strftime('%d/%m/%y')
    
    return data_str

def melhorar_entendimento_reserva(texto):
    """Processamento NLP simplificado para entender formatos livres"""
    # Normalização
    texto = texto.lower().replace("seria", "").replace("gostaria", "").strip()
    
    # Extração de elementos chave
    pessoas = re.search(r'(\d+)\s*(pessoas?|pax?|passageiros?)', texto)
    data_hora = re.search(r'(\d{1,2}/\d{1,2}/\d{2,4}).*?(\d{1,2}:\d{2})', texto) or \
                re.search(r'(\d{1,2}/\d{1,2}).*?(\d{1,2}:\d{2})', texto) or \
                re.search(r'(\d{1,2}/\d{1,2}/\d{2,4})', texto) or \
                re.search(r'(\d{1,2}/\d{1,2})', texto)
    
    # Extração de origem e destino
    locais = re.split(r'\s+(?:para|pro|pra|->|ate|até|em)\s+', texto, maxsplit=1)
    
    # Tratar datas relativas
    data = None
    hora = None
    if data_hora:
        data = parse_data_relativa(data_hora.group(1))
        if data_hora.lastindex >= 2:
            hora = data_hora.group(2)
    
    return {
        'origem': locais[0].strip() if len(locais) > 0 else None,
        'destino': locais[1].split(' ', 1)[0].strip() if len(locais) > 1 else None,
        'pessoas': int(pessoas.group(1)) if pessoas else 1,
        'data': data,
        'hora': hora
    }

def registrar_reserva_google_sheets(dados):
    if not gc:
        return False
    
    try:
        sheet = gc.open_by_key(SHEET_KEY).worksheet("Reservas_JCM")
        
        # Formatar data atual no padrão brasileiro
        data_atual = datetime.now().strftime('%d/%m/%Y')
        
        # Tentar converter data/hora para o formato do Sheets
        try:
            hora_reserva = dados.get('hora', '12:00')
            data_reserva = dados.get('data', data_atual)
        except:
            data_reserva = data_atual
            hora_reserva = "12:00"
        
        # Garantir que todos os campos estão preenchidos
        nova_linha = [
            f"RES_{datetime.now().strftime('%Y%m%d%H%M%S')}",  # ID_Reserva
            dados.get('cliente', 'N/A'),                      # Cliente
            data_atual,                                       # Data do registro
            hora_reserva,                                     # Hora_Coleta
            dados.get('origem', 'N/A'),                       # ID_Local_Origem
            dados.get('destino', 'N/A'),                      # ID_Local_Destino
            "Sedan Executivo",                                # Categoria_Veiculo
            "",                                               # ID_Motorista
            "Pendente",                                       # Status
            "300.00",                                         # Valor
            "Avulso",                                         # Tipo_Faturamento
            "Pendente",                                       # Status_Faturamento
            "", "", "", ""                                    # Campos restantes
        ]
        
        app.logger.info(f"Registrando reserva: {nova_linha}")
        sheet.append_row(nova_linha)
        return True
    except Exception as e:
        app.logger.error(f"Erro detalhado ao registrar reserva: {str(e)}")
        return False

def enviar_email_confirmacao(destinatario, reserva):
    try:
        msg = MIMEMultipart()
        msg['From'] = EMAIL_FROM
        msg['To'] = destinatario
        msg['Subject'] = f"✅ Confirmação de Reserva #{reserva['id']}"
        
        corpo = f"""
        <h2>Reserva Confirmada - JCM Transportes</h2>
        <p>Sua reserva <b>#{reserva['id']}</b> foi confirmada com sucesso!</p>
        <h3>Detalhes:</h3>
        <ul>
            <li><b>Origem:</b> {reserva['origem']}</li>
            <li><b>Destino:</b> {reserva['destino']}</li>
            <li><b>Data/Hora:</b> {reserva['data']} às {reserva['hora']}</li>
            <li><b>Veículo:</b> {reserva['categoria']}</li>
            <li><b>Valor:</b> R$ {reserva['valor']}</li>
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
    """Processa mensagens de reserva com NLP simplificado"""
    try:
        # Tentar entender formatos livres
        dados = melhorar_entendimento_reserva(mensagem)
        
        # Validar dados mínimos
        if not dados['origem'] or not dados['destino']:
            return ("🤔 Não consegui identificar origem e destino. "
                    "Poderia tentar novamente? Exemplo:\n\n"
                    "*Reserva Aeroporto GRU para Hotel Tivoli - 2 pessoas - 15/07 às 14:30*")
        
        # Dados padrão quando ausentes
        dados['pessoas'] = dados['pessoas'] or 1
        dados['data'] = dados['data'] or (datetime.now() + relativedelta(days=1)).strftime('%d/%m/%y')
        dados['hora'] = dados['hora'] or "12:00"
        data_hora_completa = f"{dados['data']} {dados['hora']}"
        
        # Estrutura de reserva
        reserva = {
            'cliente': cliente['nome'],
            'telefone': telefone,
            'origem': dados['origem'],
            'destino': dados['destino'],
            'pessoas': dados['pessoas'],
            'data': dados['data'],
            'hora': dados['hora'],
            'data_hora': data_hora_completa,
            'status': 'pendente',
            'timestamp': datetime.now().isoformat()
        }
        
        # Registra reserva
        state_manager.reservas[telefone] = reserva
        
        # Integração com Google Sheets
        if registrar_reserva_google_sheets({
            'cliente': cliente['nome'],
            'origem': dados['origem'],
            'destino': dados['destino'],
            'categoria': "Sedan Executivo",
            'valor': "300.00",
            'data_hora': data_hora_completa
        }):
            # Atribui motorista e envia confirmação
            motorista = atribuir_motorista("")
            if cliente.get('email'):
                enviar_email_confirmacao(cliente['email'], {
                    'id': f"RES_{datetime.now().strftime('%Y%m%d%H%M%S')}",
                    'origem': dados['origem'],
                    'destino': dados['destino'],
                    'data': dados['data'],
                    'hora': dados['hora'],
                    'categoria': "Sedan Executivo",
                    'valor': "300.00"
                })
            
            state_manager.set_user_state(telefone, "CONFIRMACAO")
            return (f"⏳ *Estamos processando sua reserva!*\n\n"
                    f"Em instantes enviaremos todos os detalhes da sua reserva aqui no WhatsApp e por e-mail.\n\n"
                    f"📋 Detalhes preliminares:\n"
                    f"• Origem: {dados['origem']}\n"
                    f"• Destino: {dados['destino']}\n"
                    f"• Data/Hora: {data_hora_completa}\n"
                    f"• Passageiros: {dados['pessoas']}\n\n"
                    f"Aguarde só um momentinho enquanto finalizamos tudo... ⏱️")
        else:
            return "⚠️ Reserva registrada localmente (erro no sistema principal)"
            
    except Exception as e:
        app.logger.error(f"Erro ao processar reserva: {str(e)}")
        return "❌ Ops! Tivemos um problema ao processar sua reserva. Poderia tentar novamente?"

# ================= FUNÇÕES DE RESPOSTA =================
def responder_ajuda():
    return ("🆘 *Como posso ajudar?*\n\n"
            "Você pode:\n"
            "• Fazer uma *RESERVA* de transporte\n"
            "• *CANCELAR* uma operação\n"
            "• Verificar *STATUS* de reservas\n"
            "• Solicitar *SUPORTE* técnico\n\n"
            "Me diga o que precisa! 😊")

def responder_status_reservas(telefone):
    reserva = state_manager.reservas.get(telefone, {})
    if reserva:
        return (f"🔍 *Status da sua reserva:*\n\n"
                f"• Origem: {reserva.get('origem', 'N/A')}\n"
                f"• Destino: {reserva.get('destino', 'N/A')}\n"
                f"• Data/Hora: {reserva.get('data_hora', 'N/A')}\n"
                f"• Status: {reserva.get('status', 'Pendente')}\n\n"
                f"Precisa de mais informações?")
    else:
        return "📭 Você não tem reservas ativas. Digite *RESERVA* para criar uma nova."

def responder_suporte():
    return ("🛠️ *Suporte Técnico*\n\n"
            "Para suporte técnico, contate:\n"
            "• Cleverson: +55 11 97250-8430\n"
            "• E-mail: suporte@jcm.com\n\n"
            "Estamos à disposição para ajudar!")

# ================= ROTAS ESSENCIAIS =================
@app.route('/healthz', methods=['GET', 'HEAD'])
def health_check():
    return Response("OK", status=200)

@app.route("/webhook", methods=['POST'])
def webhook():
    try:
        telefone = request.form.get('From', '')
        mensagem = request.form.get('Body', '').strip()
        mensagem_lower = mensagem.lower()
        
        if not telefone or not mensagem:
            return Response("Dados incompletos", status=400)
        
        app.logger.info(f"Mensagem de {telefone}: {mensagem}")
        cliente = identificar_cliente(telefone)
        
        # Verifica se é um novo usuário após 10 minutos de inatividade
        if state_manager.tempo_desde_ultima_interacao(telefone) > 600:  # 10 minutos
            state_manager.set_user_state(telefone, "INICIO")
        
        if not cliente['ativo']:
            resp = MessagingResponse()
            resp.message("❌ Você não tem permissão para acessar este sistema. Contate o administrador.")
            return str(resp)
        
        resposta = processar_mensagem(mensagem_lower, mensagem, telefone, cliente)
        
        resp = MessagingResponse()
        resp.message(resposta)
        return str(resp)
        
    except Exception as e:
        app.logger.exception("ERRO CRÍTICO no webhook:")
        resp = MessagingResponse()
        resp.message("⚠️ Ops! Tivemos um problema técnico. Tente novamente em alguns instantes.")
        return str(resp)

def processar_mensagem(mensagem_lower, mensagem_original, telefone, cliente):
    estado_atual = state_manager.get_user_state(telefone)
    nome_cliente = cliente['nome'] if cliente['nome'] != "Convidado" else ""
    
    # ------ COMANDOS GLOBAIS (SEMPRE disponíveis) ------
    if mensagem_lower in ['ajuda', 'help', 'comandos', 'opções']:
        return responder_ajuda()
    
    if mensagem_lower in ['cancelar', 'parar', 'voltar']:
        state_manager.set_user_state(telefone, "INICIO")
        return "Operação cancelada. Como posso ajudar?"
    
    if mensagem_lower in ['status', 'minhas reservas', 'ver reservas']:
        return responder_status_reservas(telefone)
    
    if mensagem_lower == 'suporte':
        return responder_suporte()
    
    # ------ RESPOSTAS CONTEXTUAIS ------
    if any(palavra in mensagem_lower for palavra in ["oi", "ola", "olá", "e aí", "bom dia", "boa tarde", "boa noite"]):
        state_manager.set_user_state(telefone, "AGUARDANDO_ACAO")
        return f"{saudacao()}{f', {nome_cliente}' if nome_cliente else ''}! Eu sou a Aline, assistente virtual da JCM. Como posso te ajudar hoje? 😊"
    
    if "aline" in mensagem_lower:
        if any(palavra in mensagem_lower for palavra in ["quem é você", "quem é voce", "o que você faz"]):
            return responder_identificacao()
        elif any(palavra in mensagem_lower for palavra in ["tudo bem", "como você está", "como esta", "como vai"]):
            return responder_saudacao()
        else:
            return responder_aline()
    
    if any(palavra in mensagem_lower for palavra in ["obrigad", "agradeço", "valeu", "grato"]):
        return responder_agradecimento()
    
    # Comandos administrativos
    if mensagem_lower.startswith(("admin ", "administrativo ", "sys ")):
        return processar_comando_admin(mensagem_lower, telefone)
    
    # ------ MÁQUINA DE ESTADOS ------
    if estado_atual == "INICIO":
        if any(palavra in mensagem_lower for palavra in ["reserva", "reservar", "transporte", "carro", "viagem"]):
            state_manager.set_user_state(telefone, "AGUARDANDO_RESERVA")
            return ("📝 Claro! Vamos fazer sua reserva.\n\n"
                    "Por favor, me informe:\n"
                    "• Origem e destino\n"
                    "• Número de passageiros\n"
                    "• Data e horário desejados\n\n"
                    "*Exemplo:*\n"
                    "_Reserva do Aeroporto GRU para o Hotel Tivoli - 2 pessoas - 15/07 às 14:30_\n\n"
                    "Pode me enviar em qualquer ordem! 😊")
        else:
            state_manager.set_user_state(telefone, "AGUARDANDO_ACAO")
            return (f"{saudacao()}{f', {nome_cliente}' if nome_cliente else ''}! Digite *RESERVA* para começar uma reserva ou *AJUDA* para ver opções.")
    
    elif estado_atual == "AGUARDANDO_ACAO":
        if any(palavra in mensagem_lower for palavra in ["reserva", "reservar", "transporte", "carro", "viagem"]):
            state_manager.set_user_state(telefone, "AGUARDANDO_RESERVA")
            return "📝 Ótimo! Por favor, me envie os detalhes da sua reserva."
        elif "status" in mensagem_lower:
            return responder_status_reservas(telefone)
        else:
            return "🤔 Desculpe, não entendi. Digite *RESERVA* para nova reserva ou *AJUDA* para ver opções."
    
    elif estado_atual == "AGUARDANDO_RESERVA":
        # Comando especial: sair do fluxo de reserva
        if any(palavra in mensagem_lower for palavra in ["sair", "cancelar", "voltar"]):
            state_manager.set_user_state(telefone, "INICIO")
            return "✅ Sai do modo reserva. Como posso ajudar?"
            
        return processar_reserva(mensagem_original, telefone, cliente)
    
    elif estado_atual == "CONFIRMACAO":
        reserva = state_manager.reservas.get(telefone, {})
        state_manager.set_user_state(telefone, "INICIO")
        
        return (f"✅ *Reserva confirmada!*\n\n"
                f"Aqui estão os detalhes finais:\n"
                f"• Origem: {reserva.get('origem', 'N/A')}\n"
                f"• Destino: {reserva.get('destino', 'N/A')}\n"
                f"• Data/Hora: {reserva.get('data_hora', 'N/A')}\n"
                f"• Passageiros: {reserva.get('pessoas', 'N/A')}\n"
                f"• Motorista: CONT_00{random.randint(1,5)}\n\n"
                f"📬 Enviamos um e-mail com todos os detalhes e comprovante.\n\n"
                f"Obrigada por escolher a JCM Transportes! 🚗💨\n\n"
                f"Digite *RESERVA* para novo serviço ou *AJUDA* para ver opções.")
    
    return ("🤔 Desculpe, não entendi bem.\n\n"
            "Digite *AJUDA* para ver as opções disponíveis ou *SUPORTE* para falar com nossa equipe.")

# ================= SERVIDOR PRODUÇÃO =================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    
    if os.environ.get('ENVIRONMENT') == 'production':
        from waitress import serve
        app.logger.info(f"🚀 SERVIDOR PRODUÇÃO iniciado na porta {port}")
        serve(app, host="0.0.0.0", port=port, threads=12)
    else:
        app.logger.info(f"🚀 Servidor desenvolvimento iniciado na porta {port}")
        app.run(host="0.0.0.0", port=port, debug=False)
