from odoo.tests import new_test_user, tagged

from .common import BusinessChangeCommon


@tagged('post_install', '-at_install')
class TestBusinessModels(BusinessChangeCommon):
    """ The V1 business documents. Each test is skipped when its app is not installed. """

    def _require(self, *models):
        missing = [m for m in models if m not in self.env]
        if missing:
            self.skipTest("Requires models %s" % ', '.join(missing))

    def _sale_setup(self):
        self._require('sale.order')
        self._create_rule('sale.order', ['partner_id', 'user_id', 'commitment_date', 'payment_term_id', 'state'])
        self._create_rule('sale.order.line', ['product_uom_qty', 'price_unit', 'discount'],
                          parent_field_id=self.env['ir.model.fields']._get('sale.order.line', 'order_id').id)
        product = self.env['product.product'].create({'name': 'Carton Box', 'list_price': 5.0})
        order = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'order_line': [(0, 0, {'product_id': product.id, 'product_uom_qty': 1000, 'price_unit': 5.0})],
        })
        return order

    def test_sale_order_price_quantity_date(self):
        """ The product example: Unit Price $5.00 → $4.50, Quantity 1,000 → 800, delivery date. """
        order = self._sale_setup()
        line = order.order_line
        salesman = new_test_user(self.env, login='bct_salesman', name='John Salesman',
                                 groups='sales_team.group_sale_salesman_all_leads')
        line.with_user(salesman).write({'price_unit': 4.5})
        line.with_user(salesman).write({'product_uom_qty': 800})
        order.with_user(salesman).commitment_date = '2026-10-20 08:00:00'

        history = self.Log.sudo().search(self.Log.action_open_history('sale.order', order.ids)['domain'])
        price = history.filtered(lambda l: l.field_name == 'price_unit')
        currency = order.currency_id
        self.assertEqual(price.currency_id, currency)
        self.assertIn('5.00', price.old_value)
        self.assertIn('4.50', price.new_value)
        self.assertIn(currency.symbol, price.new_value)
        self.assertEqual(price.user_id, salesman)
        self.assertEqual(price.parent_name, order.name)

        qty = history.filtered(lambda l: l.field_name == 'product_uom_qty')
        self.assertEqual((qty.old_value, qty.new_value), ('1,000.00', '800.00'))

        date = history.filtered(lambda l: l.field_name == 'commitment_date')
        self.assertEqual(date.old_value, '—')
        self.assertEqual(date.new_value_raw, '2026-10-20 08:00:00')
        # T17: datetime rendered in the viewer's timezone
        self.assertEqual(date.with_context(tz='Asia/Kolkata', lang='en_US').new_value, '10/20/2026 01:30:00 PM')
        self.assertEqual(date.with_context(tz='UTC', lang='en_US').new_value, '10/20/2026 08:00:00 AM')

    def test_sale_selection_and_many2one(self):
        order = self._sale_setup()
        new_customer = self.env['res.partner'].create({'name': 'XYZ Corp'})
        order.partner_id = new_customer
        order.action_confirm()
        logs = self._logs(order)
        customer = logs.filtered(lambda l: l.field_name == 'partner_id')
        self.assertEqual((customer.old_value, customer.new_value), ('ABC Packaging', 'XYZ Corp'))
        state = logs.filtered(lambda l: l.field_name == 'state')
        self.assertEqual((state.old_value, state.new_value), ('Quotation', 'Sales Order'))

    def test_sale_line_deletion_visible_on_order(self):
        order = self._sale_setup()
        line_name = order.order_line.display_name
        order.write({'order_line': [(2, order.order_line.id)]})
        history = self.Log.sudo().search(self.Log.action_open_history('sale.order', order.ids)['domain'])
        deletion = history.filtered(lambda l: l.operation == 'unlink')
        self.assertEqual(deletion.record_name, line_name)
        self.assertEqual(deletion.parent_res_id, order.id)

    def test_sale_recomputed_field(self):
        """ Changing the customer recomputes the payment terms: the silent reset is logged. """
        order = self._sale_setup()
        term_30 = self.env.ref('account.account_payment_term_30days')
        term_now = self.env.ref('account.account_payment_term_immediate')
        order.payment_term_id = term_30
        customer = self.env['res.partner'].create({'name': 'XYZ Corp', 'property_payment_term_id': term_now.id})
        order.partner_id = customer
        self.assertEqual(order.payment_term_id, term_now)
        log = self._logs(order, field_name='payment_term_id')[-1]
        self.assertEqual((log.old_value, log.new_value), ('30 Days', 'Immediate Payment'))

    def test_sale_record_rules(self):
        """ T29: a salesman restricted to his own orders cannot see other orders' history. """
        order = self._sale_setup()
        own_user = new_test_user(self.env, login='bct_own', name='Own Docs',
                                 groups='sales_team.group_sale_salesman,business_change_tracker.group_business_change_user')
        order.user_id = self.user_manager
        order.order_line.price_unit = 4.0
        Log = self.Log.with_user(own_user)
        self.assertFalse(Log.search([('res_model', 'in', ('sale.order', 'sale.order.line'))]))
        order.user_id = own_user
        self.env.invalidate_all()
        visible = Log.search([('res_model', 'in', ('sale.order', 'sale.order.line'))])
        self.assertIn('price_unit', visible.mapped('field_name'))

    def test_monetary_field(self):
        """ T15: a real Monetary field uses its own currency field. """
        self._require('account.payment')
        self._create_rule('account.payment', ['amount'])
        journal = self.env['account.journal'].search([('type', '=', 'bank'), ('company_id', '=', self.company_a.id)], limit=1)
        if not journal:
            self.skipTest("No bank journal (chart of accounts not installed)")
        payment = self.env['account.payment'].create({
            'amount': 100.0, 'payment_type': 'inbound', 'partner_id': self.partner.id, 'journal_id': journal.id,
        })
        payment.amount = 120.0
        log = self._field_log(payment, 'amount')
        self.assertEqual(log.currency_id, payment.currency_id)
        self.assertIn('100.00', log.old_value)
        self.assertIn('120.00', log.new_value)
        self.assertIn(payment.currency_id.symbol, log.new_value)

    def test_invoice_date(self):
        """ T16: date fields use the user's date format. """
        self._require('account.move')
        self._create_rule('account.move', ['invoice_date', 'ref'])
        move = self.env['account.move'].create({'move_type': 'out_invoice', 'partner_id': self.partner.id})
        move.invoice_date = '2026-10-10'
        move.invoice_date = '2026-10-20'
        logs = self._logs(move, field_name='invoice_date')
        self.assertEqual(logs[1].with_context(lang='en_US').old_value, '10/10/2026')
        self.assertEqual(logs[1].with_context(lang='en_US').new_value, '10/20/2026')

    def test_purchase_vendor_price(self):
        self._require('purchase.order')
        self._create_rule('purchase.order', ['partner_id'])
        self._create_rule('purchase.order.line', ['price_unit'],
                          parent_field_id=self.env['ir.model.fields']._get('purchase.order.line', 'order_id').id)
        vendor = self.env['res.partner'].create({'name': 'Vendor Two'})
        product = self.env['product.product'].create({'name': 'Raw Paper'})
        po = self.env['purchase.order'].create({
            'partner_id': self.partner.id,
            'order_line': [(0, 0, {'product_id': product.id, 'product_qty': 10, 'price_unit': 2.0})],
        })
        po.partner_id = vendor
        po.order_line.price_unit = 1.8
        history = self.Log.sudo().search(self.Log.action_open_history('purchase.order', po.ids)['domain'])
        self.assertEqual(history.filtered(lambda l: l.field_name == 'partner_id').new_value, 'Vendor Two')
        self.assertIn('1.80', history.filtered(lambda l: l.field_name == 'price_unit').new_value)

    def test_stock_picking(self):
        self._require('stock.picking')
        self._create_rule('stock.picking', ['origin', 'scheduled_date'])
        picking_type = self.env['stock.picking.type'].search([('code', '=', 'outgoing')], limit=1)
        picking = self.env['stock.picking'].create({'picking_type_id': picking_type.id, 'origin': 'SO001'})
        picking.origin = 'SO002'
        log = self._field_log(picking, 'origin')
        self.assertEqual((log.old_value, log.new_value), ('SO001', 'SO002'))
        self.assertEqual(log.company_id, picking.company_id)
