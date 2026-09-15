"""Project-only timestamped console and rotating local file logs."""
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import re
from src.config import LOG_DIRECTORY, PathLike


class SafeFormatter(logging.Formatter):
    def format(self, record):
        text = super().format(record)
        secret = os.getenv('OPENALEX_API_KEY', '')
        if secret:
            text = text.replace(secret, '[REDACTED]')
        return re.sub(r'(?i)((?:api_key|access_token|password)=)[^\s&]+', r'\1[REDACTED]', text)


def configure_logging(log_file: PathLike = LOG_DIRECTORY / 'pipeline.log') -> logging.Logger:
    logger = logging.getLogger('research_pipeline')
    logger.disabled = False
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
    extraction = logging.getLogger('src.extract.openalex_client')
    extraction.disabled = False
    # Share the configured handlers directly; retain the established logger name.
    extraction.handlers = logger.handlers[:]
    extraction.setLevel(logging.DEBUG)
    extraction.propagate = False
    return logger
