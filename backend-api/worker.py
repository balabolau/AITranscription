import os
from redis import Redis
from rq import Worker, Queue
from rq.connections import RedisConnection

redis_conn = Redis(host="localhost", port=6379, db=0)
queues = [Queue("transcriptions", connection=redis_conn)]

if __name__ == '__main__':
    worker = Worker(queues, connection=redis_conn)
    worker.work()
