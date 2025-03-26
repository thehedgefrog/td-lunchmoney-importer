"""
Lunch Money API interactions
"""
from dataclasses import dataclass
from typing import List, Dict, Optional, Any
import logging

from lunchable import LunchMoney, TransactionInsertObject
from lunchable.exceptions import LunchMoneyError

from .common import print_success, print_error

logger = logging.getLogger(__name__)

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

def verify_api_connection(lunch: LunchMoney) -> bool:
    """Verify API connection"""
    try:
        user = lunch.get_user()
        logger.info(f"API user response: {user}")
        return True
    except LunchMoneyError as e:
        logger.error(f"API connection error: {e}")
        return False

def get_user_info(lunch):
    """Get user information from Lunch Money API"""
    try:
        user = lunch.get_user()
        # Access user properties
        if hasattr(user, 'user_name'):
            return user.user_name
        else:
            # Log available attributes to help debug
            logger.info(f"Available user attributes: {dir(user)}")
            return "Unknown"
    except Exception as e:
        logger.error(f"Error retrieving user info: {e}")
        return "Unknown"

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

def update_account_balances(lunch, qfx_accounts, account_mapping, api_accounts=None):
    """Update account balances from QFX data"""
    from .utils import graceful_exit

    # Get fresh account data after transactions import
    try:
        if not api_accounts:
            api_accounts = lunch.get_assets()
    except LunchMoneyError as e:
        logger.error(f"Failed to get updated account data: {e}")
        print_error("Couldn't retrieve current balances - skipping balance updates")
        return False

    # Create lookup for account display names
    account_names = {
        asset.id: f"{asset.name} ({asset.institution_name})"
        for asset in api_accounts
    }

    from .ui import print_header
    print_header("Account Balances")

    from .ui import Style, Fore
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

    return True
