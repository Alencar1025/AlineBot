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
    
    try:
        # Processar comandos administrativos (Alencar)
        if mensagem.lower().startswith("admin ") or mensagem.lower().startswith("administrativo "):
            resposta = processar_comando_admin(mensagem, telefone)
            try:
                client.messages.create(
                    body=resposta,
                    from_=f"whatsapp:{TWILIO_PHONE_NUMBER}",
                    to=f"whatsapp:{telefone}"
                )
            except Exception as e:
                app.logger.error(f"Erro ao enviar resposta administrativa: {str(e)}")
            
            # RESPOSTA OBRIGATÓRIA PARA O TWILIO
            resp = MessagingResponse()
            return str(resp)
        
        # ... (restante do código original) ...
        
        # VERIFICAÇÃO DE USUÁRIO ATIVO (ATUALIZADO)
        if not cliente.get('ativo', False):
            resp = MessagingResponse()
            msg = resp.message()
            msg.body("❌ Você não tem permissão para usar este sistema. Contate o administrador.")
            return str(resp)
        
        # ... (restante do código) ...
        
        # RESPOSTA PADRÃO PARA CASOS NÃO TRATADOS
        resp = MessagingResponse()
        resp.message("🤖 Comando não reconhecido. Digite AJUDA para ver as opções.")
        return str(resp)
        
    except Exception as e:
        app.logger.error(f"ERRO CRÍTICO: {str(e)}")
        resp = MessagingResponse()
        resp.message("⚠️ Ocorreu um erro interno. Nossa equipe já foi notificada.")
        return str(resp)
    
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
