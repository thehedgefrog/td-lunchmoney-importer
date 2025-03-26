"""
Utility functions for TD Lunch Money Importer
"""
import sys
import logging
from datetime import datetime
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
    """Set up logging configuration"""
    from pathlib import Path

    # Constants
    LOG_DIR = Path.home() / ".lunchmoney" / "logs"
    LOG_FILE = LOG_DIR / f"importer-{datetime.now().strftime('%Y%m%d')}.log"

    # Create log directory if it doesn't exist
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    # Configure logging - file only, no console output
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(LOG_FILE)
        ]
    )

    logger.info(f"Starting importer - Log file: {LOG_FILE}")
    return LOG_FILE
