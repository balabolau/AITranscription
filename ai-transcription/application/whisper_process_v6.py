import os
import time
import math
import logging
import atexit
import psutil
from pathlib import Path
import subprocess
import torch
import whisper
import warnings
import yaml
import gc
from pydub import AudioSegment
from multiprocessing import Pool, cpu_count

warnings.filterwarnings("ignore", category=FutureWarning)

# Load configuration.
with open("config.yaml", "r") as f:
    config = yaml.safe_load(f)

# Configuration parameters.
MODEL_SIZE = config.get("model", {}).get("size", "large")
DEVICE = config.get("model", {}).get("device", "cpu")
prompt_text = config.get("model", {}).get("prompt", "")
language = config.get("transcription", {}).get("language", "")
chunk_duration = config.get("chunking", {}).get("duration", 30)
overlap_duration = config.get("chunking", {}).get("overlap", 2)
temperature = config.get("transcription", {}).get("temperature", 0.26)
beam_size = config.get("transcription", {}).get("beam_size", 5)
best_of = config.get("transcription", {}).get("best_of", 5)
num_workers = config.get("transcription", {}).get("num_workers", 1)

# Memory management configuration.
MEMORY_THRESHOLD = config.get("resources", {}).get("memory_threshold", 95)
CLEANUP_THRESHOLD = config.get("resources", {}).get("cleanup_threshold", 5)

# Configure logging.
base_dir = os.path.expanduser(config.get("directories", {}).get("base", "~/Documents/WhisperProcessor"))
log_dir = os.path.join(base_dir, config.get("directories", {}).get("logs", "logs"))
log_path = os.path.expanduser(os.path.join(log_dir, "processing.log"))
logging.basicConfig(
    filename=log_path,
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

if torch.backends.mps.is_available():
    torch.backends.mps.allow_fallback = True

def preprocess_audio(input_path):
    preprocessed_path = str(Path(input_path).with_name(Path(input_path).stem + "_preprocessed.wav"))
    command = [
        "ffmpeg", "-y", "-i", input_path,
        "-ac", "1",
        "-ar", "16000",
        "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
        preprocessed_path
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        logging.error("Error preprocessing audio: " + result.stderr)
        return None
    logging.info("Audio preprocessed successfully: " + preprocessed_path)
    return preprocessed_path

class WhisperTranscriber:
    def __init__(self):
        self.model = self._load_model()
        self.last_cleanup_time = time.time()
        self.processed_since_cleanup = 0
        atexit.register(self.cleanup)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.cleanup()

    def _load_model(self):
        logging.info("Loading Whisper model...")
        try:
            model = whisper.load_model(MODEL_SIZE)
            model = model.to(DEVICE)
            if DEVICE == "mps":
                model = model.float()
            logging.info(f"Loaded {MODEL_SIZE} model on {DEVICE}")
            return model
        except Exception as e:
            logging.error(f"Error loading model: {str(e)}")
            raise

    def check_memory_usage(self):
        memory_percent = psutil.virtual_memory().percent
        if memory_percent > MEMORY_THRESHOLD or self.processed_since_cleanup >= CLEANUP_THRESHOLD:
            self.perform_cleanup()

    def perform_cleanup(self):
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        gc.collect()
        self.processed_since_cleanup = 0
        self.last_cleanup_time = time.time()
        logging.info(f"Memory cleanup performed. Current memory usage: {psutil.virtual_memory().percent}%")

    def cleanup(self):
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        if hasattr(self, 'model'):
            del self.model
        gc.collect()
        logging.info("WhisperTranscriber cleanup completed successfully")

    def transcribe_file(self, input_path, prompt_override=None, language_override=None):
        try:
            self.check_memory_usage()
            start_time = time.time()
            logging.info(f"Starting transcription for {input_path}")
            fp16_setting = False if DEVICE in ["mps", "cpu"] else True
            effective_prompt = prompt_override if prompt_override is not None else prompt_text
            effective_language = language_override if language_override is not None else language
            transcribe_kwargs = {
                "audio": input_path,
                "task": "transcribe",
                "prompt": effective_prompt,
                "fp16": fp16_setting,
                "temperature": temperature,
                "beam_size": beam_size,
                "best_of": best_of,
            }
            if effective_language:
                transcribe_kwargs["language"] = effective_language

            result = self.model.transcribe(**transcribe_kwargs)
            self.processed_since_cleanup += 1
            processing_time = time.time() - start_time
            logging.info(f"Completed transcription in {processing_time:.2f}s for {input_path}")
            return result["text"]
        except Exception as e:
            logging.error(f"Error transcribing {input_path}: {str(e)}")
            return None

global_transcriber = WhisperTranscriber()

def init_worker():
    global worker_transcriber
    worker_transcriber = WhisperTranscriber()

def transcribe_chunk(args):
    idx, chunk_filename, prompt_override, language_override = args
    text = worker_transcriber.transcribe_file(chunk_filename, prompt_override=prompt_override, language_override=language_override)
    os.remove(chunk_filename)
    return (idx, text)

def transcribe_file_in_chunks(input_path, prompt_override=None, language_override=None, chunk_duration=chunk_duration, overlap=overlap_duration, progress_callback=None):
    audio = AudioSegment.from_file(input_path)
    audio_length = len(audio)
    step = int((chunk_duration - overlap) * 1000)
    total_chunks = 1 if audio_length <= int(chunk_duration * 1000) else math.ceil((audio_length - (chunk_duration * 1000)) / step) + 1

    logging.info(f"Starting chunk processing: {total_chunks} chunks expected.")
    overall_chunk_start = time.time()

    if num_workers <= 1:
        transcriptions = []
        i = 0
        for start in range(0, audio_length, step):
            chunk_start_time = time.time()
            end = start + int(chunk_duration * 1000)
            if end > audio_length:
                end = audio_length
            chunk = audio[start:end]
            chunk_filename = f"{input_path}_chunk_{i}.wav"
            chunk.export(chunk_filename, format="wav")
            chunk_text = global_transcriber.transcribe_file(chunk_filename, prompt_override=prompt_override, language_override=language_override)
            if chunk_text is None:
                chunk_text = ""
            transcriptions.append(chunk_text)
            os.remove(chunk_filename)
            i += 1
            chunk_time = time.time() - chunk_start_time
            progress_percent = (i / total_chunks) * 100
            log_msg = f"Chunk {i}/{total_chunks} transcribed in {chunk_time:.2f}s ({progress_percent:.2f}% complete)"
            logging.info(log_msg)
            if progress_callback:
                progress_callback(i, total_chunks, chunk_time)
        overall_chunk_time = time.time() - overall_chunk_start
        logging.info(f"All chunks processed in {overall_chunk_time:.2f}s")
        return "\n".join(transcriptions)
    else:
        chunk_files = []
        i = 0
        for start in range(0, audio_length, step):
            end = start + int(chunk_duration * 1000)
            if end > audio_length:
                end = audio_length
            chunk = audio[start:end]
            chunk_filename = f"{input_path}_chunk_{i}.wav"
            chunk.export(chunk_filename, format="wav")
            chunk_files.append((i, chunk_filename, prompt_override, language_override))
            i += 1

        results = [None] * len(chunk_files)
        with Pool(num_workers, initializer=init_worker) as pool:
            for idx, text in pool.imap_unordered(transcribe_chunk, chunk_files):
                results[idx] = text
                progress_percent = ((idx + 1) / len(chunk_files)) * 100
                logging.info(f"Chunk {idx+1}/{len(chunk_files)} transcribed ({progress_percent:.2f}% complete)")
                if progress_callback:
                    progress_callback(idx+1, len(chunk_files), None)
        overall_chunk_time = time.time() - overall_chunk_start
        logging.info(f"All chunks processed in {overall_chunk_time:.2f}s")
        return "\n".join(results)

def process_audio_file(input_path, output_dir, prompt_override=None, language_override=None, progress_callback=None):
    overall_start = time.time()
    preprocessed = preprocess_audio(input_path)
    if preprocessed is None:
        logging.error("Preprocessing failed for " + input_path)
        return False
    text = transcribe_file_in_chunks(preprocessed, prompt_override=prompt_override, language_override=language_override, chunk_duration=chunk_duration, overlap=overlap_duration, progress_callback=progress_callback)
    overall_time = time.time() - overall_start
    logging.info(f"Total processing time for {input_path}: {overall_time:.2f}s")
    mem_usage = psutil.virtual_memory().percent
    logging.info(f"System memory usage after processing: {mem_usage}%")
    if text:
        output_path = Path(output_dir) / (Path(input_path).stem + ".txt")
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(text)
        logging.info(f"Saved transcript to {output_path}")
        os.remove(preprocessed)
        return True
    return False
