from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from .common import BusinessChangeCommon


@tagged('post_install', '-at_install')
class TestSecurity(BusinessChangeCommon):

    def setUp(self):
        super().setUp()
        self.partner.phone = '222'
        self.log = self._field_log(self.partner, 'phone')

    # T29 / T30 ------------------------------------------------------------
    def test_29_user_access(self):
        Log = self.Log.with_user(self.user_tracker)
        self.assertEqual(Log.search([('res_id', '=', self.partner.id), ('operation', '=', 'write')]), self.log)
        self.assertEqual(self.log.with_user(self.user_tracker).new_value, '222')
        with self.assertRaises(AccessError):
            self.env['business.change.rule'].with_user(self.user_tracker).create(
                {'model_id': self.env['ir.model']._get('res.partner').id})
        with self.assertRaises(AccessError):
            self.partner_rule.with_user(self.user_tracker).active = False

    def test_29b_user_without_group(self):
        with self.assertRaises(AccessError):
            self.Log.with_user(self.user_plain).search([])
        with self.assertRaises(AccessError):
            self.log.with_user(self.user_plain).read(['new_value'])

    def test_30_manager_access(self):
        rule = self.partner_rule.with_user(self.user_manager)
        rule.active = False
        rule.active = True
        self.assertTrue(rule.action_id.binding_model_id)
        # managers also see deleted records' history
        partner = self.env['res.partner'].create({'name': 'Deleted Co'})
        partner_id = partner.id
        partner.unlink()
        dom = [('res_model', '=', 'res.partner'), ('res_id', '=', partner_id)]
        self.assertEqual(len(self.Log.with_user(self.user_manager).search(dom)), 2)  # create + unlink
        self.assertFalse(self.Log.with_user(self.user_tracker).search(dom))

    # T31 --------------------------------------------------------------------
    def test_31_restricted_field(self):
        """ A value of a field protected by groups is not revealed through history. """
        field = self.env['res.partner']._fields['phone']
        self.patch(field, 'groups', 'base.group_system')
        log = self.log.with_user(self.user_tracker)
        log.invalidate_recordset(['old_value', 'new_value', 'is_restricted'])
        self.assertEqual((log.old_value, log.new_value), ('Restricted', 'Restricted'))
        self.assertTrue(log.is_restricted)
        admin_log = self.log.with_user(self.env.ref('base.user_admin'))
        self.assertEqual(admin_log.new_value, '222')

    # T28 --------------------------------------------------------------------
    def test_28_multi_company(self):
        partner_b = self.env['res.partner'].create({'name': 'Company B Customer', 'company_id': self.company_b.id})
        partner_b.phone = '999'
        log_b = self._field_log(partner_b, 'phone')
        self.assertEqual(log_b.company_id, self.company_b)
        self.assertFalse(self.Log.with_user(self.user_tracker).search([('id', '=', log_b.id)]))
        with self.assertRaises(AccessError):
            log_b.with_user(self.user_tracker).read(['new_value'])
        # a manager allowed on both companies sees it once the company is active
        Log = self.Log.with_user(self.user_manager).with_context(allowed_company_ids=(self.company_a | self.company_b).ids)
        self.assertEqual(Log.search([('id', '=', log_b.id)]), log_b)
        # shared records (no company) are visible from every company
        shared = self.env['res.partner'].create({'name': 'Shared', 'company_id': False})
        shared.phone = '1'
        self.assertTrue(self.Log.with_user(self.user_tracker).search(
            [('res_id', '=', shared.id), ('field_name', '=', 'phone')]))

    # T37 --------------------------------------------------------------------
    def test_37_immutability(self):
        with self.assertRaises(AccessError):
            self.log.with_user(self.user_manager).write({'new_value_text': 'forged'})
        with self.assertRaises(AccessError):
            self.log.with_user(self.user_manager).unlink()
        with self.assertRaises(UserError):
            self.log.sudo().write({'new_value_text': 'forged'})
        with self.assertRaises(UserError):
            self.log.sudo().write({'user_id': self.user_plain.id, 'changed_at': '2020-01-01'})
        with self.assertRaises(UserError):
            self.log.sudo().unlink()
        with self.assertRaises(UserError):
            self.Log.sudo().create({'res_model': 'res.partner', 'operation': 'write', 'changed_at': '2020-01-01'})
        with self.assertRaises(AccessError):
            self.Log.with_user(self.user_manager).create({'res_model': 'res.partner', 'operation': 'write'})
        # retention flag without superuser is still refused
        with self.assertRaises(AccessError):
            self.log.with_user(self.user_manager).with_context(bct_retention_cleanup=True).unlink()
        self.assertEqual(self.log.new_value, '222')

    # T32 --------------------------------------------------------------------
    def test_32_deleted_model_or_field(self):
        """ Logs keep their snapshot labels when the field definition disappears. """
        self.assertEqual(self.log.field_label, 'Phone')
        # simulate a field removed by a module uninstall
        self.env.cr.execute("UPDATE business_change_log SET field_id = NULL, field_name = 'x_removed' WHERE id = %s",
                            [self.log.id])
        self.log.invalidate_recordset()
        log = self.log.with_user(self.user_manager)
        self.assertEqual(log.field_label, 'Phone')
        self.assertEqual(log.new_value, '222')

    def test_archived_user(self):
        self.partner.with_user(self.user_manager).email = 'archived@example.com'
        self.user_manager.active = False
        log = self._field_log(self.partner, 'email')
        self.assertEqual(log.user_id, self.user_manager)
        self.assertEqual(log.user_name, 'John Smith')
        self.assertEqual(log.new_value, 'archived@example.com')
