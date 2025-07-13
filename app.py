import os
import re
import json
import logging
import random
from datetime import datetime
from flask import Flask, request
from twilio.rest import Client
from twilio.twiml.messaging_response import MessagingResponse
from logging.handlers import RotatingFileHandler

# ================= CONFIGURAÇÃO INICIAL =================
app = Flask(__name__)

# Configuração de logs
log_handler = RotatingFileHandler('alinebot.log', maxBytes=1000000, backupCount=3)
log_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
app.logger.addHandler(log_handler)
app.logger.setLevel(logging.INFO)

# Configurações Twilio
TWILIO_ACCOUNT_SID = os.environ.get('TWILIO_ACCOUNT_SID')
TWILIO_AUTH_TOKEN = os.environ.get('TWILIO_AUTH_TOKEN')
TWILIO_PHONE_NUMBER = os.environ.get('TWILIO_PHONE_NUMBER')
client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

# ================= ESTRUTURA DE DADOS =================
# (Mantido igual ao seu código original)
# ... [Seu código existente aqui] ...

# ================= NOVA ROTA HEALTH CHECK =================
@app.route('/healthz', methods=['GET', 'HEAD'])
def health_check():
    app.logger.info("Health check solicitado")
    return "OK", 200

# ================= WEBHOOK ATUALIZADO =================
@app.route("/webhook", methods=['POST'])
def webhook():
    telefone = request.form.get('From', '')
    mensagem = request.form.get('Body', '').strip()
    
    # Log detalhado
    app.logger.info(f"Mensagem recebida de {telefone}: {mensagem}")
    
    # ... [Restante do seu código existente] ...

# ================= CONFIGURAÇÃO SERVIDOR PRODUÇÃO =================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    
    # Ambiente de produção
    if os.environ.get('ENVIRONMENT') == 'production':
        from waitress import serve
        app.logger.info(f"🚀 Iniciando servidor PRODUÇÃO na porta {port}")
        serve(app, host="0.0.0.0", port=port)
    else:
        app.logger.info(f"🚀 Iniciando servidor desenvolvimento na porta {port}")
        app.run(host="0.0.0.0", port=port)
