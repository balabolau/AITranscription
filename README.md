# AI Audio Transcriber Application

This application is a configurable, web-based speech-to-text transcription system built around OpenAI's Whisper model. It accepts audio file uploads via a simple web interface, allowing users to optionally specify a transcription language and a custom prompt. The backend API enqueues transcription jobs using Redis and processes them sequentially through an RQ worker, while real-time progress updates are broadcast to the frontend via WebSocket.

## System Overview

The application consists of several components working together:

- **Web Frontend (Streamlit UI):**  
  A Streamlit interface for uploading audio files. In addition to selecting an audio file, users can specify a transcription language (defaulting to auto-detect) and an optional prompt. The UI displays live progress updates and lists completed transcriptions available for download.

- **Backend API (main.py):**  
  Built with FastAPI, it handles file uploads, manages WebSocket connections for real-time progress updates, and provides endpoints to list and download transcriptions. Uploaded files are saved locally and passed as jobs to the transcription queue.

- **Job Queue (Redis & RQ):**  
  The application uses Redis to store progress messages and manage a job queue. Each transcription request is enqueued and processed asynchronously by a dedicated worker.

- **Transcription Processing (whisper_process.py):**  
  The core transcription logic pre-processes audio files using `ffmpeg` (for normalization, resampling, and loudness adjustment), splits audio into overlapping chunks, and transcribes each chunk using the Whisper model. Progress updates are published at key stages (transcription start, per-chunk progress, and completion).

- **Worker Process (worker.py):**  
  An RQ worker listens on the transcription queue and processes jobs sequentially. This ensures that multiple file uploads are handled one after another.

- **Centralized Logging:**  
  A centralized logging configuration outputs logs in JSON format, making them easier to integrate with monitoring tools and simplifying debugging.

## Features

- **Web-Based File Upload and Real-Time Updates:**  
  Users can upload audio files, optionally specify a language and prompt, and receive live progress updates via WebSocket.

- **Configurable Transcription Parameters:**  
  The application is highly configurable via a YAML configuration file (`config.yaml`). This file includes settings for the transcription model, chunking parameters, resource thresholds, and more.

- **Asynchronous, Sequential Processing:**  
  Transcription jobs are enqueued in Redis and processed sequentially by a single RQ worker, ensuring orderly job execution.

- **Robust Audio Preprocessing:**  
  Audio files are converted to a consistent format (mono, 16 kHz) with loudness normalization using `ffmpeg`, and are split into overlapping chunks to enhance transcription accuracy.

- **Detailed Logging and Error Reporting:**  
  Structured JSON logging is implemented throughout the application for improved monitoring and troubleshooting. All error conditions are logged, making it easier to identify and resolve issues.

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
    ├── logging_config.py          # Centralized logging configuration (JSON format)
    ├── logs/                      # Directory for log files (e.g., api.log)
    ├── uploads/                   # Directory for incoming audio files
    ├── processing/                # Temporary storage for files being processed
    └── outputs/                   # Output directory for generated transcript files
    
└── web-app/
    └── Homepage.py                # Streamlit UI for file upload and monitoring
```

## Getting Started

### Prerequisites

- **Python 3.10+**
- **Redis:** Ensure Redis is installed and running (for local development, you can run it as a daemon).
- **FFmpeg:** Installed and accessible from your system path.
- **Dependencies:** Install Python dependencies via pip. A `requirements.txt` file should list all required packages.

### Local Development

1. **Configure the Application:**  
   Edit `config.yaml` to adjust transcription parameters, directory paths, and resource thresholds as needed.

2. **Choose a Run Mode:**  
   You can run everything via the helper scripts (tmux-based) or start each process manually.

   **Option A: Use `run.sh` (recommended for local dev)**  
   This starts the backend, worker, and frontend in a tmux session named `aitranscribe`. It also starts Redis if it is not already running.
   ```bash
   ./run.sh
   ```
   To stop everything that `run.sh` started (including the tmux session and the Redis instance it spawned), run:
   ```bash
   ./kill.sh
   ```

   **Option B: Run each process manually**  
   Start Redis in daemon mode:
   ```bash
   cd backend && redis-server --daemonize yes
   ```
   From the project root, start the FastAPI server:
   ```bash
   cd backend && uvicorn main:app --reload
   ```
   In a separate terminal, run the worker:
   ```bash
   cd backend && python worker.py
   ```
   Start the Streamlit UI:
   ```bash
   cd web-app && streamlit run Homepage.py
   ```

3. **Upload and Monitor:**  
   Use the web interface to upload audio files, specifying language and prompt if desired. Monitor real-time progress and download completed transcriptions.

## Considerations for Production

- **Containerization:**  
  For production, consider containerizing the application using Docker and orchestrating services with Docker Compose.

- **Scaling:**  
  In production, you may choose to run multiple worker processes or split services (API, worker, static file server) into separate containers.

- **Security:**  
  Although the current MVP is designed for single-user access, implement proper access control (e.g., basic authentication or IP whitelisting) and secure communication (HTTPS) before wider deployment.

- **Centralized Logging and Monitoring:**  
  The application’s JSON-formatted logs are designed for integration with modern monitoring and alerting systems, providing clear visibility into operations and errors.

- **Error Handling:**  
  Comprehensive error logging is in place. For production, consider adding more robust input validations and user-friendly error responses.

## Known Limitations and Future Enhancements

- **Input Validation:**  
  More robust validation of file types and sizes is recommended before deploying to a public environment.
  
- **Automated Testing:**  
  While the current implementation serves as an MVP, adding unit and integration tests will be essential for ensuring long-term stability.
  
- **Caching and Performance Optimization:**  
  Future versions may incorporate caching mechanisms and further optimizations to reduce processing overhead and improve performance.
  
- **Enhanced Security:**  
  As the application scales, consider integrating more advanced authentication, authorization, and secrets management solutions.

## Troubleshooting

- **WebSocket and Pub/Sub Issues:**  
  Check logs in `logs/api.log` for any errors related to Redis Pub/Sub or WebSocket connections.

- **Audio Processing Errors:**  
  Review log messages for details on any `ffmpeg` or transcription errors.

- **Redis Connection Issues:**  
  Ensure Redis is running and accessible based on the settings in `config.yaml`.

## License

This project is proprietary software. All rights reserved.

No permission is granted to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the software without explicit written permission from the copyright holder.

See the LICENSE file for more details.
