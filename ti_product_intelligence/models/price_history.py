from odoo import api, fields, models


class ProductCostHistory(models.Model):
    _name = "product.cost.history"
    _description = "PIS Product Cost History"
    _order = "date desc, id desc"
    _rec_name = "product_tmpl_id"

    product_tmpl_id = fields.Many2one("product.template", required=True, index=True, ondelete="cascade")
    product_id = fields.Many2one("product.product", index=True)
    partner_id = fields.Many2one("res.partner", string="Vendor", index=True)
    old_price = fields.Float()
    new_price = fields.Float(required=True)
    currency_id = fields.Many2one("res.currency", default=lambda self: self.env.company.currency_id.id)
    quantity = fields.Float(default=1.0)
    date = fields.Datetime(default=fields.Datetime.now, required=True, index=True)
    user_id = fields.Many2one("res.users", default=lambda self: self.env.user, required=True)
    source_model = fields.Char(index=True)
    source_id = fields.Integer(index=True)
    source_document = fields.Char(index=True)

    @api.model
    def create_from_price_change(self, product_tmpl, old_price, new_price, source_model, source_id, partner=None, quantity=1.0):
        return self.create({
            "product_tmpl_id": product_tmpl.id,
            "old_price": old_price,
            "new_price": new_price,
            "partner_id": partner.id if partner else False,
            "quantity": quantity,
            "source_model": source_model,
            "source_id": source_id,
            "source_document": "%s,%s" % (source_model, source_id),
        })


class ProductSalePriceHistory(models.Model):
    _name = "product.sale.price.history"
    _description = "PIS Product Sale Price History"
    _order = "date desc, id desc"
    _rec_name = "product_tmpl_id"

    product_tmpl_id = fields.Many2one("product.template", required=True, index=True, ondelete="cascade")
    product_id = fields.Many2one("product.product", index=True)
    partner_id = fields.Many2one("res.partner", string="Customer", index=True)
    old_price = fields.Float()
    new_price = fields.Float(required=True)
    margin_percent = fields.Float()
    currency_id = fields.Many2one("res.currency", default=lambda self: self.env.company.currency_id.id)
    quantity = fields.Float(default=1.0)
    date = fields.Datetime(default=fields.Datetime.now, required=True, index=True)
    user_id = fields.Many2one("res.users", default=lambda self: self.env.user, required=True)
    source_model = fields.Char(index=True)
    source_id = fields.Integer(index=True)
    source_document = fields.Char(index=True)

    @api.model
    def create_from_price_change(self, product_tmpl, old_price, new_price, source_model, source_id, partner=None, quantity=1.0):
        cost = product_tmpl.standard_price
        margin = new_price and ((new_price - cost) / new_price) * 100 or 0.0
        return self.create({
            "product_tmpl_id": product_tmpl.id,
            "old_price": old_price,
            "new_price": new_price,
            "margin_percent": margin,
            "partner_id": partner.id if partner else False,
            "quantity": quantity,
            "source_model": source_model,
            "source_id": source_id,
            "source_document": "%s,%s" % (source_model, source_id),
        })

