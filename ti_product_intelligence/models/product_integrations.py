from odoo import _, api, fields, models


def _line_product_info(line, product):
    template = product.product_tmpl_id if product else line.env["product.template"]
    seller = template.seller_ids[:1]
    return {
        "ti_info_uid": template.ti_uid,
        "ti_info_specs": template.ti_spec_summary,
        "ti_info_vendor": template.ti_primary_vendor_id.name or (seller.partner_id.name if seller else False),
        "ti_info_cost": template.ti_latest_cost_price,
        "ti_info_margin": template.ti_margin_percent,
        "ti_info_stock": product.qty_available if product else 0.0,
        "ti_info_gov_state": template.ti_governance_state,
        "ti_info_lead_time": seller.delay if seller else 0,
    }


class PurchaseOrder(models.Model):
    _inherit = "purchase.order"

    def button_confirm(self):
        result = super().button_confirm()
        for order in self:
            for line in order.order_line.filtered("product_id"):
                product = line.product_id.product_tmpl_id
                self.env["product.cost.history"].sudo().create_from_price_change(
                    product,
                    product.standard_price,
                    line.price_unit,
                    "purchase.order",
                    order.id,
                    partner=order.partner_id,
                    quantity=line.product_qty,
                )
        return result


class SaleOrder(models.Model):
    _inherit = "sale.order"

    def action_confirm(self):
        result = super().action_confirm()
        for order in self:
            for line in order.order_line.filtered("product_id"):
                product = line.product_id.product_tmpl_id
                self.env["product.sale.price.history"].sudo().create_from_price_change(
                    product,
                    product.list_price,
                    line.price_unit,
                    "sale.order",
                    order.id,
                    partner=order.partner_id,
                    quantity=line.product_uom_qty,
                )
        return result


class PurchaseOrderLine(models.Model):
    _inherit = "purchase.order.line"

    ti_info_uid = fields.Char(compute="_compute_ti_product_info")
    ti_info_specs = fields.Char(compute="_compute_ti_product_info")
    ti_info_vendor = fields.Char(compute="_compute_ti_product_info")
    ti_info_cost = fields.Float(compute="_compute_ti_product_info", groups="ti_product_intelligence.group_ti_price_cost,ti_product_intelligence.group_ti_product_manager")
    ti_info_margin = fields.Float(compute="_compute_ti_product_info", groups="ti_product_intelligence.group_ti_price_sale,ti_product_intelligence.group_ti_product_manager")
    ti_info_stock = fields.Float(compute="_compute_ti_product_info")
    ti_info_gov_state = fields.Selection(related="product_id.product_tmpl_id.ti_governance_state", string="PIS State")
    ti_info_lead_time = fields.Integer(compute="_compute_ti_product_info")

    @api.depends("product_id", "product_id.product_tmpl_id.ti_spec_summary")
    def _compute_ti_product_info(self):
        for line in self:
            values = _line_product_info(line, line.product_id)
            for field, value in values.items():
                if field != "ti_info_gov_state":
                    setattr(line, field, value)

    def action_open_pis_product_wizard(self):
        category = False
        sibling_categories = self.order_id.order_line.filtered("product_id").mapped("product_id.product_tmpl_id.ti_category_id")
        if len(sibling_categories) == 1:
            category = sibling_categories.id
        return self.env["ti.product.creation.wizard"].with_context(default_category_id=category).action_open_from_context(source_model="purchase.order.line")


class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    ti_info_uid = fields.Char(compute="_compute_ti_product_info")
    ti_info_specs = fields.Char(compute="_compute_ti_product_info")
    ti_info_vendor = fields.Char(compute="_compute_ti_product_info")
    ti_info_cost = fields.Float(compute="_compute_ti_product_info", groups="ti_product_intelligence.group_ti_price_cost,ti_product_intelligence.group_ti_product_manager")
    ti_info_margin = fields.Float(compute="_compute_ti_product_info", groups="ti_product_intelligence.group_ti_price_sale,ti_product_intelligence.group_ti_product_manager")
    ti_info_stock = fields.Float(compute="_compute_ti_product_info")
    ti_info_gov_state = fields.Selection(related="product_id.product_tmpl_id.ti_governance_state", string="PIS State")
    ti_info_lead_time = fields.Integer(compute="_compute_ti_product_info")

    @api.depends("product_id", "product_id.product_tmpl_id.ti_spec_summary")
    def _compute_ti_product_info(self):
        for line in self:
            values = _line_product_info(line, line.product_id)
            for field, value in values.items():
                if field != "ti_info_gov_state":
                    setattr(line, field, value)

    def action_open_pis_product_wizard(self):
        category = False
        sibling_categories = self.order_id.order_line.filtered("product_id").mapped("product_id.product_tmpl_id.ti_category_id")
        if len(sibling_categories) == 1:
            category = sibling_categories.id
        return self.env["ti.product.creation.wizard"].with_context(default_category_id=category).action_open_from_context(source_model="sale.order.line")


class StockPicking(models.Model):
    _inherit = "stock.picking"

    def action_open_pis_product_wizard(self):
        return self.env["ti.product.creation.wizard"].action_open_from_context(source_model="stock.picking")


class StockQuant(models.Model):
    _inherit = "stock.quant"

    def action_open_pis_product_wizard(self):
        return self.env["ti.product.creation.wizard"].action_open_from_context(source_model="stock.quant")


class MrpProduction(models.Model):
    _inherit = "mrp.production"

    def action_open_pis_product_wizard(self):
        return self.env["ti.product.creation.wizard"].action_open_from_context(source_model="mrp.production")


class MrpBomLine(models.Model):
    _inherit = "mrp.bom.line"

    ti_governance_state = fields.Selection(related="product_tmpl_id.ti_governance_state", string="PIS State", store=False)
    ti_uid = fields.Char(related="product_tmpl_id.ti_uid", string="PIS UID", store=False)

    def action_open_pis_product_wizard(self):
        return self.env["ti.product.creation.wizard"].action_open_from_context(source_model="mrp.bom.line")


class StockMove(models.Model):
    _inherit = "stock.move"

    ti_uid = fields.Char(related="product_id.product_tmpl_id.ti_uid", string="PIS UID", store=False)
    ti_category_id = fields.Many2one(related="product_id.product_tmpl_id.ti_category_id", string="PIS Category", store=False)

    def action_open_pis_product_wizard(self):
        return self.env["ti.product.creation.wizard"].action_open_from_context(source_model="stock.move")
