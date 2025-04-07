from logging_config import *
import logging
logger = logging.getLogger(__name__)

import os
import yaml
from redis import Redis
from rq import Queue
from whisper_process import process_audio_file

# Load centralized configuration from config.yaml
with open("config.yaml", "r") as f:
    config = yaml.safe_load(f)

BASE_DIR = os.path.expanduser(config.get("directories", {}).get("base", ""))
LOGS_DIR = os.path.join(BASE_DIR, config.get("directories", {}).get("logs", "logs"))

# Get Redis configuration
redis_config = config.get("redis", {})
redis_host = redis_config.get("host", "localhost")
redis_port = redis_config.get("port", 6379)
redis_db = redis_config.get("db", 0)
logger.info(f"Connecting to Redis at {redis_host}:{redis_port}")

try:
    redis_conn = Redis(host=redis_host, port=redis_port, db=redis_db)
    redis_conn.ping()
    logger.info("Connected to Redis successfully.")
except Exception as e:
    logger.error("Failed to connect to Redis: " + str(e))
    raise e

# Create a queue for transcription jobs.
job_queue = Queue("transcriptions", connection=redis_conn)

def enqueue_transcription(file_path, output_dir, prompt_override=None, language_override=None):
    """
    Enqueue a transcription job using process_audio_file.
    
    :param file_path: Path to the audio file to transcribe.
    :param output_dir: Directory where the transcript will be saved.
    :param prompt_override: Optional transcription prompt override.
    :param language_override: Optional transcription language override.
    :return: The enqueued job ID.
    """
    try:
        job = job_queue.enqueue_call(
            func=process_audio_file,
            args=(file_path, output_dir, prompt_override, language_override),
            timeout=7200  # 120 minutes timeout
        )
        logger.info(f"Enqueued job with ID: {job.id}")
        return job.id
    except Exception as e:
        logger.error("Error enqueuing job: " + str(e))
        raise e
