"""Project-only timestamped console and rotating local file logs."""
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import re


class SafeFormatter(logging.Formatter):
    def format(self, record):
        text = super().format(record)
        secret = os.getenv('OPENALEX_API_KEY', '')
        if secret:
            text = text.replace(secret, '[REDACTED]')
        return re.sub(r'(?i)((?:api_key|access_token|password)=)[^\s&]+', r'\1[REDACTED]', text)


def configure_logging(log_file=Path('logs/pipeline.log')):
    logger = logging.getLogger('research_pipeline')
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
        handler.close()
    formatter = SafeFormatter('%(asctime)s %(levelname)s %(message)s')
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(formatter)
    logger.addHandler(console)
    Path(log_file).parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(log_file, maxBytes=2_000_000, backupCount=3, encoding='utf-8')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    return logger
