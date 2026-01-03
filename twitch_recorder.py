import streamlit as st
import streamlink
import subprocess
import json
import os
import time
import sys
import glob
import psutil
from datetime import datetime

# Configuração da página
st.set_page_config(page_title="Twitch Auto-Recorder", page_icon="🔴", layout="wide")

# --- CSS HACKS ---
st.markdown("""
    <style>
        .stDeployButton {display: none;}
        [data-testid="stToolbar"] {visibility: hidden;}
        h1 a, h2 a, h3 a, h4 a, h5 a, h6 a {display: none !important;}
        h1, h2, h3, h4, h5, h6 {pointer-events: none;}
        div[data-testid="stVerticalBlock"] > div { margin-bottom: 10px; }
    </style>
""", unsafe_allow_html=True)

# Configuração de Diretórios
DATA_DIR = "static"
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

CHANNELS_FILE = os.path.join(DATA_DIR, "watchlist.json")
RECORDINGS_FILE = os.path.join(DATA_DIR, "active_recordings.json")

# --- FUNÇÕES DE PERSISTÊNCIA ---

def load_channels():
    if os.path.exists(CHANNELS_FILE):
        with open(CHANNELS_FILE, "r") as f:
            try:
                data = json.load(f)
                if data and isinstance(data[0], str): # Migração
                    new_data = [{"name": ch, "active": True} for ch in data]
                    save_channels(new_data)
                    return new_data
                return data
            except json.JSONDecodeError:
                return []
    return []

def save_channels(channels):
    with open(CHANNELS_FILE, "w") as f:
        json.dump(channels, f)

def load_active_recordings():
    if os.path.exists(RECORDINGS_FILE):
        with open(RECORDINGS_FILE, "r") as f:
            try:
                return json.load(f) # Dict: {channel_name: {"pid": int, "filename": str, "start_time": str}}
            except json.JSONDecodeError:
                return {}
    return {}

def save_active_recordings(recordings):
    with open(RECORDINGS_FILE, "w") as f:
        json.dump(recordings, f)

# --- FUNÇÕES DE PROCESSO ---

def is_process_running(pid):
    try:
        p = psutil.Process(pid)
        return p.is_running() and p.status() != psutil.STATUS_ZOMBIE
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return False

def stop_process(pid):
    try:
        p = psutil.Process(pid)
        p.terminate()
        try:
            p.wait(timeout=3)
        except psutil.TimeoutExpired:
            p.kill()
        return True
    except (psutil.NoSuchProcess, psutil.ZombieProcess):
        return False # Já morreu
    except Exception as e:
        print(f"Erro ao matar processo {pid}: {e}")
        return False

# --- UI PRINCIPAL ---

if "monitoring" not in st.session_state:
    st.session_state.monitoring = False

st.title("🔴 Twitch Auto-Recorder")

tab_monitor, tab_recordings = st.tabs(["📡 Monitoramento", "📂 Gravações"])

# --- ABA 1: MONITORAMENTO ---
with tab_monitor:
    col_sidebar, col_main = st.columns([1, 2])

    with col_sidebar:
        st.subheader("📺 Gerenciar Canais")
        
        with st.form("add_channel_form", clear_on_submit=True):
            new_channel = st.text_input("Novo Canal", placeholder="Nome ou URL")
            if st.form_submit_button("Adicionar"):
                if new_channel:
                    channel_name = new_channel.split("twitch.tv/")[-1].split("/")[0].strip()
                    channels = load_channels()
                    if not any(c['name'] == channel_name for c in channels):
                        channels.append({"name": channel_name, "active": True})
                        save_channels(channels)
                        st.success(f"✅ {channel_name} adicionado!")
                        st.rerun()
                    else:
                        st.warning("Canal já existe.")

        st.write("---")
        
        channels = load_channels()
        if channels:
            st.caption("Ative/Desative o monitoramento individualmente:")
            for i, ch_data in enumerate(channels):
                with st.container(border=True):
                    c1, c2 = st.columns([3, 1])
                    c1.markdown(f"**{ch_data['name']}**")
                    is_active = c1.toggle("Monitorar", value=ch_data['active'], key=f"toggle_{i}")
                    if c2.button("🗑️", key=f"del_{i}"):
                        channels.pop(i)
                        save_channels(channels)
                        st.rerun()
                    if is_active != ch_data['active']:
                        channels[i]['active'] = is_active
                        save_channels(channels)
                        st.rerun()
        else:
            st.info("Nenhum canal na lista.")

    with col_main:
        st.subheader("Painel de Controle")
        
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

        st.write("---")
        
        # --- SEÇÃO DE GRAVAÇÕES ATIVAS (PERSISTENTE) ---
        st.subheader("🔴 Gravações em Andamento")
        
        active_recs = load_active_recordings()
        clean_needed = False
        has_active = False

        # Iterar sobre cópia para poder modificar o original se necessário
        for ch_name, info in list(active_recs.items()):
            pid = info['pid']
            
            if is_process_running(pid):
                has_active = True
                box = st.container(border=True)
                bc1, bc2 = box.columns([4, 1])
                bc1.markdown(f"**Gravando:** `{ch_name}` (PID: {pid})")
                bc1.caption(f"Arquivo: {os.path.basename(info['filename'])}")
                
                if bc2.button("Parar", key=f"stop_rec_{ch_name}", type="secondary"):
                    stop_process(pid)
                    del active_recs[ch_name]
                    save_active_recordings(active_recs)
                    st.toast(f"Gravação de {ch_name} parada.")
                    st.rerun()
            else:
                # Processo morreu sozinho (live acabou ou erro)
                del active_recs[ch_name]
                clean_needed = True
        
        if clean_needed:
            save_active_recordings(active_recs)
            st.rerun()
            
        if not has_active:
            st.caption("Nenhuma gravação ativa no momento.")

        # --- LÓGICA DE MONITORAMENTO ---
        if st.session_state.monitoring:
            active_targets = [c['name'] for c in channels if c['active']]
            
            # Recarregar gravações para garantir estado atualizado
            current_recs = load_active_recordings()
            
            for channel in active_targets:
                # Pular se já estiver gravando
                if channel in current_recs:
                    continue
                
                url = f"https://www.twitch.tv/{channel}"
                try:
                    streams = streamlink.streams(url)
                    if streams:
                        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
                        filename = os.path.join(DATA_DIR, f"rec_{channel}_{timestamp}.mp4")
                        
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
                        
                        # Salvar estado persistente
                        current_recs[channel] = {
                            "pid": proc.pid,
                            "filename": filename,
                            "start_time": timestamp
                        }
                        save_active_recordings(current_recs)
                        
                        st.toast(f"🟢 {channel} está ONLINE! Gravando...")
                        st.rerun()
                        
                except Exception:
                    pass
            
            time.sleep(15)
            st.rerun()

# --- ABA 2: BIBLIOTECA DE GRAVAÇÕES ---
with tab_recordings:
    st.subheader("📂 Arquivos Gravados")
    
    search_pattern = os.path.join(DATA_DIR, "rec_*.mp4")
    files = glob.glob(search_pattern)
    files.sort(key=os.path.getmtime, reverse=True)
    
    if files:
        for f in files:
            filename_only = os.path.basename(f)
            try:
                size_mb = os.path.getsize(f) / (1024 * 1024)
            except OSError:
                size_mb = 0
            
            timestamp = os.path.getmtime(f)
            date_str = datetime.fromtimestamp(timestamp).strftime('%d/%m/%Y %H:%M')
            
            # Verificar se este arquivo está sendo gravado agora
            is_recording_now = False
            active_recs = load_active_recordings()
            for info in active_recs.values():
                if os.path.abspath(info['filename']) == os.path.abspath(f):
                    is_recording_now = True
                    break
            
            with st.container(border=True):
                c1, c2, c3 = st.columns([3, 1, 1])
                
                title = f"🎬 **{filename_only}**"
                if is_recording_now:
                    title += " (🔴 GRAVANDO...)"
                
                c1.markdown(title)
                c1.caption(f"Tamanho: {size_mb:.1f} MB | Data: {date_str}")
                
                # Botão de Download
                download_url = f"app/static/{filename_only}"
                c2.markdown(f'<a href="{download_url}" download="{filename_only}" style="text-decoration:none;"><button style="width:100%; padding: 0.5rem; border-radius: 0.5rem; border: 1px solid rgba(250, 250, 250, 0.2); background-color: #262730; color: white; cursor: pointer;">⬇️ Baixar</button></a>', unsafe_allow_html=True)
                
                # Botão de Excluir
                if c3.button("🗑️ Excluir", key=f"rm_{f}", disabled=is_recording_now):
                    try:
                        os.remove(f)
                        st.toast(f"Arquivo {filename_only} excluído.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Erro ao excluir: {e}")
    else:
        st.info("Nenhuma gravação encontrada.")
