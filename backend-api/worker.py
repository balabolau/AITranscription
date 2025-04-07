"""
worker.py - This module starts an RQ worker for handling transcription jobs.
It loads configuration and sensitive credentials from config.yaml and uses the centralized logging configuration.
"""

from logging_config import *
import logging
logger = logging.getLogger(__name__)

import os
import yaml
from redis import Redis
from rq import Worker, Queue

# Load centralized configuration from config.yaml
with open("config.yaml", "r") as f:
    config = yaml.safe_load(f)

BASE_DIR = os.path.expanduser(config.get("directories", {}).get("base", ""))
LOGS_DIR = os.path.join(BASE_DIR, config.get("directories", {}).get("logs", "logs"))

# Redis configuration (stored in config.yaml)
redis_config = config.get("redis", {})
redis_conn = Redis(
    host=redis_config.get("host", "localhost"),
    port=redis_config.get("port", 6379),
    db=redis_config.get("db", 0)
)

queues = [Queue("transcriptions", connection=redis_conn)]

if __name__ == '__main__':
    try:
        logger.info("Starting RQ worker for transcription queue")
        worker = Worker(queues, connection=redis_conn)
        logger.info(f"Worker {worker.name} started, listening to queues: {', '.join([q.name for q in queues])}")
        worker.work()
    except Exception as e:
        logger.error(f"Worker encountered an error: {e}")