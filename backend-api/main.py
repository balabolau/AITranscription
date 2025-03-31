# main.py
from fastapi import FastAPI, File, UploadFile, WebSocket, WebSocketDisconnect, HTTPException, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from starlette.websockets import WebSocket as StarletteWebSocket
import shutil
import uuid
import os
import time
import asyncio
import logging
import json
import yaml
from datetime import datetime
from redis import Redis
from jobs import enqueue_transcription
from contextlib import asynccontextmanager

# Load centralized configuration
with open("config.yaml", "r") as f:
    config = yaml.safe_load(f)

BASE_DIR = os.path.expanduser(config.get("directories", {}).get("base", ""))
UPLOAD_DIR = os.path.join(BASE_DIR, config.get("directories", {}).get("uploads", "uploads"))
OUTPUT_DIR = os.path.join(BASE_DIR, config.get("directories", {}).get("outputs", "outputs"))
LOGS_DIR = os.path.join(BASE_DIR, config.get("directories", {}).get("logs", "logs"))

# Configure logging using centralized settings
log_config = config.get("logging", {})
logging.basicConfig(
    level=getattr(logging, log_config.get("level", "INFO").upper()),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(LOGS_DIR, log_config.get("file", "api.log"))),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("API server starting up")
    
    async def start_pubsub_listener():
        logger.info("Starting Redis Pub/Sub listener for job updates")
        try:
            import redis.asyncio as redis_async
            redis_sub = redis_async.Redis(
                host=redis_config.get("host", "localhost"),
                port=redis_config.get("port", 6379),
                db=redis_config.get("db", 0)
            )
            pubsub = redis_sub.pubsub()
            await pubsub.subscribe("job_updates")
            logger.info("Subscribed to 'job_updates'")
            
            async def pubsub_listener():
                logger.info("Pub/Sub listener running")
                while True:
                    try:
                        message = await pubsub.get_message(ignore_subscribe_messages=True)
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
            # Schedule the pubsub listener as a background task
            asyncio.create_task(pubsub_listener())
        except Exception as e:
            logger.error(f"Failed to start pubsub listener: {e}")

    # Call the pubsub listener function so it actually starts
    await start_pubsub_listener()
    
    yield
    logger.info("API server shutting down")

app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Redis configuration from centralized config
redis_config = config.get("redis", {})
redis_conn = Redis(
    host=redis_config.get("host", "localhost"),
    port=redis_config.get("port", 6379),
    db=redis_config.get("db", 0)
)

REDIS_MESSAGES_KEY = "transcription_messages"
MAX_MESSAGES = 100
connected_clients = set()

def store_message(message: str):
    try:
        timestamp = datetime.now().isoformat()
        message_data = json.dumps({"timestamp": timestamp, "message": message})
        redis_conn.lpush(REDIS_MESSAGES_KEY, message_data)
        redis_conn.ltrim(REDIS_MESSAGES_KEY, 0, MAX_MESSAGES - 1)
    except Exception as e:
        logger.error(f"Error storing message in Redis: {e}")

def get_recent_messages(count: int = 2):
    try:
        messages = redis_conn.lrange(REDIS_MESSAGES_KEY, 0, count - 1)
        return [json.loads(msg) for msg in messages]
    except Exception as e:
        logger.error(f"Error getting messages from Redis: {e}")
        return []

class MyWebSocket(StarletteWebSocket):
    # Override the origin check to always allow
    def _origin_allowed(self) -> bool:
        return True

@app.websocket("/ws")
async def websocket_endpoint(websocket: MyWebSocket):
    client_id = str(id(websocket))[-6:]
    try:
        logger.info(f"[WS {client_id}] Attempting to accept WebSocket connection")
        await websocket.accept()
        logger.info(f"[WS {client_id}] WebSocket connection accepted")
        connected_clients.add(websocket)
        logger.info(f"[WS {client_id}] Added to connected clients (Total: {len(connected_clients)})")

        # try:
        #     recent_messages = get_recent_messages()
        #     if recent_messages:
        #         payload = json.dumps({
        #             "type": "history",
        #             "messages": recent_messages
        #         })
        #         await websocket.send_text(payload)
        #         logger.info(f"[WS {client_id}] Sent history: {payload}")
        # except Exception as e:
        #     logger.exception(f"[WS {client_id}] Error sending history: {e}")

        while True:
            try:
                message = await websocket.receive_text()
                logger.info(f"[WS {client_id}] Received message: {message}")
                # Optionally, process the message.
            except Exception as e:
                logger.exception(f"[WS {client_id}] Exception in receive loop: {e}")
                break
    except WebSocketDisconnect:
        logger.info(f"[WS {client_id}] WebSocket client disconnected")
    except Exception as e:
        logger.exception(f"[WS {client_id}] Unexpected error in websocket_endpoint: {e}")
    finally:
        if websocket in connected_clients:
            connected_clients.remove(websocket)
            logger.info(f"[WS {client_id}] Removed from connected clients (Total: {len(connected_clients)})")

async def broadcast_message(message: str):
    logger.info(f"[Broadcast] Preparing to broadcast message: {message}")
    store_message(message)
    payload = json.dumps({
        "type": "update",
        "timestamp": datetime.now().isoformat(),
        "message": message
    })
    disconnected_clients = set()
    for client in connected_clients:
        try:
            await client.send_text(payload)
            logger.info(f"[Broadcast] Sent update to client {str(id(client))[-6:]}: {payload}")
        except Exception as e:
            logger.exception(f"[Broadcast] Error sending update to client {str(id(client))[-6:]}: {e}")
            disconnected_clients.add(client)
    for client in disconnected_clients:
        if client in connected_clients:
            connected_clients.remove(client)
            logger.info(f"[Broadcast] Removed disconnected client {str(id(client))[-6:]}")

@app.post("/upload")
async def upload_file(
    audioFile: UploadFile = File(...),
    language: str = Form("auto"),
    prompt: str = Form("")
):
    file_id = str(uuid.uuid4())
    try:
        logger.info(f"Received file: {audioFile.filename} with assigned ID: {file_id}")
        file_location = os.path.join(UPLOAD_DIR, file_id + "_" + audioFile.filename)
        with open(file_location, "wb") as buffer:
            shutil.copyfileobj(audioFile.file, buffer)
        logger.info(f"File saved at {file_location}")
    except Exception as e:
        logger.error(f"Error saving file {audioFile.filename}: {e}")
        raise HTTPException(status_code=500, detail="Error saving file") from e

    try:
        job_id = enqueue_transcription(file_location, OUTPUT_DIR, prompt_override=prompt, language_override=language)
        logger.info(f"Enqueued transcription job with ID: {job_id}")
    except Exception as e:
        logger.error(f"Error enqueuing transcription job: {e}")
        raise HTTPException(status_code=500, detail="Error enqueuing transcription job") from e
    return {"jobId": job_id, "message": "File uploaded and transcription job enqueued"}

@app.get("/transcriptions")
async def list_transcriptions():
    transcripts = []
    try:
        for filename in os.listdir(OUTPUT_DIR):
            if filename.endswith(".txt"):
                parts = filename.split("_", 1)
                if len(parts) == 2:
                    job_id = parts[0]
                    original_filename = parts[1][:-4]
                else:
                    job_id = "unknown"
                    original_filename = filename
                
                file_path = os.path.join(OUTPUT_DIR, filename)
                # Use file's modification time as the "transcribed on" time
                mtime = os.path.getmtime(file_path)  # returns a float (epoch time)

                transcripts.append({
                    "job_id": job_id,
                    "original_filename": original_filename,
                    "download_url": f"http://localhost:8000/download/{job_id}",
                    "transcribed_on": mtime
                })

        # Sort transcripts in descending order (newest first)
        transcripts.sort(key=lambda x: x["transcribed_on"], reverse=True)

    except Exception as e:
        logger.error(f"Error listing transcriptions: {e}")

    return transcripts

@app.get("/download/{job_id}")
async def download_transcript(job_id: str):
    try:
        for filename in os.listdir(OUTPUT_DIR):
            if filename.startswith(job_id + "_") and filename.endswith(".txt"):
                file_path = os.path.join(OUTPUT_DIR, filename)
                logger.info(f"Found transcript for job {job_id}: {file_path}")
                # Strip the job ID and underscore from the filename:
                original_filename = filename.split("_", 1)[1] if "_" in filename else filename
                return FileResponse(file_path, media_type="text/plain", filename=original_filename)

        logger.error(f"Transcript for job {job_id} not found")
        raise HTTPException(status_code=404, detail="Transcript not found")
    except Exception as e:
        logger.error(f"Error in download_transcript: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error") from e
