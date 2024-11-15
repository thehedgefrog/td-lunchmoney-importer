import json
import sys
import base64
import argparse
from pathlib import Path
from datetime import datetime
from ofxparse import OfxParser
from lunchable import LunchMoney, TransactionInsertObject  # Import from lunchable
from dataclasses import dataclass, asdict
from typing import Optional

# Use Path for cross-platform compatibility
CONFIG_FILE = Path.home() / ".lunchmoney_config.json"

def get_api_key():
    """Prompt user for API key"""
    while True:
        key = input("Please enter your LunchMoney API key: ").strip()
        if key:
            return key
        print("API key cannot be empty")

def load_config():
    """Load and decode existing config if it exists"""
    try:
        if CONFIG_FILE.exists():
            with open(CONFIG_FILE, 'r') as f:
                encoded_data = f.read().strip()
                json_str = base64.b64decode(encoded_data).decode('utf-8')
                return json.loads(json_str)
    except (json.JSONDecodeError, IOError, base64.binascii.Error) as e:
        print(f"Error loading config: {e}")
    return None

def save_config(config):
    """Encode and save config to file"""
    try:
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        json_str = json.dumps(config)
        encoded_data = base64.b64encode(json_str.encode('utf-8')).decode('utf-8')
        with open(CONFIG_FILE, 'w') as f:
            f.write(encoded_data)
    except (IOError, TypeError) as e:
        print(f"Error saving config: {e}")
        sys.exit(1)

def get_qfx_accounts(qfx_file):
    """Parse QFX file and return accounts"""
    try:
        with open(qfx_file) as fileobj:
            ofx = OfxParser.parse(fileobj)
        return ofx.accounts
    except Exception as e:
        print(f"Error parsing QFX file: {e}")
        sys.exit(1)

def verify_api_connection(lunch):
    """Verify API connection and greet user"""
    try:
        user = lunch.get_user()
        print(f"\nHi, {user.user_name}!")
        return True
    except Exception as e:
        print(f"Error connecting to LunchMoney API: {e}")
        return False

def get_start_date():
    """Prompt for optional start date"""
    while True:
        date_input = input("\nEnter start date for transactions (YYYY-MM-DD) or press Enter for all: ").strip()
        if not date_input:
            return None
        try:
            return datetime.strptime(date_input, "%Y-%m-%d").date()
        except ValueError:
            print("Invalid date format. Use YYYY-MM-DD")

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

def display_transactions(transactions, api_accounts):
    """Format and display transaction summary grouped by account"""
    # Create lookup for account display names
    account_names = {
        asset.id: f"{asset.name} ({asset.institution_name})"
        for asset in api_accounts
    }

    # Group transactions by asset_id
    accounts = {}
    for txn in transactions:
        if txn.asset_id not in accounts:
            accounts[txn.asset_id] = []
        accounts[txn.asset_id].append(txn)

    print("\nTransactions to import:")
    total_count = 0

    # Display transactions for each account
    for asset_id, txns in accounts.items():
        print("\n" + "-" * 80)
        print(f"Account: {account_names[asset_id]}")
        print("-" * 80)

        for txn in txns:
            print(f"{txn.date} | {txn.payee:40} | ${txn.amount:>10.2f}")

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

def main():
    parser = argparse.ArgumentParser(description="Process QFX file and match accounts")
    parser.add_argument("input_file", help="The QFX file to process")
    args = parser.parse_args()

    if not Path(args.input_file).exists():
        print(f"Input file not found: {args.input_file}")
        sys.exit(1)

    config = load_config()
    if not config:
        # First run setup
        api_key = get_api_key()
        lunch = LunchMoney(access_token=api_key)
    else:
        # Subsequent runs
        lunch = LunchMoney(access_token=config['api_key'])

    if not verify_api_connection(lunch):
        sys.exit(1)

    try:
        api_accounts = lunch.get_assets()
    except Exception as e:
        print(f"Error getting accounts: {e}")
        sys.exit(1)

    if not config:
        # Continue first run setup
        qfx_accounts = get_qfx_accounts(args.input_file)
        if not qfx_accounts:
            print("No accounts found in QFX file")
            sys.exit(1)

        print("\nAvailable LunchMoney accounts:")
        for i, asset in enumerate(api_accounts, 1):
            print(f"{i}. {asset.name} ({asset.institution_name}) - {asset.type_name}/{asset.subtype_name}")

        print("\nQFX accounts to match:")
        account_mapping = {}
        for qfx_account in qfx_accounts:
            while True:
                try:
                    print(f"\nMatching account number: {qfx_account.account_id}")
                    selection = int(input(f"Enter number (1-{len(api_accounts)}): ")) - 1
                    if 0 <= selection < len(api_accounts):
                        account_mapping[qfx_account.account_id] = api_accounts[selection].id
                        break
                    print("Invalid selection")
                except ValueError:
                    print("Please enter a valid number")

        config = {
            'api_key': api_key,
            'account_mapping': account_mapping
        }
        save_config(config)
        print(f"\nConfiguration saved to {CONFIG_FILE}")

    # Transaction import flow
    qfx_accounts = get_qfx_accounts(args.input_file)
    start_date = get_start_date()

    transactions = format_transactions(qfx_accounts, config['account_mapping'], start_date)
    if not transactions:
        print("No transactions to import")
        sys.exit(0)

    display_transactions(transactions, api_accounts)
    if not confirm_import():
        print("Import cancelled")
        sys.exit(0)

    try:
        # Pass transactions directly, API returns list of IDs
        result = lunch.insert_transactions(
            transactions=transactions,
            apply_rules=True,
            skip_duplicates=True,
            debit_as_negative=True,
            check_for_recurring=True,
            skip_balance_update=False
        )
        print(f"Successfully imported {len(result)} transactions")
    except Exception as e:
        print(f"Error importing transactions: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()