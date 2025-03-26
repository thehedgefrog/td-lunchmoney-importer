"""
Configuration management module for TD Lunch Money Importer
"""
import json
import logging
import keyring
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime

from lunchable import LunchMoney
from lunchable.exceptions import LunchMoneyError

from .common import print_error
from .utils import graceful_exit

# Constants
APP_NAME = "td-lunchmoney-importer"
KEYRING_USERNAME = "lunchmoney_api"
CONFIG_FILE = Path.home() / ".lunchmoney" / "config.json"
LOG_DIR = Path.home() / ".lunchmoney" / "logs"
LOG_FILE = LOG_DIR / f"importer-{datetime.now().strftime('%Y%m%d')}.log"

logger = logging.getLogger(__name__)

class ConfigurationState:
    """Manage application configuration state"""
    def __init__(self):
        self.config: Optional[Dict[str, Any]] = None
        self.lunch: Optional[LunchMoney] = None
        self.api_accounts: List[Any] = []

    def reset(self, keep_api_key=False) -> None:
        """Reset configuration state

        Args:
            keep_api_key: If False, also remove API key from keyring
        """
        if CONFIG_FILE.exists():
            CONFIG_FILE.unlink()

        # Remove API key from keyring if requested
        if not keep_api_key:
            reset_api_key()

        self.config = None
        self.lunch = None
        self.api_accounts = []

    def initialize(self, api_key: str) -> bool:
        """Initialize LunchMoney client"""
        from .api import verify_api_connection
        try:
            self.lunch = LunchMoney(access_token=api_key)
            return verify_api_connection(self.lunch)
        except LunchMoneyError as e:
            logger.error(f"Failed to initialize LunchMoney client: {e}")
            return False

def get_api_key() -> str:
    """Prompt user for API key"""
    while True:
        key = input("Please enter your LunchMoney API key: ").strip()
        if key:
            return key
        logger.warning("API key cannot be empty")

def save_api_key(api_key: str) -> None:
    """Save API key securely to system keyring"""
    try:
        keyring.set_password(APP_NAME, KEYRING_USERNAME, api_key)
        logger.info("API key saved to system keyring")
    except Exception as e:
        logger.error(f"Failed to save API key to keyring: {e}")
        print_error("Could not securely store API key")
        graceful_exit(1)

def get_saved_api_key() -> Optional[str]:
    """Retrieve API key from system keyring"""
    try:
        return keyring.get_password(APP_NAME, KEYRING_USERNAME)
    except Exception as e:
        logger.error(f"Failed to retrieve API key from keyring: {e}")
        return None

def reset_api_key() -> bool:
    """Remove API key from keyring"""
    try:
        keyring.delete_password(APP_NAME, KEYRING_USERNAME)
        logger.info("API key removed from system keyring")
        return True
    except Exception as e:
        logger.error(f"Failed to remove API key from keyring: {e}")
        return False

def load_config() -> Optional[Dict[str, Any]]:
    """Load configuration from file and keyring with validation"""
    try:
        # Get API key from keyring
        api_key = get_saved_api_key()

        # Get account mappings from file
        if CONFIG_FILE.exists():
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)

            # Validate config structure
            if not isinstance(config, dict):
                logger.error("Invalid configuration format: not a dictionary")
                print_error("Configuration file is corrupted (invalid structure)")
                return None

            if 'account_mapping' not in config:
                logger.warning("Missing account_mapping in config, creating empty mapping")
                config['account_mapping'] = {}

            # Validate account mapping is a dictionary
            if not isinstance(config['account_mapping'], dict):
                logger.error("Invalid account_mapping format")
                print_error("Configuration file is corrupted (invalid mapping)")
                return None

            # Check all account IDs are strings
            invalid_keys = [k for k in config['account_mapping'].keys() if not isinstance(k, str)]
            if invalid_keys:
                logger.warning(f"Invalid account keys found: {invalid_keys}, fixing")
                # Convert keys to strings
                config['account_mapping'] = {
                    str(k): v for k, v in config['account_mapping'].items()
                }

            # Merge with API key
            if api_key:
                config['api_key'] = api_key
                return config

        # If we have an API key but no config file, start with API key only
        elif api_key:
            return {'api_key': api_key, 'account_mapping': {}}

    except json.JSONDecodeError as e:
        logger.error(f"Error parsing config file: {e}")
        print_error(f"Configuration file is corrupted: {e}")
    except IOError as e:
        logger.error(f"Error accessing config file: {e}")
        print_error(f"Could not access configuration file: {e}")
    except Exception as e:
        logger.error(f"Unexpected error loading config: {e}")
        print_error(f"Error loading configuration: {e}")

    return None

def save_config(config: Dict[str, Any]) -> None:
    """Save account mappings to file and API key to keyring"""
    try:
        # Save API key to keyring
        if 'api_key' in config:
            save_api_key(config['api_key'])

        # Save account mappings to file
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        file_config = {'account_mapping': config.get('account_mapping', {})}
        with open(CONFIG_FILE, 'w') as f:
            json.dump(file_config, f)

    except (IOError, TypeError) as e:
        logger.error(f"Error saving config: {e}")
        print_error(f"Failed to save configuration: {e}")
        graceful_exit(1)

def check_new_accounts(qfx_accounts, account_mapping):
    """Check for any new accounts in QFX file"""
    new_accounts = []
    for account in qfx_accounts:
        if account.account_id not in account_mapping:
            new_accounts.append(account.account_id)
    return new_accounts
