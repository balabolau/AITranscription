"""
logging_config.py - Centralized logging configuration for the audio transcription app.
This module loads settings from config.yaml and sets up JSON logging using dictConfig.
It also reconfigures external loggers (e.g., 'rq.worker' and 'whisper_process') to use JSON formatting.
"""

import os
import yaml
import logging
import logging.config
from pythonjsonlogger import jsonlogger

# Load centralized configuration from config.yaml
with open("config.yaml", "r") as f:
    config = yaml.safe_load(f)

BASE_DIR = os.path.expanduser(config.get("directories", {}).get("base", ""))
LOGS_DIR = os.path.join(BASE_DIR, config.get("directories", {}).get("logs", "logs"))
log_config = config.get("logging", {})
log_file = os.path.join(LOGS_DIR, log_config.get("file", "api.log"))
log_level = log_config.get("level", "INFO").upper()

# Define a logging configuration dictionary using dictConfig
LOGGING_CONFIG = {
    'version': 1,
    'disable_existing_loggers': False,  # Allow existing loggers to be updated
    'formatters': {
        'json': {
            '()': 'pythonjsonlogger.jsonlogger.JsonFormatter',
            'fmt': '%(asctime)s %(name)s %(levelname)s %(message)s',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'json',
        },
        'file': {
            'class': 'logging.FileHandler',
            'filename': log_file,
            'formatter': 'json',
        },
    },
    'root': {
        'handlers': ['console', 'file'],
        'level': log_level,
    },
}

# Apply the logging configuration globally
logging.config.dictConfig(LOGGING_CONFIG)

# Reconfigure external loggers to force JSON formatting and disable propagation
external_loggers = ['rq.worker', 'whisper_process']
for logger_name in external_loggers:
    ext_logger = logging.getLogger(logger_name)
    # Clear any existing handlers that might have been set before our configuration
    ext_logger.handlers = []
    # Create new console and file handlers with our JSON formatter
    console_handler = logging.StreamHandler()
    file_handler = logging.FileHandler(log_file)
    formatter = jsonlogger.JsonFormatter('%(asctime)s %(name)s %(levelname)s %(message)s')
    console_handler.setFormatter(formatter)
    file_handler.setFormatter(formatter)
    ext_logger.addHandler(console_handler)
    ext_logger.addHandler(file_handler)
    ext_logger.setLevel(log_level)
    # Disable propagation so messages don't get handled twice
    ext_logger.propagate = False