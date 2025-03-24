from fastapi import FastAPI, File, UploadFile, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
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

# Enable CORS for all origins (adjust for production as needed)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Set up a synchronous Redis connection for the job queue
redis_conn = Redis(host="localhost", port=6379, db=0)
job_queue = Queue("transcriptions", connection=redis_conn)

# Directories for uploads and outputs
UPLOAD_DIR = "./uploads"
if not os.path.exists(UPLOAD_DIR):
    os.makedirs(UPLOAD_DIR)
    logger.info(f"Created upload directory: {UPLOAD_DIR}")

OUTPUT_DIR = "./outputs"
if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)
    logger.info(f"Created output directory: {OUTPUT_DIR}")

# Redis key for storing transcription messages (history)
REDIS_MESSAGES_KEY = "transcription_messages"
MAX_MESSAGES = 100

# Global set to store connected WebSocket clients
connected_clients = set()

# Helper function to store a message in Redis (for history)
def store_message(message):
    timestamp = datetime.now().isoformat()
    message_data = json.dumps({"timestamp": timestamp, "message": message})
    try:
        redis_conn.lpush(REDIS_MESSAGES_KEY, message_data)
        redis_conn.ltrim(REDIS_MESSAGES_KEY, 0, MAX_MESSAGES - 1)
    except Exception as e:
        logger.error(f"Error storing message in Redis: {e}")

# Helper function to get recent messages from Redis
def get_recent_messages(count=20):
    try:
        messages = redis_conn.lrange(REDIS_MESSAGES_KEY, 0, count - 1)
        return [json.loads(msg) for msg in messages]
    except Exception as e:
        logger.error(f"Error getting messages from Redis: {e}")
        return []

# WebSocket endpoint for real-time updates
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    client_id = str(id(websocket))[-6:]
    await websocket.accept()
    connected_clients.add(websocket)
    logger.debug(f"WebSocket client {client_id} connected. Total: {len(connected_clients)}")
    # Send recent history
    try:
        recent_messages = get_recent_messages()
        if recent_messages:
            await websocket.send_text(json.dumps({
                "type": "history",
                "messages": recent_messages
            }))
            logger.debug(f"Sent history to client {client_id}")
    except Exception as e:
        logger.error(f"Error sending history to client {client_id}: {e}")
    try:
        while True:
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=3600.0)
            except asyncio.TimeoutError:
                pass
    except WebSocketDisconnect:
        connected_clients.remove(websocket)
        logger.debug(f"WebSocket client {client_id} disconnected. Remaining: {len(connected_clients)}")

# Helper function to broadcast messages to all connected WebSocket clients
async def broadcast_message(message: str):
    logger.debug(f"Broadcasting: {message}")
    store_message(message)
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
            logger.error(f"Error sending to client {client_id}: {e}")
            disconnected_clients.add(client)
    for client in disconnected_clients:
        connected_clients.remove(client)

# Startup event: subscribe to Redis Pub/Sub channel "job_updates"
@app.on_event("startup")
async def start_pubsub_listener():
    logger.info("Starting Redis Pub/Sub listener for job updates")
    import redis.asyncio as redis_async
    redis_sub = redis_async.Redis(host="localhost", port=6379, db=0)
    pubsub = redis_sub.pubsub()
    await pubsub.subscribe("job_updates")
    logger.info("Subscribed to 'job_updates'")
    
    async def pubsub_listener():
        logger.info("Pub/Sub listener running")
        while True:
            try:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message:
                    data = message["data"]
                    if isinstance(data, bytes):
                        data = data.decode("utf-8")
                    logger.debug(f"Received from Redis: {data}")
                    await broadcast_message(data)
                    await asyncio.sleep(0.1)
                await asyncio.sleep(0.5)
            except Exception as e:
                logger.error(f"Error in pubsub listener: {e}")
                await asyncio.sleep(1.0)
    asyncio.create_task(pubsub_listener())

# Dummy processing function that simulates transcription and publishes updates.
def process_file(file_path, job_id):
    import time
    worker_logger = logging.getLogger(f"worker.job.{job_id}")
    worker_logger.info(f"Starting transcription for {os.path.basename(file_path)}")
    redis_sync = Redis(host="localhost", port=6379, db=0)
    redis_sync.publish("job_updates", f"Job {job_id} started processing...")
    for i in range(1, 6):
        time.sleep(1)
        progress = i * 20
        worker_logger.info(f"Job {job_id} progress: {progress}%")
        redis_sync.publish("job_updates", f"Job {job_id} progress: {progress}% complete")
    transcript = f"Transcribed text for file {os.path.basename(file_path)}"
    # Save the transcript in OUTPUT_DIR
    base, _ = os.path.splitext(os.path.basename(file_path))
    output_filename = base + ".txt"
    output_path = os.path.join(OUTPUT_DIR, output_filename)
    try:
        with open(output_path, "w") as f:
            f.write(transcript)
        worker_logger.info(f"Job {job_id} completed. Transcript saved at {output_path}")
        redis_sync.publish("job_updates", f"Job {job_id} completed. Transcript saved at {output_path}")
    except Exception as e:
        worker_logger.error(f"Error saving transcript for job {job_id}: {e}")
        redis_sync.publish("job_updates", f"Job {job_id} failed: {str(e)}")
        raise
    return transcript

# API endpoint for file uploads and job creation
@app.post("/upload")
async def upload_file(audioFile: UploadFile = File(...)):
    file_id = str(uuid.uuid4())
    worker_logger = logging.getLogger("upload")
    worker_logger.info(f"Received file: {audioFile.filename} with assigned ID: {file_id}")
    try:
        file_location = os.path.join(UPLOAD_DIR, file_id + "_" + audioFile.filename)
        with open(file_location, "wb") as buffer:
            shutil.copyfileobj(audioFile.file, buffer)
        worker_logger.info(f"File saved at {file_location}")
    except Exception as e:
        worker_logger.error(f"Error saving file {audioFile.filename}: {e}")
        raise HTTPException(status_code=500, detail="Error saving file") from e

    job = job_queue.enqueue(process_file, file_location, file_id)
    worker_logger.info(f"Enqueued job with ID: {job.get_id()}")
    return {"jobId": job.get_id(), "message": "File uploaded and job enqueued"}

# New endpoint to list all available transcription files
@app.get("/transcriptions")
async def list_transcriptions():
    transcripts = []
    for filename in os.listdir(OUTPUT_DIR):
        if filename.endswith(".txt"):
            # Assuming the filename format is: <job_id>_<original_filename>.txt
            parts = filename.split("_", 1)
            if len(parts) == 2:
                job_id = parts[0]
                original_filename = parts[1][:-4]  # Remove .txt extension
            else:
                job_id = "unknown"
                original_filename = filename
            transcripts.append({
                "job_id": job_id,
                "original_filename": original_filename,
                "download_url": f"http://localhost:8000/download/{job_id}"
            })
    return transcripts

# Existing download endpoint to serve a transcript file based on job_id
@app.get("/download/{job_id}")
async def download_transcript(job_id: str):
    for filename in os.listdir(OUTPUT_DIR):
        if filename.startswith(job_id + "_") and filename.endswith(".txt"):
            file_path = os.path.join(OUTPUT_DIR, filename)
            logger.info(f"Found transcript for job {job_id}: {file_path}")
            return FileResponse(file_path, media_type="text/plain", filename=filename)
    logger.error(f"Transcript for job {job_id} not found")
    raise HTTPException(status_code=404, detail="Transcript not found")

@app.on_event("startup")
async def startup_event():
    logger.info("API server starting up")

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("API server shutting down")

if __name__ == "__main__":
    import uvicorn
    logger.info("Starting FastAPI application")
    uvicorn.run(app, host="127.0.0.1", port=8000, reload=True)
