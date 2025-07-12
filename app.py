import os
import re
import json
import logging
import random
from datetime import datetime
from flask import Flask, request
from twilio.rest import Client
from twilio.twiml.messaging_response import MessagingResponse

app = Flask(__name__)

# ================= CONFIGURAÇÃO INICIAL =================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configurações Twilio
TWILIO_ACCOUNT_SID = os.environ.get('TWILIO_ACCOUNT_SID')
TWILIO_AUTH_TOKEN = os.environ.get('TWILIO_AUTH_TOKEN')
TWILIO_PHONE_NUMBER = os.environ.get('TWILIO_PHONE_NUMBER')
client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

# ================= ESTRUTURA DE DADOS =================
# Estado da conversa
estado_usuario = {}
contexto_reserva = {}
solicitacoes_pendentes = {}

# Dados de usuários (simulado - implementar com DB depois)
usuarios = {
    # Alencar (Proprietário)
    "+5511972508430": {
        "nome": "Cleverson Rodrigues de Alencar",
        "empresa": "JCM",
        "nivel": 4,  # Proprietário
        "ativo": True
    },
    
    # Exemplos
    "+5511999999999": {
        "nome": "Gerente Wurth",
        "empresa": "Wurth",
        "nivel": 5,  # Máximo por empresa
        "ativo": True
    },
    "+5511888888888": {
        "nome": "Funcionário Wurth",
        "empresa": "Wurth",
        "nivel": 1,  # Básico
        "ativo": True
    }
}

# Dados de empresas (simulado)
empresas = {
    "Wurth": {
        "responsaveis": ["+5511999999999"],  # Telefones dos nível 5
        "funcionarios": ["+5511888888888"]
    },
    "Teijin": {
        "responsaveis": ["+5511777777777"],
        "funcionarios": ["+5511666666666"]
    }
}

# ================= FUNÇÕES DE ACESSO =================
def verificar_acesso(telefone, acao, reserva_id=None):
    """Verifica permissões do usuário"""
    usuario = usuarios.get(telefone)
    if not usuario or not usuario['ativo']:
        return False, "❌ Usuário não autorizado"
    
    # Alencar tem acesso total
    if usuario['nivel'] == 4:
        return True, ""
    
    # Ações permitidas por nível
    if acao == "visualizar":
        return True, ""
    
    if acao == "reservar":
        if usuario['nivel'] >= 1:
            return True, ""
        return False, "❌ Nível de acesso insuficiente para reservar"
    
    if acao in ["alterar", "cancelar"]:
        if usuario['nivel'] >= 2:
            return True, ""
        
        # Nível 1 precisa de autorização
        if reserva_id:
            solicitacoes_pendentes[reserva_id] = {
                "telefone": telefone,
                "acao": acao,
                "reserva_id": reserva_id,
                "status": "pendente"
            }
            return False, "solicitacao_autorizacao"
        
        return False, "❌ Reserva não especificada"
    
    if acao == "gerenciar_usuarios":
        if usuario['nivel'] == 5 or usuario['nivel'] == 4:
            return True, ""
        return False, "❌ Apenas responsáveis podem gerenciar usuários"
    
    return False, "❌ Ação não permitida"

def enviar_solicitacao_autorizacao(telefone, reserva_id, acao):
    """Envia solicitação para os responsáveis"""
    usuario = usuarios.get(telefone)
    if not usuario:
        return False
    
    empresa = usuario['empresa']
    if empresa not in empresas:
        return False
    
    # Encontrar responsáveis da empresa
    responsaveis = empresas[empresa]['responsaveis']
    reserva = contexto_reserva.get(telefone, {}).get(reserva_id, {})
    
    for resp_telefone in responsaveis:
        try:
            client.messages.create(
                body=f"⚠️ *SOLICITAÇÃO DE AUTORIZAÇÃO*\n\n"
                     f"Usuário: {usuario['nome']}\n"
                     f"Ação: {acao.capitalize()} reserva\n"
                     f"ID: {reserva_id}\n"
                     f"Origem: {reserva.get('origem', '')}\n"
                     f"Destino: {reserva.get('destino', '')}\n\n"
                     f"Para aprovar: *APROVAR {reserva_id}*\n"
                     f"Para rejeitar: *REJEITAR {reserva_id}*",
                from_=f"whatsapp:{TWILIO_PHONE_NUMBER}",
                to=f"whatsapp:{resp_telefone}"
            )
            logger.info(f"Solicitação enviada para {resp_telefone}")
        except Exception as e:
            logger.error(f"Erro ao enviar solicitação: {str(e)}")
    
    return True

# ================= FUNÇÕES PRINCIPAIS ATUALIZADAS =================
def identificar_cliente(telefone):
    """Identifica cliente com verificação de acesso"""
    return usuarios.get(telefone, {
        "nome": "",
        "empresa": "",
        "nivel": 0,
        "ativo": False
    })

def processar_comando_admin(mensagem, telefone):
    """Processa comandos administrativos"""
    usuario = usuarios.get(telefone)
    if not usuario or usuario['nivel'] < 4:
        return "❌ Acesso negado"
    
    # Comando: ADICIONAR USUARIO
    if re.search(r'adicionar usuario', mensagem, re.IGNORECASE):
        match = re.search(r'adicionar usuario (.+) empresa (.+) nivel (\d+)', mensagem, re.IGNORECASE)
        if match:
            nome = match.group(1)
            empresa = match.group(2)
            nivel = int(match.group(3))
            
            # Gerar telefone fictício (implementar lógica real)
            novo_telefone = f"+5511{random.randint(10000000, 99999999)}"
            
            usuarios[novo_telefone] = {
                "nome": nome,
                "empresa": empresa,
                "nivel": nivel,
                "ativo": True
            }
            
            # Atualizar empresa
            if empresa not in empresas:
                empresas[empresa] = {"responsaveis": [], "funcionarios": []}
            
            if nivel == 5:
                empresas[empresa]['responsaveis'].append(novo_telefone)
            else:
                empresas[empresa]['funcionarios'].append(novo_telefone)
            
            return f"✅ Usuário {nome} adicionado!\nTelefone: {novo_telefone}\nNível: {nivel}"
    
    # Comando: LISTAR USUARIOS
    elif re.search(r'listar usuarios', mensagem, re.IGNORECASE):
        lista = ["📋 Lista de Usuários:"]
        for tel, user in usuarios.items():
            if tel == telefone: continue  # Pular próprio usuário
            lista.append(f"- {user['nome']} ({tel}) | {user['empresa']} | Nível {user['nivel']}")
        return "\n".join(lista)
    
    return "Comando administrativo desconhecido. Use: *ADICIONAR USUARIO [nome] empresa [empresa] nivel [1-5]*"

# ================= WEBHOOK ATUALIZADO =================
@app.route("/webhook", methods=['POST'])
def webhook():
    telefone = request.form.get('From', '')
    mensagem = request.form.get('Body', '').strip()
    
    # Verificar comandos administrativos (Alencar)
    if mensagem.lower().startswith("admin ") or mensagem.lower().startswith("administrativo "):
        resposta = processar_comando_admin(mensagem, telefone)
        try:
            client.messages.create(
                body=resposta,
                from_=f"whatsapp:{TWILIO_PHONE_NUMBER}",
                to=f"whatsapp:{telefone}"
            )
        except Exception as e:
            logger.error(f"Erro ao enviar resposta administrativa: {str(e)}")
        return ""
    
    # Log e identificação
    logger.info(f"Mensagem de {telefone}: {mensagem}")
    cliente = identificar_cliente(telefone)
    
    # Processar respostas de autorização
    if mensagem.startswith("APROVAR ") or mensagem.startswith("REJEITAR "):
        match = re.search(r'(APROVAR|REJEITAR) (\w+)', mensagem)
        if match:
            acao = match.group(1).lower()
            reserva_id = match.group(2)
            solicitacao = solicitacoes_pendentes.get(reserva_id)
            
            if solicitacao:
                usuario_solicitante = usuarios.get(solicitacao['telefone'])
                if acao == "aprovar":
                    # Atualizar reserva conforme ação
                    resposta_solicitante = f"✅ Sua solicitação para {solicitacao['acao']} a reserva {reserva_id} foi APROVADA!"
                    solicitacoes_pendentes[reserva_id]['status'] = "aprovado"
                else:
                    resposta_solicitante = f"❌ Sua solicitação para {solicitacao['acao']} a reserva {reserva_id} foi REJEITADA"
                    solicitacoes_pendentes[reserva_id]['status'] = "rejeitado"
                
                # Enviar resposta ao solicitante
                try:
                    client.messages.create(
                        body=resposta_solicitante,
                        from_=f"whatsapp:{TWILIO_PHONE_NUMBER}",
                        to=f"whatsapp:{solicitacao['telefone']}"
                    )
                except Exception as e:
                    logger.error(f"Erro ao enviar resposta de autorização: {str(e)}")
                
                return ""
    
    # Verificar se usuário está ativo
    if not cliente.get('ativo', False):
        resp = MessagingResponse()
        msg = resp.message()
        msg.body("❌ Você não tem permissão para usar este sistema. Contate o administrador.")
        return str(resp)
    
    # ... (o restante do código do webhook permanece similar)
    # COM ADICÃO DAS VERIFICAÇÕES DE ACESSO NAS AÇÕES

    # Exemplo na ação de cancelamento:
    if intencao == "cancelar":
        match = re.search(r'cancelar (\w+)', mensagem, re.IGNORECASE)
        if match:
            reserva_id = match.group(1).upper()
            permissao, motivo = verificar_acesso(telefone, "cancelar", reserva_id)
            
            if not permissao:
                if motivo == "solicitacao_autorizacao":
                    enviar_solicitacao_autorizacao(telefone, reserva_id, "cancelar")
                    msg.body("📬 Solicitação de cancelamento enviada para aprovação")
                else:
                    msg.body(motivo)
                return str(resp)
            
            # Processar cancelamento
            # ...

    # Implementação similar para outras ações

# ================= ROTAS ADICIONAIS ================= 
@app.route("/")
def home():
    return "Sistema JCM com Controle de Acessos v2.0"

@app.route("/health")
@app.route("/healthz")
def health_check():
    return "OK", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    logger.info(f"Sistema iniciado na porta {port}")
    app.run(host="0.0.0.0", port=port)
