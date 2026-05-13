from odoo import fields, models, tools


class TiMissingSpecReport(models.Model):
    _name = "ti.missing.spec.report"
    _description = "PIS Missing Mandatory Specification Report"
    _auto = False

    product_tmpl_id = fields.Many2one("product.template", string="Product", readonly=True)
    category_id = fields.Many2one("ti.product.category", string="PIS Category", readonly=True)
    attribute_id = fields.Many2one("ti.product.attribute", string="Missing Specification", readonly=True)
    missing_count = fields.Integer(readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %s AS (
                SELECT
                    row_number() OVER () AS id,
                    pt.id AS product_tmpl_id,
                    tc.id AS category_id,
                    ta.id AS attribute_id,
                    1 AS missing_count
                FROM product_template pt
                JOIN ti_product_category tc ON pt.ti_category_id = tc.id
                JOIN ti_product_attribute ta ON ta.category_id = tc.id AND ta.mandatory = true
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM ti_product_spec_line tsl
                    WHERE tsl.product_tmpl_id = pt.id
                      AND tsl.attribute_id = ta.id
                      AND coalesce(tsl.display_value, '') != ''
                )
            )
        """ % self._table)


class ProductSlowMoveReport(models.Model):
    _name = "product.slow.move.report"
    _description = "PIS Slow-Moving Inventory Report"
    _auto = False

    product_tmpl_id = fields.Many2one("product.template", string="Product", readonly=True)
    product_id = fields.Many2one("product.product", string="Variant", readonly=True)
    ti_category_id = fields.Many2one("ti.product.category", string="PIS Category", readonly=True)
    qty_available = fields.Float(readonly=True)
    last_move_date = fields.Datetime(readonly=True)
    slow_count = fields.Integer(readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %s AS (
                SELECT
                    pp.id AS id,
                    pt.id AS product_tmpl_id,
                    pp.id AS product_id,
                    pt.ti_category_id AS ti_category_id,
                    coalesce(sq.qty_available, 0) AS qty_available,
                    sm.last_move_date AS last_move_date,
                    1 AS slow_count
                FROM product_product pp
                JOIN product_template pt ON pp.product_tmpl_id = pt.id
                LEFT JOIN (
                    SELECT product_id, sum(quantity) AS qty_available
                    FROM stock_quant
                    GROUP BY product_id
                ) sq ON sq.product_id = pp.id
                LEFT JOIN (
                    SELECT product_id, max(date) AS last_move_date
                    FROM stock_move
                    WHERE state = 'done'
                    GROUP BY product_id
                ) sm ON sm.product_id = pp.id
                WHERE pt.active = true
                  AND pt.ti_category_id IS NOT NULL
                  AND (sm.last_move_date IS NULL OR sm.last_move_date < (now() - interval '90 days'))
            )
        """ % self._table)


class TiBomUsageReport(models.Model):
    _name = "ti.bom.usage.report"
    _description = "PIS BOM Usage Report"
    _auto = False

    product_tmpl_id = fields.Many2one("product.template", string="Component Product", readonly=True)
    ti_category_id = fields.Many2one("ti.product.category", string="PIS Category", readonly=True)
    bom_id = fields.Many2one("mrp.bom", string="BOM", readonly=True)
    usage_count = fields.Integer(readonly=True)
    consumed_qty = fields.Float(readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %s AS (
                SELECT
                    min(mbl.id) AS id,
                    pt.id AS product_tmpl_id,
                    pt.ti_category_id AS ti_category_id,
                    mbl.bom_id AS bom_id,
                    count(mbl.id) AS usage_count,
                    sum(mbl.product_qty) AS consumed_qty
                FROM mrp_bom_line mbl
                JOIN product_product pp ON mbl.product_id = pp.id
                JOIN product_template pt ON pp.product_tmpl_id = pt.id
                GROUP BY pt.id, pt.ti_category_id, mbl.bom_id
            )
        """ % self._table)

