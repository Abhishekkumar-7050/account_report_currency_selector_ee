from odoo.exceptions import ValidationError
from odoo.tests import Form, tagged

from .common import BusinessChangeCommon


@tagged('post_install', '-at_install')
class TestChangeTracking(BusinessChangeCommon):

    # T01 -------------------------------------------------------------
    def test_01_installation(self):
        module = self.env['ir.module.module'].search([('name', '=', 'business_change_tracker')])
        self.assertEqual(module.state, 'installed')
        self.assertTrue(self.env.ref('business_change_tracker.group_business_change_manager'))
        self.assertTrue(self.env.ref('business_change_tracker.ir_cron_retention_cleanup'))

    # T04 -------------------------------------------------------------
    def test_04_rule_creation(self):
        self.assertEqual(self.partner_rule.name, 'Contact')
        self.assertEqual(len(self.partner_rule.field_ids), 12)
        action = self.partner_rule.action_id
        self.assertEqual(action.binding_model_id.model, 'res.partner')
        self.assertIn("'res.partner'", action.code)
        config = self.Rule._get_tracking_map()['res.partner']
        self.assertEqual(set(config['fields']), set(self.partner_rule.field_ids.mapped('name')))

    def test_04b_invalid_rules(self):
        log_model = self.env['ir.model']._get('business.change.log')
        with self.assertRaises(ValidationError):
            self.Rule.create({'model_id': log_model.id})
        wizard_model = self.env['ir.model']._get('res.config.settings')
        with self.assertRaises(ValidationError):
            self.Rule.create({'model_id': wizard_model.id})
        # field of another model
        user_field = self.env['ir.model.fields']._get('res.users', 'login')
        with self.assertRaises(ValidationError):
            self.partner_rule.field_ids = [(4, user_field.id)]
        # non stored field
        display = self.env['ir.model.fields']._get('res.partner', 'display_name')
        with self.assertRaises(ValidationError):
            self.partner_rule.field_ids = [(4, display.id)]
        # one2many
        children = self.env['ir.model.fields']._get('res.partner', 'child_ids')
        with self.assertRaises(ValidationError):
            self.partner_rule.field_ids = [(4, children.id)]

    # T05 -------------------------------------------------------------
    def test_05_enable_disable(self):
        self.partner_rule.active = False
        self.assertFalse(self.partner_rule.action_id.binding_model_id)
        self.partner.phone = '222'
        self.assertFalse(self._logs(self.partner))
        self.partner_rule.active = True
        self.assertTrue(self.partner_rule.action_id.binding_model_id)
        self.partner.phone = '333'
        log = self._field_log(self.partner, 'phone')
        self.assertEqual((log.old_value, log.new_value), ('222', '333'))

    # T06 / T07 / T08 / T09 / T34 --------------------------------------
    def test_06_tracked_field(self):
        self.partner.with_user(self.user_tracker).write({'phone': '999'})
        log = self._field_log(self.partner, 'phone')
        self.assertRecordValues(log, [{
            'operation': 'write', 'field_label': 'Phone', 'field_type': 'char',
            'old_value': '111', 'new_value': '999', 'user_id': self.user_tracker.id,
            'user_name': 'Sarah Jones', 'record_name': 'ABC Packaging',
            'company_id': self.company_a.id, 'res_model': 'res.partner', 'res_id': self.partner.id,
        }])
        self.assertTrue(log.changed_at)

    def test_07_untracked_field(self):
        self.partner.write({'street': 'Main Street 1', 'city': 'Brussels'})
        self.assertFalse(self._logs(self.partner))

    def test_08_same_value_write(self):
        self.partner.write({'phone': '111', 'email': 'abc@example.com', 'name': 'ABC Packaging'})
        self.assertFalse(self._logs(self.partner))

    def test_09_multiple_fields(self):
        self.partner.write({'phone': '222', 'email': 'new@example.com', 'street': 'Ignored'})
        logs = self._logs(self.partner)
        self.assertEqual(sorted(logs.mapped('field_name')), ['email', 'phone'])
        self.assertEqual(logs.filtered(lambda l: l.field_name == 'email').new_value, 'new@example.com')

    def test_34_no_duplicates(self):
        self.partner.phone = '222'
        self.partner.phone = '222'
        self.partner.write({'phone': '222'})
        self.assertEqual(len(self._logs(self.partner)), 1)

    # T10 - T18: field types and human readable values (T40) ----------
    def test_10_many2one(self):
        parent_1 = self.env['res.partner'].create({'name': 'Parent One', 'is_company': True})
        parent_2 = self.env['res.partner'].create({'name': 'Parent Two', 'is_company': True})
        self.partner.parent_id = parent_1
        self.partner.parent_id = parent_2
        self.partner.parent_id = False
        logs = self._logs(self.partner, field_name='parent_id')
        self.assertEqual(logs.mapped('old_value'), ['—', 'Parent One', 'Parent Two'])
        self.assertEqual(logs.mapped('new_value'), ['Parent One', 'Parent Two', '—'])
        self.assertEqual(logs[0].new_value_raw, parent_1.id)

    def test_11_selection(self):
        self.partner.type = 'invoice'
        log = self._field_log(self.partner, 'type')
        self.assertEqual((log.old_value, log.new_value), ('Contact', 'Invoice'))
        self.assertEqual((log.old_value_raw, log.new_value_raw), ('contact', 'invoice'))

    def test_12_boolean(self):
        self.partner.is_company = True
        log = self._field_log(self.partner, 'is_company')
        self.assertEqual((log.old_value, log.new_value), ('No', 'Yes'))

    def test_13_integer(self):
        self.partner.color = 1000
        self.partner.color = 800
        logs = self._logs(self.partner, field_name='color')
        self.assertEqual(logs.mapped('old_value'), ['0', '1,000'])
        self.assertEqual(logs.mapped('new_value'), ['1,000', '800'])

    def test_14_float(self):
        self.partner.partner_latitude = 50.8503
        log = self._field_log(self.partner, 'partner_latitude')
        # partner_latitude has digits (10, 7): the declared precision is kept
        self.assertEqual(log.new_value, '50.8503000')
        self.assertEqual(log.new_value_raw, 50.8503)

    def test_14b_float_precision_noop(self):
        # a difference below the field precision is not a business change
        self.partner.partner_latitude = 1.0
        self.partner.partner_latitude = 1.00000001
        self.assertEqual(len(self._logs(self.partner, field_name='partner_latitude')), 1)

    def test_16_html_text_is_plain(self):
        self.partner.comment = '<p>Hello <script>alert(1)</script><b>World</b></p>'
        log = self._field_log(self.partner, 'comment')
        self.assertNotIn('<', log.new_value)
        self.assertIn('Hello', log.new_value)
        self.assertIn('World', log.new_value)

    def test_16b_huge_text_truncated(self):
        self.partner.name = 'X' * 50000
        log = self._field_log(self.partner, 'name')
        self.assertEqual(len(log.new_value), 2001)
        self.assertTrue(log.new_value.endswith('…'))

    def test_18_many2many(self):
        self.partner.category_id = self.tag_old
        self.partner.category_id = [(3, self.tag_old.id), (4, self.tag_vip.id)]
        logs = self._logs(self.partner, field_name='category_id')
        self.assertEqual(len(logs), 2)
        self.assertEqual(logs[0].new_value, 'Added: Old Customer')
        self.assertEqual(logs[1].old_value, 'Old Customer')
        self.assertEqual(logs[1].new_value, 'Added: VIP Customer\nRemoved: Old Customer')
        self.assertEqual(logs[1].new_value_raw, [self.tag_vip.id])

    def test_18b_many2many_same_value(self):
        self.partner.category_id = self.tag_vip
        self.partner.category_id = [(6, 0, self.tag_vip.ids)]
        self.assertEqual(len(self._logs(self.partner, field_name='category_id')), 1)

    def test_18c_deleted_many2one_target(self):
        tag = self.env['res.partner.category'].create({'name': 'Temporary'})
        self.partner.category_id = tag
        tag.unlink()
        log = self._field_log(self.partner, 'category_id')
        # the name was captured at change time and survives the target deletion
        self.assertEqual(log.new_value, 'Added: Temporary')

    def test_19_one2many(self):
        """ One2many fields are not tracked themselves: the child model needs its own
        rule, and its changes are listed on the parent through 'Show Changes On'. """
        self.partner_rule.parent_field_id = self.env['ir.model.fields']._get('res.partner', 'parent_id')
        self.partner.write({'is_company': True, 'child_ids': [(0, 0, {'name': 'Child Contact'})]})
        child = self.partner.child_ids
        child.phone = '555'
        history = self.Log.search(self.Log.action_open_history('res.partner', self.partner.ids)['domain'])
        self.assertIn(child.display_name, history.mapped('record_name'))
        child_log = history.filtered(lambda l: l.res_id == child.id and l.field_name == 'phone')
        self.assertEqual(child_log.parent_name, 'ABC Packaging')
        self.assertEqual(child_log.new_value, '555')

    def test_40_lang_rendering(self):
        """ Dates / numbers follow the viewer's language; captured names do not change. """
        self.env['res.lang']._activate_lang('fr_FR')
        self.partner.color = 1000
        log = self._field_log(self.partner, 'color')
        self.assertIn(log.with_context(lang='fr_FR').new_value, ('1\u202f000', '1\xa0000'))
        self.assertEqual(log.with_context(lang='en_US').new_value, '1,000')

    # T20 / T21 / T32 ----------------------------------------------------
    def test_20_create_event(self):
        partner = self.env['res.partner'].with_user(self.user_tracker).create({'name': 'New Customer'})
        log = self._logs(partner, operation='create')
        self.assertRecordValues(log, [{'record_name': 'New Customer', 'user_id': self.user_tracker.id,
                                        'field_name': False}])
        self.partner_rule.track_create = False
        partner_2 = self.env['res.partner'].create({'name': 'Silent'})
        self.assertFalse(self._logs(partner_2, operation='create'))

    def test_21_delete_event(self):
        partner = self.env['res.partner'].create({'name': 'To Delete'})
        partner_id = partner.id
        partner.unlink()
        log = self.Log.sudo().search([('res_model', '=', 'res.partner'), ('res_id', '=', partner_id),
                                      ('operation', '=', 'unlink')])
        self.assertEqual(log.record_name, 'To Delete')
        self.assertFalse(log.record_exists)

    # T22 -----------------------------------------------------------------
    def test_22_multi_record_write(self):
        partners = self.env['res.partner'].create([{'name': f'P{i}', 'phone': str(i)} for i in range(5)])
        partners.write({'phone': '3'})  # P3 already has '3'
        logs = self._logs(partners)
        self.assertEqual(len(logs), 4)
        by_record = {log.res_id: log for log in logs}
        self.assertNotIn(partners[3].id, by_record)
        for i, partner in enumerate(partners):
            if i != 3:
                self.assertEqual(by_record[partner.id].old_value, str(i))
                self.assertEqual(by_record[partner.id].new_value, '3')
                self.assertEqual(by_record[partner.id].record_name, f'P{i}')

    # T26 -----------------------------------------------------------------
    def test_26_sudo_keeps_real_user(self):
        self.partner.with_user(self.user_tracker).sudo().write({'phone': '777'})
        self.assertEqual(self._field_log(self.partner, 'phone').user_id, self.user_tracker)

    def test_26b_no_track_context(self):
        self.partner.with_context(bct_no_track=True).phone = '000'
        self.assertFalse(self._logs(self.partner))

    # T27 -----------------------------------------------------------------
    def test_27_rollback(self):
        with self.assertRaises(ValueError), self.env.cr.savepoint():
            self.partner.phone = '666'
            self.assertTrue(self._logs(self.partner))
            raise ValueError("business error")
        self.env.invalidate_all()
        self.assertEqual(self.partner.phone, '111')
        self.assertFalse(self._logs(self.partner))

    # T36 -----------------------------------------------------------------
    def test_36_no_recursion(self):
        """ The tracker never logs its own records nor technical models. """
        self.partner.phone = '888'
        self.assertFalse(self.Log.sudo().search([('res_model', 'like', 'business.change.%')]))
        self.assertFalse(self.Log.sudo().search([('res_model', 'like', 'ir.%')]))
        self.partner_rule.write({'track_unlink': False})
        self.assertFalse(self.Log.sudo().search([('res_model', '=', 'business.change.rule')]))

    # T38 / T39 -------------------------------------------------------------
    def test_38_navigation(self):
        self.partner.phone = '222'
        log = self._field_log(self.partner, 'phone')
        action = log.with_user(self.user_manager).action_open_record()
        self.assertEqual((action['res_model'], action['res_id']), ('res.partner', self.partner.id))
        partner = self.env['res.partner'].create({'name': 'Gone'})
        partner.phone = '1'
        gone_log = self._field_log(partner, 'phone')
        partner.unlink()
        with self.assertRaisesRegex(Exception, 'Record no longer exists'):
            gone_log.with_user(self.user_manager).action_open_record()

    def test_39_search_and_filter(self):
        self.partner.with_user(self.user_tracker).phone = '222'
        self.partner.with_user(self.user_manager).email = 'x@example.com'
        Log = self.Log.with_user(self.user_manager)
        base = [('res_model', '=', 'res.partner'), ('res_id', '=', self.partner.id)]
        self.assertEqual(Log.search(base + [('user_id', '=', self.user_tracker.id)]).field_name, 'phone')
        self.assertEqual(Log.search(base + [('field_label', 'ilike', 'mail')]).field_name, 'email')
        self.assertEqual(Log.search(base + [('new_value_text', 'ilike', 'x@example')]).field_name, 'email')
        self.assertEqual(len(Log.search(base + [('operation', '=', 'write')])), 2)
        groups = Log._read_group(base + [('operation', '=', 'write')], ['user_id'], ['__count'])
        self.assertEqual({user.id: count for user, count in groups},
                         {self.user_tracker.id: 1, self.user_manager.id: 1})

    def test_form_ui_write(self):
        """ A form save (web client path) produces the same history. """
        with Form(self.partner.with_user(self.user_tracker)) as form:
            form.phone = '123'
            form.email = 'abc@example.com'  # unchanged
        log = self._field_log(self.partner, 'phone')
        self.assertEqual((log.old_value, log.new_value), ('111', '123'))
        self.assertFalse(self._logs(self.partner, field_name='email'))
