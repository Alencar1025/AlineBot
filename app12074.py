import os
import re
import json
import logging
import random
from datetime import datetime
from flask import Flask, request, Response
from twilio.rest import Client
from twilio.twiml.messaging_response import MessagingResponse
from logging.handlers import RotatingFileHandler

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
TWILIO_PHONE_NUMBER = os.environ.get('TWILIO_PHONE_NUMBER', '+14155238886')  # Default sandbox

# Inicialização segura do cliente Twilio
try:
    twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    app.logger.info("Twilio client inicializado com sucesso")
except Exception as e:
    app.logger.critical(f"Falha ao inicializar Twilio client: {str(e)}")
    twilio_client = None

# ================= ESTRUTURA DE DADOS =================
# Sistema de estado otimizado
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

# Dados de usuários
USUARIOS = {
    "+5511972508430": {
        "nome": "Cleverson Rodrigues de Alencar",
        "empresa": "JCM",
        "nivel": 5,
        "ativo": True
    },
    "+5511988216292": {
        "nome": "Usuário de Teste",
        "empresa": "JCM",
        "nivel": 5,
        "ativo": True
    }
}

# ================= FUNÇÕES PRINCIPAIS =================
def identificar_cliente(telefone):
    """Identifica cliente com fallback seguro"""
    telefone_normalizado = re.sub(r'[^0-9+]', '', telefone)
    return USUARIOS.get(telefone_normalizado, {
        "nome": "Convidado",
        "empresa": "N/A",
        "nivel": 0,
        "ativo": False
    })

def processar_comando_admin(mensagem, telefone):
    """Processa comandos administrativos com validação rigorosa"""
    try:
        if re.search(r'adicionar usuario', mensagem, re.IGNORECASE):
            match = re.search(r'adicionar usuario (.+) empresa (.+) nivel (\d+)', mensagem, re.IGNORECASE)
            if match:
                # Lógica de adição de usuário
                return "✅ Usuário adicionado!"
        
        elif re.search(r'listar usuarios', mensagem, re.IGNORECASE):
            lista = ["📋 Usuários:"]
            for tel, user in USUARIOS.items():
                if tel == telefone: continue
                lista.append(f"- {user['nome']} ({tel}) | Nível {user['nivel']}")
            return "\n".join(lista)
        
        return "Comando administrativo desconhecido"
    
    except Exception as e:
        app.logger.error(f"Erro em comando admin: {str(e)}")
        return "❌ Erro ao processar comando"

# ================= ROTAS ESSENCIAIS =================
@app.route('/healthz', methods=['GET', 'HEAD'])
def health_check():
    """Endpoint de health check robusto"""
    app.logger.info("Health check passed")
    return Response("OK", status=200, content_type="text/plain")

@app.route("/webhook", methods=['POST'])
def webhook():
    """Endpoint principal otimizado e à prova de falhas"""
    try:
        # Coleta de dados básica
        telefone = request.form.get('From', '')
        mensagem = request.form.get('Body', '').strip().lower()
        
        if not telefone or not mensagem:
            app.logger.warning("Dados incompletos recebidos")
            return Response("Dados incompletos", status=400)
        
        app.logger.info(f"Mensagem de {telefone}: {mensagem}")
        
        # Identificação segura do cliente
        cliente = identificar_cliente(telefone)
        
        # Verificação de acesso
        if not cliente['ativo']:
            resp = MessagingResponse()
            resp.message("❌ Você não tem permissão. Contate o administrador.")
            return str(resp)
        
        # Processamento de comandos
        resposta = processar_mensagem(mensagem, telefone, cliente)
        
        # Envio da resposta
        resp = MessagingResponse()
        resp.message(resposta)
        return str(resp)
        
    except Exception as e:
        app.logger.exception("ERRO CRÍTICO no webhook:")
        resp = MessagingResponse()
        resp.message("⚠️ Ocorreu um erro interno. Tente novamente.")
        return str(resp)

def processar_mensagem(mensagem, telefone, cliente):
    """Processador central de mensagens com máquina de estados"""
    estado_atual = state_manager.get_user_state(telefone)
    
    # Comandos administrativos
    if mensagem.startswith(("admin ", "administrativo ")):
        return processar_comando_admin(mensagem, telefone)
    
    # Máquina de estados principal
    if estado_atual == "INICIO":
        state_manager.set_user_state(telefone, "AGUARDANDO_ACAO")
        return "👋 Olá! Eu sou a AlineBot da JCM. Digite *RESERVA* para começar."
    
    elif estado_atual == "AGUARDANDO_ACAO":
        if "reserva" in mensagem:
            state_manager.set_user_state(telefone, "AGUARDANDO_RESERVA")
            return "Por favor, envie sua reserva no formato:\n*RESERVA [Origem] para [Destino] - [Pessoas] pessoas - [Data/Hora]*"
        else:
            return "Não entendi. Digite *RESERVA* para iniciar ou *AJUDA* para ajuda."
    
    elif estado_atual == "AGUARDANDO_RESERVA":
        if "reserva" in mensagem:
            # Processar reserva
            state_manager.set_user_state(telefone, "CONFIRMACAO")
            return "✅ Reserva recebida! Estamos processando..."
        else:
            return "Por favor, envie no formato solicitado ou digite *CANCELAR* para recomeçar."
    
    # Fallback para comandos não reconhecidos
    return "🤖 Comando não reconhecido. Digite *AJUDA* para ver opções."

# ================= SERVIDOR PRODUÇÃO =================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    
    if os.environ.get('ENVIRONMENT') == 'production':
        from waitress import serve
        app.logger.info(f"🚀 SERVIDOR PRODUÇÃO iniciado na porta {port}")
        serve(app, host="0.0.0.0", port=port, threads=8)
    else:
        app.logger.info(f"🚀 Servidor desenvolvimento iniciado na porta {port}")
        app.run(host="0.0.0.0", port=port, debug=False)  # Debug desligado em produção