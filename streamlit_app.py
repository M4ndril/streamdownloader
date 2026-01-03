import streamlit as st
import streamlink
import subprocess
import sys
import os

# Set page configuration
st.set_page_config(
    page_title="Streamlink Launcher",
    page_icon="📺",
    layout="centered"
)

# Title and Description
st.title("📺 Streamlink Launcher")
st.markdown("Uma interface simples para assistir streams usando o poder do **Streamlink**.")

# Input Section
url = st.text_input("Cole a URL da stream aqui:", placeholder="ex: https://www.twitch.tv/gaules")

# Quality Selection
quality = st.selectbox("Qualidade:", ["best", "1080p60", "1080p", "720p60", "720p", "480p", "360p", "worst", "audio_only"])

# Action
if st.button("🔍 Buscar Stream", type="primary"):
    if url:
        try:
            with st.spinner(f"Processando {url}..."):
                # Fetch streams
                streams = streamlink.streams(url)
                
                if not streams:
                    st.error("Nenhuma stream encontrada. Verifique a URL ou se a live está online.")
                else:
                    # Determine which stream to use
                    if quality in streams:
                        stream = streams[quality]
                    elif "best" in streams:
                        st.warning(f"Qualidade '{quality}' não disponível. Usando 'best'.")
                        stream = streams["best"]
                    else:
                        # Fallback to the first available if 'best' is somehow missing
                        first_quality = list(streams.keys())[0]
                        stream = streams[first_quality]
                        st.warning(f"Qualidade desejada não encontrada. Usando '{first_quality}'.")

                    # Get the direct stream URL
                    stream_url = stream.url
                    
                    st.success("Stream encontrada com sucesso!")
                    
                    # Display Info
                    st.code(stream_url, language="text")
                    st.caption("Copie o link acima para usar no seu player favorito, ou clique abaixo:")

                    # Buttons to launch
                    col1, col2 = st.columns(2)
                    
                    with col1:
                        # Open in Browser/System Default
                        # Note: This runs on the server (User's PC), so it opens the local player
                        if st.button("▶️ Abrir no Player Padrão"):
                            try:
                                if sys.platform == 'win32':
                                    os.startfile(stream_url)
                                elif sys.platform == 'darwin':
                                    subprocess.Popen(['open', stream_url])
                                else:
                                    subprocess.Popen(['xdg-open', stream_url])
                                st.toast("Abrindo player...")
                            except Exception as e:
                                st.error(f"Erro ao abrir player: {e}")

                    with col2:
                        # VLC specific launch attempt (common use case)
                        if st.button("🟠 Tentar abrir no VLC"):
                            try:
                                # Common paths for VLC on Windows
                                vlc_paths = [
                                    r"C:\Program Files\VideoLAN\VLC\vlc.exe",
                                    r"C:\Program Files (x86)\VideoLAN\VLC\vlc.exe"
                                ]
                                vlc_exe = "vlc" # Default command
                                
                                for path in vlc_paths:
                                    if os.path.exists(path):
                                        vlc_exe = path
                                        break
                                
                                subprocess.Popen([vlc_exe, stream_url])
                                st.toast("Enviando para o VLC...")
                            except FileNotFoundError:
                                st.error("VLC não encontrado no caminho padrão/PATH.")
                            except Exception as e:
                                st.error(f"Erro: {e}")

        except streamlink.PluginError as e:
            st.error(f"Erro no plugin: {e}")
        except Exception as e:
            st.error(f"Ocorreu um erro: {e}")
    else:
        st.warning("Por favor, insira uma URL.")

# Footer
st.markdown("---")
st.caption("Rodando localmente usando Streamlit e Streamlink Library")
