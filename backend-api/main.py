from fastapi import FastAPI, File, UploadFile, WebSocket, WebSocketDisconnect, HTTPException
import shutil
import uuid
import os
import asyncio
from redis import Redis
from rq import Queue

app = FastAPI()

# Set up a synchronous Redis connection for the job queue
redis_conn = Redis(host="localhost", port=6379, db=0)
job_queue = Queue("transcriptions", connection=redis_conn)

# Directory to store uploaded files
UPLOAD_DIR = "./uploads"
if not os.path.exists(UPLOAD_DIR):
    os.makedirs(UPLOAD_DIR)

# Global set to store connected WebSocket clients
connected_clients = set()

# WebSocket endpoint for real-time updates
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    connected_clients.add(websocket)
    try:
        while True:
            # Optionally, receive messages from the client if needed
            await websocket.receive_text()
    except WebSocketDisconnect:
        connected_clients.remove(websocket)

# Helper function to broadcast messages to all connected WebSocket clients
async def broadcast_message(message: str):
    for client in connected_clients:
        try:
            await client.send_text(message)
        except Exception as e:
            print(f"Error sending message: {e}")

# Startup event: subscribe to Redis Pub/Sub channel "job_updates" using the async interface.
@app.on_event("startup")
async def start_pubsub_listener():
    # Use the async Redis client from redis.asyncio
    import redis.asyncio as redis_async
    redis_sub = redis_async.Redis(host="localhost", port=6379, db=0)
    pubsub = redis_sub.pubsub()
    await pubsub.subscribe("job_updates")
    
    async def pubsub_listener():
        while True:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if message:
                data = message["data"]
                if isinstance(data, bytes):
                    data = data.decode("utf-8")
                await broadcast_message(data)
            await asyncio.sleep(0.1)
    
    asyncio.create_task(pubsub_listener())

# Dummy processing function that simulates transcription and publishes updates via Redis Pub/Sub.
def process_file(file_path, job_id):
    import time
    # Create a synchronous Redis connection for publishing messages
    redis_sync = Redis(host="localhost", port=6379, db=0)
    redis_sync.publish("job_updates", f"Job {job_id} started processing...")
    for i in range(1, 6):
        time.sleep(1)
        redis_sync.publish("job_updates", f"Job {job_id} progress: {i*20}% complete")
    transcript = f"Transcribed text for file {os.path.basename(file_path)}"
    output_path = file_path + ".txt"
    with open(output_path, "w") as f:
        f.write(transcript)
    redis_sync.publish("job_updates", f"Job {job_id} completed. Transcript saved at {output_path}")
    return transcript

# API endpoint to handle file uploads and job creation
@app.post("/upload")
async def upload_file(audioFile: UploadFile = File(...)):
    try:
        file_id = str(uuid.uuid4())
        file_location = os.path.join(UPLOAD_DIR, file_id + "_" + audioFile.filename)
        with open(file_location, "wb") as buffer:
            shutil.copyfileobj(audioFile.file, buffer)
    except Exception as e:
        raise HTTPException(status_code=500, detail="Error saving file") from e

    # Enqueue the transcription job
    job = job_queue.enqueue(process_file, file_location, file_id)
    return {"jobId": job.get_id(), "message": "File uploaded and job enqueued"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000, reload=True)
