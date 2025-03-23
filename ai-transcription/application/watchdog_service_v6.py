import os
import time
import logging
import shutil
import subprocess
import yaml
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from whisper_process_v6 import process_audio_file, WhisperTranscriber

# Load configuration from YAML.
with open("config.yaml", "r") as f:
    config = yaml.safe_load(f)

# Setup directories from config.
BASE_DIR = os.path.expanduser(config.get("directories", {}).get("base", "~/Documents/WhisperProcessor"))
INPUT_DIR = os.path.join(BASE_DIR, config.get("directories", {}).get("input", "audio_input"))
PROCESSING_DIR = os.path.join(BASE_DIR, config.get("directories", {}).get("processing", "processing"))
OUTPUT_DIR = os.path.join(BASE_DIR, config.get("directories", {}).get("transcripts", "transcripts"))
LOGS_DIR = os.path.join(BASE_DIR, config.get("directories", {}).get("logs", "logs"))
ERROR_DIR = os.path.join(BASE_DIR, config.get("directories", {}).get("error", "error"))

for d in [INPUT_DIR, PROCESSING_DIR, OUTPUT_DIR, LOGS_DIR, ERROR_DIR]:
    os.makedirs(d, exist_ok=True)

# Mac-specific flags.
enable_caffeinate = config.get("mac", {}).get("enable_caffeinate", False)
enable_terminal_log = config.get("mac", {}).get("enable_terminal_log", False)
caffeinate_proc = None

def start_caffeinate():
    global caffeinate_proc
    if not enable_caffeinate:
        return
    if caffeinate_proc is None:
        try:
            caffeinate_proc = subprocess.Popen(["caffeinate", "-dims"])
            logging.info(f"Started caffeinate process (PID: {caffeinate_proc.pid}).")
        except Exception as e:
            logging.error(f"Failed to start caffeinate: {e}")

def stop_caffeinate():
    global caffeinate_proc
    if not enable_caffeinate:
        return
    if caffeinate_proc is not None:
        try:
            caffeinate_proc.terminate()
            logging.info(f"Stopped caffeinate process (PID: {caffeinate_proc.pid}).")
        except Exception as e:
            logging.error(f"Failed to stop caffeinate: {e}")
        finally:
            caffeinate_proc = None

def is_work_pending():
    return bool(os.listdir(INPUT_DIR) or os.listdir(PROCESSING_DIR))

def launch_log_terminal():
    if not enable_terminal_log:
        return
    log_file = os.path.expanduser(os.path.join(LOGS_DIR, "processing.log"))
    if not os.path.exists(log_file):
        open(log_file, "a").close()
    apple_script = f'''
tell application "Terminal"
    activate
    do script "tail -f '{log_file}'"
end tell
'''
    result = subprocess.run(["osascript", "-e", apple_script], capture_output=True, text=True)
    if result.returncode != 0:
        logging.error("osascript error: " + result.stderr)
    else:
        logging.info("Terminal log viewer launched successfully.")
        return True
    return False

class FileReadyMonitor:
    def __init__(self, min_stable_time=0.5, check_interval=0.1, timeout=30):
        self.min_stable_time = min_stable_time
        self.check_interval = check_interval
        self.timeout = timeout
        
    def is_file_ready(self, filepath):
        start_time = time.time()
        last_size = -1
        stable_since = None
        while time.time() - start_time < self.timeout:
            try:
                current_size = os.path.getsize(filepath)
                if current_size == last_size:
                    if stable_since is None:
                        stable_since = time.time()
                    elif time.time() - stable_since >= self.min_stable_time:
                        logging.info(f"File {filepath} is ready for processing")
                        return True
                else:
                    stable_since = None
                last_size = current_size
                time.sleep(self.check_interval)
            except FileNotFoundError:
                logging.error(f"File {filepath} no longer exists")
                return False
            except Exception as e:
                logging.error(f"Error checking file {filepath}: {e}")
                return False
        logging.warning(f"Timeout reached waiting for file {filepath} to stabilize")
        return False

class AudioHandler(FileSystemEventHandler):
    def __init__(self):
        self.file_monitor = FileReadyMonitor(min_stable_time=0.5, check_interval=0.1, timeout=30)

    def on_created(self, event):
        if not event.is_directory:
            if self.file_monitor.is_file_ready(event.src_path):
                self.process_file(event.src_path)
            else:
                logging.error(f"File {event.src_path} not ready for processing")
                if os.path.exists(event.src_path):
                    shutil.move(event.src_path, ERROR_DIR)

    def process_file(self, src_path):
        supported_extensions = [".wav", ".mp3", ".m4a", ".ogg", ".flac", ".mp4"]
        ext = os.path.splitext(src_path)[1].lower()
        if ext not in supported_extensions:
            logging.error(f"Unsupported file format for {src_path}")
            filename = os.path.basename(src_path)
            error_path = os.path.join(ERROR_DIR, filename)
            shutil.move(src_path, error_path)
            logging.info(f"Moved unsupported file '{filename}' to error directory.")
            return
        if not os.path.exists(src_path):
            logging.info(f"File {src_path} no longer exists; skipping processing.")
            return
        filename = os.path.basename(src_path)
        processing_path = os.path.join(PROCESSING_DIR, filename)
        shutil.move(src_path, processing_path)
        logging.info(f"Moved file '{filename}' to processing directory.")
        success = process_audio_file(processing_path, OUTPUT_DIR)
        if success:
            os.remove(processing_path)
            logging.info(f"Processed and removed file: {filename}")
        else:
            logging.error(f"Failed to process file: {filename}")
            error_path = os.path.join(ERROR_DIR, filename)
            shutil.move(processing_path, error_path)
            logging.info(f"Moved failed file '{filename}' to error directory.")

def run_watcher():
    if enable_terminal_log:
        launch_log_terminal()
    event_handler = AudioHandler()
    observer = Observer()
    observer.schedule(event_handler, INPUT_DIR, recursive=False)
    observer.start()
    logging.info("Started file watcher on: " + INPUT_DIR)
    try:
        while True:
            time.sleep(10)
            if is_work_pending():
                start_caffeinate()
            else:
                stop_caffeinate()
    except KeyboardInterrupt:
        observer.stop()
        logging.info("Watcher stopped by keyboard interrupt.")
        stop_caffeinate()
    observer.join()

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler()]
    )
    run_watcher()
