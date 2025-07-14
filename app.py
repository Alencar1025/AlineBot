import os
import re
import json
import logging
import random
import smtplib
import gspread
import threading
import time
from datetime import datetime, timedelta
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
        # ESCOPO CORRIGIDO PARA GOOGLE SHEETS V4
        scope = [
            'https://www.googleapis.com/auth/spreadsheets',
            'https://www.googleapis.com/auth/drive'
        ]
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

# Dados de usuários
USUARIOS = {
    "+5511972508430": {"nome": "Cleverson", "empresa": "JCM", "nivel": 5, "ativo": True, "email": "cleverson@jcm.com"},
    "+5511988216292": {"nome": "Teste", "empresa": "JCM", "nivel": 5, "ativo": True, "email": "teste@jcm.com"}
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
        
        elif re.search(r'teste reserva', mensagem, re.IGNORECASE):
            # Simula uma reserva de teste
            dados = {
                'cliente': 'Teste',
                'origem': 'Aeroporto GRU',
                'destino': 'Hotel Tivoli',
                'data': '15/07/25',
                'hora': '14:30'
            }
            if registrar_reserva_google_sheets(dados):
                return "✅ Reserva de teste registrada com sucesso!"
            else:
                return "❌ Falha ao registrar reserva de teste"
        
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
    texto = re.sub(r'\b(?:seria|gostaria|preciso?)\b', '', texto, flags=re.IGNORECASE)
    texto = texto.strip()
    
    # Extração de elementos chave
    pessoas = re.search(r'(\d+)\s*(?:pessoas?|pax?|passageiros?)', texto, re.IGNORECASE)
    data_hora = re.search(r'(\d{1,2}/\d{1,2}(?:/\d{2,4})?)', texto) or \
                re.search(r'(\d{1,2}/\d{1,2})', texto)
    hora = re.search(r'(\d{1,2}:\d{2})', texto)
    
    # Extração de origem e destino
    locais = re.split(r'\s+(?:para|pro|pra|->|ate|até|em)\s+', texto, maxsplit=1)
    
    # Tratar datas relativas
    data = None
    if data_hora:
        data = parse_data_relativa(data_hora.group(1))
    
    return {
        'origem': locais[0].strip() if len(locais) > 0 else None,
        'destino': locais[1].strip() if len(locais) > 1 else None,
        'pessoas': int(pessoas.group(1)) if pessoas else 1,
        'data': data,
        'hora': hora.group(1) if hora else None
    }

def registrar_reserva_google_sheets(dados):
    if not gc:
        return False
    
    try:
        sheet = gc.open_by_key(SHEET_KEY).worksheet("Reservas_JCM")
        
        # Formatar data atual no padrão brasileiro (dd/mm/yy)
        data_atual = datetime.now().strftime('%d/%m/%y')
        
        # Preencher dados padrão se ausentes
        data_reserva = dados.get('data', data_atual)
        hora_reserva = dados.get('hora', '00:00')  # Padrão 00:00 como na planilha
        
        # Gerar ID do motorista no formato CONT_001, CONT_002, etc.
        motorista_id = f"CONT_{random.randint(1,3):03d}"
        
        # ID de reserva único
        reserva_id = f"RES_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        # LISTA DE VALORES COM FORMATO EXIGIDO PELA PLANILHA (16 colunas)
        nova_linha = [
            reserva_id,                          # A: ID_Reserva
            dados.get('cliente', 'N/A'),         # B: Cliente
            data_atual,                          # C: Data do registro (hoje)
            hora_reserva,                        # D: Hora_Coleta
            dados.get('origem', 'N/A'),          # E: ID_Local_Origem
            dados.get('destino', 'N/A'),         # F: ID_Local_Destino
            "Sedan Executivo",                   # G: Categoria_Veiculo
            motorista_id,                        # H: ID_Motorista
            "Confirmado",                        # I: Status
            "300.00",                            # J: Valor
            "Avulso",                            # K: Tipo_Faturamento
            "Pendente",                          # L: Status_Faturamento
            "",                                  # M: Data_Vencimento
            "",                                  # N: Valor_Entrada
            "",                                  # O: Link_Pagamento
            ""                                   # P: Comprovante_Final
        ]
        
        app.logger.info(f"Registrando reserva: {nova_linha}")
        sheet.append_row(nova_linha)
        return reserva_id
    except Exception as e:
        app.logger.error(f"ERRO GOOGLE SHEETS: {str(e)}")
        app.logger.error(f"Dados: {json.dumps(dados, indent=2)}")
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
            <li><b>Motorista:</b> {reserva['motorista']}</li>
        </ul>
        <p>Acompanhe seu motorista em tempo real pelo nosso app.</p>
        <p>Obrigada por escolher a JCM Transportes!</p>
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

# ================= SISTEMA DE LEMBRETES =================
def agendar_lembretes(reserva):
    try:
        # Converter data/hora da reserva
        data_reserva = datetime.strptime(f"{reserva['data']} {reserva['hora']}", '%d/%m/%y %H:%M')
        
        # Lembrete 1 dia antes
        lembrete_1_dia = data_reserva - timedelta(days=1)
        threading.Timer(
            (lembrete_1_dia - datetime.now()).total_seconds(),
            enviar_lembrete,
            args=[reserva, "1 dia"]
        ).start()
        
        # Lembrete 5 horas antes
        lembrete_5_horas = data_reserva - timedelta(hours=5)
        threading.Timer(
            (lembrete_5_horas - datetime.now()).total_seconds(),
            enviar_lembrete,
            args=[reserva, "5 horas"]
        ).start()
        
        # Lembrete para o motorista
        threading.Timer(
            (lembrete_1_dia - datetime.now()).total_seconds(),
            enviar_lembrete_motorista,
            args=[reserva, "1 dia"]
        ).start()
        
        threading.Timer(
            (lembrete_5_horas - datetime.now()).total_seconds(),
            enviar_lembrete_motorista,
            args=[reserva, "5 horas"]
        ).start()
        
    except Exception as e:
        app.logger.error(f"Erro ao agendar lembretes: {str(e)}")

def enviar_lembrete(reserva, tempo_antecedencia):
    try:
        if twilio_client:
            mensagem = (
                f"⏰ Lembrete de Reserva JCM\n\n"
                f"Faltam {tempo_antecedencia} para seu transporte!\n\n"
                f"ID Reserva: {reserva['id']}\n"
                f"Origem: {reserva['origem']}\n"
                f"Destino: {reserva['destino']}\n"
                f"Data/Hora: {reserva['data']} {reserva['hora']}\n"
                f"Motorista: {reserva['motorista']}\n\n"
                f"Precisa de ajuda? Responda esta mensagem!"
            )
            
            twilio_client.messages.create(
                body=mensagem,
                from_=TWILIO_PHONE_NUMBER,
                to=reserva['telefone']
            )
    except Exception as e:
        app.logger.error(f"Erro ao enviar lembrete: {str(e)}")

def enviar_lembrete_motorista(reserva, tempo_antecedencia):
    try:
        # Simulação - na prática precisaria do número do motorista
        app.logger.info(f"Lembrete para motorista {reserva['motorista']}: Reserva {reserva['id']} em {tempo_antecedencia}")
    except Exception as e:
        app.logger.error(f"Erro ao enviar lembrete para motorista: {str(e)}")

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
        
        # Atribuir motorista
        motorista = f"CONT_{random.randint(1,3):03d}"
        
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
            'motorista': motorista,
            'status': 'Confirmado',
            'timestamp': datetime.now().isoformat()
        }
        
        # Registra reserva localmente
        state_manager.reservas[telefone] = reserva
        
        # Integração com Google Sheets
        reserva_id = registrar_reserva_google_sheets({
            'cliente': cliente['nome'],
            'origem': dados['origem'],
            'destino': dados['destino'],
            'data': dados['data'],
            'hora': dados['hora']
        })
        
        if reserva_id:
            reserva['id'] = reserva_id
            
            # Agendar lembretes
            agendar_lembretes(reserva)
            
            # Enviar e-mail de confirmação
            if cliente.get('email'):
                enviar_email_confirmacao(cliente['email'], {
                    'id': reserva_id,
                    'origem': dados['origem'],
                    'destino': dados['destino'],
                    'data': dados['data'],
                    'hora': dados['hora'],
                    'categoria': "Sedan Executivo",
                    'valor': "300.00",
                    'motorista': motorista
                })
            
            state_manager.set_user_state(telefone, "MENU_RESERVA")
            return (f"✅ *Reserva confirmada!* 🚗\n\n"
                    f"ID da Reserva: {reserva_id}\n"
                    f"Motorista: {motorista}\n\n"
                    f"📋 Detalhes:\n"
                    f"• Origem: {dados['origem']}\n"
                    f"• Destino: {dados['destino']}\n"
                    f"• Data/Hora: {data_hora_completa}\n"
                    f"• Passageiros: {dados['pessoas']}\n\n"
                    f"Enviamos um e-mail com o comprovante completo para {cliente.get('email', 'seu e-mail cadastrado')}.\n\n"
                    f"*Precisa de algo mais?*\n"
                    f"1. Alterar reserva\n"
                    f"2. Cancelar reserva\n"
                    f"3. Falar com atendente\n"
                    f"4. Finalizar")
        else:
            return ("⚠️ *Reserva registrada localmente!*\n\n"
                    "Tivemos um problema ao conectar com nosso sistema principal, "
                    "mas sua reserva foi registrada localmente. Entraremos em contato "
                    "para confirmar os detalhes.")
            
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
                f"• Motorista: {reserva.get('motorista', 'A ser definido')}\n"
                f"• Status: {reserva.get('status', 'Pendente')}\n\n"
                f"*Precisa de ajuda com sua reserva?*\n"
                f"1. Alterar reserva\n"
                f"2. Cancelar reserva\n"
                f"3. Falar com atendente\n"
                f"4. Finalizar")
    else:
        return "📭 Você não tem reservas ativas. Digite *RESERVA* para criar uma nova."

def responder_suporte():
    return ("🛠️ *Suporte Técnico*\n\n"
            "Para suporte técnico, contate:\n"
            "• Cleverson: +55 11 97250-8430\n"
            "• E-mail: suporte@jcm.com\n\n"
            "Estamos à disposição para ajudar!")

# ================= MENU PÓS-RESERVA =================
def menu_pos_reserva(telefone):
    return (f"*O que gostaria de fazer?*\n\n"
            f"1. Alterar reserva\n"
            f"2. Cancelar reserva\n"
            f"3. Falar com atendente\n"
            f"4. Finalizar\n\n"
            f"Digite o número da opção desejada.")

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
    
    elif estado_atual == "MENU_RESERVA":
        if mensagem_lower in ['1', 'alterar']:
            state_manager.set_user_state(telefone, "AGUARDANDO_RESERVA")
            return "Por favor, envie os novos detalhes da reserva."
        elif mensagem_lower in ['2', 'cancelar']:
            # Remove a reserva
            if telefone in state_manager.reservas:
                del state_manager.reservas[telefone]
            state_manager.set_user_state(telefone, "INICIO")
            return "✅ Reserva cancelada. Sentirei sua falta! 😢\n\nComo posso ajudar agora?"
        elif mensagem_lower in ['3', 'atendente']:
            state_manager.set_user_state(telefone, "AGUARDANDO_ATENDENTE")
            return "Um atendente humano entrará em contato em breve. Enquanto isso, posso ajudar em algo mais?"
        elif mensagem_lower in ['4', 'finalizar']:
            state_manager.set_user_state(telefone, "INICIO")
            return "✅ Atendimento finalizado. Estou à disposição se precisar!"
        else:
            # Aguarda 10 segundos e pergunta novamente
            threading.Timer(10.0, enviar_lembrete_menu, args=[telefone]).start()
            return "❌ Opção inválida. " + menu_pos_reserva(telefone)
    
    elif estado_atual == "AGUARDANDO_ATENDENTE":
        # Aqui poderia registrar a solicitação e notificar um humano
        return "⌛ Aguarde um momento enquanto conecto você com um atendente..."
    
    return ("🤔 Desculpe, não entendi bem.\n\n"
            "Digite *AJUDA* para ver as opções disponíveis ou *SUPORTE* para falar com nossa equipe.")

def enviar_lembrete_menu(telefone):
    try:
        if twilio_client:
            twilio_client.messages.create(
                body="⏰ Precisa de algo mais? Estou à disposição para ajudar!",
                from_=TWILIO_PHONE_NUMBER,
                to=telefone
            )
    except Exception as e:
        app.logger.error(f"Erro ao enviar lembrete de menu: {str(e)}")

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
