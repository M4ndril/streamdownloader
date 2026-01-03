import streamlit as st
import streamlink
import subprocess
import json
import os
import time
import sys
import glob
from datetime import datetime

# Configuração da página
st.set_page_config(page_title="Twitch Auto-Recorder", page_icon="🔴", layout="wide")

# --- CSS HACKS ---
# Remove botão de deploy, menu hamburger (opcional), footer e links dos cabeçalhos
st.markdown("""
    <style>
        /* Esconder botão de Deploy e Toolbar superior */
        .stDeployButton {display: none;}
        [data-testid="stToolbar"] {visibility: hidden;}
        
        /* Esconder links (âncoras) dos títulos */
        h1 a, h2 a, h3 a, h4 a, h5 a, h6 a {display: none !important;}
        h1, h2, h3, h4, h5, h6 {pointer-events: none;}
        
        /* Ajuste visual para os cards de canais */
        div[data-testid="stVerticalBlock"] > div {
            margin-bottom: 10px;
        }
    </style>
""", unsafe_allow_html=True)

# Configuração de Diretórios para Docker
DATA_DIR = "data"
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

# Arquivo para salvar a lista de canais
CHANNELS_FILE = os.path.join(DATA_DIR, "watchlist.json")

# Função para carregar canais (com migração de dados antiga -> nova)
def load_channels():
    if os.path.exists(CHANNELS_FILE):
        with open(CHANNELS_FILE, "r") as f:
            try:
                data = json.load(f)
                # Migração: Se for lista de strings, converte para lista de objetos
                if data and isinstance(data[0], str):
                    new_data = [{"name": ch, "active": True} for ch in data]
                    save_channels(new_data)
                    return new_data
                return data
            except json.JSONDecodeError:
                return []
    return []

# Função para salvar canais
def save_channels(channels):
    with open(CHANNELS_FILE, "w") as f:
        json.dump(channels, f)

# Inicializar estado da sessão
if "monitoring" not in st.session_state:
    st.session_state.monitoring = False
if "processes" not in st.session_state:
    st.session_state.processes = {} # Dicionário: canal -> subprocesso

st.title("🔴 Twitch Auto-Recorder")

# Criar Abas
tab_monitor, tab_recordings = st.tabs(["📡 Monitoramento", "📂 Gravações"])

# --- ABA 1: MONITORAMENTO ---
with tab_monitor:
    col_sidebar, col_main = st.columns([1, 2])

    with col_sidebar:
        st.subheader("📺 Gerenciar Canais")
        
        # Adicionar Canal
        with st.form("add_channel_form", clear_on_submit=True):
            new_channel = st.text_input("Novo Canal", placeholder="Nome ou URL")
            submitted = st.form_submit_button("Adicionar")
            if submitted and new_channel:
                channel_name = new_channel.split("twitch.tv/")[-1].split("/")[0].strip()
                channels = load_channels()
                # Verificar duplicatas
                if not any(c['name'] == channel_name for c in channels):
                    channels.append({"name": channel_name, "active": True})
                    save_channels(channels)
                    st.success(f"✅ {channel_name} adicionado!")
                    st.rerun()
                else:
                    st.warning("Canal já existe.")

        st.write("---")
        
        # Listar Canais com Toggle Individual
        channels = load_channels()
        if channels:
            st.caption("Ative/Desative o monitoramento individualmente:")
            for i, ch_data in enumerate(channels):
                with st.container(border=True):
                    c1, c2 = st.columns([3, 1])
                    c1.markdown(f"**{ch_data['name']}**")
                    
                    # Toggle de Ativo/Inativo
                    is_active = c1.toggle("Monitorar", value=ch_data['active'], key=f"toggle_{i}")
                    
                    # Botão de Excluir
                    if c2.button("🗑️", key=f"del_{i}"):
                        channels.pop(i)
                        save_channels(channels)
                        st.rerun()
                    
                    # Salvar alteração do toggle se mudou
                    if is_active != ch_data['active']:
                        channels[i]['active'] = is_active
                        save_channels(channels)
                        st.rerun()
        else:
            st.info("Nenhum canal na lista.")

    with col_main:
        st.subheader("Painel de Controle")
        
        # Botão Mestre de Serviço
        # O usuário pediu para iniciar/parar individualmente, mas precisamos de um "loop" rodando.
        # Vamos deixar o serviço "Ligado" por padrão ou fácil de ligar.
        
        status_cols = st.columns([2, 1])
        if st.session_state.monitoring:
            status_cols[0].success("✅ **SERVIÇO DE MONITORAMENTO: ATIVO**")
            if status_cols[1].button("⏹️ PARAR SERVIÇO"):
                st.session_state.monitoring = False
                st.rerun()
        else:
            status_cols[0].warning("⚠️ **SERVIÇO DE MONITORAMENTO: PARADO**")
            if status_cols[1].button("▶️ INICIAR SERVIÇO", type="primary"):
                st.session_state.monitoring = True
                st.rerun()

        st.info("ℹ️ O Serviço precisa estar **ATIVO** para processar os canais marcados como 'Monitorar'.")
        st.write("---")
        
        # --- SEÇÃO DE GRAVAÇÕES ATIVAS ---
        st.subheader("🔴 Gravações em Andamento")
        
        # Verificar processos ativos e limpar os terminados
        active_channels = list(st.session_state.processes.keys())
        has_active = False
        
        for ch in active_channels:
            proc = st.session_state.processes[ch]
            if proc.poll() is None: # Ainda rodando
                has_active = True
                box = st.container(border=True)
                bc1, bc2 = box.columns([4, 1])
                bc1.markdown(f"**Gravando:** `{ch}` (PID: {proc.pid})")
                if bc2.button("Parar", key=f"stop_rec_{ch}", type="secondary"):
                    proc.terminate()
                    try:
                        proc.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                    del st.session_state.processes[ch]
                    st.toast(f"Gravação de {ch} parada.")
                    st.rerun()
            else:
                # Terminou sozinho
                del st.session_state.processes[ch]
        
        if not has_active:
            st.caption("Nenhuma gravação ativa no momento.")

        # --- LÓGICA DE MONITORAMENTO (Roda a cada refresh) ---
        if st.session_state.monitoring:
            
            # Filtrar apenas canais ativos
            active_targets = [c['name'] for c in channels if c['active']]
            
            if not active_targets:
                st.warning("Serviço rodando, mas nenhum canal está marcado para monitorar.")
            
            for channel in active_targets:
                # Pular se já estiver gravando
                if channel in st.session_state.processes:
                    continue
                
                url = f"https://www.twitch.tv/{channel}"
                try:
                    # Verificar streams (rápido)
                    streams = streamlink.streams(url)
                    if streams:
                        # ONLINE -> Iniciar Gravação
                        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
                        filename = os.path.join(DATA_DIR, f"rec_{channel}_{timestamp}.mp4")
                        
                        # Redirecionando stdout/stderr para DEVNULL
                        cmd = [sys.executable, "-m", "streamlink", url, "best", "-o", filename]
                        
                        kwargs = {}
                        if sys.platform == "win32":
                            kwargs['creationflags'] = 0x08000000
                        
                        proc = subprocess.Popen(
                            cmd, 
                            stdout=subprocess.DEVNULL, 
                            stderr=subprocess.DEVNULL,
                            **kwargs
                        )
                        st.session_state.processes[channel] = proc
                        st.toast(f"🟢 {channel} está ONLINE! Gravando...")
                        st.rerun() # Atualizar UI para mostrar o novo processo
                        
                except Exception:
                    pass # Ignorar erros de conexão temporários
            
            # Aguardar e recarregar
            time.sleep(15)
            st.rerun()

# --- ABA 2: BIBLIOTECA DE GRAVAÇÕES ---
with tab_recordings:
    st.subheader("📂 Arquivos Gravados")
    
    # Listar arquivos mp4 na pasta de dados
    search_pattern = os.path.join(DATA_DIR, "rec_*.mp4")
    files = glob.glob(search_pattern)
    files.sort(key=os.path.getmtime, reverse=True)
    
    if files:
        for f in files:
            filename_only = os.path.basename(f)
            size_mb = os.path.getsize(f) / (1024 * 1024)
            timestamp = os.path.getmtime(f)
            date_str = datetime.fromtimestamp(timestamp).strftime('%d/%m/%Y %H:%M')
            
            with st.container(border=True):
                c1, c2, c3 = st.columns([3, 1, 1])
                c1.markdown(f"🎬 **{filename_only}**")
                c1.caption(f"Tamanho: {size_mb:.1f} MB | Data: {date_str}")
                
                with open(f, "rb") as file_content:
                    c2.download_button(
                        label="⬇️ Baixar",
                        data=file_content,
                        file_name=filename_only,
                        mime="video/mp4",
                        key=f"dl_{f}"
                    )
                
                if c3.button("🗑️ Excluir", key=f"rm_{f}"):
                    try:
                        os.remove(f)
                        st.toast(f"Arquivo {filename_only} excluído.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Erro ao excluir: {e}")
    else:
        st.info("Nenhuma gravação encontrada.")
