from decimal import Decimal, ROUND_HALF_UP

LTP = Decimal("109160")
SHARES = Decimal("200000")

# ================================================================
# AUDITED FY2025-26 CONSOLIDATED FIGURES
# ================================================================

TOTAL_ASSETS = Decimal("9999.50")
TOTAL_LIABILITIES = Decimal("1326.05")
ACCOUNTING_NAV = TOTAL_ASSETS - TOTAL_LIABILITIES

NOTE6_GROSS = Decimal("9955.54")
DIMINUTION = Decimal("0.00")
AIF_UNADJUSTED_LOSS = Decimal("0.80")
NOTE6_NET = Decimal("9954.74")

# ================================================================
# NOTE 6 NET INVESTMENT CATEGORIES
# ₹ Cr
# ================================================================

ASIAN_PAINTS = Decimal("8794.14")
OTHER_QUOTED = Decimal("118.58")
UNQUOTED_EQUITY = Decimal("78.84")
CCPS = Decimal("40.51")
MUTUAL_FUNDS = Decimal("757.52")
GOVT_SECURITIES = Decimal("0.49")
CORPORATE_BONDS = Decimal("10.29")
AIF = Decimal("154.36")

CATEGORIES = [
    ("Asian Paints", ASIAN_PAINTS),
    ("Other quoted equity", OTHER_QUOTED),
    ("Unquoted equity", UNQUOTED_EQUITY),
    ("CCPS", CCPS),
    ("Mutual funds", MUTUAL_FUNDS),
    ("Government securities", GOVT_SECURITIES),
    ("Corporate bonds", CORPORATE_BONDS),
    ("AIF", AIF),
]

CATEGORY_TOTAL = sum(v for _, v in CATEGORIES)

# ================================================================
# CATEGORY-SPECIFIC REALIZATION ASSUMPTIONS
#
# These are MODEL ASSUMPTIONS, NOT AUDITED VALUES.
# Each scenario is independently defined.
# ================================================================

SCENARIOS = {
    "BULL": {
        "Asian Paints": Decimal("0.05"),
        "Other quoted equity": Decimal("0.05"),
        "Unquoted equity": Decimal("0.20"),
        "CCPS": Decimal("0.25"),
        "Mutual funds": Decimal("0.02"),
        "Government securities": Decimal("0.01"),
        "Corporate bonds": Decimal("0.05"),
        "AIF": Decimal("0.15"),
        "holding_company": Decimal("0.03"),
        "tax_reserve": Decimal("0.00"),
    },

    "BASE": {
        "Asian Paints": Decimal("0.10"),
        "Other quoted equity": Decimal("0.12"),
        "Unquoted equity": Decimal("0.30"),
        "CCPS": Decimal("0.35"),
        "Mutual funds": Decimal("0.05"),
        "Government securities": Decimal("0.03"),
        "Corporate bonds": Decimal("0.10"),
        "AIF": Decimal("0.25"),
        "holding_company": Decimal("0.03"),
        "tax_reserve": Decimal("0.00"),
    },

    "BEAR": {
        "Asian Paints": Decimal("0.25"),
        "Other quoted equity": Decimal("0.25"),
        "Unquoted equity": Decimal("0.45"),
        "CCPS": Decimal("0.50"),
        "Mutual funds": Decimal("0.12"),
        "Government securities": Decimal("0.05"),
        "Corporate bonds": Decimal("0.20"),
        "AIF": Decimal("0.40"),
        "holding_company": Decimal("0.08"),
        "tax_reserve": Decimal("0.02"),
    },
}


def rs(x):
    return f"₹{x.quantize(Decimal('1'), rounding=ROUND_HALF_UP):,.0f}"


def cr(x):
    return (
        f"₹{x.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):,.2f} Cr"
    )


def pct(x):
    return f"{(x * Decimal('100')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):.2f}%"


def per_share(cr_value):
    return (
        cr_value * Decimal("10000000") / SHARES
    ).quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def realized(value, discount):
    return value * (Decimal("1") - discount)


def upside(value_per_share):
    return ((value_per_share / LTP) - Decimal("1")) * Decimal("100")


def scenario_model(name):
    assumptions = SCENARIOS[name]

    realized_categories = []

    for category, value in CATEGORIES:
        discount = assumptions[category]
        realized_value = realized(value, discount)
        realized_categories.append(
            (category, value, discount, realized_value)
        )

    investment_realization = sum(
        item[3] for item in realized_categories
    )

    # The portfolio is valued against audited net investment value.
    # Difference between category sum and audited net investment value
    # is treated transparently rather than silently ignored.
    reconciliation = NOTE6_NET - CATEGORY_TOTAL

    # Preserve audited net investment anchor.
    adjusted_investment_realization = (
        investment_realization + reconciliation
    )

    # Holding-company realization friction.
    holding_company_reserve = (
        adjusted_investment_realization
        * assumptions["holding_company"]
    )

    after_holding_company = (
        adjusted_investment_realization
        - holding_company_reserve
    )

    # Tax reserve is modelled as a percentage of realizable investment
    # value. This is a conservative modelling reserve, not an audited tax.
    tax_reserve = (
        after_holding_company
        * assumptions["tax_reserve"]
    )

    after_reserves = after_holding_company - tax_reserve

    # Reconcile investment value back to consolidated accounting NAV.
    # Accounting NAV includes the audited investment portfolio and other
    # assets/liabilities. The difference between NAV and investments is
    # therefore retained as the non-investment net asset/liability anchor.
    non_investment_net_assets = ACCOUNTING_NAV - NOTE6_NET

    final_nav = max(
        after_reserves + non_investment_net_assets,
        Decimal("0")
    )

    return {
        "categories": realized_categories,
        "category_total": CATEGORY_TOTAL,
        "reconciliation": reconciliation,
        "investment_realization": investment_realization,
        "adjusted_investment_realization": adjusted_investment_realization,
        "holding_company_reserve": holding_company_reserve,
        "tax_reserve": tax_reserve,
        "final_nav": final_nav,
        "value_per_share": per_share(final_nav),
    }


market_cap = LTP * SHARES / Decimal("10000000")

# ================================================================
# AUDIT CHECKS
# ================================================================

gross_net_adjustment = NOTE6_GROSS - NOTE6_NET
category_reconciliation = NOTE6_NET - CATEGORY_TOTAL
audit_difference = (
    NOTE6_GROSS
    - DIMINUTION
    - AIF_UNADJUSTED_LOSS
    - NOTE6_NET
)

# ================================================================
# OUTPUT
# ================================================================

print("=" * 82)
print("PEREZ AI — ELCID CATEGORY-SPECIFIC SOTP REALIZABLE VALUE ENGINE")
print("=" * 82)

print(f"LTP                         : {rs(LTP)}")
print(f"Shares Outstanding          : {SHARES:,.0f}")
print(f"Market Capitalization       : {cr(market_cap)}")
print()

print("AUDITED FY2025-26 CONSOLIDATED")
print("-" * 82)
print(f"Total Assets                : {cr(TOTAL_ASSETS)}")
print(f"Total Liabilities           : {cr(TOTAL_LIABILITIES)}")
print(f"Accounting Net Assets       : {cr(ACCOUNTING_NAV)}")
print(f"Reported NAV / Share        : {rs(per_share(ACCOUNTING_NAV))}")
print()

print("NOTE 6 AUDITED INVESTMENT ANCHOR")
print("-" * 82)
print(f"Gross Investments           : {cr(NOTE6_GROSS)}")
print(f"Diminution                  : -{cr(DIMINUTION)}")
print(f"AIF Unadjusted Loss         : -{cr(AIF_UNADJUSTED_LOSS)}")
print(f"Net Investment Value        : {cr(NOTE6_NET)}")
print()

print("CATEGORY RECONCILIATION")
print("-" * 82)

for category, value in CATEGORIES:
    print(f"{category:<27}: {cr(value):>16}")

print("-" * 82)
print(f"Category subtotal           : {cr(CATEGORY_TOTAL)}")
print(f"Audited net investment     : {cr(NOTE6_NET)}")
print(f"Category reconciliation     : {cr(category_reconciliation)}")
print()

print("AUDIT INTEGRITY CHECK")
print("-" * 82)
print(f"Gross → Net adjustment      : {cr(gross_net_adjustment)}")
print(f"Expected adjustment         : {cr(DIMINUTION + AIF_UNADJUSTED_LOSS)}")
print(f"Audit difference            : {cr(audit_difference)}")
print(
    "STATUS                      : "
    + ("PASS" if abs(audit_difference) <= Decimal("0.02") else "CHECK")
)
print()

# ================================================================
# SCENARIO TABLE
# ================================================================

results = {}

for scenario in ("BULL", "BASE", "BEAR"):
    results[scenario] = scenario_model(scenario)

print("CATEGORY-SPECIFIC REALIZATION ASSUMPTIONS")
print("-" * 82)

for scenario in ("BULL", "BASE", "BEAR"):
    print(f"\n{scenario}")
    print("-" * 82)

    for category, value in CATEGORIES:
        discount = SCENARIOS[scenario][category]
        print(
            f"{category:<27}: discount={pct(discount):>7}  "
            f"realizable={cr(realized(value, discount))}"
        )

    print(
        f"{'Holding-company reserve':<27}: "
        f"{pct(SCENARIOS[scenario]['holding_company'])}"
    )

    print(
        f"{'Tax reserve':<27}: "
        f"{pct(SCENARIOS[scenario]['tax_reserve'])}"
    )

print()
print("REALIZABLE NAV SCENARIOS")
print("-" * 82)

for scenario in ("BULL", "BASE", "BEAR"):
    result = results[scenario]
    value = result["value_per_share"]

    print(
        f"{scenario + ' NAV':<27}: "
        f"{cr(result['final_nav'])}"
    )
    print(
        f"{scenario + ' value / share':<27}: "
        f"{rs(value)}"
    )
    print(
        f"{scenario + ' upside vs LTP':<27}: "
        f"{upside(value):.2f}%"
    )
    print()

print("VALUATION GAP")
print("-" * 82)

reported_per_share = per_share(ACCOUNTING_NAV)

print(
    f"Market Price / Reported NAV  : "
    f"{(LTP / reported_per_share * Decimal('100')):.2f}%"
)

print(
    f"Discount to Reported NAV     : "
    f"{((1 - LTP / reported_per_share) * Decimal('100')):.2f}%"
)

print(
    f"NAV Premium vs Market Price  : "
    f"{((reported_per_share / LTP - 1) * Decimal('100')):.2f}%"
)

print()
print("MODEL SAFETY / AUDIT FLAGS")
print("-" * 82)
print("• Audited FY2025-26 figures are preserved.")
print("• Note 6 gross and net investment values are explicitly separated.")
print("• AIF is explicitly included.")
print("• Category-specific Bull/Base/Bear discounts are model assumptions.")
print("• Holding-company reserve is explicit.")
print("• Bear case includes an explicit tax reserve.")
print("• No hidden reconciliation remainder is used.")
print("• No trading signal is generated.")
print("• No order logic is connected to this module.")
print("• MODE                       : READ ONLY")
print("• ORDERS ENABLED             : FALSE")
print()
print("CLASSIFICATION             : HIDDEN VALUE — CATEGORY SOTP")
print("MODE                       : READ ONLY")
print("ORDERS ENABLED             : FALSE")
print("=" * 82)
