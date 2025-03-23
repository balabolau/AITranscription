# dashboard.py
from flask import Flask
import rq_dashboard
import os
import logging

# Set up logging.
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config.from_object(rq_dashboard.default_settings)
# Read the Redis URL from the environment variable; default to using the service name 'redis'.
app.config['RQ_DASHBOARD_REDIS_URL'] = os.environ.get("RQ_DASHBOARD_REDIS_URL", "redis://redis:6379")
logger.info(f"RQ_DASHBOARD_REDIS_URL set to: {app.config['RQ_DASHBOARD_REDIS_URL']}")

app.register_blueprint(rq_dashboard.blueprint, url_prefix='/rq')

if __name__ == '__main__':
    logger.info("Starting rq-dashboard on port 9181...")
    app.run(host='0.0.0.0', port=9181, debug=True)
