# ---------- IMPORTS OBRIGATÓRIOS ----------
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
import re
import os
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime

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
    "saudacao": ["oi", "olá", "ola", "bom dia", "boa tarde", "boa noite", "aline", "alô", "hello", "ei", "e aí"],
    "ajuda": ["ajuda", "socorro", "opções", "comandos", "menu", "help"],
    "reserva": ["reserva", "reservar", "agendar", "viagem", "passagem", "voo", "roteiro", "pacote"],
    "pagar": ["pagar", "pagamento", "pague", "comprar", "pagto", "débito", "crédito", "boleto"],
    "status": ["status", "situação", "verificar", "consulta", "onde está", "localizar", "acompanhar"],
    "cancelar": ["cancelar", "desmarcar", "anular", "remover", "desistir", "estornar"],
    "suporte": ["suporte", "atendente", "humano", "pessoa", "falar com alguém", "operador"],
    "continuar": ["continuar", "seguir", "voltar", "retomar", "prosseguir"]
}

# ---------- CONTROLE DE ESTADO AVANÇADO ----------
# Armazena: {telefone: {"estado": str, "ultima_interacao": timestamp, "primeira_vez": bool}}
ESTADOS = {}

def obter_periodo_dia():
    """Retorna a saudação conforme o período do dia"""
    hora_atual = datetime.now().hour
    if 5 <= hora_atual < 12:
        return "Bom dia"
    elif 12 <= hora_atual < 18:
        return "Boa tarde"
    else:
        return "Boa noite"

def detectar_intencao(mensagem):
    """Detecta a intenção por palavras-chave com lógica melhorada"""
    mensagem = mensagem.lower().strip()
    
    # Verificar saudações especiais primeiro
    if any(saudacao in mensagem for saudacao in ["bom dia", "boa tarde", "boa noite"]):
        return "saudacao"
    
    # Verificar outros comandos
    for intencao, palavras in INTENTOES.items():
        if any(palavra in mensagem for palavra in palavras):
            return intencao
            
    # Verificação adicional para mensagens curtas
    if len(mensagem) <= 4:
        if mensagem in ["oi", "ola", "olá", "oi!"]:
            return "saudacao"
    
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

def saudacao_personalizada(cliente, primeira_vez):
    """Cria mensagem de saudação personalizada"""
    saudacao_periodo = obter_periodo_dia()
    
    if cliente:
        nome = cliente.get('Nome', 'cliente VIP').split()[0]  # Pega o primeiro nome
        tratamento = f"{saudacao_periodo}, {nome}!"
    else:
        tratamento = f"{saudacao_periodo}!"
    
    if primeira_vez:
        return tratamento + " Eu sou a Aline, assistente virtual da JCM Viagens 🧳✨\n\nComo posso ajudar?"
    else:
        return tratamento + " Que bom ver você de novo! Podemos continuar de onde paramos?"

# ---------- ROTA PRINCIPAL ATUALIZADA ----------
@app.route('/webhook', methods=['POST'])
def webhook():
    # Obter dados da mensagem
    from_number = request.values.get('From', '')
    mensagem = request.values.get('Body', '').strip()
    
    # Normalizar número de telefone
    telefone = re.sub(r'\D', '', from_number)[-11:]
    
    # Gerenciar estados do usuário
    estado_usuario = ESTADOS.get(telefone, {
        "estado": "INICIO",
        "ultima_interacao": datetime.now().isoformat(),
        "primeira_vez": True
    })
    
    # Calcular tempo desde a última interação (em minutos)
    ultima_interacao = datetime.fromisoformat(estado_usuario["ultima_interacao"])
    tempo_desde_ultima = (datetime.now() - ultima_interacao).total_seconds() / 60
    
    # Atualizar registro de interação
    estado_usuario["ultima_interacao"] = datetime.now().isoformat()
    ESTADOS[telefone] = estado_usuario
    
    # Detectar intenção
    intencao = detectar_intencao(mensagem)
    
    # Verificar se é cliente recorrente
    cliente = identificar_cliente(telefone)
    
    # Inicializar resposta
    resp = MessagingResponse()
    msg = resp.message()
    
    # ----- LÓGICA PRINCIPAL MELHORADA -----
    estado_atual = estado_usuario["estado"]
    
    # Se passou mais de 30 minutos desde a última mensagem, reiniciar conversa
    if tempo_desde_ultima > 30 and estado_atual != "INICIO":
        msg.body(f"{obter_periodo_dia()}! Percebi que passou um tempo desde nossa última conversa. Vamos recomeçar?")
        estado_usuario["estado"] = "INICIO"
        estado_usuario["primeira_vez"] = False
        ESTADOS[telefone] = estado_usuario
        return str(resp)
    
    # Estado INICIO - Saudação
    if estado_atual == "INICIO":
        if intencao in ["saudacao", "ajuda"] or estado_usuario["primeira_vez"]:
            # Saudação personalizada
            resposta = saudacao_personalizada(cliente, estado_usuario["primeira_vez"])
            resposta += "\n\n*Comandos disponíveis:*\n"
            resposta += "- RESERVA: Nova reserva\n"
            resposta += "- STATUS: Verificar reserva\n"
            resposta += "- PAGAR: Pagamento\n"
            resposta += "- CANCELAR: Cancelamento\n"
            resposta += "- SUPORTE: Atendente humano\n\n"
            resposta += "Digite o comando desejado!"
            
            msg.body(resposta)
            estado_usuario["estado"] = "AGUARDANDO_ACAO"
            estado_usuario["primeira_vez"] = False
            ESTADOS[telefone] = estado_usuario
            
        elif intencao == "continuar":
            msg.body("Vamos continuar de onde paramos! Qual era a última ação?")
            # Aqui você pode implementar lógica para recuperar o contexto anterior
            estado_usuario["estado"] = "AGUARDANDO_ACAO"
            ESTADOS[telefone] = estado_usuario
            
        else:
            msg.body("Não entendi. Digite *OI* para começar ou *AJUDA* para ver opções")
    
    # Estado AGUARDANDO_ACAO - Menu principal
    elif estado_atual == "AGUARDANDO_ACAO":
        if intencao == "reserva":
            msg.body("✈️ Para reservar, envie:\nRESERVA [ORIGEM] para [DESTINO] - [PESSOAS] pessoas - [DATA]\n\nExemplo:\nRESERVA GRU para São Paulo - 4 pessoas - 20/07")
            estado_usuario["estado"] = "AGUARDANDO_RESERVA"
            ESTADOS[telefone] = estado_usuario
        
        elif intencao == "pagar":
            msg.body("💳 Link para pagamento: https://jcmviagens.com/pagar\n\nEnvie o número da reserva para pagamento específico")
            estado_usuario["estado"] = "AGUARDANDO_PAGAMENTO"
            ESTADOS[telefone] = estado_usuario
        
        elif intencao == "status":
            msg.body("🔍 Digite o número da reserva para verificar o status:")
            estado_usuario["estado"] = "AGUARDANDO_NUMERO_RESERVA"
            ESTADOS[telefone] = estado_usuario
        
        elif intencao == "cancelar":
            msg.body("❌ Digite o número da reserva que deseja cancelar:")
            estado_usuario["estado"] = "AGUARDANDO_CANCELAMENTO"
            ESTADOS[telefone] = estado_usuario
        
        elif intencao == "suporte":
            msg.body("⏳ Redirecionando para atendente humano...")
            # Adicionar lógica para notificar atendente aqui
            estado_usuario["estado"] = "SUPORTE_ATIVO"
            ESTADOS[telefone] = estado_usuario
        
        else:
            msg.body("⚠️ Opção não reconhecida. Digite *AJUDA* para ver opções")
    
    # ----- ESTADO DE RESERVA -----
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
        
        estado_usuario["estado"] = "INICIO"
        ESTADOS[telefone] = estado_usuario
    
    # ----- ESTADO DE STATUS -----
    elif estado_atual == "AGUARDANDO_NUMERO_RESERVA":
        if mensagem.isdigit():
            # Simular busca na planilha
            msg.body(f"✅ Reserva #{mensagem} encontrada!\nStatus: Confirmada\nData: 15/07/2025\nValor: R$ 1.200,00")
        else:
            msg.body("❌ Número inválido. Digite apenas números (ex: 175)")
        
        estado_usuario["estado"] = "INICIO"
        ESTADOS[telefone] = estado_usuario
    
    # ----- ESTADO DE CANCELAMENTO -----
    elif estado_atual == "AGUARDANDO_CANCELAMENTO":
        if mensagem.isdigit():
            msg.body(f"✅ Reserva #{mensagem} cancelada com sucesso!\nValor será estornado em até 5 dias úteis.")
        else:
            msg.body("❌ Número inválido. Digite apenas números (ex: 175)")
        
        estado_usuario["estado"] = "INICIO"
        ESTADOS[telefone] = estado_usuario
    
    # ----- ESTADO DE PAGAMENTO -----
    elif estado_atual == "AGUARDANDO_PAGAMENTO":
        if mensagem.isdigit():
            msg.body(f"💳 Pagamento para reserva #{mensagem}:\n🔗 Link: https://jcmviagens.com/pagar?id={mensagem}\n\nValidade: 24 horas")
        else:
            msg.body("⚠️ Digite apenas o número da reserva para pagamento")
        
        estado_usuario["estado"] = "INICIO"
        ESTADOS[telefone] = estado_usuario
    
    # ----- ESTADO DE SUPORTE -----
    elif estado_atual == "SUPORTE_ATIVO":
        msg.body("⌛ Um atendente humano já foi notificado e entrará em contato em breve!")
        estado_usuario["estado"] = "INICIO"
        ESTADOS[telefone] = estado_usuario
    
    # ----- OUTROS ESTADOS -----
    else:
        msg.body("🔄 Reiniciando conversa... Digite *OI* para começar")
        estado_usuario["estado"] = "INICIO"
        ESTADOS[telefone] = estado_usuario
    
    return str(resp)

# ... (código existente)

# ========== ROTA DE WARM-UP ==========
@app.route('/warmup')
def warmup():
    print("🔥 Instance warmed up!")
    return "Instance is warm!", 200

# ---------- INICIAR SERVIDOR ----------
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
