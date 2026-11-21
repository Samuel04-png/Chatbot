"""Production entry point: `gunicorn -c deploy/gunicorn.conf.py wsgi:app`. Configuration comes only from
the process environment (the hosting platform's secret settings); no .env file is read in production."""
import logging
import sys

from app import create_app

logging.basicConfig(stream=sys.stdout, level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
app = create_app()
