# ---------- IMPORTS OBRIGATÓRIOS ----------
from flask import Flask, request, jsonify
from twilio.rest import Client
from twilio.twiml.messaging_response import MessagingResponse
from datetime import datetime, timedelta
import gspread
from google.oauth2.service_account import Credentials
import os
import re
import random

# ---------- CONFIGURAÇÕES INICIAIS ----------
app = Flask(__name__)

# Autenticação Twilio (preencher no Render)
twilio_client = Client(
    os.environ.get('TWILIO_ACCOUNT_SID'),
    os.environ.get('TWILIO_AUTH_TOKEN')
)

# Configuração Google Sheets
SCOPES = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
GOOGLE_CREDS = os.environ.get('GOOGLE_CREDS_JSON')

# ---------- FUNÇÕES PRINCIPAIS ----------
def conectar_google_sheets():
    """Conecta às planilhas do Google"""
    try:
        creds = Credentials.from_service_account_info(eval(GOOGLE_CREDS), scopes=SCOPES)
        return gspread.authorize(creds)
    except Exception as e:
        print(f"ERRO CONEXÃO GOOGLE: {str(e)}")
        return None

def identificar_cliente(telefone):
    """Busca cliente na planilha de recorrentes"""
    try:
        gc = conectar_google_sheets()
        planilha = gc.open("Clientes_Recorrentes").sheet1
        clientes = planilha.get_all_records()
        
        # Padroniza número
        telefone_limpo = re.sub(r'\D', '', telefone)[-11:]  # Mantém últimos 11 dígitos
        
        for cliente in clientes:
            tel_planilha = re.sub(r'\D', '', cliente['Telefone'])[-11:]
            if telefone_limpo == tel_planilha:
                return cliente
        
        return None
    except Exception as e:
        print(f"ERRO IDENTIFICAÇÃO: {str(e)}")
        return None

def verificar_disponibilidade(data, horario, duracao):
    """Verifica motoristas disponíveis na agenda"""
    try:
        gc = conectar_google_sheets()
        planilha = gc.open("Agenda_Motoristas").sheet1
        slots = planilha.get_all_records()
        
        # Converter para objetos datetime
        hora_inicio = datetime.strptime(f"{data} {horario}", "%Y-%m-%d %H:%M")
        hora_fim = hora_inicio + timedelta(hours=duracao)
        
        motoristas_disponiveis = []
        
        for slot in slots:
            slot_inicio = datetime.strptime(f"{slot['Data']} {slot['Horário Início']}", "%Y-%m-%d %H:%M")
            slot_fim = datetime.strptime(f"{slot['Data']} {slot['Horário Fim']}", "%Y-%m-%d %H:%M")
            
            if (hora_inicio >= slot_inicio) and (hora_fim <= slot_fim) and (slot['Status'] == 'Disponível'):
                motoristas_disponiveis.append(slot['Motorista'])
        
        return motoristas_disponiveis
    except Exception as e:
        print(f"ERRO DISPONIBILIDADE: {str(e)}")
        return []

def calcular_valor_reserva(tipo_viagem, tipo_veiculo, distancia):
    """Calcula valor com base nas regras"""
    try:
        gc = conectar_google_sheets()
        planilha = gc.open("Regras_Reservas").sheet1
        regras = planilha.get_all_records()
        
        for regra in regras:
            if (regra['Tipo de Viagem'] == tipo_viagem and 
                regra['Tipo de Veículo'] == tipo_veiculo):
                
                # Extrai fórmula de cálculo
                formula = regra['Cálculo de Valor']
                base = float(re.search(r'R\$\s*(\d+)', formula).group(1))
                por_km = float(re.search(r'R\$\s*(\d+,\d+)', formula).group(1).replace(',', '.'))
                
                return base + (por_km * distancia)
        
        # Valor padrão se não encontrar regra
        return 200 + (3.5 * distancia)
    except Exception as e:
        print(f"ERRO CÁLCULO: {str(e)}")
        return None

def registrar_reserva(dados):
    """Registra reserva em todas planilhas"""
    try:
        gc = conectar_google_sheets()
        
        # Agenda Motoristas
        agenda = gc.open("Agenda_Motoristas").sheet1
        agenda.append_row([
            dados['data'],
            dados['motorista'],
            dados['veiculo'],
            dados['placa'],
            dados['hora_inicio'],
            dados['hora_fim'],
            dados['cliente_nome'],
            dados['cliente_tel'],
            dados['origem'],
            dados['destino'],
            "Confirmado",
            dados['observacoes']
        ])
        
        # Pagamentos
        pagamentos = gc.open("Pagamentos").sheet1
        pagamentos.append_row([
            f"RES-{random.randint(1000,9999)}",
            dados['cliente_tel'],
            dados['valor_total'],
            dados['valor_entrada'],
            "Pix" if dados['valor_entrada'] > 0 else "Faturamento",
            datetime.now().strftime("%Y-%m-%d"),
            "Pendente" if dados['valor_entrada'] < dados['valor_total'] else "Pago",
            dados['link_pagamento'],
            dados['data'],
            ""
        ])
        
        # Histórico
        historico = gc.open("Historico_Interacoes").sheet1
        historico.append_row([
            datetime.now().strftime("%Y-%m-%d"),
            datetime.now().strftime("%H:%M"),
            dados['cliente_tel'],
            f"Reserva: {dados['origem']} para {dados['destino']}",
            f"Reserva #{dados['id']} confirmada",
            "Aline",
            "Concluído"
        ])
        
        return True
    except Exception as e:
        print(f"ERRO REGISTRO: {str(e)}")
        return False

# ---------- ROTAS DO WHATSAPP ----------
@app.route("/webhook", methods=["POST"])
def webhook():
    # Processar mensagem recebida
    mensagem = request.form.get("Body", "").strip().lower()
    telefone = request.form.get("From", "")
    
    # Identificar cliente
    cliente = identificar_cliente(telefone)
    saudacao = "Bom dia" if datetime.now().hour < 12 else "Boa tarde"
    
    if cliente:
        resposta = f"{saudacao}, {cliente['Nome']}! Como posso ajudar?"
    else:
        resposta = f"{saudacao}! Sou a Aline, assistente da JC Transfers. Digite AJUDA para ver opções."
    
    # Comandos principais
    if "reserv" in mensagem:
        resposta = "Para reservar, envie:\nRESERVA [ORIGEM] para [DESTINO] - [PESSOAS] pessoas - [DATA]\nEx: RESERVA GRU para São Paulo - 4 pessoas - 20/07"
    
    elif "ajuda" in mensagem:
        resposta = "Comandos disponíveis:\n\n" \
                   "• RESERVA: Iniciar nova reserva\n" \
                   "• STATUS: Verificar reserva existente\n" \
                   "• PAGAR: Link para pagamento\n" \
                   "• CANCELAR: Cancelar reserva\n" \
                   "• SUPORTE: Falar com atendente"
    
    elif mensagem.startswith("reserva "):
        try:
            # Exemplo: "reserva gru para são paulo - 4 pessoas - 20/07"
            partes = mensagem.split(" ")
            origem = partes[1]
            destino = partes[3]
            pessoas = int(partes[5])
            data = partes[8]
            
            # Determinar tipo de veículo
            tipo_veiculo = "Sedan" if pessoas <= 4 else "Minivan" if pessoas <= 8 else "Van"
            
            # Calcular distância (simulação)
            distancia = 100 if "gru" in origem.lower() else 200
            
            # Calcular valor
            valor = calcular_valor_reserva("Aeroporto", tipo_veiculo, distancia)
            
            # Verificar disponibilidade
            motoristas = verificar_disponibilidade(data, "08:00", 4)  # 4h estimadas
            
            if motoristas:
                resposta = f"✅ RESERVA DISPONÍVEL!\n" \
                           f"De: {origem.upper()}\n" \
                           f"Para: {destino.upper()}\n" \
                           f"Veículo: {tipo_veiculo} ({pessoas} pessoas)\n" \
                           f"Valor: R${valor:.2f}\n\n" \
                           f"Digite CONFIRMAR para finalizar"
            else:
                resposta = "⚠️ Nenhum motorista disponível nesta data. Tente outra data ou horário."
                
        except Exception as e:
            resposta = "⚠️ Formato inválido! Use:\nRESERVA [ORIGEM] para [DESTINO] - [PESSOAS] pessoas - [DATA]"

    elif "confirmar" in mensagem:
        resposta = "✅ Reserva confirmada! Em instantes enviarei o link de pagamento.\n\n" \
                   "Acompanhe seu motorista em tempo real com o código: JCT-2025"
        
    else:
        resposta = "Não entendi. Digite AJUDA para ver opções disponíveis."

    # Registrar interação
    try:
        gc = conectar_google_sheets()
        planilha = gc.open("Historico_Interacoes").sheet1
        planilha.append_row([
            datetime.now().strftime("%Y-%m-%d"),
            datetime.now().strftime("%H:%M"),
            telefone,
            mensagem,
            resposta[:100],  # Limita tamanho
            "Aline",
            "Processado"
        ])
    except:
        pass

    # Enviar resposta via Twilio
    twiml = MessagingResponse()
    twiml.message(resposta)
    return str(twiml)

# ---------- ROTA DE STATUS ----------
@app.route("/")
def status():
    return "Aline Bot Online! Última atualização: " + datetime.now().strftime("%d/%m/%Y %H:%M")

# ---------- INICIALIZAÇÃO ----------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)