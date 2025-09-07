# ruff: noqa: E501
import textwrap

from financial_analysis import CanonicalTransaction, CSVNormalizer


def _dedent(s: str) -> str:
    # Keep internal newlines, but normalize indentation for readability.
    return textwrap.dedent(s).lstrip("\n").rstrip()


def test_amex_snapshot_to_ctv():
    csv_text = _dedent(
        r"""
        Date,Description,Card Member,Account #,Amount,Extended Details,Appears On Your Statement As,Address,City/State,Zip Code,Country,Reference,Category
        08/29/2025,UBER,JENNY O LEARY,-11016,11.18,"EBHM6M1B SF76ERQ6 10014
        Uber Trip
        help.uber.com
        CA
        SF76ERQ6 10014",Uber Trip help.uber.com CA,"1455 MARKET ST
        4TH FLOOR","SAN FRANCISCO
        CA",94103,UNITED STATES,320252410422442649,Transportation-Taxis & Coach
        08/28/2025,AMAZON.COM AMZN.COM/BILL WA,ADAM BOSSY,-11008,31.56,"3ZAD0U74GLQ MERCHANDISE
        AMAZON.COM
        AMZN.COM/BILL
        WA
        MERCHANDISE",AMAZON.COM AMZN.COM/BILL WA,410 TERRY AVE N,"SEATTLE
        WA",98109,UNITED STATES,320252400412664970,Merchandise & Supplies-Internet Purchase
        """
    )

    rows = CSVNormalizer.normalize(provider="amex", csv_text=csv_text)
    assert len(rows) == 2

    # Expected CTV rows
    memo0 = (
        "EBHM6M1B SF76ERQ6 10014\n"
        "Uber Trip\n"
        "help.uber.com\n"
        "CA\n"
        "SF76ERQ6 10014"
        " | Address=1455 MARKET ST\n4TH FLOOR"
        " | City/State=SAN FRANCISCO\nCA"
        " | Zip Code=94103"
        " | Country=UNITED STATES"
        " | Card Member=JENNY O LEARY"
        " | Account #=-11016"
        " | Description=UBER"
        " | AppearsAs=Uber Trip help.uber.com CA"
    )
    memo1 = (
        "3ZAD0U74GLQ MERCHANDISE\n"
        "AMAZON.COM\n"
        "AMZN.COM/BILL\n"
        "WA\n"
        "MERCHANDISE"
        " | Address=410 TERRY AVE N"
        " | City/State=SEATTLE\nWA"
        " | Zip Code=98109"
        " | Country=UNITED STATES"
        " | Card Member=ADAM BOSSY"
        " | Account #=-11008"
    )

    expected = [
        CanonicalTransaction(
            idx=0,
            id="320252410422442649",
            description="Uber Trip help.uber.com CA",
            amount="-11.18",
            date="2025-08-29",
            merchant="UBER",
            category="Transportation-Taxis & Coach",
            memo=memo0,
        ),
        CanonicalTransaction(
            idx=1,
            id="320252400412664970",
            description="AMAZON.COM AMZN.COM/BILL WA",
            amount="-31.56",
            date="2025-08-28",
            merchant="AMAZON.COM AMZN.COM/BILL WA",
            category="Merchandise & Supplies-Internet Purchase",
            memo=memo1,
        ),
    ]

    assert rows == expected


def test_chase_snapshot_to_ctv():
    csv_text = _dedent(
        r"""
        Transaction Date,Post Date,Description,Category,Type,Amount,Memo
        08/26/2025,08/27/2025,REPLIT  INC.,Shopping,Sale,-16.33,
        08/24/2025,08/25/2025,WISPR,Shopping,Sale,-15.00,
        """
    )

    rows = CSVNormalizer.normalize(provider="chase", csv_text=csv_text)

    expected = [
        CanonicalTransaction(
            idx=0,
            id=None,
            description="REPLIT  INC.",
            amount="-16.33",
            date="2025-08-27",
            merchant="REPLIT  INC.",
            category="Shopping",
            memo="Type=Sale",
        ),
        CanonicalTransaction(
            idx=1,
            id=None,
            description="WISPR",
            amount="-15.00",
            date="2025-08-25",
            merchant="WISPR",
            category="Shopping",
            memo="Type=Sale",
        ),
    ]

    assert rows == expected


def test_alliant_snapshot_to_ctv():
    csv_text = _dedent(
        r"""
        Date,Description,Amount,Balance
        01/02/2025,"WITHDRAWAL ACH AMEX EPAYMENT TYPE: ACH PMT ID: 0005000040 DATA: AM CO: AMEX EPAYMENT NAME: Adam bossy",($4556.29),$25708.51
        01/06/2025,"WITHDRAWAL ACH VERIZON TYPE: PAYMENTREC ID: 9783397101 CO: VERIZON NAME: ADAMBOSSY",($89.99),$25618.52
        """
    )

    rows = CSVNormalizer.normalize(provider="alliant", csv_text=csv_text)

    expected = [
        CanonicalTransaction(
            idx=0,
            id=None,
            description=(
                "WITHDRAWAL ACH AMEX EPAYMENT TYPE: ACH PMT ID: 0005000040 DATA: AM CO: AMEX EPAYMENT NAME: Adam bossy"
            ),
            amount="-4556.29",
            date="2025-01-02",
            merchant=None,
            category=None,
            memo=(
                "WITHDRAWAL ACH AMEX EPAYMENT TYPE: ACH PMT ID: 0005000040 DATA: AM CO: AMEX EPAYMENT NAME: Adam bossy"
                " | Balance=$25708.51"
            ),
        ),
        CanonicalTransaction(
            idx=1,
            id=None,
            description=(
                "WITHDRAWAL ACH VERIZON TYPE: PAYMENTREC ID: 9783397101 CO: VERIZON NAME: ADAMBOSSY"
            ),
            amount="-89.99",
            date="2025-01-06",
            merchant=None,
            category=None,
            memo=(
                "WITHDRAWAL ACH VERIZON TYPE: PAYMENTREC ID: 9783397101 CO: VERIZON NAME: ADAMBOSSY"
                " | Balance=$25618.52"
            ),
        ),
    ]

    assert rows == expected


def test_morgan_stanley_snapshot_to_ctv():
    csv_text = _dedent(
        r"""
        Activity Date,Transaction Date,Account,Institution Name,Activity,Description,Memo,Tags,Amount($)
        08/29/2025,08/29/2025,Platinum CashPlus 101 234882,Morgan Stanley,Direct Deposit,"DIRECT DEP FUNDS RECVD
        Deel PEOVATHC5MB
        PAYMENTS",,,"6,010.67"
        08/29/2025,08/29/2025,AAA 101 209320,Morgan Stanley,Direct Deposit,"DIRECT DEP FUNDS RECVD
        AIRBNB 4977
        AIRBNB",,,"2,942.20"
        """
    )

    rows = CSVNormalizer.normalize(provider="morgan_stanley", csv_text=csv_text)

    expected = [
        CanonicalTransaction(
            idx=0,
            id=None,
            description=("DIRECT DEP FUNDS RECVD\nDeel PEOVATHC5MB\nPAYMENTS"),
            amount="6010.67",
            date="2025-08-29",
            merchant=None,
            category=None,
            memo=(
                "Activity=Direct Deposit"
                " | Account=Platinum CashPlus 101 234882"
                " | Institution Name=Morgan Stanley"
            ),
        ),
        CanonicalTransaction(
            idx=1,
            id=None,
            description=("DIRECT DEP FUNDS RECVD\nAIRBNB 4977\nAIRBNB"),
            amount="2942.20",
            date="2025-08-29",
            merchant=None,
            category=None,
            memo=(
                "Activity=Direct Deposit | Account=AAA 101 209320 | Institution Name=Morgan Stanley"
            ),
        ),
    ]

    assert rows == expected


def test_amazon_orders_snapshot_to_ctv():
    csv_text = _dedent(
        r"""
        order id,order url,items,to,date,total,shipping,shipping_refund,gift,tax,refund,payments
        112-1744040-7220259,https://www.amazon.com/gp/css/order-details?orderID=112-1744040-7220259&ref=ppx_yo2ov_dt_b_fed_order_details,"toolant Impact Torx Bit Set 27pcs (TT7-TT40), S2 Steel Security Torx Bit Set, Tamper Proof Star Bit Set with CNC Machined Tips, 1""&2"" Long Impact Bits with Magnetic Bit Holder and Storage Box; ",Adam Bossy,2025-08-30,11.97,0,,,0.98,,American Express ending in 1008: 2025-08-30: $11.97; 
        112-4509574-9385869,https://www.amazon.com/gp/css/order-details?orderID=112-4509574-9385869&ref=ppx_yo2ov_dt_b_fed_order_details,"Bounty Quick Size Paper Towels, White, 8 Family Rolls = 20 Regular Rolls; ",Adam Bossy,2025-08-29,26.59,0,,,2.17,,American Express ending in 1008: 2025-08-29: $26.59; 
        """
    )

    rows = CSVNormalizer.normalize(provider="amazon_orders", csv_text=csv_text)
    assert len(rows) == 2

    expected_descr0 = 'toolant Impact Torx Bit Set 27pcs (TT7-TT40), S2 Steel Security Torx Bit Set, Tamper Proof Star Bit Set with CNC Machined Tips, 1"&2" Long Impact Bits with Magnetic Bit Holder and Storage Box'

    expected = [
        CanonicalTransaction(
            idx=0,
            id="112-1744040-7220259",
            description=expected_descr0,
            amount="-11.97",
            date="2025-08-30",
            merchant="Amazon.com",
            category=None,
            memo=(
                "order_url=https://www.amazon.com/gp/css/order-details?orderID=112-1744040-7220259&ref=ppx_yo2ov_dt_b_fed_order_details"
                " | payments=American Express ending in 1008: 2025-08-30: $11.97;"
                " | tax=0.98"
            ),
        ),
        CanonicalTransaction(
            idx=1,
            id="112-4509574-9385869",
            description="Bounty Quick Size Paper Towels, White, 8 Family Rolls = 20 Regular Rolls",
            amount="-26.59",
            date="2025-08-29",
            merchant="Amazon.com",
            category=None,
            memo=(
                "order_url=https://www.amazon.com/gp/css/order-details?orderID=112-4509574-9385869&ref=ppx_yo2ov_dt_b_fed_order_details"
                " | payments=American Express ending in 1008: 2025-08-29: $26.59;"
                " | tax=2.17"
            ),
        ),
    ]

    assert rows == expected


def test_venmo_snapshot_to_ctv():
    csv_text = _dedent(
        r"""
        ,ID,Datetime,Type,Status,Note,From,To,Amount (total),Amount (tip),Amount (tax),Amount (fee),Tax Rate,Tax Exempt,Funding Source,Destination,Beginning Balance,Ending Balance,Statement Period Venmo Fees,Terminal Location,Year to Date Venmo Fees,Disclaimer
        ,,,,,,,,,,,,,,,,$186.62,,,,,
        ,4393643203804452439,2025-08-07T01:44:44,Payment,Complete,Couch,Ben Jones,Adam Bossy,+ $375.00,,0,,0,,,Venmo balance,,,,Venmo,,
        ,4397227876707878296,2025-08-12T00:26:51,Payment,Complete,:venmo_dollar: :venmo_dollar: :venmo_dollar: :venmo_dollar:,Adam Bossy,Keela Williams,- $20.00,,0,,0,,Venmo balance,,,,,Venmo,,
        """
    )

    rows = CSVNormalizer.normalize(provider="venmo", csv_text=csv_text)
    assert len(rows) == 2

    expected = [
        CanonicalTransaction(
            idx=0,
            id="4393643203804452439",
            description="Couch",
            amount="375.00",
            date="2025-08-07",
            merchant="Ben Jones",
            category=None,
            memo=("Tax Rate=0 | Destination=Venmo balance"),
        ),
        CanonicalTransaction(
            idx=1,
            id="4397227876707878296",
            description=":venmo_dollar: :venmo_dollar: :venmo_dollar: :venmo_dollar:",
            amount="-20.00",
            date="2025-08-12",
            merchant="Keela Williams",
            category=None,
            memo=("Tax Rate=0 | Funding Source=Venmo balance"),
        ),
    ]

    assert rows == expected
