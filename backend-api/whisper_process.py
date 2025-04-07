"""
whisper_process.py - This module handles audio preprocessing and transcription using the Whisper model.
It includes functionality to split audio into chunks, transcribe each chunk, and perform resource cleanup.
All configuration and sensitive settings are loaded from config.yaml.
"""

from logging_config import *
import logging
logger = logging.getLogger(__name__)

import os
import time
import math
import atexit
import psutil
from pathlib import Path
import subprocess
import torch
import whisper
import warnings
import yaml
import gc
import json
from datetime import datetime
from pydub import AudioSegment
import concurrent.futures

warnings.filterwarnings("ignore", category=FutureWarning)

# Load centralized configuration from config.yaml
with open("config.yaml", "r") as f:
    config = yaml.safe_load(f)

BASE_DIR = os.path.expanduser(config.get("directories", {}).get("base", ""))
LOGS_DIR = os.path.join(BASE_DIR, config.get("directories", {}).get("logs", "logs"))
PROCESSING_DIR = os.path.join(BASE_DIR, config.get("directories", {}).get("processing", "processing"))
FFMPEG_TIMEOUT = config.get("ffmpeg", {}).get("timeout", 300)

# Configuration parameters
MODEL_SIZE = config.get("model", {}).get("size", "turbo")
DEVICE = config.get("model", {}).get("device", "cpu")
PROMPT_TEXT = config.get("model", {}).get("prompt", "")
LANGUAGE = config.get("transcription", {}).get("language", "")
CHUNK_DURATION = config.get("chunking", {}).get("duration", 20)
OVERLAP_DURATION = config.get("chunking", {}).get("overlap", 2)
TEMPERATURE = config.get("transcription", {}).get("temperature", 0.26)
BEAM_SIZE = config.get("transcription", {}).get("beam_size", 5)
BEST_OF = config.get("transcription", {}).get("best_of", 5)
NUM_WORKERS = config.get("transcription", {}).get("num_workers", 1)

MEMORY_THRESHOLD = config.get("resources", {}).get("memory_threshold", 95)
CLEANUP_THRESHOLD = config.get("resources", {}).get("cleanup_threshold", 3)

if torch.backends.mps.is_available():
    torch.backends.mps.allow_fallback = True

def default_progress_callback(message: str):
    try:
        import redis
        r = redis.Redis(host="localhost", port=6379, db=0)
        r.publish("job_updates", message)
    except Exception as e:
        logger.error("Failed to publish progress: " + str(e))

def preprocess_audio(input_path):
    preprocessed_path = os.path.join(PROCESSING_DIR, Path(input_path).stem + "_preprocessed.wav")
    logger.info(f"Preprocessed audio will be saved to: {preprocessed_path}")
    command = [
        "ffmpeg", "-y", "-i", input_path,
        "-ac", "1",
        "-ar", "16000",
        "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
        preprocessed_path
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=FFMPEG_TIMEOUT,
            stdin=subprocess.DEVNULL
        )
    except subprocess.TimeoutExpired as te:
        logger.error(f"FFmpeg command timed out: {te}")
        return None
    except Exception as e:
        logger.error("Error running ffmpeg command: " + str(e))
        return None

    if result.returncode != 0:
        logger.error("Error preprocessing audio: " + result.stderr)
        return None
    logger.info("Audio preprocessed successfully: " + preprocessed_path)
    return preprocessed_path

class WhisperTranscriber:
    def __init__(self):
        logger.info("Initializing WhisperTranscriber...")
        try:
            self.model = self._load_model()
        except Exception as e:
            logger.error(f"Failed to load model: {e}")
            raise
        self.last_cleanup_time = time.time()
        self.processed_since_cleanup = 0
        atexit.register(self.cleanup)
        logger.info("WhisperTranscriber initialized successfully.")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.cleanup()

    def _load_model(self):
        logger.info("Loading Whisper model...")
        try:
            model = whisper.load_model(MODEL_SIZE)
            model = model.to(DEVICE)
            if DEVICE == "mps":
                model = model.float()
            logger.info(f"Loaded {MODEL_SIZE} model on {DEVICE}")
            return model
        except Exception as e:
            logger.error(f"Error loading model: {e}")
            raise

    def check_memory_usage(self):
        try:
            memory_percent = psutil.virtual_memory().percent
            logger.info(f"Current memory usage: {memory_percent}%")
            if memory_percent > MEMORY_THRESHOLD or self.processed_since_cleanup >= CLEANUP_THRESHOLD:
                self.perform_cleanup()
        except Exception as e:
            logger.error(f"Error checking memory usage: {e}")

    def perform_cleanup(self):
        logger.info("Performing memory cleanup...")
        try:
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                logger.info("Emptied CUDA cache.")
            gc.collect()
            self.processed_since_cleanup = 0
            self.last_cleanup_time = time.time()
            logger.info(f"Memory cleanup done. Memory usage: {psutil.virtual_memory().percent}%")
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")

    def cleanup(self):
        logger.info("Cleaning up WhisperTranscriber resources...")
        try:
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            if hasattr(self, "model"):
                del self.model
            gc.collect()
            logger.info("WhisperTranscriber cleanup completed successfully.")
        except Exception as e:
            logger.error(f"Error during final cleanup: {e}")

    def transcribe_file(self, input_path, prompt_override=None, language_override=None):
        logger.info(f"Starting transcription for {input_path}")
        try:
            self.check_memory_usage()
        except Exception as e:
            logger.error(f"Memory check failed: {e}")
        start_time = time.time()
        fp16_setting = False if DEVICE in ["mps", "cpu"] else True
        effective_prompt = prompt_override if prompt_override != "" else ""
        effective_language = language_override if language_override.lower() != "auto" else ""
        logger.info(f"Transcribing with prompt: {effective_prompt}, language: {effective_language}")
        transcribe_kwargs = {
            "audio": input_path,
            "task": "transcribe",
            "prompt": effective_prompt,
            "fp16": fp16_setting,
            "temperature": TEMPERATURE,
            "beam_size": BEAM_SIZE,
            "best_of": BEST_OF,
        }
        if effective_language:
            transcribe_kwargs["language"] = effective_language
        try:
            result = self.model.transcribe(**transcribe_kwargs)
        except Exception as e:
            logger.error(f"Transcription error: {e}")
            return None
        self.processed_since_cleanup += 1
        processing_time = time.time() - start_time
        logger.info(f"Completed transcription in {processing_time:.2f}s for {input_path}")
        return result["text"]

global_transcriber = WhisperTranscriber()

def init_worker():
    global worker_transcriber
    try:
        worker_transcriber = WhisperTranscriber()
    except Exception as e:
        logger.error(f"Worker initialization failed: {e}")
        raise

def transcribe_chunk(args):
    idx, chunk_filename, prompt_override, language_override = args
    try:
        text = worker_transcriber.transcribe_file(chunk_filename, prompt_override=prompt_override, language_override=language_override)
    except Exception as e:
        logger.error(f"Error transcribing chunk {chunk_filename}: {e}")
        text = ""
    try:
        os.remove(chunk_filename)
    except Exception as e:
        logger.error(f"Error removing chunk file {chunk_filename}: {e}")
    return (idx, text)

def transcribe_file_in_chunks(input_path, prompt_override=None, language_override=None, chunk_duration=CHUNK_DURATION, overlap=OVERLAP_DURATION, progress_callback=None):
    try:
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(AudioSegment.from_file, input_path)
            audio = future.result(timeout=60)
    except concurrent.futures.TimeoutError:
        logger.error("Timeout reading audio file for chunk processing: " + input_path)
        return None
    except Exception as e:
        logger.error(f"Error loading audio file {input_path}: {e}")
        return None

    audio_length = len(audio)
    step = int((chunk_duration - overlap) * 1000)
    total_chunks = 1 if audio_length <= int(chunk_duration * 1000) else math.ceil((audio_length - (chunk_duration * 1000)) / step) + 1
    logger.info(f"Starting chunk processing for {input_path} - {total_chunks} chunks expected.")
    if progress_callback:
        progress_callback(f"Starting chunk processing - {total_chunks} chunks expected")
    overall_chunk_start = time.time()
    if NUM_WORKERS <= 1:
        transcriptions = []
        i = 0
        for start in range(0, audio_length, step):
            chunk_start_time = time.time()
            end = start + int(chunk_duration * 1000)
            if end > audio_length:
                end = audio_length
            chunk = audio[start:end]
            chunk_filename = f"{input_path}_chunk_{i}.wav"
            try:
                chunk.export(chunk_filename, format="wav")
                logger.info(f"Exported chunk {i} to {chunk_filename}")
            except Exception as e:
                logger.error(f"Error exporting chunk {i} from {input_path}: {e}")
                continue
            chunk_text = global_transcriber.transcribe_file(chunk_filename, prompt_override=prompt_override, language_override=language_override)
            if chunk_text is None:
                chunk_text = ""
            transcriptions.append(chunk_text)
            try:
                os.remove(chunk_filename)
            except Exception as e:
                logger.error(f"Error removing chunk file {chunk_filename}: {e}")
            i += 1
            chunk_time = time.time() - chunk_start_time
            progress_percent = ((i) / total_chunks) * 100
            msg = f"Chunk {i}/{total_chunks} transcribed in {chunk_time:.2f}s ({progress_percent:.2f}% complete)"
            logger.info(msg)
            if progress_callback:
                progress_callback(msg)
        overall_chunk_time = time.time() - overall_chunk_start
        logger.info(f"All chunks processed in {overall_chunk_time:.2f}s")
        if progress_callback:
            progress_callback(f"All chunks processed in {overall_chunk_time:.2f}s")
        return "\n".join(transcriptions)
    else:
        from multiprocessing import Pool
        chunk_files = []
        i = 0
        for start in range(0, audio_length, step):
            end = start + int(chunk_duration * 1000)
            if end > audio_length:
                end = audio_length
            chunk = audio[start:end]
            chunk_filename = f"{input_path}_chunk_{i}.wav"
            try:
                chunk.export(chunk_filename, format="wav")
            except Exception as e:
                logger.error(f"Error exporting chunk {i} from {input_path}: {e}")
                continue
            chunk_files.append((i, chunk_filename, prompt_override, language_override))
            i += 1
        results = [None] * len(chunk_files)
        from multiprocessing import Pool
        try:
            with Pool(NUM_WORKERS, initializer=init_worker) as pool:
                for idx, text in pool.imap_unordered(transcribe_chunk, chunk_files):
                    results[idx] = text
                    progress_percent = ((idx + 1) / len(chunk_files)) * 100
                    logger.info(f"Chunk {idx+1}/{len(chunk_files)} transcribed ({progress_percent:.2f}% complete)")
                    if progress_callback:
                        progress_callback(idx+1, len(chunk_files), None)
        except Exception as e:
            logger.error(f"Error processing chunks in parallel: {e}")
            return None
        overall_chunk_time = time.time() - overall_chunk_start
        logger.info(f"All chunks processed in {overall_chunk_time:.2f}s")
        return "\n".join(results)

def process_audio_file(input_path, output_dir, prompt_override=None, language_override=None, progress_callback=default_progress_callback):
    overall_start = time.time()
    logger.info(f"Processing audio file: {input_path}")
    if progress_callback:
        progress_callback(f"Transcription started for {input_path.split('/')[-1]}")
    preprocessed = preprocess_audio(input_path)
    if preprocessed is None:
        logger.error("Preprocessing failed for " + input_path)
        if progress_callback:
            progress_callback("Preprocessing failed")
        return False
    logger.info("Audio preprocessed successfully: " + preprocessed)
    if progress_callback:
        progress_callback("Audio preprocessed successfully")
    text = transcribe_file_in_chunks(preprocessed, prompt_override=prompt_override, language_override=language_override,
                                     chunk_duration=CHUNK_DURATION, overlap=OVERLAP_DURATION, progress_callback=progress_callback)
    overall_time = time.time() - overall_start
    logger.info(f"Total processing time for {input_path}: {overall_time:.2f}s")
    if progress_callback:
        progress_callback(f"Transcription finished in {overall_time:.2f}s")
    try:
        mem_usage = psutil.virtual_memory().percent
        logger.info(f"System memory usage after processing: {mem_usage}%")
    except Exception as e:
        logger.error(f"Error reading system memory usage: {e}")
    if text:
        from pathlib import Path
        output_path = Path(output_dir) / (Path(input_path).stem + ".txt")
        try:
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(text)
            logger.info(f"Saved transcript to {output_path}")
        except Exception as e:
            logger.error(f"Error saving transcript to {output_path}: {e}")
            return False
        try:
            os.remove(preprocessed)
        except Exception as e:
            logger.error(f"Error removing preprocessed file {preprocessed}: {e}")
        try:
            os.remove(input_path)
        except Exception as e:
            logger.error(f"Error removing original file {input_path}: {e}")
        return True
    return False