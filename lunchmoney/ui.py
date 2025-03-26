"""
User interface module for TD Lunch Money Importer
"""
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable
from colorama import Fore, Style, init
from datetime import datetime

from .common import print_success, print_error, print_header, show_progress

logger = logging.getLogger(__name__)

def display_welcome_header():
    """Display welcome header with program information"""
    print(f"\n{Fore.GREEN}{Style.BRIGHT}💰 TD Lunch Money Importer{Style.RESET_ALL}")
    print(f"{Fore.GREEN}{'=' * 30}{Style.RESET_ALL}\n")

def display_user_info(lunch):
    """Display user information"""
    from .api import get_user_info  # Import here to avoid circular import
    user_name = get_user_info(lunch)
    print(f"Connected as: {Fore.CYAN}{user_name}{Style.RESET_ALL}\n")

def get_validated_input(prompt, validator, error_msg):
    """Get user input with validation"""
    while True:
        user_input = input(f"{prompt}: ").strip()
        if validator(user_input):
            return user_input
        print(f"{Fore.RED}{error_msg}{Style.RESET_ALL}")

def display_menu(options):
    """Display a menu of selectable options"""
    print(f"\n{Fore.YELLOW}Options:{Style.RESET_ALL}")
    # Create a mapping of numbers to option keys
    number_map = {}
    for i, (key, desc) in enumerate(options.items(), 1):
        print(f"{Fore.YELLOW}{i}{Style.RESET_ALL}. {desc}")
        number_map[str(i)] = key
    return number_map

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

def confirm_import():
    """Ask user for confirmation"""
    while True:
        response = input("\nDo you want to proceed with the import? (yes/no): ").lower().strip()
        if response in ['yes', 'y']:
            return True
        if response in ['no', 'n']:
            return False
        print("Please answer 'yes' or 'no'")

def get_qfx_path() -> str:
    """Prompt for QFX file path"""
    while True:
        path = input("Enter path to QFX file: ").strip()
        if path and Path(path).exists():
            return path
        print("File not found. Please enter a valid path.")

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

def get_start_date():
    """Prompt for optional start date with additional options"""
    while True:
        option_map = display_menu({
            "date": "Import transactions after specific date (YYYY-MM-DD)",
            "all": "Import all transactions",
            "api_key": "Change API key only",
            "config": "Reconfigure accounts",
            "reset": "Reset all configuration",
            "exit": "Quit the program"
        })

        choice = input("\nEnter option (1-6): ").strip().lower()

        # Check if user entered a number
        if choice in option_map:
            choice = option_map[choice]

        if choice == 'exit':
            return 'exit'
        elif choice == 'config':
            return 'config'
        elif choice == 'api_key':
            return 'api_key'
        elif choice == 'reset':
            return 'reset'
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
