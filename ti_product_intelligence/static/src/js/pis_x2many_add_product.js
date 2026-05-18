/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";
import { ListRenderer } from "@web/views/list/list_renderer";

patch(ListRenderer.prototype, "ti_product_intelligence.pis_x2many_add_product", {
    setup() {
        this._super(...arguments);
        this.pisAction = useService("action");
        this.pisOrm = useService("orm");
    },

    async add(params = {}) {
        const context = params.context || {};
        if (!context.pis_open_product_wizard) {
            return this._super(...arguments);
        }

        const parentModel = context.pis_parent_model;
        if (!["sale.order", "purchase.order"].includes(parentModel)) {
            return this._super(...arguments);
        }

        const root = this.props.list.model.root;
        const listContext = this.props.list.context || {};
        const parentId = (root && root.resId) || listContext.active_id || context.active_id;
        if (!parentId || typeof parentId !== "number") {
            this.notificationService.add(_t("Save the order before adding governed products."), {
                type: "warning",
            });
            return;
        }

        const action = await this.pisOrm.call(
            parentModel,
            "action_open_pis_product_line_wizard",
            [[parentId]],
            { context }
        );
        return this.pisAction.doAction(action, {
            onClose: async () => {
                if (root && root.load) {
                    await root.load();
                    if (root.model && root.model.notify) {
                        root.model.notify();
                    }
                } else if (this.props.list.model.notify) {
                    this.props.list.model.notify();
                }
            },
        });
    },
});
