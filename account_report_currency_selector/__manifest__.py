{
    'name': 'Account Report Currency Selector',
    "version": "16.0.1.0.0",
    'summary': 'Adds a selector to display financial reports in any active currency.',
    'description': """
        This module extends the Odoo 16 financial reports (like Balance Sheet)
        to include a dropdown menu of all active currencies.
        When a currency is selected, the report values are recalculated
        based on the exchange rate of that currency.
    """,
    'author': 'Abhishek Kumar',
    'maintainer': 'Abhishek Kumar',
    'company': 'Codetrade India Private Limited',
    'category': 'Accounting/Reporting',
    'currency': 'USD',
    'price': 15,
    'depends': [
        'account_reports', 'account'
    ],
    'data': [
        'views/search_template_currency.xml',
    ],
    'images': ['static/description/multi-currency-button.png'],
    'installable': True,
    'license': 'OPL-1',
}
