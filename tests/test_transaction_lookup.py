from app.services.transaction_lookup import resolve_transaction_direction


class TestResolveTransactionDirection:
    def test_internal_when_both_addresses_known(self):
        accounts = {"0xFrom", "0xTo"}
        address, category = resolve_transaction_direction(
            "0xFrom",
            "0xTo",
            accounts,
        )
        assert address == "0xFrom"
        assert category == "internal"

    def test_receive_when_only_recipient_known(self):
        accounts = {"0xTo"}
        address, category = resolve_transaction_direction(
            "0xOther",
            "0xTo",
            accounts,
        )
        assert address == "0xTo"
        assert category == "receive"

    def test_send_when_only_sender_known(self):
        accounts = {"0xFrom"}
        address, category = resolve_transaction_direction(
            "0xFrom",
            "0xOther",
            accounts,
        )
        assert address == "0xFrom"
        assert category == "send"

    def test_none_when_unrelated(self):
        address, category = resolve_transaction_direction(
            "0xA",
            "0xB",
            {"0xC"},
        )
        assert address is None
        assert category is None
