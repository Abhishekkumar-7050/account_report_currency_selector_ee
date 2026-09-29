{
    'name': 'Business Change Tracker',
    'version': '19.0.1.0.0',
    'summary': 'See what changed, who changed it, when, and the old vs new value — in business terms.',
    'description': """
Business Change Tracker
=======================
Configurable, field-level change history for business documents
(sales, purchases, invoices, contacts, transfers or any other model).
Values are shown in business language (names, labels, dates, amounts),
not technical IDs.
""",
    'author': 'Abhishek Kumar',
    'maintainer': 'Abhishek Kumar',
    'category': 'Productivity',
    'license': 'OPL-1',
    'depends': ['base'],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/ir_cron.xml',
        'views/change_log_views.xml',
        'views/change_rule_views.xml',
        'views/res_config_settings_views.xml',
        'views/menus.xml',
    ],
    'images': ['static/description/banner.png'],
    'post_init_hook': 'post_init_hook',
    'uninstall_hook': 'uninstall_hook',
    'application': True,
    'installable': True,
}
