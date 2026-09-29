import logging
import time
from datetime import timedelta

from odoo import fields
from odoo.tests import tagged

from .common import BusinessChangeCommon

_logger = logging.getLogger(__name__)


@tagged('post_install', '-at_install')
class TestOperations(BusinessChangeCommon):

    # T23 -----------------------------------------------------------------
    def test_23_import(self):
        partners = self.env['res.partner'].create([{'name': f'Import {i}', 'phone': f'old-{i}'} for i in range(100)])
        self.env['ir.model.data'].create([
            {'module': '__import__', 'name': f'bct_p{partner.id}', 'model': 'res.partner', 'res_id': partner.id}
            for partner in partners])
        data = [[f'__import__.bct_p{partner.id}', f'new-{i}' if i % 2 == 0 else f'old-{i}']
                for i, partner in enumerate(partners)]
        result = self.env['res.partner'].with_user(self.user_manager).with_context(import_file=True).load(['id', 'phone'], data)
        self.assertFalse(result['messages'], result['messages'])
        logs = self._logs(partners, field_name='phone')
        # only the 50 rows whose value really changed
        self.assertEqual(len(logs), 50)
        by_record = {log.res_id: log for log in logs}
        for i, partner in enumerate(partners):
            if i % 2 == 0:
                self.assertEqual((by_record[partner.id].old_value, by_record[partner.id].new_value),
                                 (f'old-{i}', f'new-{i}'))
                self.assertEqual(by_record[partner.id].user_id, self.user_manager)
            else:
                self.assertNotIn(partner.id, by_record)

    # T24 -----------------------------------------------------------------
    def test_24_automated_action(self):
        if 'base.automation' not in self.env:
            self.skipTest("base_automation not installed")
        action = self.env['ir.actions.server'].create({
            'name': 'Normalize phone',
            'model_id': self.env['ir.model']._get('res.partner').id,
            'state': 'code',
            'code': "for rec in records:\n    if rec.email and rec.email != rec.email.lower():\n        rec.write({'email': rec.email.lower()})",
        })
        self.env['base.automation'].create({
            'name': 'Lower-case emails',
            'model_id': self.env['ir.model']._get('res.partner').id,
            'trigger': 'on_create_or_write',
            'trigger_field_ids': [(6, 0, self.env['ir.model.fields']._get('res.partner', 'email').ids)],
            'action_server_ids': [(6, 0, action.ids)],
        })
        self.partner.with_user(self.user_tracker).email = 'NEW@EXAMPLE.COM'
        logs = self._logs(self.partner, field_name='email')
        self.assertEqual(logs.mapped('new_value'), ['NEW@EXAMPLE.COM', 'new@example.com'])
        # the automation runs in the transaction of the user who triggered it
        self.assertEqual(logs.user_id, self.user_tracker)

    # T25 -----------------------------------------------------------------
    def test_25_scheduled_action(self):
        cron = self.env['ir.cron'].create({
            'name': 'BCT test cron',
            'model_id': self.env['ir.model']._get('res.partner').id,
            'state': 'code',
            'code': "env['res.partner'].browse(%d).write({'phone': 'from-cron'})" % self.partner.id,
            'user_id': self.env.ref('base.user_root').id,
        })
        cron.ir_actions_server_id.with_user(cron.user_id).run()
        log = self._field_log(self.partner, 'phone')
        self.assertEqual(log.new_value, 'from-cron')
        self.assertEqual(log.user_id, self.env.ref('base.user_root'))

    # T33 -----------------------------------------------------------------
    def _make_old_logs(self, days_list):
        now = fields.Datetime.now()
        self.Log._bct_create([{
            'res_model': 'res.partner', 'res_id': self.partner.id, 'record_name': 'ABC Packaging',
            'operation': 'write', 'field_name': 'phone', 'field_label': 'Phone', 'field_type': 'char',
            'old_value_text': 'a', 'new_value_text': f'{days}', 'changed_at': now - timedelta(days=days),
            'company_id': self.company_a.id, 'user_id': self.env.uid,
        } for days in days_list])

    def test_33_retention(self):
        self.patch(type(self.env['ir.cron']), '_commit_progress', lambda self, processed=0, **kw: float('inf'))
        self._make_old_logs([1, 29, 31, 89, 91, 400])
        IrConfig = self.env['ir.config_parameter'].sudo()
        search_ages = lambda: sorted(int(v) for v in self._logs(self.partner).mapped('new_value_text'))  # noqa: E731

        # Forever: nothing is deleted
        IrConfig.set_param('business_change_tracker.retention_days', '0')
        self.Log._cron_retention_cleanup()
        self.assertEqual(search_ages(), [1, 29, 31, 89, 91, 400])

        IrConfig.set_param('business_change_tracker.retention_days', '90')
        self.Log._cron_retention_cleanup()
        self.assertEqual(search_ages(), [1, 29, 31, 89])

        # a too small (tampered) value is clamped to the 30 days minimum
        IrConfig.set_param('business_change_tracker.retention_days', '1')
        self.Log._cron_retention_cleanup()
        self.assertEqual(search_ages(), [1, 29])

        # cleanup itself leaves no trace in the history
        self.assertFalse(self.Log.sudo().search([('res_model', '=', 'business.change.log')]))

    def test_33b_retention_settings(self):
        settings = self.env['res.config.settings'].create({'bct_retention_days': '180'})
        settings.execute()
        self.assertEqual(self.env['ir.config_parameter'].sudo().get_param('business_change_tracker.retention_days'), '180')

    def test_33c_retention_batches(self):
        self.patch(type(self.env['ir.cron']), '_commit_progress', lambda self, processed=0, **kw: float('inf'))
        self._make_old_logs([100] * 25)
        self.env['ir.config_parameter'].sudo().set_param('business_change_tracker.retention_days', '30')
        cutoff = self.Log._bct_get_retention_cutoff()
        self.assertEqual(self.Log._bct_purge_batch(cutoff, batch_size=10), 10)
        self.Log._cron_retention_cleanup()
        self.assertFalse(self._logs(self.partner))

    def test_presets(self):
        created = self.Rule.action_load_presets()
        self.assertGreaterEqual(created, 1)
        rules = self.Rule.search([('model_name', '!=', 'res.partner')])
        self.assertFalse(any(rules.mapped('active')), "suggested rules must be created disabled")
        self.assertEqual(self.Rule.action_load_presets(), 0)

    # T35 -----------------------------------------------------------------
    def test_35_performance(self):
        """ The cost of a tracked write does not grow with the number of records
        (no N+1), and a 10,000 entries history stays fast to query. """
        partners_10 = self.env['res.partner'].create([{'name': f'S{i}'} for i in range(10)])
        partners_200 = self.env['res.partner'].create([{'name': f'L{i}'} for i in range(200)])
        self.env.invalidate_all()
        self.env.flush_all()
        count_before = self.env.cr.sql_log_count
        partners_10.write({'phone': 'x', 'email': 'y@example.com'})
        self.env.flush_all()
        queries_10 = self.env.cr.sql_log_count - count_before
        self.env.invalidate_all()
        count_before = self.env.cr.sql_log_count
        partners_200.write({'phone': 'x', 'email': 'y@example.com'})
        self.env.flush_all()
        queries_200 = self.env.cr.sql_log_count - count_before
        self.assertEqual(len(self._logs(partners_200)), 400)
        self.assertLessEqual(queries_200, queries_10 + 5, "tracked write must be batched")

        # untracked models are not affected at all
        self.env.invalidate_all()
        count_before = self.env.cr.sql_log_count
        self.env['res.partner.category'].create({'name': 'Untracked'}).write({'name': 'Still untracked'})
        self.env.flush_all()
        self.assertLessEqual(self.env.cr.sql_log_count - count_before, 4)

        self._make_old_logs([1] * 10000)
        start = time.time()
        Log = self.Log.with_user(self.user_manager)
        history = Log.search(Log.action_open_history('res.partner', self.partner.ids)['domain'], limit=80)
        history.mapped('new_value')
        total = Log.search_count([])
        elapsed = time.time() - start
        _logger.info("BCT perf: %d logs, record history page + count in %.3fs", total, elapsed)
        self.assertGreaterEqual(total, 10000)
        self.assertLess(elapsed, 5)


@tagged('post_install', '-at_install', '-standard', 'bct_perf')
class TestPerformanceLarge(BusinessChangeCommon):
    """ Opt-in: ``--test-tags bct_perf``. Measures history queries on 100,000 entries. """

    def test_100k(self):
        now = fields.Datetime.now()
        partners = self.env['res.partner'].create([{'name': f'Perf {i}'} for i in range(1000)])
        start = time.time()
        for chunk in range(10):
            self.Log._bct_create([{
                'res_model': 'res.partner', 'res_id': partners[i % 1000].id, 'record_name': 'Perf',
                'operation': 'write', 'field_name': 'phone', 'field_label': 'Phone', 'field_type': 'char',
                'old_value_text': 'a', 'new_value_text': 'b', 'changed_at': now - timedelta(minutes=i),
                'company_id': self.company_a.id, 'user_id': self.env.uid,
            } for i in range(chunk * 10000, (chunk + 1) * 10000)])
            self.env.flush_all()
            self.env.invalidate_all()
        _logger.info("BCT perf: inserted 100,000 logs in %.1fs", time.time() - start)
        self.env.cr.execute("ANALYZE business_change_log")
        Log = self.Log.with_user(self.user_manager)
        timings = {}
        for label, domain in [
            ('record history', Log.action_open_history('res.partner', partners[:1].ids)['domain']),
            ('global list', []),
            ('by user', [('user_id', '=', self.env.uid)]),
            ('by field', [('field_label', 'ilike', 'phone')]),
        ]:
            start = time.time()
            Log.search(domain, limit=80).mapped('new_value')
            Log.search_count(domain)
            timings[label] = time.time() - start
        _logger.info("BCT perf 100k: %s", {k: '%.3fs' % v for k, v in timings.items()})
        self.assertLess(timings['record history'], 1.0)
