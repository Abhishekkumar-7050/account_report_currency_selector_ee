import { AccountReportFilters } from "@account_reports/components/account_report/filters/filters";
import { patch } from "@web/core/utils/patch";

patch(AccountReportFilters.prototype, {
    get selectedCustomCurrencyName() {
        const options = this.controller.cachedFilterOptions();
        const selected = (options.available_currencies || []).find((c) => c.id === options.custom_currency_id);
        return selected ? selected.name : "Currency";
    },

    selectCustomCurrency(currencyId) {
        this.filterClicked({ optionKey: "custom_currency_id", optionValue: currencyId, reload: true });
    },
});
