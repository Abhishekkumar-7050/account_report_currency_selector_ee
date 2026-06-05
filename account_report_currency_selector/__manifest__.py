{
    'name': 'Account Report Currency Selector',
    'version': '19.0.1.0',
    'summary': 'Adds a selector to display financial reports in any active currency.',
    'description': """
        This module extends the Odoo 19 financial reports (like Balance Sheet)
        to include a dropdown menu of all active currencies.
        When a currency is selected, the report values are recalculated
        based on the exchange rate of that currency.
    """,
    'author': 'Abhishek Kumar',
    'maintainer': 'Abhishek Kumar',
    'company': 'Abhicode Technologies',
    'category': 'Accounting/Reporting',
    'currency': 'USD',
    'price': 10,
    'web_icon': 'account_report_currency_selector,static/src/img/icon.png',
    'depends': [
        'account_reports', 'account'
    ],
    'data': [
    ],
    'images': [
    'static/description/multi-currency-button.png', 
    ],
    'assets': {
        'web.assets_backend': [
            'account_report_currency_selector/static/src/js/account_report_client_action.js',
            'account_report_currency_selector/static/src/xml/report.xml',
        ],
    },
    'installable': True,
    'license': 'OPL-1',

}
