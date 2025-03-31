# AI Audio Transcriber Application

This application is a configurable, web-based speech-to-text transcription system built around OpenAI's Whisper model. It accepts audio file uploads via a simple web interface, allowing users to optionally specify a transcription language and a custom prompt. The backend API enqueues transcription jobs using Redis and processes them sequentially through an RQ worker, while real-time progress updates are broadcast to the frontend via WebSocket.

## System Overview

The application consists of several components working together:

- **Web Frontend (index.html):**  
  A minimal interface for uploading audio files. In addition to selecting an audio file, users can specify a transcription language (defaulting to auto-detect) and an optional prompt. The frontend displays live progress updates and lists completed transcriptions available for download.

- **Backend API (main.py):**  
  Built with FastAPI, it handles file uploads, starts a WebSocket for real-time updates, and serves endpoints to list and download transcriptions. Uploaded files are saved locally and passed as jobs to the transcription queue.

- **Job Queue (Redis & RQ):**  
  The application uses Redis to store progress messages and to manage a job queue. Each transcription request is enqueued and processed asynchronously by a worker.

- **Transcription Processing (whisper_process.py):**  
  The core transcription logic pre-processes audio files using `ffmpeg` (normalization, resampling, and loudness adjustment), splits audio into overlapping chunks, and transcribes each chunk using the Whisper model. Progress updates are published at key stages (e.g., transcription start, per-chunk progress, transcription completion).

- **Worker Process (worker.py):**  
  An RQ worker listens on the transcription queue and processes jobs one at a time, ensuring that multiple file uploads are handled sequentially rather than in parallel.

## Features

- **Web-Based File Upload and Real-Time Updates:**  
  Users can upload audio files, optionally specify a language and prompt, and receive live progress updates via WebSocket.

- **Configurable Transcription Parameters:**  
  The application uses a YAML configuration file (`config.yaml`) to set parameters such as model size, device, chunk duration, overlap, and resource thresholds. Users can override language and prompt on the fly.

- **Asynchronous, Sequential Processing:**  
  Transcription jobs are enqueued in Redis and processed sequentially by a single RQ worker, ensuring that jobs are handled one after the other.

- **Robust Audio Preprocessing:**  
  Uses `ffmpeg` to convert audio to a consistent format (mono, 16 kHz) with loudness normalization and splits audio into overlapping chunks for improved transcription accuracy.

- **Detailed Logging and Progress Reporting:**  
  Logs are written to file and streamed to the frontend via WebSocket, providing a clear view of the processing stages and performance metrics.

## Directory Structure

The project is organized as follows:

```
AITranscription/
└── backend-api/
    ├── config.yaml                # Configuration file (YAML format)
    ├── jobs.py                    # Job queue management code
    ├── main.py                    # FastAPI backend (file upload, WebSocket, endpoints)
    ├── whisper_process.py         # Core transcription and audio processing module
    ├── worker.py                  # RQ worker for processing transcription jobs
    ├── logs/                      # Directory for log files (e.g., api.log)
    ├── uploads/                   # Directory for incoming audio files
    ├── processing/                # Temporary storage for files being processed
    └── outputs/                   # Output directory for generated transcript files
    
└── web-app/
    └── index.html                 # Web frontend for file upload and monitoring
```

## Getting Started

### Prerequisites

- **Python 3.10+**
- **Redis:** Ensure Redis is installed and running (for local development you can run it as a daemon).
- **FFmpeg:** Installed and accessible from your system path.
- **Dependencies:** Install Python dependencies via pip (see `requirements.txt` if provided).

### Local Development

1. **Configure the Application:**  
   Edit `config.yaml` to adjust transcription parameters, directory paths, and resource thresholds as needed.

2. **Start Redis:**  
   Run Redis in daemon mode:
   ```bash
   redis-server --daemonize yes
   ```

3. **Launch the Backend API:**  
   From the project root, start the FastAPI server (for example, with uvicorn):
   ```bash
   uvicorn main:app
   ```

4. **Start the Worker:**  
   In a separate terminal, run:
   ```bash
   python worker.py
   ```

5. **Access the Web Interface:**  
   Open your browser and navigate to the location where you serve `index.html` (for local testing, you might use a simple HTTP server, e.g., `python -m http.server 8080`).

6. **Upload and Monitor:**  
   Use the web interface to upload audio files, specifying language and prompt if desired. Monitor real-time progress and download completed transcriptions.

## Considerations for Production

- **Containerization:**  
  For production, consider containerizing the application using Docker and orchestrating services with Docker Compose.

- **Scaling:**  
  In production, you may choose to run multiple worker processes or even split services (API, worker, static file server) into separate containers.

- **Security:**  
  Implement proper access control (e.g., authentication, HTTPS) for both the API and the web interface.

- **File Naming:**  
  Transcripts are stored with a unique name that includes the job ID. You can customize the download endpoint to present a clean file name to the user if desired.

## Troubleshooting

- **WebSocket and Pub/Sub Issues:**  
  Check logs in `logs/api.log` for any errors related to Redis Pub/Sub or WebSocket connections.

- **Audio Processing Errors:**  
  Inspect log messages for details on any `ffmpeg` or transcription errors.

- **Redis Connection Issues:**  
  Verify that Redis is running and accessible based on the settings in `config.yaml`.

## License

This project is proprietary software. All rights reserved.

No permission is granted to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the software without explicit written permission from the copyright holder.

See the LICENSE file for more details.