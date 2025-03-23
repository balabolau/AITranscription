# AI Audio Transcriber Application

This application is a robust, configurable speech-to-text transcription system built around OpenAI's Whisper model. It automates the transcription of audio files, preprocessing audio (normalization, resampling via `ffmpeg`), splitting audio into overlapping chunks, and transcribing each chunk using Whisper. The system includes detailed error handling, performance monitoring, and dynamic resource management.

## System Overview

The application consists of several components working together:

- **Telegram Bot (bot_v7.py):**  
  An asynchronous Telegram bot built with the python-telegram-bot library. Users can submit audio files via chat, select a transcription language using inline keyboards, and receive the transcript as a text file. Access is controlled through allowed chat IDs specified in a YAML configuration file.

- **Redis Queue System:**  
  The application uses Redis and RQ (Redis Queue) to manage transcription jobs, allowing for distributed processing and better resource management.

- **Worker Process:**  
  Processes transcription jobs from the Redis queue. Multiple workers can be deployed to handle jobs in parallel.

- **RQ Dashboard (dashboard.py):**  
  A web interface for monitoring the queue and job status, accessible on port 9181.

The core transcription logic is implemented in **whisper_process_v6.py**, which:
- Preprocesses audio using `ffmpeg` (mono conversion, resampling to 16 kHz, and loudness normalization)
- Splits audio into overlapping chunks to improve transcription quality
- Processes chunks sequentially or in parallel (configurable via a YAML file) while managing system memory and performing periodic cleanup
- Logs processing progress and errors to a dedicated log file

## Features

- **Asynchronous Job Processing:**  
  Uses Redis Queue to handle transcription requests asynchronously, improving system scalability and reliability.
  
- **Docker Containerization:**  
  The entire application is containerized using Docker and orchestrated with Docker Compose, making deployment and scaling straightforward.

- **Audio Preprocessing:**  
  Converts audio files to a consistent format (mono, 16 kHz) and applies volume normalization using `ffmpeg`.

- **Chunked Transcription:**  
  Splits audio into overlapping chunks to handle long files efficiently and improve transcription accuracy.

- **Configurable Processing Parameters:**  
  Uses a YAML configuration file (`config.yaml`) to set parameters such as model size, device, transcription temperature, beam size, chunk duration, overlap, and resource thresholds.

- **Telegram Bot Integration:**  
  Provides an asynchronous Telegram bot interface for on-demand transcription. Users interact with inline keyboards to select transcription language and submit prompts.

- **Web-based Monitoring Dashboard:**  
  Provides real-time visibility into the job queue, worker status, and job completion statistics.

- **Dynamic Resource Management:**  
  Monitors system memory and performs cleanups automatically during transcription to maintain performance.

- **Robust Error Handling & Logging:**  
  Logs detailed progress and error messages to help diagnose issues. Unsupported or failed files are automatically moved to a designated error directory.

## Directory Structure

The project has the following directory structure:

```
ai-transcriber-app/
├── application/                # Application code
│   ├── bot_v7.py              # Telegram bot for on-demand transcription
│   ├── whisper_process_v6.py  # Core transcription and audio processing module
│   ├── jobs.py                # Job queue management code
│   ├── dashboard.py           # RQ Dashboard for monitoring jobs
│   ├── requirements.txt       # Python dependencies
│   ├── Dockerfile             # For building the application container
│   └── docker-compose.yml     # Container orchestration
├── config.yaml                # Configuration file (YAML format)
├── audio_input/               # Directory for input audio files
├── processing/                # Temporary storage for files being processed
├── transcripts/               # Output directory for generated transcript files
├── logs/                      # Log files directory
├── downloads/                 # Temporary storage for downloaded audio files
├── error/                     # Directory for unsupported or failed files
└── archive/                   # Archive of processed files
```

## Getting Started

### Prerequisites

- **Docker and Docker Compose:** For containerized deployment.
- **GPU (Optional):** The application can run on CPU, but a GPU will significantly improve transcription speed.

### Configuration

1. **config.yaml:**  
   Adjust `config.yaml` to set your desired transcription parameters, directories, Telegram bot token, allowed chat IDs, and model settings.

2. **Directory Permissions:**  
   Ensure that the directories defined in `config.yaml` exist and are writable by the Docker containers.

### Deployment with Docker Compose

The application is designed to be deployed using Docker Compose:

1. **Build the Docker Image:**
   ```bash
   cd application
   docker build -t whisper-transcriber-app:v7 .
   ```

2. **Start the Services:**
   ```bash
   docker-compose up -d
   ```

   This starts the following services:
   - Redis server for job queuing
   - Main application with the Telegram bot
   - RQ Dashboard for monitoring jobs
   - Worker processes to handle transcription jobs

3. **Monitoring:**  
   Access the RQ Dashboard at `http://your-server-ip:9181/rq` to monitor job status.

## Docker Compose Services

The application uses Docker Compose to orchestrate multiple containers:

- **Redis:** Message broker and job queue database
- **App:** Runs the Telegram bot and handles user interactions
- **Dashboard:** Provides the RQ web interface for monitoring jobs
- **Worker:** Processes transcription jobs from the queue

Each service is configured with appropriate resource limits and restart policies for production use.

## Troubleshooting

- **Audio Preprocessing Errors:**  
  Check the logs for detailed error messages related to `ffmpeg` commands.

- **Memory Issues:**  
  Check the Docker log files and consider adjusting memory limits in the docker-compose.yml file.

- **Redis Connection Issues:**  
  Verify that the Redis service is running and that your environment variables are correctly set.

- **Telegram Bot Not Responding:**  
  Verify that the bot token is correct and that your allowed chat IDs are configured properly in `config.yaml`.

- **Worker Not Processing Jobs:**  
  Check worker logs and verify that it's connected to Redis correctly. Adjust JOB_TIMEOUT in docker-compose.yml if jobs are timing out.

## License

This project is proprietary software. All rights reserved.

No permission is granted to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the software without explicit written permission from the copyright holder.

See the LICENSE file for more details.