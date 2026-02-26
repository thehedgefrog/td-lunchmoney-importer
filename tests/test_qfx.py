import unittest
from datetime import datetime, date
from types import SimpleNamespace

from lunchmoney.qfx import format_transactions, check_new_accounts


class TestQfxFormatting(unittest.TestCase):
    def test_format_transactions_filters_date_and_uses_defaults(self):
        account = SimpleNamespace(
            account_id="acct-123",
            statement=SimpleNamespace(
                transactions=[
                    SimpleNamespace(
                        id="txn-1",
                        date=datetime(2025, 1, 10, 12, 0, 0),
                        amount=123.45,
                        payee="Coffee Shop",
                    ),
                    SimpleNamespace(
                        id="txn-2",
                        date=datetime(2024, 12, 31, 12, 0, 0),
                        amount=50,
                        payee=None,
                    ),
                ]
            ),
        )

        result = format_transactions(
            accounts=[account],
            account_mapping={"acct-123": 42},
            start_date=date(2025, 1, 1),
        )

        self.assertEqual(len(result), 1)
        txn = result[0]
        self.assertEqual(txn.date, date(2025, 1, 10))
        self.assertEqual(txn.amount, 123.45)
        self.assertEqual(txn.payee, "Coffee Shop")
        self.assertEqual(txn.asset_id, 42)
        self.assertEqual(txn.external_id, "acct-123-txn-1")

    def test_format_transactions_skips_unmapped_account(self):
        account = SimpleNamespace(
            account_id="acct-999",
            statement=SimpleNamespace(
                transactions=[
                    SimpleNamespace(
                        id="txn-1",
                        date=datetime(2025, 1, 10, 12, 0, 0),
                        amount=1,
                        payee="Any",
                    )
                ]
            ),
        )

        result = format_transactions(
            accounts=[account],
            account_mapping={"acct-123": 42},
            start_date=None,
        )

        self.assertEqual(result, [])

    def test_check_new_accounts_returns_only_missing_ids(self):
        qfx_accounts = [
            SimpleNamespace(account_id="acct-1"),
            SimpleNamespace(account_id="acct-2"),
            SimpleNamespace(account_id="acct-3"),
        ]

        result = check_new_accounts(
            qfx_accounts=qfx_accounts,
            account_mapping={"acct-1": 101, "acct-3": 303},
        )

        self.assertEqual(result, ["acct-2"])


if __name__ == "__main__":
    unittest.main()
