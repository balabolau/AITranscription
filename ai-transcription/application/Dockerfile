# Use a CUDA 12.4.0 base image with Ubuntu 22.04
# FROM nvidia/cuda:12.4.0-base-ubuntu22.04
# python3.9 python3-pip \

# Use a lightweight Python 3.9 image
FROM python:3.9-slim

# Prevent Python from writing .pyc files and enable unbuffered output.
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install system dependencies.
RUN apt-get update && apt-get install -y \
    ffmpeg \
    git \
    gcc \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Set the working directory.
WORKDIR /app

# Copy the requirements file and install Python dependencies.
COPY requirements.txt .
RUN pip install --no-cache-dir -U pip setuptools wheel && \
    # Install torch separately as it's the largest package
    pip install --no-cache-dir torch==2.0.0 && \
    # Install whisper separately
    pip install --no-cache-dir openai-whisper==20240930 && \
    # Install the rest of the requirements
    pip install --no-cache-dir -r requirements.txt

# Copy the entire application into the container.
COPY . /app

# Expose the port for the dashboard (if needed).
EXPOSE 9181

# Set the default command to run your Telegram bot using python3.
CMD ["python3", "bot_v7.py"]

