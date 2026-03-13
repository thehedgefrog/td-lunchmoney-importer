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
class ImportResult:
    """Structured import outcome for CLI and GUI flows."""

    success: bool
    imported_count: int = 0
    message_lines: Optional[List[str]] = None

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
        logger.info(f"API user response: {user}")

        # Extract user name
        if hasattr(user, 'user_name'):
            user_name = user.user_name
        else:
            logger.info(f"Available user attributes: {dir(user)}")
            user_name = "Unknown"

        # Extract budget name from user object
        if hasattr(user, 'budget_name'):
            budget_name = user.budget_name
        else:
            logger.info(f"Budget name not found in user response")
            budget_name = "Default Budget"

        return user_name, budget_name

    except Exception as e:
        logger.error(f"Error retrieving user info: {e}")
        return "Unknown", "Unknown"

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

def import_transactions(lunch: LunchMoney, transactions: List[TransactionInsertObject]) -> ImportResult:
    """Import transactions with proper error handling."""
    try:
        if not validate_transactions(transactions):
            return ImportResult(success=False, message_lines=["No valid transactions to import."])

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
            message_lines = [
                "No new transactions imported.",
                "Note: This usually means all transactions already exist in Lunch Money",
                "(Duplicate detection is based on transaction external ID)",
            ]
            for line in message_lines:
                print(f"\n{line}" if line == message_lines[0] else line)
            return ImportResult(success=True, imported_count=0, message_lines=message_lines)

        success_line = f"Successfully imported {len(result)} transactions"
        print(f"\n{success_line}")
        return ImportResult(success=True, imported_count=len(result), message_lines=[success_line])

    except LunchMoneyError as e:
        logger.error(f"API error during import: {e}")
        print(f"Error importing transactions: {e}")
        return ImportResult(success=False, message_lines=[f"Error importing transactions: {e}"])
    except ValueError as e:
        logger.error(f"Data validation error: {e}")
        print(f"Error validating transactions: {e}")
        return ImportResult(success=False, message_lines=[f"Error validating transactions: {e}"])
    except Exception as e:
        logger.error(f"Unexpected error during import: {e}")
        print(f"Unexpected error: {e}")
        return ImportResult(success=False, message_lines=[f"Unexpected error: {e}"])

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
