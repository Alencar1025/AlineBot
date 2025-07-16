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

# Configurações Google Sheets (INTEGRAÇÃO ATUALIZADA)
GOOGLE_CREDS_JSON = os.environ.get('GOOGLE_CREDS_JSON')
if GOOGLE_CREDS_JSON:
    try:
        GOOGLE_CREDS = json.loads(GOOGLE_CREDS_JSON)
    except json.JSONDecodeError:
        app.logger.error("Falha ao decodificar GOOGLE_CREDS_JSON. Verifique o formato.")
        GOOGLE_CREDS = None
else:
    GOOGLE_CREDS = None

# ID da planilha principal (ATUALIZADO)
SHEET_KEY = os.environ.get('JCM_SHEET_ID')  # ID da planilha

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

# Inicialização Google Sheets (CONFIGURAÇÃO PARA SITE)
if GOOGLE_CREDS and SHEET_KEY:
    try:
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

# ================= MELHORIAS NO STATUS DE RESERVA =================
def buscar_reservas_cliente(telefone):
    """Busca todas reservas do cliente pelo telefone"""
    if not gc:
        return []
    
    try:
        sheet = gc.open_by_key(SHEET_KEY).worksheet("Reservas_JCM")
        records = sheet.get_all_records()
        
        reservas_cliente = []
        telefone_normalizado = re.sub(r'[^0-9+]', '', telefone)
        
        for row in records:
            # Comparar telefones normalizados
            row_telefone = re.sub(r'[^0-9+]', '', row.get('Telefone_Cliente', ''))
            if row_telefone == telefone_normalizado:
                reservas_cliente.append({
                    'id': row.get('ID_Reserva', 'N/A'),
                    'origem': row.get('ID_Local_Origem', 'N/A'),
                    'destino': row.get('ID_Local_Destino', 'N/A'),
                    'data': row.get('Data_Coleta', 'N/A'),
                    'hora': row.get('Hora_Coleta', 'N/A'),
                    'status': row.get('Status', 'Pendente'),
                    'motorista': row.get('ID_Motorista', 'A ser definido')
                })
        
        return reservas_cliente
    except Exception as e:
        app.logger.error(f"Erro ao buscar reservas: {str(e)}")
        return []

def responder_status_reservas(telefone):
    """Resposta aprimorada com todas reservas do cliente"""
    reservas = buscar_reservas_cliente(telefone)
    
    if reservas:
        resposta = ["🔍 *Suas Reservas Ativas:*"]
        for i, reserva in enumerate(reservas, 1):
            resposta.append(
                f"\n*Reserva {i}:*\n"
                f"• ID: {reserva['id']}\n"
                f"• Origem: {reserva['origem']}\n"
                f"• Destino: {reserva['destino']}\n"
                f"• Data/Hora: {reserva['data']} {reserva['hora']}\n"
                f"• Motorista: {reserva['motorista']}\n"
                f"• Status: {reserva['status']}"
            )
        
        resposta.append("\n*O que deseja fazer?*\n1. Alterar reserva\n2. Cancelar reserva\n3. Falar com atendente\n4. Finalizar")
        return "\n".join(resposta)
    else:
        return "📭 Você não tem reservas ativas. Digite *RESERVA* para criar uma nova."

# ================= ATUALIZAÇÃO NO PROCESSAMENTO DE RESERVAS =================
def registrar_reserva_google_sheets(dados):
    if not gc:
        return False
    
    try:
        sheet = gc.open_by_key(SHEET_KEY).worksheet("Reservas_JCM")
        
        # Formatar data atual no padrão brasileiro (dd/mm/yy)
        data_atual = datetime.now().strftime('%d/%m/%y')
        
        # Preencher dados padrão se ausentes
        data_reserva = dados.get('data', data_atual)
        hora_reserva = dados.get('hora', '00:00')
        
        # Gerar ID do motorista
        motorista_id = f"CONT_{random.randint(1,3):03d}"
        
        # ID de reserva único
        reserva_id = f"RES_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        # LISTA DE VALORES COM TELEFONE DO CLIENTE (NOVA COLUNA)
        nova_linha = [
            reserva_id,                          # ID_Reserva
            dados.get('cliente', 'N/A'),         # Cliente
            dados.get('telefone', 'N/A'),        # Telefone_Cliente (NOVO)
            data_atual,                          # Data do registro
            hora_reserva,                        # Hora_Coleta
            dados.get('origem', 'N/A'),          # ID_Local_Origem
            dados.get('destino', 'N/A'),         # ID_Local_Destino
            "Sedan Executivo",                   # Categoria_Veiculo
            motorista_id,                        # ID_Motorista
            "Confirmado",                        # Status
            "300.00",                            # Valor
            "Avulso",                            # Tipo_Faturamento
            "Pendente",                          # Status_Faturamento
            "",                                  # Data_Vencimento
            "",                                  # Valor_Entrada
            "",                                  # Link_Pagamento
            ""                                   # Comprovante_Final
        ]
        
        app.logger.info(f"Registrando reserva: {nova_linha}")
        sheet.append_row(nova_linha)
        return reserva_id
    except Exception as e:
        app.logger.error(f"ERRO GOOGLE SHEETS: {str(e)}")
        return False

# ================= ATUALIZAÇÃO NO PROCESSADOR DE MENSAGENS =================
def processar_mensagem(mensagem_lower, mensagem_original, telefone, cliente):
    # ... (código anterior) ...
    
    if mensagem_lower in ['status', 'minhas reservas', 'ver reservas']:
        return responder_status_reservas(telefone)  # Função aprimorada
    
    # ... (restante do código) ...

# ================= ATUALIZAÇÃO NO FLUXO DE RESERVA =================
def processar_reserva(mensagem, telefone, cliente):
    # ... (código anterior) ...
    
    # Registro na planilha com telefone
    reserva_id = registrar_reserva_google_sheets({
        'cliente': cliente['nome'],
        'telefone': telefone,  # TELEFONE ADICIONADO
        'origem': dados['origem'],
        'destino': dados['destino'],
        'data': dados['data'],
        'hora': dados['hora']
    })
    
    # ... (restante do código) ...

# ================= CONFIGURAÇÕES DE SEGURANÇA =================
def normalizar_telefone(telefone):
    """Remove todos caracteres não numéricos"""
    return re.sub(r'[^0-9+]', '', telefone)

# ================= FUNÇÕES ADICIONAIS PARA RESERVAS =================
def cancelar_reserva(reserva_id, telefone):
    """Cancela uma reserva na planilha"""
    if not gc:
        return False
    
    try:
        sheet = gc.open_by_key(SHEET_KEY).worksheet("Reservas_JCM")
        cell = sheet.find(reserva_id)
        
        if cell:
            # Atualiza status para Cancelado
            sheet.update_cell(cell.row, 10, "Cancelado")  # Coluna 10 = Status
            return True
    except Exception as e:
        app.logger.error(f"Erro ao cancelar reserva: {str(e)}")
    
    return False

# ... (restante do código da Aline Bot permanece igual) ...

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
