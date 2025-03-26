# jobs.py
import logging
import os
from redis import Redis
from rq import Queue
from whisper_process_v6 import process_audio_file, preprocess_audio, transcribe_file_in_chunks

# Set up logging.
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Read the Redis host from the environment variable; default to 'redis' for Docker Compose.
redis_host = os.environ.get("REDIS_HOST", "redis")
logger.info(f"Connecting to Redis at {redis_host}:6379")

try:
    redis_conn = Redis(host="localhost", port=6379, db=0)
    # Test connection.
    redis_conn.ping()
    logger.info("Connected to Redis successfully.")
except Exception as e:
    logger.error("Failed to connect to Redis: " + str(e))
    raise e

# Create a queue for transcription jobs.
job_queue = Queue('transcriptions', connection=redis_conn)

def enqueue_transcription(file_path, output_dir, prompt_override=None, language_override=None):
    """
    Enqueue a transcription job using process_audio_file.
    Returns the job ID.
    """
    try:
        job = job_queue.enqueue_call(
            func=process_audio_file,
            args=(file_path, output_dir, prompt_override, language_override),
            timeout=1800  # 30 minutes timeout
        )
        logger.info(f"Enqueued job with ID: {job.id}")
        return job.id
    except Exception as e:
        logger.error("Error enqueuing job: " + str(e))
        raise e


if __name__ == '__main__':
    # Test enqueuing a job (adjust file paths as needed).
    test_file = 'test_audio.wav'  # Ensure this file exists for testing.
    test_output = 'test_output'     # Ensure this directory exists or adjust as needed.
    test_prompt = 'Test prompt'
    test_language = 'en'
    try:
        job_id = enqueue_transcription(test_file, test_output, test_prompt, test_language)
        logger.info(f"Test job enqueued with ID: {job_id}")
    except Exception as e:
        logger.error("Test call failed: " + str(e))
