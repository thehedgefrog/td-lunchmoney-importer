"""
QFX file handling module for TD Lunch Money Importer
"""
import logging
from pathlib import Path
from typing import List, Dict, Optional, Any
from io import StringIO
from ofxparse import OfxParser
from lunchable import TransactionInsertObject
from datetime import datetime

from .utils import graceful_exit, print_error

logger = logging.getLogger(__name__)

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
            try:
                with open(qfx_file, 'r', encoding='utf-8', errors='ignore') as fileobj:
                    content = fileobj.read()
                    # Remove or replace problematic characters
                    content = content.encode('cp1252', errors='ignore').decode('cp1252')
                    ofx = OfxParser.parse(StringIO(content))
                    return ofx.accounts
            except Exception as parsing_error:
                logger.error(f"Failed to parse QFX after multiple attempts: {parsing_error}")
                print_error(f"Could not parse QFX file: {parsing_error}")
                graceful_exit(1)
    except FileNotFoundError:
        logger.error(f"QFX file not found: {qfx_file}")
        print_error(f"File not found: {qfx_file}")
        graceful_exit(1)
    except Exception as e:
        logger.error(f"Error parsing QFX file: {e}")
        print_error(f"Error parsing QFX file: {e}")
        graceful_exit(1)

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

def check_new_accounts(qfx_accounts, account_mapping):
    """Check for any new accounts in QFX file"""
    new_accounts = []
    for account in qfx_accounts:
        if account.account_id not in account_mapping:
            new_accounts.append(account.account_id)
    return new_accounts
