from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestProductIntelligence(TransactionCase):

    def setUp(self):
        super().setUp()
        self.category = self.env.ref("ti_product_intelligence.ti_category_bearings")
        self.model_attr = self.env.ref("ti_product_intelligence.attr_bearing_model")
        self.partner = self.env["res.partner"].create({"name": "PIS Test Partner"})

    def _standard_bearing_name(self, model, brand=False):
        parts = [self.category.name, model]
        if brand:
            parts.append(brand)
        return " - ".join(parts)

    def _create_governed_bearing(self, model="6007 ZZ", uid="RM-BRG-6007ZZ-900", brand="SKF", vendor_code="SKF-6007"):
        return self.env["product.template"].with_context(ti_allow_product_create=True).create({
            "name": self._standard_bearing_name(model, brand),
            "ti_uid": uid,
            "default_code": uid,
            "ti_governance_state": "approved",
            "ti_category_id": self.category.id,
            "categ_id": self.category.categ_id.id,
            "ti_brand": brand,
            "ti_vendor_code": vendor_code,
            "ti_primary_vendor_id": self.partner.id,
            "ti_spec_line_ids": [(0, 0, {
                "attribute_id": self.model_attr.id,
                "value_char": model,
            })],
        })

    def test_uid_generation_uses_category_and_specs(self):
        uid = self.category.uid_rule_id.generate_uid(
            self.category,
            {self.model_attr.id: "6007 ZZ"},
            brand="SKF",
            vendor=False,
        )
        self.assertIn("RM-BRG", uid)
        self.assertIn("6007ZZ", uid)

    def test_legacy_default_code_is_preserved_as_alias(self):
        product = self.env["product.template"].with_context(ti_allow_product_create=True).create({
            "name": "Legacy Bearing 6007 ZZ",
            "default_code": "OLD-BRG-6007",
            "ti_category_id": self.category.id,
            "categ_id": self.category.categ_id.id,
        })
        self.assertEqual(product.ti_legacy_ref, "OLD-BRG-6007")
        self.assertTrue(product.ti_alias_ids.filtered(lambda alias: alias.name == "OLD-BRG-6007"))

    def test_duplicate_similarity_for_reordered_bearing_name(self):
        product = self.env["product.template"].with_context(ti_allow_product_create=True).create({
            "name": "Bearing 6007 ZZ",
            "ti_category_id": self.category.id,
            "categ_id": self.category.categ_id.id,
            "ti_spec_line_ids": [(0, 0, {
                "attribute_id": self.model_attr.id,
                "value_char": "6007 ZZ",
            })],
        })
        other = self.env["product.template"].with_context(ti_allow_product_create=True).create({
            "name": "6007ZZ Bearing",
            "ti_category_id": self.category.id,
            "categ_id": self.category.categ_id.id,
            "ti_spec_line_ids": [(0, 0, {
                "attribute_id": self.model_attr.id,
                "value_char": "6007ZZ",
            })],
        })
        scores = product.ti_find_duplicate_candidates(limit=10)
        matched = [item for item in scores if item["product"] == other]
        self.assertTrue(matched)
        self.assertGreaterEqual(matched[0]["score"], 60)

    def test_creation_wizard_blocks_duplicate_without_override(self):
        self.env["product.template"].with_context(ti_allow_product_create=True).create({
            "name": "Bearing Deep Groove 6007 ZZ",
            "ti_category_id": self.category.id,
            "categ_id": self.category.categ_id.id,
            "ti_spec_line_ids": [(0, 0, {
                "attribute_id": self.model_attr.id,
                "value_char": "6007 ZZ",
            })],
        })
        wizard = self.env["ti.product.creation.wizard"].create({
            "name": "6007ZZ Bearing",
            "category_id": self.category.id,
            "spec_line_ids": [(0, 0, {
                "attribute_id": self.model_attr.id,
                "value_char": "6007ZZ",
            })],
        })
        wizard.action_check_duplicates()
        self.assertTrue(wizard.duplicate_line_ids)

    def test_wizard_search_finds_uid_alias_specs_and_category(self):
        product = self._create_governed_bearing()
        self.env["ti.product.alias"].create({
            "product_tmpl_id": product.id,
            "alias_type": "vendor_code",
            "name": "ALT-6007",
            "partner_id": self.partner.id,
        })
        wizard = self.env["ti.product.creation.wizard"].create({
            "category_id": self.category.id,
            "search_query": "ALT-6007",
        })
        wizard.action_search_products()
        self.assertIn(product, wizard.search_result_ids.mapped("product_tmpl_id"))
        wizard.search_result_ids[:1].action_select_existing_product()
        self.assertEqual(wizard.selected_product_tmpl_id, product)

    def test_selecting_existing_product_creates_sale_order_line(self):
        product = self._create_governed_bearing(model="6205 ZZ", uid="RM-BRG-6205ZZ-900")
        order = self.env["sale.order"].create({"partner_id": self.partner.id})
        wizard = self.env["ti.product.creation.wizard"].create({
            "source_model": "sale.order",
            "source_res_id": order.id,
            "selected_product_tmpl_id": product.id,
            "line_quantity": 3.0,
            "sale_price_unit": 250.0,
            "sale_discount": 5.0,
            "sale_customer_lead": 2.0,
        })
        wizard._fill_from_product(product)
        wizard.write({
            "line_quantity": 3.0,
            "sale_price_unit": 250.0,
            "sale_discount": 5.0,
            "sale_customer_lead": 2.0,
        })
        wizard.action_apply_to_order()
        line = self.env["sale.order.line"].search([("order_id", "=", order.id)])
        self.assertEqual(len(line), 1)
        self.assertEqual(line.product_id.product_tmpl_id, product)
        self.assertEqual(line.product_uom_qty, 3.0)
        self.assertEqual(line.price_unit, 250.0)
        self.assertEqual(line.discount, 5.0)

    def test_selecting_existing_product_creates_purchase_order_line(self):
        product = self._create_governed_bearing(model="6304 ZZ", uid="RM-BRG-6304ZZ-900")
        order = self.env["purchase.order"].create({"partner_id": self.partner.id})
        wizard = self.env["ti.product.creation.wizard"].create({
            "source_model": "purchase.order",
            "source_res_id": order.id,
            "selected_product_tmpl_id": product.id,
            "line_quantity": 4.0,
            "purchase_price_unit": 150.0,
            "purchase_vendor_id": self.partner.id,
            "purchase_planned_date": "2026-05-20 10:00:00",
        })
        wizard._fill_from_product(product)
        wizard.write({
            "line_quantity": 4.0,
            "purchase_price_unit": 150.0,
            "purchase_vendor_id": self.partner.id,
            "purchase_planned_date": "2026-05-20 10:00:00",
        })
        wizard.action_apply_to_order()
        line = self.env["purchase.order.line"].search([("order_id", "=", order.id)])
        self.assertEqual(len(line), 1)
        self.assertEqual(line.product_id.product_tmpl_id, product)
        self.assertEqual(line.product_qty, 4.0)
        self.assertEqual(line.price_unit, 150.0)

    def test_wizard_create_product_adds_sale_line_and_preview_does_not_consume_uid(self):
        order = self.env["sale.order"].create({"partner_id": self.partner.id})
        sequence = self.category.uid_rule_id.sequence_id
        before = sequence.number_next_actual
        wizard = self.env["ti.product.creation.wizard"].create({
            "source_model": "sale.order",
            "source_res_id": order.id,
            "category_id": self.category.id,
            "brand": "NBC",
            "line_quantity": 2.0,
            "sale_price_unit": 99.0,
            "spec_line_ids": [(0, 0, {
                "attribute_id": self.model_attr.id,
                "value_char": "6901 ZZ",
            })],
        })
        wizard._recompute_preview()
        self.assertEqual(sequence.number_next_actual, before)
        wizard.action_apply_to_order()
        self.assertEqual(sequence.number_next_actual, before + 1)
        line = self.env["sale.order.line"].search([("order_id", "=", order.id)])
        self.assertEqual(len(line), 1)
        self.assertEqual(line.product_id.product_tmpl_id.name, self._standard_bearing_name("6901 ZZ", "NBC"))

    def test_governed_product_name_validation_blocks_random_names(self):
        with self.assertRaises(ValidationError):
            self.env["product.template"].with_context(ti_allow_product_create=True).create({
                "name": "Random Bearing Name",
                "ti_uid": "RM-BRG-BAD-001",
                "default_code": "RM-BRG-BAD-001",
                "ti_governance_state": "approved",
                "ti_category_id": self.category.id,
                "categ_id": self.category.categ_id.id,
                "ti_spec_line_ids": [(0, 0, {
                    "attribute_id": self.model_attr.id,
                    "value_char": "BAD",
                })],
            })

    def test_non_steward_cannot_override_duplicates(self):
        self.env["product.template"].with_context(ti_allow_product_create=True).create({
            "name": "Bearing Deep Groove 6008 ZZ",
            "ti_category_id": self.category.id,
            "categ_id": self.category.categ_id.id,
            "ti_spec_line_ids": [(0, 0, {
                "attribute_id": self.model_attr.id,
                "value_char": "6008 ZZ",
            })],
        })
        user = self.env["res.users"].create({
            "name": "PIS User Only",
            "login": "pis_user_only",
            "email": "pis_user_only@example.com",
            "groups_id": [(6, 0, [
                self.env.ref("base.group_user").id,
                self.env.ref("ti_product_intelligence.group_ti_product_user").id,
            ])],
        })
        wizard = self.env["ti.product.creation.wizard"].with_user(user).create({
            "category_id": self.category.id,
            "brand": "SKF",
            "override_duplicate": True,
            "override_reason": "Need separate product",
            "spec_line_ids": [(0, 0, {
                "attribute_id": self.model_attr.id,
                "value_char": "6008ZZ",
            })],
        })
        with self.assertRaises(AccessError):
            wizard.action_create_product()
