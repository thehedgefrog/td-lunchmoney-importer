"""
Utility functions for TD Lunch Money Importer
"""
import sys
import logging
import logging.handlers
from datetime import datetime
from pathlib import Path
from colorama import Fore, Style

# Configure logger
logger = logging.getLogger(__name__)

def graceful_exit(code: int = 0) -> None:
    """Handle clean program exit"""
    cleanup()
    logger.info(f"Exiting program with code {code}")
    sys.exit(code)  # This ensures the program actually exits

def cleanup() -> None:
    """Cleanup resources"""
    # Flush any open file handles and logging buffers
    try:
        # Shutdown logging
        logging.shutdown()
    except Exception:
        # Don't raise errors during cleanup
        pass

def print_error(text):
    """Print error message with red color"""
    print(f"{Fore.RED}✗ {text}{Style.RESET_ALL}")

def print_success(text):
    """Print success message with green color"""
    print(f"{Fore.GREEN}✓ {text}{Style.RESET_ALL}")

def setup_logging():
    """Set up logging with rotation"""
    import logging.handlers

    # Constants
    LOG_DIR = Path.home() / ".lunchmoney" / "logs"
    LOG_FILE = LOG_DIR / "importer.log"

    # Create log directory if it doesn't exist
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    # Configure rotating file handler (5 files, 1MB each)
    handler = logging.handlers.RotatingFileHandler(
        LOG_FILE, maxBytes=1_000_000, backupCount=5
    )

    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)

    # Get root logger and configure
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # Remove any existing handlers to prevent duplicates
    for hdlr in root_logger.handlers[:]:
        root_logger.removeHandler(hdlr)

    root_logger.addHandler(handler)

    logger.info("Starting importer")
    logger.info(f"Log files will rotate at 1MB, keeping 5 backups at {LOG_FILE}")

    return LOG_FILE
