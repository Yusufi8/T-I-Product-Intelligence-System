from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestProductIntelligence(TransactionCase):

    def setUp(self):
        super().setUp()
        self.category = self.env.ref("ti_product_intelligence.ti_category_bearings")
        self.model_attr = self.env.ref("ti_product_intelligence.attr_bearing_model")

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
