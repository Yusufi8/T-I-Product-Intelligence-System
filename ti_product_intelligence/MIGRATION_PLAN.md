# PIS Phased Migration Plan

## Immediate Guardrail

Existing products can be edited normally. New products created by PIS users must go through the governed wizard unless the operation runs with `context={'ti_allow_product_create': True}` for migration/import code.

## Phase 1: Products Used in Last 12 Months

Prioritize products that appear in Purchase Orders, Sales Orders, Bills of Materials, and Manufacturing consumption.

```sql
SELECT DISTINCT pt.id, pt.name, pt.default_code
FROM product_template pt
JOIN product_product pp ON pp.product_tmpl_id = pt.id
LEFT JOIN purchase_order_line pol ON pol.product_id = pp.id
LEFT JOIN sale_order_line sol ON sol.product_id = pp.id
LEFT JOIN mrp_bom_line mbl ON mbl.product_id = pp.id
LEFT JOIN stock_move sm ON sm.product_id = pp.id
WHERE pt.ti_category_id IS NULL
  AND (
    pol.create_date >= now() - interval '12 months'
    OR sol.create_date >= now() - interval '12 months'
    OR mbl.id IS NOT NULL
    OR sm.date >= now() - interval '12 months'
  )
ORDER BY pt.name;
```

## Phase 2: Steward Category Review

Stewards review migrated batches category by category, complete mandatory technical specs, approve generated UIDs, and resolve duplicate logs.

```sql
SELECT tc.name AS category, pt.ti_governance_state, count(*) AS product_count
FROM product_template pt
JOIN ti_product_category tc ON tc.id = pt.ti_category_id
GROUP BY tc.name, pt.ti_governance_state
ORDER BY tc.name, pt.ti_governance_state;
```

## Phase 3: Remaining Products in Batches of 500

Use the Migration Cleanup wizard by category. It preserves existing `default_code` as `ti_legacy_ref`, creates aliases, and generates proposed PIS UIDs where enough category/spec data exists.

```sql
SELECT pt.id, pt.name, pt.default_code, pc.complete_name AS odoo_category
FROM product_template pt
LEFT JOIN product_category pc ON pc.id = pt.categ_id
WHERE pt.active = true
  AND pt.ti_category_id IS NULL
ORDER BY pc.complete_name, pt.name
LIMIT 500;
```

## Daily Duplicate Review

The scheduled action scans 500 governed products per run and skips products that have not changed since their previous scan.

