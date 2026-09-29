# Suggested rules for common business documents. They are created *disabled*:
# nothing is tracked until an administrator reviews and enables them.
PRESETS = {
    'sale.order': (['partner_id', 'user_id', 'commitment_date', 'payment_term_id', 'pricelist_id', 'state'], None),
    'sale.order.line': (['product_id', 'product_uom_qty', 'price_unit', 'discount', 'product_uom_id'], 'order_id'),
    'purchase.order': (['partner_id', 'date_planned', 'payment_term_id', 'currency_id', 'state'], None),
    'purchase.order.line': (['product_id', 'product_qty', 'price_unit', 'date_planned'], 'order_id'),
    'account.move': (['partner_id', 'invoice_date', 'invoice_date_due', 'invoice_payment_term_id', 'ref', 'state'], None),
    'res.partner': (['name', 'email', 'phone', 'vat', 'street', 'city', 'country_id', 'category_id', 'user_id'], None),
    'stock.picking': (['partner_id', 'scheduled_date', 'origin', 'location_dest_id', 'state'], None),
}


def post_init_hook(env):
    env['business.change.rule']._bct_create_presets(PRESETS)


def uninstall_hook(env):
    # The "Change History" actions are created per rule (no XML id), so the
    # module data cleanup would not remove them and they would point to a
    # model that no longer exists.
    rules = env['business.change.rule'].with_context(active_test=False).search([])
    rules.action_id.unlink()
