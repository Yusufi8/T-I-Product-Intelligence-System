from odoo import _, api, fields, models


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

    def action_open_pis_product_wizard(self):
        return self.env["ti.product.creation.wizard"].action_open_from_context(source_model="purchase.order.line")


class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    def action_open_pis_product_wizard(self):
        return self.env["ti.product.creation.wizard"].action_open_from_context(source_model="sale.order.line")


class MrpBomLine(models.Model):
    _inherit = "mrp.bom.line"

    ti_governance_state = fields.Selection(related="product_tmpl_id.ti_governance_state", string="PIS State", store=False)
    ti_uid = fields.Char(related="product_tmpl_id.ti_uid", string="PIS UID", store=False)


class StockMove(models.Model):
    _inherit = "stock.move"

    ti_uid = fields.Char(related="product_id.product_tmpl_id.ti_uid", string="PIS UID", store=False)
    ti_category_id = fields.Many2one(related="product_id.product_tmpl_id.ti_category_id", string="PIS Category", store=False)

