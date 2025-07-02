# ---------- IMPORTS OBRIGATÓRIOS ----------
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
import re
import os
import gspread
from google.oauth2.service_account import Credentials

# ---------- CONFIGURAÇÕES INICIAIS ----------
app = Flask(__name__)

# Autenticação Twilio (preencher no Render)
twilio_account_sid = os.environ.get('TWILIO_ACCOUNT_SID')
twilio_auth_token = os.environ.get('TWILIO_AUTH_TOKEN')

# Configuração Google Sheets
SCOPES = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
GOOGLE_CREDS = os.environ.get('GOOGLE_CREDS_JSON')

# ---------- SISTEMA DE INTENÇÕES ATUALIZADO ----------
INTENTOES = {
    "saudacao": ["oi", "olá", "ola", "bom dia", "boa tarde", "boa noite", "aline", "alô", "hello"],
    "ajuda": ["ajuda", "socorro", "opções", "comandos", "menu", "help"],
    "reserva": ["reserva", "reservar", "agendar", "viagem", "passagem", "voo", "roteiro"],
    "pagar": ["pagar", "pagamento", "pague", "comprar", "pagto", "débito", "crédito"],
    "status": ["status", "situação", "verificar", "consulta", "onde está", "localizar"],
    "cancelar": ["cancelar", "desmarcar", "anular", "remover", "desistir", "estornar"],
    "suporte": ["suporte", "atendente", "humano", "pessoa", "falar com alguém", "operador"]
}

# ---------- CONTROLE DE ESTADO ----------
ESTADOS = {}

def detectar_intencao(mensagem):
    """Detecta a intenção por palavras-chave (versão melhorada)"""
    mensagem = mensagem.lower().strip()
    for intencao, palavras in INTENTOES.items():
        if any(palavra in mensagem for palavra in palavras):
            return intencao
    return None

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
        
        telefone_limpo = re.sub(r'\D', '', telefone)[-11:]
        
        for cliente in clientes:
            tel_planilha = re.sub(r'\D', '', cliente['Telefone'])[-11:]
            if telefone_limpo == tel_planilha:
                return cliente
        
        return None
    except:
        return None

# ---------- ROTA PRINCIPAL ATUALIZADA ----------
@app.route('/webhook', methods=['POST'])
def webhook():
    # Obter dados da mensagem
    from_number = request.values.get('From', '')
    mensagem = request.values.get('Body', '').strip()
    
    # Normalizar número de telefone
    telefone = re.sub(r'\D', '', from_number)[-11:]
    
    # Detectar intenção
    intencao = detectar_intencao(mensagem)
    
    # Verificar se é cliente recorrente
    cliente = identificar_cliente(telefone)
    saudacao = "Olá cliente VIP! " if cliente else "Olá! "
    
    # Gerenciar estados
    estado_atual = ESTADOS.get(telefone, "INICIO")
    
    # Inicializar resposta
    resp = MessagingResponse()
    msg = resp.message()
    
    # ----- LÓGICA PRINCIPAL MELHORADA -----
    if estado_atual == "INICIO":
        if intencao in ["saudacao", "ajuda"]:
            resposta = saudacao + "Bem-vindo à JCM Viagens 🧳✨\n\n"
            resposta += "*Comandos disponíveis:*\n"
            resposta += "- RESERVA: Nova reserva\n"
            resposta += "- STATUS: Verificar reserva\n"
            resposta += "- PAGAR: Pagamento\n"
            resposta += "- CANCELAR: Cancelamento\n"
            resposta += "- SUPORTE: Atendente humano"
            msg.body(resposta)
            ESTADOS[telefone] = "AGUARDANDO_ACAO"
        else:
            msg.body("Não entendi. Digite *OI* ou *AJUDA* para ver opções")
    
    elif estado_atual == "AGUARDANDO_ACAO":
        if intencao == "reserva":
            msg.body("✈️ Para reservar, envie:\nRESERVA [ORIGEM] para [DESTINO] - [PESSOAS] pessoas - [DATA]\n\nExemplo:\nRESERVA GRU para São Paulo - 4 pessoas - 20/07")
            ESTADOS[telefone] = "AGUARDANDO_RESERVA"
        
        elif intencao == "pagar":
            msg.body("💳 Link para pagamento: https://jcmviagens.com/pagar\n\nEnvie o número da reserva para pagamento específico")
            ESTADOS[telefone] = "AGUARDANDO_PAGAMENTO"
        
        elif intencao == "status":
            msg.body("🔍 Digite o número da reserva para verificar o status:")
            ESTADOS[telefone] = "AGUARDANDO_NUMERO_RESERVA"
        
        elif intencao == "cancelar":
            msg.body("❌ Digite o número da reserva que deseja cancelar:")
            ESTADOS[telefone] = "AGUARDANDO_CANCELAMENTO"
        
        elif intencao == "suporte":
            msg.body("⏳ Redirecionando para atendente humano...")
            # Adicionar lógica para notificar atendente aqui
            ESTADOS[telefone] = "SUPORTE_ATIVO"
        
        else:
            msg.body("⚠️ Opção não reconhecida. Digite *AJUDA* para ver opções")
    
    # ----- ESTADO DE RESERVA MELHORADO -----
    elif estado_atual == "AGUARDANDO_RESERVA":
        if "reserva" in mensagem.lower():
            # Extrair dados da reserva (exemplo simplificado)
            try:
                partes = mensagem.split('-')
                origem_destino = partes[0].replace('RESERVA', '').strip()
                pessoas = partes[1].replace('pessoas', '').strip()
                data = partes[2].strip()
                
                msg.body(f"✅ Reserva recebida!\n\nOrigem: {origem_destino}\nPessoas: {pessoas}\nData: {data}\n\nEstamos processando sua solicitação!")
            except:
                msg.body("📝 Formato incorreto. Envie no formato:\nRESERVA [ORIGEM] para [DESTINO] - [PESSOAS] pessoas - [DATA]")
        else:
            msg.body("📝 Formato incorreto. Envie no formato:\nRESERVA [ORIGEM] para [DESTINO] - [PESSOAS] pessoas - [DATA]")
        
        ESTADOS[telefone] = "INICIO"
    
    # ----- ESTADO DE STATUS MELHORADO -----
    elif estado_atual == "AGUARDANDO_NUMERO_RESERVA":
        if mensagem.isdigit():
            # Simular busca na planilha
            msg.body(f"✅ Reserva #{mensagem} encontrada!\nStatus: Confirmada\nData: 15/07/2025\nValor: R$ 1.200,00")
        else:
            msg.body("❌ Número inválido. Digite apenas números (ex: 175)")
        
        ESTADOS[telefone] = "INICIO"
    
    # ----- ESTADO DE CANCELAMENTO MELHORADO -----
    elif estado_atual == "AGUARDANDO_CANCELAMENTO":
        if mensagem.isdigit():
            msg.body(f"✅ Reserva #{mensagem} cancelada com sucesso!\nValor será estornado em até 5 dias úteis.")
        else:
            msg.body("❌ Número inválido. Digite apenas números (ex: 175)")
        
        ESTADOS[telefone] = "INICIO"
    
    # ----- ESTADO DE PAGAMENTO MELHORADO -----
    elif estado_atual == "AGUARDANDO_PAGAMENTO":
        if mensagem.isdigit():
            msg.body(f"💳 Pagamento para reserva #{mensagem}:\n🔗 Link: https://jcmviagens.com/pagar?id={mensagem}\n\nValidade: 24 horas")
        else:
            msg.body("⚠️ Digite apenas o número da reserva para pagamento")
        
        ESTADOS[telefone] = "INICIO"
    
    # ----- OUTROS ESTADOS -----
    else:
        msg.body("🔄 Reiniciando conversa... Digite *OI* para começar")
        ESTADOS[telefone] = "INICIO"
    
    return str(resp)

# ---------- INICIAR SERVIDOR ----------
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
