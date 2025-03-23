import os
import logging
from redis import Redis
from rq import Worker, Queue
from rq.connections import RedisConnection

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("worker.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

redis_conn = Redis(host="localhost", port=6379, db=0)
queues = [Queue("transcriptions", connection=redis_conn)]

if __name__ == '__main__':
    logger.info("Starting RQ worker for transcription queue")
    worker = Worker(queues, connection=redis_conn)
    logger.info(f"Worker {worker.name} started, listening to queues: {', '.join([q.name for q in queues])}")
    worker.work()
