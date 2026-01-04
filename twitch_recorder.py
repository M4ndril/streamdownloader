import streamlit as st
import json
import os
import time
import glob
import psutil
from datetime import datetime
import settings_manager
import uploader_service


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
SERVICE_STATE_FILE = os.path.join(DATA_DIR, "service_state.json")

# --- FUNÇÕES DE PERSISTÊNCIA ---

def load_json(filepath, default):
    if os.path.exists(filepath):
        with open(filepath, "r") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return default
    return default

def save_json(filepath, data):
    with open(filepath, "w") as f:
        json.dump(data, f)

def load_channels():
    data = load_json(CHANNELS_FILE, [])
    if data and isinstance(data[0], str): # Migração
        new_data = [{"name": ch, "active": True} for ch in data]
        save_json(CHANNELS_FILE, new_data)
        return new_data
    return data

def save_channels(channels):
    save_json(CHANNELS_FILE, channels)

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
        return False
    except Exception as e:
        print(f"Erro ao matar processo {pid}: {e}")
        return False

# --- UI PRINCIPAL ---

st.title("🔴 Twitch Auto-Recorder")

tab_monitor, tab_recordings, tab_settings = st.tabs(["📡 Monitoramento", "📂 Gravações", "⚙️ Configurações"])


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
        
        # Controle do Serviço de Background
        service_state = load_json(SERVICE_STATE_FILE, {"enabled": False})
        
        status_cols = st.columns([2, 1])
        if service_state.get("enabled"):
            status_cols[0].success("✅ **SERVIÇO DE MONITORAMENTO: ATIVO**")
            if status_cols[1].button("⏹️ PARAR SERVIÇO"):
                service_state["enabled"] = False
                save_json(SERVICE_STATE_FILE, service_state)
                st.rerun()
        else:
            status_cols[0].warning("⚠️ **SERVIÇO DE MONITORAMENTO: PARADO**")
            if status_cols[1].button("▶️ INICIAR SERVIÇO", type="primary"):
                service_state["enabled"] = True
                save_json(SERVICE_STATE_FILE, service_state)
                st.rerun()

        st.info("ℹ️ O Serviço roda em segundo plano. Você pode fechar esta janela.")
        st.write("---")
        
        # --- SEÇÃO DE GRAVAÇÕES ATIVAS ---
        st.subheader("🔴 Gravações em Andamento")
        
        # Ler arquivo atualizado pelo serviço
        active_recs = load_json(RECORDINGS_FILE, {})
        has_active = False

        for ch_name, info in list(active_recs.items()):
            pid = info['pid']
            # O serviço limpa processos mortos, mas podemos checar aqui também para UI responsiva
            
            has_active = True
            box = st.container(border=True)
            bc1, bc2 = box.columns([4, 1])
            bc1.markdown(f"**Gravando:** `{ch_name}` (PID: {pid})")
            bc1.caption(f"Arquivo: {os.path.basename(info['filename'])}")
            
            if bc2.button("Parar", key=f"stop_rec_{ch_name}", type="secondary"):
                # Matar processo diretamente
                stop_process(pid)
                # Remover do JSON para feedback imediato (o serviço limparia depois, mas assim é mais rápido)
                del active_recs[ch_name]
                save_json(RECORDINGS_FILE, active_recs)
                st.toast(f"Gravação de {ch_name} parada.")
                st.rerun()
        
        if not has_active:
            st.caption("Nenhuma gravação ativa no momento.")

# --- ABA 2: BIBLIOTECA DE GRAVAÇÕES ---
with tab_recordings:
    st.subheader("📂 Arquivos Gravados")
    
    search_pattern = os.path.join(DATA_DIR, "rec_*.*")
    all_files = glob.glob(search_pattern)
    # Filter for supported extensions
    files = [f for f in all_files if f.lower().endswith(('.mp4', '.ts', '.mkv'))]

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
            active_recs = load_json(RECORDINGS_FILE, {})
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

            # Botão de Upload com Expander
            with st.expander(f"⬆️ Upload: {filename_only}"):
                st.caption("Selecione o destino para enviar este vídeo:")
                
                target = st.selectbox("Destino", ["Archive.org", "YouTube"], key=f"sel_{f}")
                
                if target == "Archive.org":
                    st.info("O arquivo será enviado para sua biblioteca do Archive.org.")
                    meta_title = st.text_input("Título no Archive.org", value=filename_only, key=f"meta_t_{f}")
                    
                    if st.button("🚀 Iniciar Upload", key=f"up_{f}"):
                        st.toast("Iniciando upload... aguarde.")
                        
                        settings = settings_manager.load_settings()
                        uploader = uploader_service.UploaderService(settings)
                        
                        with st.spinner("Enviando para o Archive.org... Isso pode demorar dependendo do tamanho."):
                            success, msg = uploader.upload_to_archive(f, metadata={'title': meta_title, 'mediatype': 'movies'})
                            
                            if success:
                                st.success(msg)
                                st.balloons()
                            else:
                                st.error(msg)

                elif target == "YouTube":
                    st.info("Envio direto para o YouTube via API.")
                    
                    yt_title = st.text_input("Título do Vídeo", value=filename_only, key=f"yt_t_{f}")
                    yt_desc = st.text_area("Descrição", value=f"Gravado automaticamente de {os.path.basename(f)}", key=f"yt_d_{f}")
                    yt_privacy = st.selectbox("Privacidade", ["private", "unlisted", "public"], index=0, key=f"yt_p_{f}")
                    
                    if st.button("🚀 Iniciar Upload YouTube", key=f"up_yt_{f}"):
                        st.toast("Iniciando upload para YouTube... aguarde.")
                         
                        settings = settings_manager.load_settings()
                        uploader = uploader_service.UploaderService(settings)
                        
                        with st.spinner("Enviando para o YouTube... Isso pode demorar."):
                            success, msg = uploader.upload_to_youtube(f, title=yt_title, description=yt_desc, privacy_status=yt_privacy)
                            
                            if success:
                                st.success(msg)
                                st.balloons()
                            else:
                                st.error(msg)


    else:
        st.info("Nenhuma gravação encontrada.")

# --- ABA 3: CONFIGURAÇÕES ---
with tab_settings:
    st.subheader("⚙️ Configurações do Sistema")
    
    settings = settings_manager.load_settings()
    
    st.markdown("### Geral")

    new_interval = st.number_input("Intervalo de Monitoramento (segundos)", min_value=5, value=settings.get("check_interval", 15))
    
    current_format = settings.get("recording_format", "mp4")
    new_format = st.selectbox("Formato de Gravação", ["mp4", "ts", "mkv"], index=["mp4", "ts", "mkv"].index(current_format))
    
    st.caption("Nota: 'ts' é mais seguro para lives (menos chance de corromper), mas arquivos ficam maiores. 'mp4' é mais compatível.")



    st.markdown("### Upload - Arquivo e Credenciais")
    
    tab_archive, tab_youtube = st.tabs(["🏛️ Archive.org", "📹 YouTube"])
    
    with tab_archive:
        st.caption("Obtenha suas chaves em: https://archive.org/account/s3.php")
        
        archive_cfg = settings.get("upload_targets", {}).get("archive", {})
        bk_access = archive_cfg.get("access_key", "")
        bk_secret = archive_cfg.get("secret_key", "")
        
        new_access = st.text_input("Access Key", value=bk_access, type="password")
        new_secret = st.text_input("Secret Key", value=bk_secret, type="password")

    with tab_youtube:
        st.caption("1. Crie um projeto no Google Cloud Console.")
        st.caption("2. Habilite a 'YouTube Data API v3'.")
        st.caption("3. Crie credenciais OAuth 2.0 (Desktop App) e baixe o JSON.")
        
        yt_cfg = settings.get("upload_targets", {}).get("youtube", {})
        current_secrets = yt_cfg.get("client_secrets", "")
        has_token = bool(yt_cfg.get("token"))
        
        new_secrets = st.text_area("Cole o conteúdo do client_secrets.json aqui", value=current_secrets, height=150)
        
        if st.button("Autenticar com YouTube"):
            if not new_secrets:
                st.error("Cole o JSON de segredos primeiro.")
            else:
                uploader = uploader_service.UploaderService(settings)
                token_json, msg = uploader.authenticate_youtube(new_secrets)
                if token_json:
                    st.success("Autenticado com sucesso!")
                    # Save immediately to session state / temp settings so we can persist on save button
                    if "upload_targets" not in settings: settings["upload_targets"] = {}
                    if "youtube" not in settings["upload_targets"]: settings["upload_targets"]["youtube"] = {}
                    
                    settings["upload_targets"]["youtube"]["token"] = token_json
                    # We also update the secrets in case they changed
                    settings["upload_targets"]["youtube"]["client_secrets"] = new_secrets
                    
                    # Force save here to ensure token isn't lost if user doesn't click main save
                    settings_manager.save_settings(settings)
                    st.rerun()
                else:
                    st.error(msg)
        
        if has_token:
            st.success("✅ Token válido salvo. Pronto para upload!")
        else:
            st.warning("⚠️ Não autenticado.")

    
    if st.button("💾 Salvar Configurações"):
        # Update settings object
        settings["check_interval"] = new_interval
        settings["recording_format"] = new_format
        
        if "upload_targets" not in settings:

            settings["upload_targets"] = {}
        if "archive" not in settings["upload_targets"]:
            settings["upload_targets"]["archive"] = {}
            
        settings["upload_targets"]["archive"]["access_key"] = new_access
        settings["upload_targets"]["archive"]["secret_key"] = new_secret
        
        settings_manager.save_settings(settings)
        st.success("Configurações salvas com sucesso! As alterações no intervalo entrarão em vigor no próximo ciclo do serviço.")
        st.rerun()



# --- RODAPÉ / REFRESH ---
st.sidebar.markdown("---")
auto_refresh = st.sidebar.checkbox("Auto-refresh (5s)", value=True)

if auto_refresh:
    time.sleep(5)
    st.rerun()
