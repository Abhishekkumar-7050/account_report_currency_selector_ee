from odoo.tests import TransactionCase, new_test_user


class BusinessChangeCommon(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Log = cls.env['business.change.log']
        cls.Rule = cls.env['business.change.rule'].with_context(active_test=False)
        # presets may exist from the post-init hook: tests define their own rules
        cls.Rule.search([]).unlink()

        cls.company_a = cls.env.company
        cls.company_b = cls.env['res.company'].create({'name': 'BCT Company B'})

        cls.user_tracker = new_test_user(
            cls.env, login='bct_user', name='Sarah Jones',
            groups='base.group_user,base.group_partner_manager,business_change_tracker.group_business_change_user',
            company_id=cls.company_a.id, company_ids=[(6, 0, cls.company_a.ids)])
        cls.user_manager = new_test_user(
            cls.env, login='bct_manager', name='John Smith',
            groups='base.group_user,base.group_partner_manager,business_change_tracker.group_business_change_manager',
            company_id=cls.company_a.id, company_ids=[(6, 0, (cls.company_a | cls.company_b).ids)])
        cls.user_plain = new_test_user(
            cls.env, login='bct_plain', name='Plain Employee',
            groups='base.group_user,base.group_partner_manager')

        cls.partner_rule = cls._create_rule('res.partner', [
            'name', 'email', 'phone', 'comment', 'color', 'partner_latitude',
            'type', 'is_company', 'category_id', 'parent_id', 'user_id', 'lang',
        ])
        cls.tag_vip = cls.env['res.partner.category'].create({'name': 'VIP Customer'})
        cls.tag_old = cls.env['res.partner.category'].create({'name': 'Old Customer'})
        cls.partner = cls.env['res.partner'].create({
            'name': 'ABC Packaging', 'email': 'abc@example.com', 'phone': '111',
            'company_id': cls.company_a.id,
        })

    @classmethod
    def _create_rule(cls, model_name, fnames, **kwargs):
        model = cls.env['ir.model']._get(model_name)
        fields_ = cls.env['ir.model.fields'].search([('model_id', '=', model.id), ('name', 'in', fnames)])
        return cls.Rule.create({'model_id': model.id, 'field_ids': [(6, 0, fields_.ids)], **kwargs})

    def _logs(self, record, operation='write', **domain):
        dom = [('res_model', '=', record._name), ('res_id', 'in', record.ids), ('operation', '=', operation)]
        dom += [(key, '=', value) for key, value in domain.items()]
        return self.Log.sudo().search(dom, order='id')

    def _field_log(self, record, fname):
        logs = self._logs(record, field_name=fname)
        self.assertEqual(len(logs), 1, "expected exactly one log for %s" % fname)
        return logs
