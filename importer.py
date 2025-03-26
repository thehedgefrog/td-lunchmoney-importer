import json
import sys
import base64
import logging
import argparse
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, Any
from dataclasses import dataclass
from ofxparse import OfxParser
from lunchable import LunchMoney, TransactionInsertObject
from lunchable.exceptions import LunchMoneyError
from io import StringIO
from colorama import Fore, Style, init

# Constants
CONFIG_FILE = Path.home() / ".lunchmoney" / ".lunchmoney_config.json"
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
logger = logging.getLogger(__name__)

# Log startup
logger.info(f"Starting importer - Log file: {LOG_FILE}")

# Constants
CONFIG_FILE = Path.home() / ".lunchmoney" / ".lunchmoney_config.json"

class ConfigurationState:
    """Manage application configuration state"""
    def __init__(self):
        self.config: Optional[Dict[str, Any]] = None
        self.lunch: Optional[LunchMoney] = None
        self.api_accounts: List[Any] = []

    def reset(self) -> None:
        """Reset configuration state"""
        if CONFIG_FILE.exists():
            CONFIG_FILE.unlink()
        self.config = None
        self.lunch = None
        self.api_accounts = []

    def initialize(self, api_key: str) -> bool:
        """Initialize LunchMoney client"""
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

def load_config() -> Optional[Dict[str, Any]]:
    """Load and decode existing config"""
    try:
        if CONFIG_FILE.exists():
            with open(CONFIG_FILE, 'r') as f:
                encoded_data = f.read().strip()
                json_str = base64.b64decode(encoded_data).decode('utf-8')
                return json.loads(json_str)
    except (json.JSONDecodeError, IOError, base64.binascii.Error) as e:
        logger.error(f"Error loading config: {e}")
    return None

def save_config(config: Dict[str, Any]) -> None:
    """Encode and save config"""
    try:
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        json_str = json.dumps(config)
        encoded_data = base64.b64encode(json_str.encode('utf-8')).decode('utf-8')
        with open(CONFIG_FILE, 'w') as f:
            f.write(encoded_data)
    except (IOError, TypeError) as e:
        logger.error(f"Error saving config: {e}")
        graceful_exit(1)

def get_qfx_accounts(qfx_file):
    """Parse QFX file and return accounts"""
    try:
        # First try reading with UTF-8
        with open(qfx_file, 'r', encoding='utf-8') as fileobj:
            ofx = OfxParser.parse(fileobj)
            return ofx.accounts
    except UnicodeError:
        try:
            # If UTF-8 fails, try with cp1252 (Windows encoding)
            with open(qfx_file, 'r', encoding='cp1252') as fileobj:
                ofx = OfxParser.parse(fileobj)
                return ofx.accounts
        except Exception as e:
            # If both fail, try to read and clean the file
            with open(qfx_file, 'r', encoding='utf-8', errors='ignore') as fileobj:
                content = fileobj.read()
                # Remove or replace problematic characters
                content = content.encode('cp1252', errors='ignore').decode('cp1252')
                ofx = OfxParser.parse(StringIO(content))
                return ofx.accounts
    except Exception as e:
        print(f"Error parsing QFX file: {e}")
        logger.error(f"Error parsing QFX file: {e}")
        sys.exit(1)

def verify_api_connection(lunch: LunchMoney) -> bool:
    """Verify API connection"""
    try:
        user = lunch.get_user()
        logger.info(f"API user response: {user}")
        return True
    except LunchMoneyError as e:
        logger.error(f"API connection error: {e}")
        return False

def do_onboarding(lunch, qfx_accounts, api_accounts):
    """Handle account mapping workflow"""

    print_header("Available Lunch Money Accounts")
    for i, asset in enumerate(api_accounts, 1):
        print(f"{i}. {Fore.CYAN}{asset.name} ({asset.institution_name}){Style.RESET_ALL} - {asset.type_name}/{asset.subtype_name}")

    print_header("QFX Accounts to Match")
    account_mapping = {}
    for qfx_account in qfx_accounts:
        while True:
            try:
                print(f"\n{Fore.CYAN}Account:{Style.RESET_ALL} {qfx_account.account_id}")
                selection = int(input(f"Enter number (1-{len(api_accounts)}): ")) - 1
                if 0 <= selection < len(api_accounts):
                    account_mapping[qfx_account.account_id] = api_accounts[selection].id
                    print_success(f"Matched with {api_accounts[selection].name}")
                    break
                print_error("Invalid selection")
            except ValueError:
                print_error("Please enter a valid number")
    return account_mapping

def check_new_accounts(qfx_accounts, account_mapping):
    """Check for any new accounts in QFX file"""
    new_accounts = []
    for account in qfx_accounts:
        if account.account_id not in account_mapping:
            new_accounts.append(account.account_id)
    return new_accounts

def display_menu(options):
    """Display a menu of selectable options"""
    print(f"\n{Fore.YELLOW}Options:{Style.RESET_ALL}")
    # Create a mapping of numbers to option keys
    number_map = {}
    for i, (key, desc) in enumerate(options.items(), 1):
        print(f"{Fore.YELLOW}{i}{Style.RESET_ALL}. {desc}")
        number_map[str(i)] = key
    return number_map

def get_start_date():
    """Prompt for optional start date with additional options"""
    while True:
        option_map = display_menu({
            "date": "Import transactions after specific date (YYYY-MM-DD)",
            "all": "Import all transactions",
            "config": "Reconfigure API key and accounts",
            "exit": "Quit the program"
        })

        choice = input("\nEnter option (1-4): ").strip().lower()

        # Check if user entered a number
        if choice in option_map:
            choice = option_map[choice]

        if choice == 'exit':
            return 'exit'
        elif choice == 'config':
            return 'config'
        elif choice == 'all':
            return None
        elif choice == 'date':
            date_input = input("Enter date (YYYY-MM-DD): ").strip()
            try:
                return datetime.strptime(date_input, "%Y-%m-%d").date()
            except ValueError:
                print_error("Invalid date format. Use YYYY-MM-DD")
        else:
            print_error("Invalid option. Please select a number from the menu")

def graceful_exit(code: int = 0) -> None:
    """Handle clean program exit"""
    cleanup()
    logger.info(f"Exiting program with code {code}")
    sys.exit(code)  # This ensures the program actually exits

@dataclass
class TransactionObject:
    """Base class for transactions"""
    date: str
    amount: str
    payee: str
    asset_id: int
    status: str = "cleared"
    external_id: Optional[str] = None
    currency: Optional[str] = None
    category_id: Optional[int] = None
    notes: Optional[str] = None
    tags: Optional[list] = None

def format_transactions(accounts, account_mapping, start_date=None):
    """Format transactions for API using lunchable's TransactionInsertObject"""
    transactions = []
    for account in accounts:
        asset_id = account_mapping.get(account.account_id)
        if not asset_id:
            continue

        for txn in account.statement.transactions:
            if start_date and txn.date.date() < start_date:
                continue

            transaction = TransactionInsertObject(
                date=txn.date.strftime("%Y-%m-%d"),
                amount=float(txn.amount),
                payee=txn.payee if txn.payee else "Unknown",
                asset_id=asset_id,
                external_id=f"{account.account_id}-{txn.id}"
            )
            transactions.append(transaction)
    return transactions

def display_transactions(transactions, api_accounts, account_mapping):
    """Format and display transaction summary grouped by account"""
    # Create lookup for account display names
    account_names = {
        asset.id: f"{asset.name} ({asset.institution_name})"
        for asset in api_accounts
    }

    # Create reverse mapping from asset_id to account_id
    reverse_mapping = {v: k for k, v in account_mapping.items()}

    # Group transactions by asset_id
    accounts = {}
    for txn in transactions:
        if txn.asset_id not in accounts:
            accounts[txn.asset_id] = []
        accounts[txn.asset_id].append(txn)

    print_header("Transactions to import")
    total_count = 0

    # Display transactions for each account
    for asset_id, txns in accounts.items():
        print("\n" + "-" * 80)
        qfx_account_id = reverse_mapping.get(asset_id, "Unknown")
        print(f"Account: {Fore.CYAN}{account_names[asset_id]}{Style.RESET_ALL} (Account # {qfx_account_id})")
        print("-" * 80)

        for txn in txns:
            amount_color = Fore.RED if txn.amount < 0 else Fore.GREEN
            print(f"{txn.date} | {txn.payee:40} | {amount_color}${abs(txn.amount):>10.2f}{Style.RESET_ALL}")

        count = len(txns)
        total_count += count
        print(f"Account transactions: {count}")

    print("\n" + "=" * 80)
    print(f"Total transactions to import: {total_count}")

def confirm_import():
    """Ask user for confirmation"""
    while True:
        response = input("\nDo you want to proceed with the import? (yes/no): ").lower().strip()
        if response in ['yes', 'y']:
            return True
        if response in ['no', 'n']:
            return False
        print("Please answer 'yes' or 'no'")

def update_account_balances(lunch, qfx_accounts, account_mapping):
    """Update account balances from QFX data"""
    # Get fresh account data after transactions import
    try:
        api_accounts = lunch.get_assets()
    except LunchMoneyError as e:
        logger.error(f"Failed to get updated account data: {e}")
        print_error("Couldn't retrieve current balances - skipping balance updates")
        graceful_exit()  # Add graceful exit here to ensure clean exit

    # Create lookup for account display names
    account_names = {
        asset.id: f"{asset.name} ({asset.institution_name})"
        for asset in api_accounts
    }

    print_header("Account Balances")

    updates = []
    for account in qfx_accounts:
        asset_id = account_mapping.get(account.account_id)
        if not asset_id or not hasattr(account.statement, 'available_balance'):
            continue

        new_balance = float(account.statement.available_balance)

        # Find current balance from fresh API data
        current_balance = None
        for asset in api_accounts:
            if asset.id == asset_id:
                current_balance = float(asset.balance)
                break

        print(f"\nAccount: {Fore.CYAN}{account_names[asset_id]}{Style.RESET_ALL} (Account # {account.account_id})")

        diff = new_balance - current_balance
        diff_color = Fore.RED if diff < 0 else Fore.GREEN if diff > 0 else Fore.WHITE
        print(f"Current balance: ${current_balance:,.2f}")
        print(f"QFX balance: ${new_balance:,.2f}")
        print(f"Difference: {diff_color}${diff:,.2f}{Style.RESET_ALL}")

        if current_balance != new_balance:
            while True:
                response = input("Update this account balance? (yes/no): ").lower().strip()
                if response in ['yes', 'y']:
                    updates.append((asset_id, new_balance))
                    break
                if response in ['no', 'n']:
                    break
                print("Please answer 'yes' or 'no'")

    if updates:
        print("\nUpdating account balances...")
        for asset_id, balance in updates:
            try:
                lunch.update_asset(asset_id=asset_id, balance=balance)
                print_success(f"Updated {account_names[asset_id]}")
            except Exception as e:
                print_error(f"Error updating {account_names[asset_id]}: {e}")
    else:
        print("\nNo balance updates requested")
        # Graceful exit will happen when returning to main() function

    return True

def validate_transactions(transactions: List[TransactionInsertObject]) -> bool:
    """Validate transactions before import"""
    if not transactions:
        logger.warning("No transactions to validate")
        return False

    for txn in transactions:
        if not all([txn.date, txn.amount, txn.asset_id]):
            logger.error(f"Invalid transaction: {txn}")
            return False
    return True

def import_transactions(lunch: LunchMoney, transactions: List[TransactionInsertObject]) -> bool:
    """Import transactions with proper error handling"""
    try:
        if not validate_transactions(transactions):
            return False

        result = lunch.insert_transactions(
            transactions=transactions,
            apply_rules=True,
            skip_duplicates=True,
            debit_as_negative=True,
            check_for_recurring=True,
            skip_balance_update=False
        )

        # Log result
        logger.info(f"Import result: {len(result)} transactions imported")

        # User feedback
        if len(result) == 0:
            print("\nNo new transactions imported.")
            print("Note: This usually means all transactions already exist in Lunch Money")
            print("(Duplicate detection is based on transaction external ID)")
        else:
            print(f"\nSuccessfully imported {len(result)} transactions")

        return True

    except LunchMoneyError as e:
        logger.error(f"API error during import: {e}")
        print(f"Error importing transactions: {e}")
        return False
    except ValueError as e:
        logger.error(f"Data validation error: {e}")
        print(f"Error validating transactions: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error during import: {e}")
        print(f"Unexpected error: {e}")
        return False

def cleanup() -> None:
    """Cleanup resources"""
    # Add cleanup operations if needed
    pass

def get_qfx_path() -> str:
    """Prompt for QFX file path"""
    while True:
        path = input("Enter path to QFX file: ").strip()
        if path and Path(path).exists():
            return path
        print("File not found. Please enter a valid path.")

def print_header(text):
    """Print a styled section header"""
    print(f"\n{Fore.CYAN}{Style.BRIGHT}{text}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{'-' * len(text)}{Style.RESET_ALL}")

def print_success(text):
    print(f"{Fore.GREEN}✓ {text}{Style.RESET_ALL}")

def print_error(text):
    print(f"{Fore.RED}✗ {text}{Style.RESET_ALL}")

def show_progress(message):
    """Show a simple progress indicator"""
    print(f"\n{Fore.BLUE}⏳ {message}...{Style.RESET_ALL}")

# Improve input validation feedback
def get_validated_input(prompt, validator, error_msg):
    """Get user input with validation"""
    while True:
        user_input = input(f"{prompt}: ").strip()
        if validator(user_input):
            return user_input
        print(f"{Fore.RED}{error_msg}{Style.RESET_ALL}")

def display_welcome_header():
    """Display welcome header with program information"""
    print(f"\n{Fore.GREEN}{Style.BRIGHT}💰 TD Lunch Money Importer{Style.RESET_ALL}")
    print(f"{Fore.GREEN}{'=' * 30}{Style.RESET_ALL}\n")

def get_user_info(lunch):
    """Get user information from Lunch Money API"""
    try:
        user = lunch.get_user()
        # Access user properties properly
        if hasattr(user, 'user_name'):
            return user.user_name
        elif hasattr(user, 'username'):
            return user.username
        elif hasattr(user, 'name'):
            return user.name
        else:
            # Log available attributes to help debug
            logger.info(f"Available user attributes: {dir(user)}")
            return "Unknown"
    except Exception as e:
        logger.error(f"Error retrieving user info: {e}")
        return "Unknown"

def display_user_info(lunch):
    """Display user information"""
    user_name = get_user_info(lunch)
    print(f"Connected as: {Fore.CYAN}{user_name}{Style.RESET_ALL}\n")

def main() -> None:
    """Main program flow"""
    # Initialize colorama
    init(autoreset=True)

    # Show welcome header
    display_welcome_header()

    state = ConfigurationState()

    try:
        parser = argparse.ArgumentParser(description="Process QFX file and match accounts")
        parser.add_argument("input_file", nargs='?', help="The QFX file to process")
        args = parser.parse_args()

        # Get file path either from args or user input
        qfx_path = args.input_file if args.input_file else get_qfx_path()

        if not Path(qfx_path).exists():
            logger.error(f"Input file not found: {qfx_path}")
            graceful_exit(1)

        while True:
            state.config = load_config()

            if not state.config:
                api_key = get_api_key()
                if not state.initialize(api_key):
                    print("\nInvalid API key or connection error. Please try again.")
                    continue
            else:
                if not state.initialize(state.config['api_key']):
                    print("\nStored API key is invalid. Please enter a new one.")
                    state.reset()
                    continue

            try:
                show_progress("Connecting to Lunch Money API")
                state.api_accounts = state.lunch.get_assets()
                display_user_info(state.lunch)
            except LunchMoneyError as e:
                logger.error(f"Failed to get accounts: {e}")
                print(f"\nAPI Error: {e}")
                continue

            qfx_accounts = get_qfx_accounts(qfx_path)
            if not qfx_accounts:
                logger.error("No accounts found in QFX file")
                graceful_exit(1)

            if state.config:
                new_accounts = check_new_accounts(qfx_accounts, state.config['account_mapping'])
                if new_accounts:
                    logger.info(f"New accounts found: {', '.join(new_accounts)}")
                    state.config['account_mapping'].update(
                        do_onboarding(state.lunch, [a for a in qfx_accounts if a.account_id in new_accounts], state.api_accounts)
                    )
                    save_config(state.config)
            else:
                state.config = {
                    'api_key': api_key,
                    'account_mapping': do_onboarding(state.lunch, qfx_accounts, state.api_accounts)
                }
                save_config(state.config)

            start_date = get_start_date()
            if start_date == 'exit':
                graceful_exit()
            elif start_date == 'config':
                state.reset()
                continue

            # Process transactions
            show_progress("Processing transactions")
            transactions = format_transactions(qfx_accounts, state.config['account_mapping'], start_date)
            if not transactions:
                print("No transactions to import")
                graceful_exit()

            # Always display transactions and confirm
            display_transactions(transactions, state.api_accounts, state.config['account_mapping'])
            if not confirm_import():
                print("Import cancelled")
                graceful_exit()

            if import_transactions(state.lunch, transactions):
                update_account_balances(state.lunch, qfx_accounts, state.config['account_mapping'])
                print_success("Import process complete")
                graceful_exit()
            else:
                print_error("Import failed")
                graceful_exit(1)

    except KeyboardInterrupt:
        logger.info("Operation cancelled by user")
        graceful_exit()

if __name__ == "__main__":
    main()