"""
Common utilities shared across modules
"""
import logging
from colorama import Fore, Style

logger = logging.getLogger(__name__)

def print_success(text):
    """Print success message with green color"""
    print(f"{Fore.GREEN}✓ {text}{Style.RESET_ALL}")

def print_error(text):
    """Print error message with red color"""
    print(f"{Fore.RED}✗ {text}{Style.RESET_ALL}")

def print_header(text):
    """Print a styled section header"""
    print(f"\n{Fore.CYAN}{Style.BRIGHT}{text}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{'-' * len(text)}{Style.RESET_ALL}")

def show_progress(message):
    """Show a simple progress indicator"""
    print(f"\n{Fore.BLUE}⏳ {message}...{Style.RESET_ALL}")