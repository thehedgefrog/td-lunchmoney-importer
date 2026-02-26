import unittest
from unittest.mock import Mock, patch

from lunchable import TransactionInsertObject
from lunchable.exceptions import LunchMoneyError

from lunchmoney.api import validate_transactions, import_transactions


class TestApiTransactions(unittest.TestCase):
    def make_txn(self, amount=10.0, asset_id=1):
        return TransactionInsertObject(
            date="2025-01-01",
            amount=amount,
            payee="Test",
            asset_id=asset_id,
            external_id="ext-1",
        )

    def test_validate_transactions_returns_false_for_empty(self):
        self.assertFalse(validate_transactions([]))

    def test_validate_transactions_returns_true_for_valid_items(self):
        self.assertTrue(validate_transactions([self.make_txn()]))

    def test_import_transactions_calls_lunch_api_with_expected_flags(self):
        lunch = Mock()
        lunch.insert_transactions.return_value = [object()]
        txns = [self.make_txn()]

        result = import_transactions(lunch, txns)

        self.assertTrue(result)
        lunch.insert_transactions.assert_called_once_with(
            transactions=txns,
            apply_rules=True,
            skip_duplicates=True,
            debit_as_negative=True,
            check_for_recurring=True,
            skip_balance_update=False,
        )

    def test_import_transactions_returns_false_when_validation_fails(self):
        lunch = Mock()
        with patch("lunchmoney.api.validate_transactions", return_value=False):
            result = import_transactions(lunch, [self.make_txn()])

        self.assertFalse(result)
        lunch.insert_transactions.assert_not_called()

    def test_import_transactions_handles_lunchmoney_error(self):
        lunch = Mock()
        lunch.insert_transactions.side_effect = LunchMoneyError("bad request")

        result = import_transactions(lunch, [self.make_txn()])

        self.assertFalse(result)


if __name__ == "__main__":
    unittest.main()
