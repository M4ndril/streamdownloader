import psutil
import sys
import time
import subprocess


def kill_proc_tree(pid, including_parent=True):    
    try:
        parent = psutil.Process(pid)
        for child in parent.children(recursive=True):
            child.kill()
        if including_parent:
            parent.kill()
    except psutil.NoSuchProcess:
        pass

def main():
    print("🚀 Starting Twitch Recorder App (Local Mode)...")
    
    # Define commands
    # Use 'streamlit run' via module to avoid path issues
    cmd_streamlit = [sys.executable, "-m", "streamlit", "run", "twitch_recorder.py", "--server.port=8501"]
    cmd_monitor = [sys.executable, "monitor_service.py"]

    processes = []

    try:
        # Start Monitor Service
        print("Starting Monitor Service...")
        p_monitor = subprocess.Popen(cmd_monitor)
        processes.append(p_monitor)

        # Start Streamlit
        print("Starting Streamlit UI...")
        p_streamlit = subprocess.Popen(cmd_streamlit)
        processes.append(p_streamlit)

        print("\n✅ All services started! Press Ctrl+C to stop.")
        
        # Wait for processes
        while True:
            time.sleep(1)
            # Check if any process died
            if p_monitor.poll() is not None:
                print("⚠️ Monitor Service died! Exiting...")
                break
            if p_streamlit.poll() is not None:
                print("⚠️ Streamlit UI died! Exiting...")
                break

    except KeyboardInterrupt:
        print("\n🛑 Stopping services...")
    finally:
        for p in processes:
            if p.poll() is None:
                print(f"Killing process {p.pid} and its children...")
                kill_proc_tree(p.pid)
        print("👋 Bye!")

if __name__ == "__main__":
    main()
