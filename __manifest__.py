{
    'name': "Aronia",
    'description': "ARONIA",
    'summary': "",
    'author': 'ARONIA',
    'category': 'base',
    'version': '1.0',
    'description': """
        This module introduces custom features for Aronia
    """,
    'author': 'ARONIA',
    'website': 'http://www.aronia.com',
    'category': '',
    'depends': ['base','product'],
    'data': [
        'views/product_product_prestashop.xml',
        'views/view_product_prestashop_number.xml',
        'views/view_product_template_prestashop.xml',
        'views/order.xml',
        'security/ir.model.access.csv',
        'data/cron.xml',
        'data/fetch.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}
