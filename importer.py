#!/usr/bin/env python
"""
TD Lunch Money Importer - Main entry point
A utility to import TD Bank transactions to Lunch Money
"""
import sys
import argparse
from pathlib import Path
from typing import Optional
from colorama import init
from lunchmoney.gui import launch_gui

# Import from our modules
from lunchmoney import (
    # Setup
    setup_logging, display_welcome_header,
    # Configuration
    ConfigurationState, load_config, get_api_key, save_config, reset_api_key,  # Include it here
    # QFX Processing
    get_qfx_accounts, format_transactions, check_new_accounts,
    # UI
    display_user_info, display_menu, print_success, print_error,
    show_progress, do_onboarding, confirm_import, get_qfx_path,
    display_transactions, get_start_date,
    # API operations
    import_transactions, update_account_balances,
    # Utilities
    graceful_exit
)

def run_cli(input_file: Optional[str] = None) -> None:
    """Run the interactive terminal (CLI) flow."""
    state = ConfigurationState()

    try:
        # Get file path either from args or user input
        if input_file:
            qfx_path = input_file
        else:
            try:
                qfx_path = get_qfx_path()
            except (EOFError, RuntimeError):
                print_error(
                    "No interactive input is available in CLI mode. "
                    "Pass a QFX path (e.g. '--cli /path/to/file.qfx') or run without '--cli' for GUI mode."
                )
                graceful_exit(1)

        if not Path(qfx_path).exists():
            print_error(f"Input file not found: {qfx_path}")
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
            except Exception as e:
                print_error(f"\nAPI Error: {e}")
                continue

            qfx_accounts = get_qfx_accounts(qfx_path)
            if not qfx_accounts:
                print_error("No accounts found in QFX file")
                graceful_exit(1)

            if state.config and 'account_mapping' in state.config:
                new_accounts = check_new_accounts(qfx_accounts, state.config['account_mapping'])
                if new_accounts:
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
                # Keep API key, but reset account mappings
                state.reset(keep_api_key=True)
                continue
            elif start_date == 'api_key':
                # Only reset API key and request a new one
                reset_api_key()
                api_key = get_api_key()
                if not state.initialize(api_key):
                    print("\nInvalid API key or connection error. Please try again.")
                else:
                    # Save the new API key with existing account mappings
                    state.config['api_key'] = api_key
                    save_config(state.config)
                    print_success("API key updated successfully")
                continue
            elif start_date == 'reset':
                # Reset everything
                state.reset(keep_api_key=False)
                continue

            # Process transactions
            show_progress("Processing transactions")
            transactions = format_transactions(qfx_accounts, state.config['account_mapping'], start_date)
            if not transactions:
                print_error("No transactions to import")
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
        print("\nOperation cancelled by user")
        graceful_exit()


def main() -> None:
    """Application entry point.

    Default mode is GUI. Use --cli to force terminal mode.
    """
    setup_logging()
    init(autoreset=True)

    parser = argparse.ArgumentParser(description="Import TD QFX transactions into Lunch Money")
    parser.add_argument("input_files", nargs='*', help="Optional QFX file path(s)")
    parser.add_argument("--cli", action="store_true", help="Force terminal/CLI mode")
    args = parser.parse_args()

    if args.cli:
        display_welcome_header()
        if len(args.input_files) > 1:
            print_error("CLI mode currently supports one QFX file at a time. Using the first file provided.")
        run_cli(args.input_files[0] if args.input_files else None)
        return

    # GUI default: supports drag-and-drop and optional startup file list.
    try:
        raise_code = launch_gui(args.input_files or None)
    except Exception as exc:
        print_error(f"Failed to launch GUI: {exc}")
        graceful_exit(1)
    if raise_code:
        graceful_exit(raise_code)

if __name__ == "__main__":
    main()
