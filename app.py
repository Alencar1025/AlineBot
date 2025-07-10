# ---------- IMPORTS OBRIGATÓRIOS ----------
from flask import Flask, request, jsonify
from twilio.twiml.messaging_response import MessagingResponse
import re
import os
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
import threading
import time
import requests
import logging
from functools import lru_cache
import json

# ---------- CONFIGURAÇÕES INICIAIS ----------
app = Flask(__name__)

# Configuração de Logs
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)
logging.getLogger('googleapiclient').setLevel(logging.WARNING)

# Autenticação Twilio (preencher no Render)
twilio_account_sid = os.environ.get('TWILIO_ACCOUNT_SID')
twilio_auth_token = os.environ.get('TWILIO_AUTH_TOKEN')

# ========== CONFIGURAÇÃO GOOGLE SHEETS ATUALIZADA ==========
SCOPES = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]

# Carregar credenciais do JSON único
creds_json = os.environ.get('GOOGLE_CREDS_JSON')
if creds_json:
    try:
        GOOGLE_CREDS = json.loads(creds_json)
        print("✅ Credenciais Google carregadas com sucesso!")
    except Exception as e:
        print(f"❌ ERRO ao decodificar JSON: {str(e)}")
        GOOGLE_CREDS = {}
else:
    print("⚠️ AVISO: GOOGLE_CREDS_JSON não encontrada!")
    GOOGLE_CREDS = {}

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
ESTADOS = {}

def obter_periodo_dia():
    hora_atual = datetime.now().hour
    if 5 <= hora_atual < 12:
        return "Bom dia"
    elif 12 <= hora_atual < 18:
        return "Boa tarde"
    else:
        return "Boa noite"

def detectar_intencao(mensagem):
    mensagem = mensagem.lower().strip()
    
    if any(saudacao in mensagem for saudacao in ["bom dia", "boa tarde", "boa noite"]):
        return "saudacao"
    
    for intencao, palavras in INTENTOES.items():
        if any(palavra in mensagem for palavra in palavras):
            return intencao
            
    if len(mensagem) <= 4:
        if mensagem in ["oi", "ola", "olá", "oi!"]:
            return "saudacao"
    
    return None

def conectar_google_sheets():
    try:
        if not GOOGLE_CREDS:
            print("❌ Credenciais Google não disponíveis!")
            return None
            
        # Extrair e formatar a chave privada corretamente
        private_key = GOOGLE_CREDS.get('private_key', '')
        private_key = private_key.replace('\\\\n', '\n')  # Para ambientes Windows/Linux
        private_key = private_key.replace('\\n', '\n')     # Para ambientes Render/Cloud
        
        # Criar credenciais com a chave formatada
        creds_info = {
            "type": GOOGLE_CREDS["type"],
            "project_id": GOOGLE_CREDS["project_id"],
            "private_key_id": GOOGLE_CREDS["private_key_id"],
            "private_key": private_key,
            "client_email": GOOGLE_CREDS["client_email"],
            "client_id": GOOGLE_CREDS["client_id"],
            "auth_uri": GOOGLE_CREDS["auth_uri"],
            "token_uri": GOOGLE_CREDS["token_uri"],
            "auth_provider_x509_cert_url": GOOGLE_CREDS["auth_provider_x509_cert_url"],
            "client_x509_cert_url": GOOGLE_CREDS["client_x509_cert_url"],
            "universe_domain": GOOGLE_CREDS.get("universe_domain", "googleapis.com")
        }
        
        creds = Credentials.from_service_account_info(creds_info, scopes=SCOPES)
        return gspread.authorize(creds)
    except Exception as e:
        print(f"ERRO CONEXÃO GOOGLE: {str(e)}")
        return None

# ========== FUNÇÃO DE BUSCA EM PLANILHAS ==========
@lru_cache(maxsize=100)
def buscar_na_planilha(nome_planilha, coluna_busca, valor_busca):
    try:
        gc = conectar_google_sheets()
        if not gc:
            print("❌ Conexão não estabelecida!")
            return None
            
        planilha = gc.open(nome_planilha).sheet1
        dados = planilha.get_all_records()
        
        for linha in dados:
            if str(linha[coluna_busca]).strip() == str(valor_busca).strip():
                return linha
        return None
    except Exception as e:
        print(f"ERRO BUSCA {nome_planilha}: {str(e)}")
        return None

# ========== IDENTIFICAÇÃO DO CLIENTE ==========
def identificar_cliente(telefone):
    """Busca informações do cliente na planilha"""
    try:
        # Buscar na planilha de clientes especiais
        cliente = buscar_na_planilha("Clientes_Especiais_JCM", "Telefone", telefone)
        if cliente:
            return cliente
        
        # Se não encontrado, retorna um cliente padrão
        return {
            "Nome": "Cliente JCM",
            "Telefone": telefone,
            "Tipo": "Regular"
        }
    except Exception as e:
        print(f"Erro ao identificar cliente: {str(e)}")
        return None

def saudacao_personalizada(cliente, primeira_vez):
    saudacao_periodo = obter_periodo_dia()
    
    if cliente:
        nome = cliente.get('Nome', 'cliente VIP').split()[0]
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
    from_number = request.values.get('From', '')
    mensagem = request.values.get('Body', '').strip()
    
    telefone = re.sub(r'\D', '', from_number)[-11:]
    
    estado_usuario = ESTADOS.get(telefone, {
        "estado": "INICIO",
        "ultima_interacao": datetime.now().isoformat(),
        "primeira_vez": True
    })
    
    ultima_interacao = datetime.fromisoformat(estado_usuario["ultima_interacao"])
    tempo_desde_ultima = (datetime.now() - ultima_interacao).total_seconds() / 60
    
    estado_usuario["ultima_interacao"] = datetime.now().isoformat()
    ESTADOS[telefone] = estado_usuario
    
    intencao = detectar_intencao(mensagem)
    cliente = identificar_cliente(telefone)
    
    resp = MessagingResponse()
    msg = resp.message()
    
    estado_atual = estado_usuario["estado"]
    
    if tempo_desde_ultima > 30 and estado_atual != "INICIO":
        msg.body(f"{obter_periodo_dia()}! Percebi que passou um tempo desde nossa última conversa. Vamos recomeçar?")
        estado_usuario["estado"] = "INICIO"
        estado_usuario["primeira_vez"] = False
        ESTADOS[telefone] = estado_usuario
        return str(resp)
    
    if estado_atual == "INICIO":
        if intencao in ["saudacao", "ajuda"] or estado_usuario["primeira_vez"]:
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
            estado_usuario["estado"] = "AGUARDANDO_ACAO"
            ESTADOS[telefone] = estado_usuario
            
        else:
            msg.body("Não entendi. Digite *OI* para começar ou *AJUDA* para ver opções")
    
    elif estado_atual == "AGUARDANDO_ACAO":
        if intencao == "reserva":
            # Mensagem mais clara com exemplo não executável
            msg.body("✈️ Para fazer uma reserva, envie no seguinte formato:\n\n"
                     "RESERVA [origem] para [destino] - [número] pessoas - [data]\n\n"
                     "*Exemplo:*\n"
                     "RESERVA GRU para Campinas - 4 pessoas - 25/07/2025\n\n"
                     "Por favor, substitua os valores entre colchetes com suas informações reais.")
            estado_usuario["estado"] = "AGUARDANDO_RESERVA"
            ESTADOS[telefone] = estado_usuario
        
        elif intencao == "pagar":
            msg.body("💳 Link para pagamento: https://jcmviagens.com/pagar\n\nEnvie o número da reserva para pagamento específico")
            estado_usuario["estado"] = "AGUARDANDO_PAGAMENTO"
            ESTADOS[telefone] = estado_usuario
        
        elif intencao == "status":
            msg.body("🔍 Digite o número completo da reserva (ex: RES_123456) para verificar o status:")
            estado_usuario["estado"] = "AGUARDANDO_NUMERO_RESERVA"
            ESTADOS[telefone] = estado_usuario
        
        elif intencao == "cancelar":
            msg.body("❌ Digite o número completo da reserva que deseja cancelar (ex: RES_123456):")
            estado_usuario["estado"] = "AGUARDANDO_CANCELAMENTO"
            ESTADOS[telefone] = estado_usuario
        
        elif intencao == "suporte":
            msg.body("⏳ Redirecionando para atendente humano...")
            estado_usuario["estado"] = "SUPORTE_ATIVO"
            ESTADOS[telefone] = estado_usuario
        
        else:
            msg.body("⚠️ Opção não reconhecida. Digite *AJUDA* para ver opções")
    
    # ========== FLUXO DE RESERVA INTEGRADO ==========
    elif estado_atual == "AGUARDANDO_RESERVA":
        try:
            # Verificar se é um comando de exemplo
            if "exemplo" in mensagem.lower() or "como" in mensagem.lower():
                msg.body("Por favor, envie sua reserva REAL no formato:\n\n"
                         "RESERVA [origem] para [destino] - [número] pessoas - [data]\n\n"
                         "Substitua os valores entre colchetes com suas informações.")
                return str(resp)
                
            # Validação básica do formato
            if '-' not in mensagem or 'para' not in mensagem:
                raise ValueError("Formato inválido")
                
            # Extrair partes da mensagem
            partes = [part.strip() for part in mensagem.split('-')]
            if len(partes) < 3:
                raise ValueError("Faltam partes na reserva")
                
            origem_destino = partes[0].replace('RESERVA', '').strip()
            pessoas_part = partes[1].replace('pessoas', '').replace('pessoa', '').strip()
            data_reserva = partes[2].strip()
            
            # Extrair origem e destino
            if ' para ' not in origem_destino:
                raise ValueError("Formato origem-destino inválido")
                
            origem, destino = origem_destino.split(' para ', 1)
            origem = origem.strip()
            destino = destino.strip()
            
            # Validar número de pessoas
            try:
                pessoas = int(pessoas_part)
            except ValueError:
                raise ValueError("Número de pessoas inválido")
            
            # Determinar veículo e valor
            if pessoas <= 0:
                raise ValueError("Número de pessoas deve ser positivo")
            elif pessoas <= 4:
                veiculo = "Sedan"
                valor = 600.00
            elif pessoas <= 7:
                veiculo = "SUV"
                valor = 750.00
            else:
                veiculo = "Van"
                valor = 900.00
            
            id_reserva = f"RES_{int(time.time())}"
            
            reserva_data = {
                "ID_Reserva": id_reserva,
                "Cliente": telefone,
                "Data": data_reserva,
                "Hora_Coleta": "08:00",
                "ID_Local_Origem": "LOC_005",  # Aeroporto GRU
                "ID_Local_Destino": "LOC_001",  # Meliá Campinas
                "Categoria_Veiculo": veiculo,
                "ID_Motorista": "MOT_001",  # Alencar
                "Status": "Confirmado",
                "Valor": valor
            }
            
            # Salvar na planilha com verificação de conexão
            gc = conectar_google_sheets()
            if gc:
                planilha_reservas = gc.open("Reservas_JCM").sheet1
                planilha_reservas.append_row(list(reserva_data.values()))
                
                # Registrar pagamento
                pagamento_data = {
                    "Reserva_ID": id_reserva,
                    "Motorista": "Alencar",
                    "Valor_Base": valor * 0.8,
                    "Valor_Espera": 0.00,
                    "Comissao_JCM": valor * 0.2,
                    "Ambiente": "Producao",
                    "Status": "Pendente"
                }
                planilha_pagamentos = gc.open("Pagamentos_Motoristas_JCM").sheet1
                planilha_pagamentos.append_row(list(pagamento_data.values()))
                
                msg.body(f"✅ Reserva {id_reserva} confirmada!\n\n" 
                         f"*Detalhes:*\n"
                         f"- Origem: {origem}\n"
                         f"- Destino: {destino}\n"
                         f"- Data: {data_reserva}\n"
                         f"- Veículo: {veiculo}\n"
                         f"- Valor: R$ {valor:.2f}\n\n"
                         f"Pagamento motorista registrado ✅")
            else:
                msg.body("❌ Erro na conexão com o Google Sheets. Tente novamente mais tarde.")
            
        except Exception as e:
            # Não mostrar erro técnico ao usuário
            print(f"ERRO RESERVA: {str(e)}")
            msg.body("❌ Formato incorreto! Por favor, envie:\n\n"
                     "RESERVA [origem] para [destino] - [número] pessoas - [data]\n\n"
                     "*Exemplo:*\n"
                     "RESERVA Aeroporto GRU para Hotel Campinas - 4 pessoas - 25/07/2025\n\n"
                     "Certifique-se de usar o formato exato.")
        
        estado_usuario["estado"] = "INICIO"
        ESTADOS[telefone] = estado_usuario
    
    # ========== CONSULTA DE STATUS INTEGRADA ==========
    elif estado_atual == "AGUARDANDO_NUMERO_RESERVA":
        try:
            # Normalizar o ID da reserva
            reserva_id = mensagem.strip().upper()
            if not reserva_id.startswith("RES_"):
                reserva_id = "RES_" + reserva_id
            
            reserva = buscar_na_planilha("Reservas_JCM", "ID_Reserva", reserva_id)
            
            if reserva:
                # Buscar motorista associado
                motorista = buscar_na_planilha("Motoristas_JCM", "ID_Contato", reserva["ID_Motorista"])
                nome_motorista = motorista["Nome"] if motorista else "Não atribuído"
                
                # Buscar origem/destino
                origem = buscar_na_planilha("Locais_Especificos_JCM", "ID_Local", reserva["ID_Local_Origem"])
                destino = buscar_na_planilha("Locais_Especificos_JCM", "ID_Local", reserva["ID_Local_Destino"])
                
                nome_origem = origem["Nome"] if origem else "Desconhecido"
                nome_destino = destino["Nome"] if destino else "Desconhecido"
                
                resposta = (f"✅ Reserva *{reserva_id}*\n"
                            f"Status: {reserva['Status']}\n"
                            f"Data: {reserva['Data']}\n"
                            f"Origem: {nome_origem}\n"
                            f"Destino: {nome_destino}\n"
                            f"Veículo: {reserva['Categoria_Veiculo']}\n"
                            f"Motorista: {nome_motorista}\n"
                            f"Valor: R$ {reserva['Valor']:.2f}")
            else:
                resposta = f"❌ Reserva {reserva_id} não encontrada. Verifique o número."
        except Exception as e:
            resposta = f"❌ Erro ao buscar reserva: {str(e)}"
        
        msg.body(resposta)
        estado_usuario["estado"] = "INICIO"
        ESTADOS[telefone] = estado_usuario
    
    elif estado_atual == "AGUARDANDO_CANCELAMENTO":
        # Normalizar o ID da reserva
        reserva_id = mensagem.strip().upper()
        if not reserva_id.startswith("RES_"):
            reserva_id = "RES_" + reserva_id
        
        if len(reserva_id) > 4:
            msg.body(f"✅ Reserva #{reserva_id} cancelada com sucesso!\nValor será estornado em até 5 dias úteis.")
        else:
            msg.body("❌ Número inválido. Digite o ID completo da reserva (ex: RES_123456)")
        
        estado_usuario["estado"] = "INICIO"
        ESTADOS[telefone] = estado_usuario
    
    elif estado_atual == "AGUARDANDO_PAGAMENTO":
        # Normalizar o ID da reserva
        reserva_id = mensagem.strip().upper()
        if not reserva_id.startswith("RES_"):
            reserva_id = "RES_" + reserva_id
        
        if len(reserva_id) > 4:
            msg.body(f"💳 Pagamento para reserva #{reserva_id}:\n🔗 Link: https://jcmviagens.com/pagar?id={reserva_id}\n\nValidade: 24 horas")
        else:
            msg.body("⚠️ Digite o número completo da reserva para pagamento (ex: RES_123456)")
        
        estado_usuario["estado"] = "INICIO"
        ESTADOS[telefone] = estado_usuario
    
    elif estado_atual == "SUPORTE_ATIVO":
        msg.body("⌛ Um atendente humano já foi notificado e entrará em contato em breve!")
        estado_usuario["estado"] = "INICIO"
        ESTADOS[telefone] = estado_usuario
    
    else:
        msg.body("🔄 Reiniciando conversa... Digite *OI* para começar")
        estado_usuario["estado"] = "INICIO"
        ESTADOS[telefone] = estado_usuario
    
    return str(resp)

# ========== ROTA DE TESTE DE PLANILHAS ==========
@app.route('/teste-sheets')
def teste_sheets():
    try:
        gc = conectar_google_sheets()
        if gc:
            planilha = gc.open("Reservas_JCM").sheet1
            primeira_linha = planilha.row_values(1)
            return f"Conexão OK! Cabeçalhos: {primeira_linha}"
        else:
            return "❌ Falha na conexão com Google Sheets"
    except Exception as e:
        return f"ERRO: {str(e)}"

# ========== ROTA DE DIAGNÓSTICO DE CREDENCIAIS ==========
@app.route('/debug-creds')
def debug_creds():
    if not GOOGLE_CREDS:
        return jsonify({"status": "error", "message": "Credenciais não carregadas"})
    
    try:
        # Verificar informações básicas
        debug_info = {
            "status": "success",
            "client_email": GOOGLE_CREDS.get("client_email", ""),
            "private_key_length": len(GOOGLE_CREDS.get("private_key", "")),
            "private_key_start": GOOGLE_CREDS.get("private_key", "")[:30],
            "private_key_end": GOOGLE_CREDS.get("private_key", "")[-30:],
            "contains_newline": "\n" in GOOGLE_CREDS.get("private_key", ""),
            "is_valid_format": "-----BEGIN PRIVATE KEY-----" in GOOGLE_CREDS.get("private_key", "")
        }
        
        return jsonify(debug_info)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

# ========== WARMUP ==========
@app.route('/warmup')
def warmup():
    print("🔥 Instance warmed up!")
    return "Instance is warm!", 200

# ========== HEALTH CHECK ==========
@app.route('/healthz')
def health_check():
    return "✅ AlineBot Online", 200

# ========== LIMPEZA AUTOMÁTICA DE MEMÓRIA ==========
def limpeza_automatica():
    while True:
        time.sleep(1800)
        agora = datetime.now()
        print("⏰ Verificando estados inativos...")
        
        telefones = list(ESTADOS.keys())
        
        for telefone in telefones:
            estado = ESTADOS[telefone]
            ultima_interacao = datetime.fromisoformat(estado["ultima_interacao"])
            
            if (agora - ultima_interacao).total_seconds() > 7200:
                del ESTADOS[telefone]
                print(f"♻️ Estado removido: {telefone[-4:]}")
                
# ========== WARMUP AUTOMÁTICO ==========
def warmup_periodico():
    while True:
        try:
            requests.get("https://alinebotjcm.onrender.com/warmup")
            print("🔥 Warmup automático executado")
        except Exception as e:
            print(f"⚠️ Erro no warmup automático: {str(e)}")
        time.sleep(300)

# ---------- INICIAR SERVIDOR ----------
if __name__ == '__main__':
    limpador = threading.Thread(target=limpeza_automatica)
    limpador.daemon = True
    limpador.start()
    
    warmup_thread = threading.Thread(target=warmup_periodico)
    warmup_thread.daemon = True
    warmup_thread.start()
    
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
