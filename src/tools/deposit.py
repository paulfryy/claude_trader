"""
CLI tool to record a deposit or withdrawal.

Usage:
  python -m src.tools.deposit --env .env.live --amount 1200 --note "Fidelity transfer"
  python -m src.tools.deposit --env .env.paper --amount -500 --note "Withdrew profits"
  python -m src.tools.deposit --env .env.live --list

Positive amounts are deposits, negative are withdrawals.
"""

import argparse
import sys

from dotenv import load_dotenv

from src.config import load_settings
from src.logging_utils.deposits import (
    get_capital_base,
    load_deposits,
    record_deposit,
    total_net_deposits,
)


def main():
    parser = argparse.ArgumentParser(description="Record cash deposits and withdrawals")
    parser.add_argument("--env", required=True, help="Path to env file (.env.live or .env.paper)")
    parser.add_argument("--amount", type=float, help="Dollar amount (positive=deposit, negative=withdrawal)")
    parser.add_argument("--note", default="", help="Free-text note")
    parser.add_argument("--list", action="store_true", help="Just list current entries, don't add")
    args = parser.parse_args()

    load_dotenv(args.env, override=True)
    settings = load_settings(env_file=args.env)
    mode = settings.trading_mode

    if args.list:
        entries = load_deposits(mode)
        print(f"=== Deposits for {mode.upper()} ===")
        print(f"Starting capital: ${settings.starting_capital:,.2f}")
        if not entries:
            print("No deposits recorded.")
        else:
            for e in entries:
                sign = "+" if e["amount"] >= 0 else ""
                print(f"  {e['timestamp'][:19]}  {sign}${e['amount']:>10,.2f}  {e['note']}")
        print(f"Net deposits:     ${total_net_deposits(mode):,.2f}")
        print(f"Capital base:     ${get_capital_base(settings):,.2f}")
        return

    if args.amount is None:
        print("Error: --amount required unless --list", file=sys.stderr)
        sys.exit(1)

    entry = record_deposit(mode, args.amount, args.note)
    new_base = get_capital_base(settings)
    action = "Deposit" if args.amount >= 0 else "Withdrawal"
    print(f"{action} recorded: ${entry['amount']:,.2f}")
    print(f"Note: {entry['note'] or '(none)'}")
    print(f"New capital base ({mode}): ${new_base:,.2f}")


if __name__ == "__main__":
    main()
