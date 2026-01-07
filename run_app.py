import sys
import subprocess
import time
import os

def main():
    print("🚀 Starting Streamlink Recorder (FastAPI)...")
    
    # Define commands
    # Use 'uvicorn' via module
    cmd_server = [sys.executable, "-m", "uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8501", "--reload", "--no-access-log"]
    cmd_monitor = [sys.executable, "monitor_service.py"]

    processes = []

    try:
        # Start Monitor Service
        print("Starting Monitor Service...")
        p_monitor = subprocess.Popen(cmd_monitor)
        processes.append(p_monitor)

        # Start Web Server
        print("Starting Web Server...")
        p_server = subprocess.Popen(cmd_server)
        processes.append(p_server)

        print("\n✅ All services started!")
        print("➡️  Open http://localhost:8000 in your browser.")
        print("Press Ctrl+C to stop.")
        
        # Wait for processes
        while True:
            time.sleep(1)
            if p_monitor.poll() is not None:
                print("⚠️ Monitor Service died!")
                break
            if p_server.poll() is not None:
                print("⚠️ Web Server died!")
                break

    except KeyboardInterrupt:
        print("\n🛑 Stopping services...")
    finally:
        for p in processes:
            if p.poll() is None:
                p.terminate()
        print("👋 Bye!")

if __name__ == "__main__":
    main()
