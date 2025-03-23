from fastapi import FastAPI, File, UploadFile, WebSocket, WebSocketDisconnect, HTTPException
import shutil
import uuid
import os
import asyncio
import logging
import json
from datetime import datetime
from redis import Redis
from rq import Queue

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("api.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

app = FastAPI()

# Set up a synchronous Redis connection for the job queue
redis_conn = Redis(host="localhost", port=6379, db=0)
job_queue = Queue("transcriptions", connection=redis_conn)

# Redis key for storing transcription messages
REDIS_MESSAGES_KEY = "transcription_messages"

# Maximum number of messages to keep in Redis
MAX_MESSAGES = 100

# Directory to store uploaded files
UPLOAD_DIR = "./uploads"
if not os.path.exists(UPLOAD_DIR):
    os.makedirs(UPLOAD_DIR)
    logger.info(f"Created upload directory: {UPLOAD_DIR}")

# Global set to store connected WebSocket clients
connected_clients = set()

# Helper function to store message in Redis
def store_message(message):
    timestamp = datetime.now().isoformat()
    message_data = json.dumps({"timestamp": timestamp, "message": message})
    
    # Add to Redis list and trim to keep only recent messages
    try:
        redis_conn.lpush(REDIS_MESSAGES_KEY, message_data)
        redis_conn.ltrim(REDIS_MESSAGES_KEY, 0, MAX_MESSAGES - 1)
        logger.debug(f"Stored message in Redis: {message}")
    except Exception as e:
        logger.error(f"Error storing message in Redis: {e}")

# Helper function to get recent messages from Redis
def get_recent_messages(count=20):
    try:
        messages = redis_conn.lrange(REDIS_MESSAGES_KEY, 0, count - 1)
        result = []
        for msg_data in messages:
            msg = json.loads(msg_data)
            result.append(msg)
        return result
    except Exception as e:
        logger.error(f"Error getting messages from Redis: {e}")
        return []

# WebSocket endpoint for real-time updates
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    client_id = str(id(websocket))[-6:]  # Use last 6 digits of object id as identifier
    await websocket.accept()
    connected_clients.add(websocket)
    logger.debug(f"WebSocket client {client_id} connected. Total clients: {len(connected_clients)}")
    
    # Send recent message history to the client upon connect
    try:
        recent_messages = get_recent_messages()
        if recent_messages:
            # Send history message
            await websocket.send_text(json.dumps({
                "type": "history", 
                "messages": recent_messages
            }))
            logger.debug(f"Sent {len(recent_messages)} history messages to client {client_id}")
    except Exception as e:
        logger.error(f"Error sending history to client {client_id}: {e}")
    
    try:
        while True:
            # Wait for a message but don't require one to keep the connection alive
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=3600.0)  # 1 hour timeout
            except asyncio.TimeoutError:
                # This is expected behavior for long-polling, just continue
                pass
    except WebSocketDisconnect:
        connected_clients.remove(websocket)
        logger.debug(f"WebSocket client {client_id} disconnected. Remaining clients: {len(connected_clients)}")

# Helper function to broadcast messages to all connected WebSocket clients
async def broadcast_message(message: str):
    logger.debug(f"Broadcasting message to {len(connected_clients)} clients: {message}")
    
    # Store message in Redis for history
    store_message(message)
    
    # Format as a regular update message
    update_message = json.dumps({
        "type": "update",
        "timestamp": datetime.now().isoformat(),
        "message": message
    })
    
    disconnected_clients = set()
    
    for client in connected_clients:
        try:
            await client.send_text(update_message)
        except Exception as e:
            client_id = str(id(client))[-6:]
            logger.error(f"Error sending message to client {client_id}: {e}")
            # Mark this client for removal
            disconnected_clients.add(client)
    
    # Remove any disconnected clients outside the iteration loop
    for client in disconnected_clients:
        client_id = str(id(client))[-6:]
        logger.debug(f"Removing disconnected client {client_id}")
        connected_clients.remove(client)

# Startup event: subscribe to Redis Pub/Sub channel "job_updates" using the async interface.
@app.on_event("startup")
async def start_pubsub_listener():
    logger.info("Starting Redis Pub/Sub listener for job updates")
    # Use the async Redis client from redis.asyncio
    import redis.asyncio as redis_async
    redis_sub = redis_async.Redis(host="localhost", port=6379, db=0)
    pubsub = redis_sub.pubsub()
    await pubsub.subscribe("job_updates")
    
    async def pubsub_listener():
        logger.info("Pub/Sub listener task started")
        while True:
            try:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message:
                    data = message["data"]
                    if isinstance(data, bytes):
                        data = data.decode("utf-8")
                    logger.debug(f"Received message from Redis: {data}")
                    await broadcast_message(data)
                    # Add a short delay after broadcasting a message
                    # This helps ensure clients have time to process the message
                    await asyncio.sleep(0.1)
                # Reduce the polling frequency to avoid excessive CPU usage
                await asyncio.sleep(0.5)
            except Exception as e:
                logger.error(f"Error in pubsub listener: {e}")
                await asyncio.sleep(1.0)  # Wait a bit longer on error
    
    asyncio.create_task(pubsub_listener())

# Dummy processing function that simulates transcription and publishes updates via Redis Pub/Sub.
def process_file(file_path, job_id):
    import time
    logger = logging.getLogger(f"worker.job.{job_id}")
    logger.info(f"Starting transcription job {job_id} for file {os.path.basename(file_path)}")
    # Create a synchronous Redis connection for publishing messages
    redis_sync = Redis(host="localhost", port=6379, db=0)
    redis_sync.publish("job_updates", f"Job {job_id} started processing...")
    for i in range(1, 6):
        time.sleep(1)
        progress = i * 20
        logger.info(f"Job {job_id} progress: {progress}%")
        redis_sync.publish("job_updates", f"Job {job_id} progress: {progress}% complete")
    transcript = f"Transcribed text for file {os.path.basename(file_path)}"
    output_path = file_path + ".txt"
    try:
        with open(output_path, "w") as f:
            f.write(transcript)
        logger.info(f"Job {job_id} completed. Transcript saved at {output_path}")
        redis_sync.publish("job_updates", f"Job {job_id} completed. Transcript saved at {output_path}")
    except Exception as e:
        logger.error(f"Error saving transcript for job {job_id}: {e}")
        redis_sync.publish("job_updates", f"Job {job_id} failed: {str(e)}")
        raise
    return transcript

# API endpoint to handle file uploads and job creation
@app.post("/upload")
async def upload_file(audioFile: UploadFile = File(...)):
    file_id = str(uuid.uuid4())
    logger.info(f"Processing upload request for file: {audioFile.filename}, assigned ID: {file_id}")
    try:
        file_location = os.path.join(UPLOAD_DIR, file_id + "_" + audioFile.filename)
        with open(file_location, "wb") as buffer:
            shutil.copyfileobj(audioFile.file, buffer)
        logger.info(f"File saved successfully at {file_location}")
    except Exception as e:
        logger.error(f"Error saving file {audioFile.filename}: {e}")
        raise HTTPException(status_code=500, detail="Error saving file") from e

    # Enqueue the transcription job
    job = job_queue.enqueue(process_file, file_location, file_id)
    logger.info(f"Transcription job enqueued with ID: {job.get_id()}")
    return {"jobId": job.get_id(), "message": "File uploaded and job enqueued"}

@app.on_event("startup")
async def startup_event():
    logger.info("API server starting up")

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("API server shutting down")

if __name__ == "__main__":
    import uvicorn
    logger.info("Starting FastAPI application")