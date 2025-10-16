from odoo import models, fields, api
from odoo.exceptions import UserError
import requests
from datetime import datetime, timedelta
import json
import xml.etree.ElementTree as ET
import logging
_logger = logging.getLogger(__name__)


class ProductTemplate(models.Model):
    _inherit = "product.template"

    id_prestashop = fields.Integer(
        string='PrestaShop Product ID',
        help='Automatically filled after export to PrestaShop',
        copy=False,
        readonly=True
    )

    def _get_or_create_prestashop_manufacturer(self, manufacturer_name):
        """Get or create PrestaShop manufacturer by name"""
        if not manufacturer_name:
            return 0

        try:
            # Search for existing manufacturer
            response = requests.get(
                "https://outletna.com/api/manufacturers",
                auth=("86TN4NX1QDTBJC2XS9HUHL9RI53ANB3N", ""),
                params={'filter[name]': manufacturer_name, 'display': 'full'},
                timeout=30
            )

            if response.status_code == 200:
                import xml.etree.ElementTree as ET
                root = ET.fromstring(response.content)

                # Check if manufacturer exists
                for manufacturer in root.findall('.//manufacturer'):
                    name_elem = manufacturer.find('name')
                    manuf_id = manufacturer.find('id')
                    if name_elem is not None and manuf_id is not None and name_elem.text == manufacturer_name:
                        return int(manuf_id.text)

            # Create manufacturer if not found
            return self._create_prestashop_manufacturer(manufacturer_name)

        except Exception as e:
            _logger.error(f"Error getting manufacturer {manufacturer_name}: {str(e)}")
            return 0

    def _create_prestashop_manufacturer(self, manufacturer_name):
        """Create a new manufacturer in PrestaShop"""
        xml_data = f"""<?xml version="1.0" encoding="UTF-8"?>
<prestashop xmlns:xlink="http://www.w3.org/1999/xlink">
  <manufacturer>
    <active><![CDATA[1]]></active>
    <name><![CDATA[{manufacturer_name}]]></name>
  </manufacturer>
</prestashop>"""

        try:
            response = requests.post(
                "https://outletna.com/api/manufacturers",
                auth=("86TN4NX1QDTBJC2XS9HUHL9RI53ANB3N", ""),
                headers={"Content-Type": "application/xml"},
                data=xml_data.encode('utf-8'),
                timeout=30
            )

            if response.status_code in [200, 201]:
                import xml.etree.ElementTree as ET
                root = ET.fromstring(response.content)
                manufacturer_id = root.find('.//manufacturer/id')
                if manufacturer_id is not None:
                    _logger.info(f"✅ Manufacturer '{manufacturer_name}' created with ID: {manufacturer_id.text}")
                    return int(manufacturer_id.text)
            else:
                _logger.error(f"Failed to create manufacturer: {response.text}")
                return 0
        except Exception as e:
            _logger.error(f"Error creating manufacturer: {str(e)}")
            return 0

    def _get_or_create_prestashop_category(self, category_name, parent_id=2):
        """Get or create PrestaShop category by name"""
        try:
            # Search for existing category
            response = requests.get(
                "https://outletna.com/api/categories",
                auth=("86TN4NX1QDTBJC2XS9HUHL9RI53ANB3N", ""),
                params={'filter[name]': category_name, 'display': 'full'},
                timeout=30
            )

            if response.status_code == 200:
                import xml.etree.ElementTree as ET
                root = ET.fromstring(response.content)

                # Check if category exists in results
                for category in root.findall('.//category'):
                    name_elem = category.find('.//name/language')
                    cat_id = category.find('id')
                    if name_elem is not None and cat_id is not None and name_elem.text == category_name:
                        return int(cat_id.text)

            # Create category if not found
            return self._create_prestashop_category(category_name, parent_id)

        except Exception as e:
            _logger.error(f"Error getting category {category_name}: {str(e)}")
            return None

    def _create_prestashop_category(self, category_name, parent_id=2):
        """Create a new category in PrestaShop"""
        # Generate link_rewrite from category name
        link_rewrite = category_name.lower().replace(' ', '-').replace('/', '-')

        xml_data = f"""<?xml version="1.0" encoding="UTF-8"?>
<prestashop xmlns:xlink="http://www.w3.org/1999/xlink">
  <category>
    <id_parent><![CDATA[{parent_id}]]></id_parent>
    <active><![CDATA[1]]></active>
    <name>
      <language id="1"><![CDATA[{category_name}]]></language>
    </name>
    <link_rewrite>
      <language id="1"><![CDATA[{link_rewrite}]]></language>
    </link_rewrite>
    <description>
      <language id="1"><![CDATA[{category_name}]]></language>
    </description>
  </category>
</prestashop>"""

        try:
            response = requests.post(
                "https://outletna.com/api/categories",
                auth=("86TN4NX1QDTBJC2XS9HUHL9RI53ANB3N", ""),
                headers={"Content-Type": "application/xml"},
                data=xml_data.encode('utf-8'),
                timeout=30
            )

            if response.status_code in [200, 201]:
                import xml.etree.ElementTree as ET
                root = ET.fromstring(response.content)
                category_id = root.find('.//category/id')
                if category_id is not None:
                    _logger.info(f"✅ Category '{category_name}' created with ID: {category_id.text}")
                    return int(category_id.text)
            else:
                _logger.error(f"Failed to create category: {response.text}")
                return None
        except Exception as e:
            _logger.error(f"Error creating category: {str(e)}")
            return None

    def _get_product_categories(self):
        """Get all categories from Odoo product (including parent hierarchy)"""
        category_ids = []

        if not self.categ_id:
            return [2]  # Default to Home category

        # Get main category
        main_category = self.categ_id
        ps_category_id = self._get_or_create_prestashop_category(main_category.name)
        if ps_category_id:
            category_ids.append(ps_category_id)

        # Get parent categories (hierarchy)
        current_category = main_category.parent_id
        while current_category and current_category.name not in ['All', 'All / Saleable']:
            ps_cat_id = self._get_or_create_prestashop_category(current_category.name)
            if ps_cat_id and ps_cat_id not in category_ids:
                category_ids.append(ps_cat_id)
            current_category = current_category.parent_id

        # Always include Home category (ID 2)
        if 2 not in category_ids:
            category_ids.append(2)

        return category_ids

    def action_export_to_prestashop(self):
        """Export only products not yet exported (id_prestashop = 0)"""
        if not self:
            raise UserError("No product selected.")

        exported_count = 0
        skipped_count = 0
        exported_products = []

        for product in self:
            if product.id_prestashop and product.id_prestashop != 0:
                skipped_count += 1
                _logger.info(f"⏩ Skipped: {product.name} (already exported with ID {product.id_prestashop})")
                continue

            if not product.x_studio_item_id:
                _logger.warning(f"⚠️ Skipped: {product.name} (missing reference x_studio_item_id)")
                continue

            _logger.info(f"🚀 Exporting product: {product.name} | Reference: {product.x_studio_item_id}")

            # Get manufacturer ID
            manufacturer_id = 0
            if product.x_studio_marque:
                manufacturer_id = product._get_or_create_prestashop_manufacturer(product.x_studio_marque)

            # Get categories
            category_ids = product._get_product_categories()
            default_category = category_ids[0] if category_ids else 2

            # Build categories XML
            categories_xml = '\n            '.join([
                f'<category><id><![CDATA[{cat_id}]]></id></category>'
                for cat_id in category_ids
            ])

            # Manufacturer XML
            if manufacturer_id > 0:
                manufacturer_xml = f'<id_manufacturer xlink:href="https://outletna.com/api/manufacturers/{manufacturer_id}"><![CDATA[{manufacturer_id}]]></id_manufacturer>'
            else:
                manufacturer_xml = '<id_manufacturer><![CDATA[0]]></id_manufacturer>'

            ean_value = product.barcode or ''
            link_rewrite = product.name.lower().replace(' ', '-')

            # XML Product Data
            xml_data = f"""<?xml version="1.0" encoding="UTF-8"?>
    <prestashop xmlns:xlink="http://www.w3.org/1999/xlink">
      <product>
        <id_category_default><![CDATA[{default_category}]]></id_category_default>
        {manufacturer_xml}
        <active><![CDATA[1]]></active>
        <reference><![CDATA[{product.x_studio_item_id}]]></reference>
        <ean13><![CDATA[{ean_value}]]></ean13>
        <price><![CDATA[{product.list_price:.2f}]]></price>
        <minimal_quantity><![CDATA[1]]></minimal_quantity>
        <available_for_order><![CDATA[1]]></available_for_order>
        <show_price><![CDATA[1]]></show_price>
        <condition><![CDATA[new]]></condition>
        <name>
          <language id="1"><![CDATA[{product.name}]]></language>
        </name>
        <link_rewrite>
          <language id="1"><![CDATA[{link_rewrite}]]></language>
        </link_rewrite>
        <description_short>
          <language id="1"><![CDATA[{product.description_sale or ''}]]></language>
        </description_short>
        <description>
          <language id="1"><![CDATA[{product.description_sale or ''}]]></language>
        </description>
        <associations>
          <categories>
            {categories_xml}
          </categories>
        </associations>
      </product>
    </prestashop>"""

            try:
                response = requests.post(
                    "https://outletna.com/api/products",
                    auth=("86TN4NX1QDTBJC2XS9HUHL9RI53ANB3N", ""),
                    headers={"Content-Type": "application/xml"},
                    data=xml_data.encode('utf-8'),
                    timeout=30
                )

                if response.status_code in [200, 201]:
                    root = ET.fromstring(response.content)
                    prestashop_id = root.find('.//product/id')
                    if prestashop_id is not None:
                        product.id_prestashop = int(prestashop_id.text)

                    exported_count += 1
                    exported_products.append(product.name)
                    _logger.info(f"✅ Exported: {product.name} (New ID: {product.id_prestashop})")

                    category_names = []
                    if product.categ_id:
                        current = product.categ_id
                        while current and current.name not in ['All', 'All / Saleable']:
                            category_names.append(current.name)
                            current = current.parent_id

                    categories_display = ' > '.join(reversed(category_names)) if category_names else 'Home'
                    manufacturer_display = f"<br/>Manufacturer: {product.x_studio_marque}" if product.x_studio_marque else ""

                    product.message_post(
                        body=f"✅ Product exported to PrestaShop successfully!<br/>"
                             f"Product ID: {product.id_prestashop}<br/>"
                             f"Reference: {product.x_studio_item_id}<br/>"
                             f"Categories: {categories_display}{manufacturer_display}"
                    )

                else:
                    _logger.error(f"❌ Error for {product.name}: {response.status_code} - {response.text}")
                    continue

            except Exception as e:
                _logger.error(f"⚠️ Exception during export for {product.name}: {e}", exc_info=True)
                continue

        _logger.info(f"🎯 Export completed: {exported_count} products exported, {skipped_count} skipped.")
        _logger.info(f"🧾 Exported product names: {', '.join(exported_products)}")

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Export Completed',
                'message': f'{exported_count} products exported successfully. {skipped_count} skipped.',
                'type': 'success' if exported_count else 'warning',
                'sticky': False,
            }
        }

    def cron_export_new_products_to_prestashop(self):
        """
        Cron job method: Export products with id_prestashop = 0 or False
        Runs every 5 minutes to automatically sync new products
        """
        _logger.info("CRON: Starting automatic PrestaShop export")
        try:
            # Find products that need to be exported
            products_to_export = self.search([
                '|',
                ('id_prestashop', '=', False),
                ('id_prestashop', '=', 0),
                ('x_studio_item_id', '!=', False),  # Must have reference
            ])
            if not products_to_export:
                _logger.info("✅ CRON: No new products to export")
                return
            _logger.info(f"📦 CRON: Found {len(products_to_export)} product(s) to export")
            products_to_export.action_export_to_prestashop()
            _logger.info("✅ CRON: Export completed successfully")

        except Exception as e:
            _logger.error(f"❌CRON ERROR: {str(e)}")

class ProductProductPrest(models.Model):
    _inherit = "product.product"

    id_prestashop_variant = fields.Integer(
        string='PrestaShop Combination ID',
        help='Stores the PrestaShop variant ID after export',
        copy=False,
        readonly=True
    )

    def _get_prestashop_attribute_id(self, attribute_name):
        """Get or create PrestaShop attribute ID by name (Color, Size, etc.)"""
        try:
            # Search for existing attribute
            response = requests.get(
                "https://outletna.com/api/product_options",
                auth=("86TN4NX1QDTBJC2XS9HUHL9RI53ANB3N", ""),
                params={'filter[name]': attribute_name, 'display': 'full'},
                timeout=30
            )

            if response.status_code == 200:
                import xml.etree.ElementTree as ET
                root = ET.fromstring(response.content)
                attribute_id = root.find('.//product_option/id')
                if attribute_id is not None:
                    return int(attribute_id.text)

            return None
        except Exception as e:
            raise UserError(f"Error getting attribute {attribute_name}: {str(e)}")

    def _get_or_create_prestashop_attribute_value(self, attribute_id, value_name):
        """Get or create PrestaShop attribute value ID"""
        try:
            # Search for existing value
            response = requests.get(
                "https://outletna.com/api/product_option_values",
                auth=("86TN4NX1QDTBJC2XS9HUHL9RI53ANB3N", ""),
                params={'filter[id_attribute_group]': attribute_id, 'display': 'full'},
                timeout=30
            )

            if response.status_code == 200:
                import xml.etree.ElementTree as ET
                root = ET.fromstring(response.content)

                # Check if value exists
                for value in root.findall('.//product_option_value'):
                    name_elem = value.find('.//name/language')
                    if name_elem is not None and name_elem.text == value_name:
                        value_id = value.find('id')
                        if value_id is not None:
                            return int(value_id.text)

                # Create new value if not found
                return self._create_prestashop_attribute_value(attribute_id, value_name)

            return None
        except Exception as e:
            raise UserError(f"Error with attribute value {value_name}: {str(e)}")

    def _create_prestashop_attribute_value(self, attribute_id, value_name):
        """Create a new attribute value in PrestaShop"""
        xml_data = f"""<?xml version="1.0" encoding="UTF-8"?>
<prestashop xmlns:xlink="http://www.w3.org/1999/xlink">
  <product_option_value>
    <id_attribute_group><![CDATA[{attribute_id}]]></id_attribute_group>
    <name>
      <language id="1"><![CDATA[{value_name}]]></language>
    </name>
  </product_option_value>
</prestashop>"""

        try:
            response = requests.post(
                "https://outletna.com/api/product_option_values",
                auth=("86TN4NX1QDTBJC2XS9HUHL9RI53ANB3N", ""),
                headers={"Content-Type": "application/xml"},
                data=xml_data.encode('utf-8'),
                timeout=30
            )

            if response.status_code in [200, 201]:
                import xml.etree.ElementTree as ET
                root = ET.fromstring(response.content)
                value_id = root.find('.//product_option_value/id')
                if value_id is not None:
                    return int(value_id.text)
            else:
                raise UserError(f"Failed to create attribute value: {response.text}")
        except Exception as e:
            raise UserError(f"Error creating attribute value: {str(e)}")

    def _get_or_create_prestashop_category(self, category_name, parent_id=2):
        """Get or create PrestaShop category by name"""
        try:
            # Search for existing category
            response = requests.get(
                "https://outletna.com/api/categories",
                auth=("86TN4NX1QDTBJC2XS9HUHL9RI53ANB3N", ""),
                params={'filter[name]': category_name, 'display': 'full'},
                timeout=30
            )

            if response.status_code == 200:
                import xml.etree.ElementTree as ET
                root = ET.fromstring(response.content)
                category_id = root.find('.//category/id')
                if category_id is not None:
                    return int(category_id.text)

            # Create category if not found
            return self._create_prestashop_category(category_name, parent_id)

        except Exception as e:
            raise UserError(f"Error getting category {category_name}: {str(e)}")

    def _create_prestashop_category(self, category_name, parent_id=2):
        """Create a new category in PrestaShop"""
        xml_data = f"""<?xml version="1.0" encoding="UTF-8"?>
<prestashop xmlns:xlink="http://www.w3.org/1999/xlink">
  <category>
    <id_parent><![CDATA[{parent_id}]]></id_parent>
    <active><![CDATA[1]]></active>
    <name>
      <language id="1"><![CDATA[{category_name}]]></language>
    </name>
    <link_rewrite>
      <language id="1"><![CDATA[{category_name.lower().replace(' ', '-')}]]></language>
    </link_rewrite>
  </category>
</prestashop>"""

        try:
            response = requests.post(
                "https://outletna.com/api/categories",
                auth=("86TN4NX1QDTBJC2XS9HUHL9RI53ANB3N", ""),
                headers={"Content-Type": "application/xml"},
                data=xml_data.encode('utf-8'),
                timeout=30
            )

            if response.status_code in [200, 201]:
                import xml.etree.ElementTree as ET
                root = ET.fromstring(response.content)
                category_id = root.find('.//category/id')
                if category_id is not None:
                    return int(category_id.text)
            else:
                raise UserError(f"Failed to create category: {response.text}")
        except Exception as e:
            raise UserError(f"Error creating category: {str(e)}")

    def _get_variant_attribute_values(self):
        """Extract attribute values from Odoo variant"""
        attribute_values = []

        for value in self.product_template_attribute_value_ids:
            attribute_name = value.attribute_id.name
            value_name = value.name

            # Map common Odoo attribute names to PrestaShop
            # Adjust this mapping based on your attribute names
            if 'color' in attribute_name.lower() or 'colour' in attribute_name.lower():
                prestashop_attr = 'Color'
            elif 'size' in attribute_name.lower() or 'taille' in attribute_name.lower():
                prestashop_attr = 'Size'
            else:
                prestashop_attr = attribute_name

            attribute_values.append({
                'prestashop_name': prestashop_attr,
                'value': value_name
            })

        return attribute_values

    def _update_product_categories(self, product_id_prestashop):
        """Update PrestaShop product with Odoo categories"""
        template = self.product_tmpl_id

        if not template.categ_id:
            return None

        # Get or create categories in PrestaShop
        category_ids = []

        # Main category
        main_category = template.categ_id
        ps_category_id = self._get_or_create_prestashop_category(main_category.name)
        if ps_category_id:
            category_ids.append(ps_category_id)

        # Parent categories (if you want hierarchy)
        current_category = main_category.parent_id
        while current_category and current_category.name != 'All':
            ps_cat_id = self._get_or_create_prestashop_category(current_category.name)
            if ps_cat_id and ps_cat_id not in category_ids:
                category_ids.append(ps_cat_id)
            current_category = current_category.parent_id

        if not category_ids:
            return None

        # Get current product data
        try:
            response = requests.get(
                f"https://outletna.com/api/products/{product_id_prestashop}",
                auth=("86TN4NX1QDTBJC2XS9HUHL9RI53ANB3N", ""),
                params={'display': 'full'},
                timeout=30
            )

            if response.status_code != 200:
                return None

            import xml.etree.ElementTree as ET
            root = ET.fromstring(response.content)

            # Update categories associations
            associations = root.find('.//associations')
            if associations is None:
                associations = ET.SubElement(root.find('.//product'), 'associations')

            # Remove old categories
            old_categories = associations.find('categories')
            if old_categories is not None:
                associations.remove(old_categories)

            # Add new categories
            categories_elem = ET.SubElement(associations, 'categories')
            for cat_id in category_ids:
                category = ET.SubElement(categories_elem, 'category')
                id_elem = ET.SubElement(category, 'id')
                id_elem.text = str(cat_id)

            # Also set id_category_default to the main category
            id_category_default = root.find('.//id_category_default')
            if id_category_default is not None:
                id_category_default.text = str(category_ids[0])

            # Convert back to XML string
            updated_xml = ET.tostring(root, encoding='utf-8', method='xml')

            # Update product
            update_response = requests.put(
                f"https://outletna.com/api/products/{product_id_prestashop}",
                auth=("86TN4NX1QDTBJC2XS9HUHL9RI53ANB3N", ""),
                headers={"Content-Type": "application/xml"},
                data=updated_xml,
                timeout=30
            )

            if update_response.status_code == 200:
                return category_ids

            return None

        except Exception as e:
            # Log error but don't fail the combination export
            self.message_post(body=f"⚠️ Warning: Could not update categories: {str(e)}")
            return None

    def action_export_combination_to_prestashop(self):
        """Export product variant (combination) to PrestaShop"""
        self.ensure_one()

        template = self.product_tmpl_id

        if not template.id_prestashop:
            raise UserError("❌ PrestaShop Product ID is missing on the template!")

        if not self.default_code:
            raise UserError("❌ Reference / EAN (default_code) is required!")

        # Get variant attributes
        variant_attributes = self._get_variant_attribute_values()

        if not variant_attributes:
            raise UserError("❌ No attributes found on this variant!")

        # Get or create attribute values in PrestaShop
        option_value_ids = []
        for attr in variant_attributes:
            # Get PrestaShop attribute ID
            ps_attr_id = self._get_prestashop_attribute_id(attr['prestashop_name'])

            if not ps_attr_id:
                raise UserError(
                    f"❌ Attribute '{attr['prestashop_name']}' not found in PrestaShop. Please create it first.")

            # Get or create value
            ps_value_id = self._get_or_create_prestashop_attribute_value(ps_attr_id, attr['value'])

            if ps_value_id:
                option_value_ids.append(ps_value_id)

        # Build XML with dynamic option values
        option_values_xml = '\n        '.join([
            f'<product_option_value><id><![CDATA[{vid}]]></id></product_option_value>'
            for vid in option_value_ids
        ])

        # Optional: price difference from base template price
        price_diff = self.lst_price - template.list_price

        xml_data = f"""<?xml version="1.0" encoding="UTF-8"?>
<prestashop xmlns:xlink="http://www.w3.org/1999/xlink">
  <combination>
    <id_product><![CDATA[{template.id_prestashop}]]></id_product>
    <reference><![CDATA[{self.default_code}]]></reference>
    <ean13><![CDATA[{self.default_code}]]></ean13>
    <price><![CDATA[{price_diff:.2f}]]></price>
    <minimal_quantity><![CDATA[1]]></minimal_quantity>
    <associations>
      <product_option_values>
        {option_values_xml}
      </product_option_values>
    </associations>
  </combination>
</prestashop>"""

        try:
            response = requests.post(
                "https://outletna.com/api/combinations",
                auth=("86TN4NX1QDTBJC2XS9HUHL9RI53ANB3N", ""),
                headers={"Content-Type": "application/xml"},
                data=xml_data.encode('utf-8'),
                timeout=30
            )

            if response.status_code in [200, 201]:
                # Extract PrestaShop combination ID from response
                import xml.etree.ElementTree as ET
                root = ET.fromstring(response.content)
                prestashop_variant_id = root.find('.//combination/id')
                if prestashop_variant_id is not None:
                    self.id_prestashop_variant = int(prestashop_variant_id.text)

                # Update product categories (only once per product)
                category_ids = self._update_product_categories(template.id_prestashop)
                category_info = f"<br/>Categories: {', '.join([str(c) for c in category_ids])}" if category_ids else ""

                # Build attributes string
                attributes_str = ', '.join([f"{a['prestashop_name']}: {a['value']}" for a in variant_attributes])

                self.message_post(
                    body=f"✅ Combination exported successfully!<br/>"
                         f"Variant ID: {self.id_prestashop_variant}<br/>"
                         f"Reference/EAN: {self.default_code}<br/>"
                         f"Attributes: {attributes_str}{category_info}"
                )

                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Success!',
                        'message': 'Combination created successfully in PrestaShop!',
                        'type': 'success',
                    }
                }

            else:
                raise UserError(f"❌ Failed to create combination: {response.status_code}\n{response.text}")

        except Exception as e:
            raise UserError(f"❌ Error while creating combination: {str(e)}")

    def action_export_to_prestashop_combin(self):
        """Export one or multiple products to PrestaShop"""
        products = self.filtered(lambda p: not p.id_prestashop_variant)
        if not products:
            raise UserError("✅ Tous les produits sélectionnés sont déjà exportés vers PrestaShop.")

        success_count = 0
        failed = []

        for product in products:
            try:
                # Export each combination (existing method)
                product.action_export_combination_to_prestashop()
                success_count += 1

            except Exception as e:
                # Log errors but continue with others
                failed.append(f"{product.display_name}: {str(e)}")
                continue

        # Build result message
        msg = f"✅ {success_count} produits exportés avec succès."
        if failed:
            msg += f"\n⚠️ {len(failed)} échecs :\n" + "\n".join(failed[:10])
            if len(failed) > 10:
                msg += "\n..."

        # Send notification to user
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Exportation PrestaShop terminée',
                'message': msg,
                'type': 'success' if success_count else 'warning',
                'sticky': True,
            }
        }

class WebsiteOrder(models.Model):
    _name = 'stock.website.order'
    _description = 'Stock Website Order Synced from API'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    ticket_id = fields.Char(string="Id Commande", required=True, unique=True)
    reference = fields.Char(string="Référence de la commande")
    payment_method = fields.Char(string="Mode de Paiement")
    store_id = fields.Integer(string="Store ID")
    client_name = fields.Char(string="Nom du Client")
    date_commande = fields.Date(string="Date de Commande")
    line_ids = fields.One2many('stock.website.order.line', 'order_id', string="Lignes de Commande")
    email = fields.Char(string="Email")
    phone = fields.Char(string="Phone")
    mobile = fields.Char(string="Mobile")
    adresse = fields.Char(string="Adresse 1")
    second_adresse = fields.Char(string="Adresse 2")
    city = fields.Char(string="Ville")
    postcode = fields.Char(string="Postcode")
    pays= fields.Char(string="Pays")
    status = fields.Selection([
        ('initial', 'Initial'),
        ('prepare', 'Préparé'),
        ('delivered', 'Livré'),
        ('en_cours_preparation', 'En cours de préparation'),
        ('encourdelivraison', 'En cours de Livraison'),
        ('annuler', 'Annulé'),
    ], string="Statut", default='initial')

class StockWebsiteOrderLine(models.Model):
    _name = 'stock.website.order.line'
    _description = 'Ligne de commande du site'

    order_id = fields.Many2one('stock.website.order', string="Commande")
    product_id = fields.Many2one('product.product', string="Produit")
    product_name = fields.Char(string="Nom du Produit")
    quantity = fields.Float(string="Quantité")
    price = fields.Float(string="Prix", store=True)
    discount = fields.Float(string="Remise")
    magasin_name = fields.Char(string="Magasin",store=True,
                               help="Nom du magasin où le produit est stocké")
    stock_count = fields.Float(string="Stock Disponible", store=True,
                               help="Quantité disponible en stock dans l'entrepôt")
    code_barre = fields.Char(string="Code Barre", help="Code barre du produit")
    numero_recu = fields.Char(string="Numéro De Ticket", help="Numéro de reçu/ticket de la commande POS",readonly=True)
    status_ligne_commande = fields.Selection([
        ('initial', 'Initial'),
        ('prepare', 'Préparé'),
        ('delivered', 'Livré'),
        ('en_cours_preparation', 'En cours de préparation'),
        ('encourdelivraison', 'En cours de Livraison'),
        ('annuler', 'Annulé')
    ], string="Statut", default='initial')

class CustomerFetcher(models.TransientModel):
    _name = 'customer.fetch'
    _description = 'Customer Data Fetcher'

    API_BASE_URL = "https://outletna.com/api"
    TOKEN = "86TN4NX1QDTBJC2XS9HUHL9RI53ANB3N"

    @api.model
    def fetch_customer_data(self):
        _logger.info("Starting order data fetch...")

        # Get yesterday and today dates
        today = datetime.now().date()
        yesterday = today - timedelta(days=15)
        tomorrow = today + timedelta(days=1)

        # Format dates for API filter
        date_filter = f"[{yesterday},{tomorrow}]"
        orders_url = f"{self.API_BASE_URL}/orders?filter[date_add]={date_filter}&date=1"

        try:
            _logger.info("Making API request to: %s", orders_url)

            # Use basic authentication with token as username
            response = requests.get(orders_url, auth=(self.TOKEN, ''))

            if response.status_code == 200:
                _logger.info("SUCCESS: API call successful!")

                root = ET.fromstring(response.content)
                orders = root.find('orders')
                if orders is None:
                    _logger.warning("No <orders> element found in response.")
                    return

                order_elements = orders.findall('order')
                _logger.info("Total orders found: %d", len(order_elements))

                for i, order in enumerate(order_elements):
                    order_id = order.get('id')
                    href = order.get('{http://www.w3.org/1999/xlink}href')

                    # Check if order already exists in Odoo
                    if self.env['stock.website.order'].search([('ticket_id', '=', order_id)], limit=1):
                        _logger.info("Skipping existing order ID=%s", order_id)
                        continue

                    _logger.info("New Order %s: ID=%s, URL=%s", i + 1, order_id, href)
                    self._fetch_and_log_order_details(order_id)

            else:
                _logger.error("FAILED: Status %s - %s", response.status_code, response.text)

        except requests.exceptions.Timeout:
            _logger.error("TIMEOUT: API request timed out")

        except requests.exceptions.ConnectionError:
            _logger.error("🔌 CONNECTION ERROR: Unable to reach API")

        except Exception as e:
            _logger.exception("EXCEPTION: %s", str(e))

        _logger.info("Order data fetch completed")

    def _fetch_and_log_order_details(self, order_id):
        order_url = f"{self.API_BASE_URL}/orders/{order_id}"
        try:
            # Use basic authentication here too
            response = requests.get(order_url, auth=(self.TOKEN, ''), timeout=30)
            if response.status_code == 200:
                tree = ET.fromstring(response.content)
                order = tree.find('order')

                customer_elem = order.find('id_customer')
                address_delivery_elem = order.find('id_address_delivery')

                customer_url = customer_elem.attrib.get('{http://www.w3.org/1999/xlink}href')
                address_delivery_url = address_delivery_elem.attrib.get('{http://www.w3.org/1999/xlink}href')

                customer_details = self._get_complete_customer_details(customer_url, address_delivery_url)

                # Get or create/update contact based on phone and email
                partner = self._find_or_create_partner(customer_details)

                # Order info
                date_commande_str = order.findtext('date_add', default='').strip()
                date_commande = datetime.strptime(date_commande_str,
                                                  '%Y-%m-%d %H:%M:%S').date() if date_commande_str else None
                reference = order.findtext('reference', default='').strip()
                payment = order.findtext('payment', default='').strip()
                if payment == "Paiement comptant à la livraison (Cash on delivery)":
                    payment = "COD"
                # Use PrestaShop data for order_rec, not Odoo partner data
                order_rec = self.env['stock.website.order'].create({
                    'ticket_id': order_id,
                    'reference': reference,
                    'client_name': f"{customer_details.get('firstname', '')} {customer_details.get('lastname', '')}".strip(),
                    'email': customer_details.get('email', ''),
                    'phone': customer_details.get('phone', ''),
                    'mobile': customer_details.get('phone_mobile', ''),
                    'adresse': customer_details.get('address1', ''),
                    'second_adresse': customer_details.get('address2', ''),
                    'city': customer_details.get('city', ''),
                    'postcode': customer_details.get('postcode', ''),
                    'pays': self.env['res.country'].search([('name', '=', customer_details.get('country'))],
                                                           limit=1) if customer_details.get('country') else False,
                    'date_commande': date_commande,
                    'payment_method': payment,
                })

                order_rows = order.findall('.//order_row')
                total_amount = 0

                for row in order_rows:
                    product_name = row.findtext('product_name', default='').strip()
                    product_reference = row.findtext('product_ean13', default='').strip()
                    quantity = row.findtext('product_quantity', default='0').strip()
                    price = row.findtext('product_price', default='0.00').strip()
                    unit_price_incl = row.findtext('unit_price_tax_incl', default='0.00').strip()
                    line_total = float(quantity) * float(unit_price_incl) if quantity and unit_price_incl else 0
                    total_amount += line_total

                    product = self.env['product.product'].search([('default_code', '=', product_reference)], limit=1)
                    if not product:
                        _logger.warning("No product found with reference: %s", product_reference)
                        continue

                    self.env['stock.website.order.line'].create({
                        'order_id': order_rec.id,
                        'product_id': product.id,
                        'code_barre': product_reference,
                        'product_name': product.name,
                        'price':unit_price_incl,
                        'quantity': float(quantity),
                        'discount': float(row.findtext('total_discounts', default='0.00')),
                    })

                total_paid = order.findtext('total_paid_tax_incl', default='0.00')
                payment_method = order.findtext('payment', default='')

                _logger.info("ORDER #%s Summary:", order_id)
                _logger.info("   Total Paid: %s MAD", total_paid)
                _logger.info("   Payment Method: %s", payment_method)
                _logger.info("=" * 80)

            else:
                _logger.error("Failed to fetch order details for %s, status code: %s", order_id, response.status_code)
        except Exception as e:
            _logger.exception("Exception fetching details for order %s: %s", order_id, str(e))

    def _get_complete_customer_details(self, customer_url, address_url):
        """Fetch complete customer details including address information"""
        customer_details = {}

        # Fetch customer basic info
        if customer_url:
            customer_data = self._fetch_api_data(customer_url)
            if customer_data:
                tree = ET.fromstring(customer_data)
                customer_details.update({
                    'firstname': self._get_text_content(tree, './/firstname'),
                    'lastname': self._get_text_content(tree, './/lastname'),
                    'email': self._get_text_content(tree, './/email'),
                })

        # Fetch address details
        if address_url:
            address_data = self._fetch_api_data(address_url)
            if address_data:
                tree = ET.fromstring(address_data)
                customer_details.update({
                    'phone': self._get_text_content(tree, './/phone'),
                    'phone_mobile': self._get_text_content(tree, './/phone_mobile'),
                    'company': self._get_text_content(tree, './/company'),
                    'address1': self._get_text_content(tree, './/address1'),
                    'address2': self._get_text_content(tree, './/address2'),
                    'city': self._get_text_content(tree, './/city'),
                    'postcode': self._get_text_content(tree, './/postcode'),
                })

                # Get country name if available
                country_elem = tree.find('.//id_country')
                if country_elem is not None:
                    country_url = country_elem.attrib.get('{http://www.w3.org/1999/xlink}href')
                    if country_url:
                        country_data = self._fetch_api_data(country_url)
                        if country_data:
                            country_tree = ET.fromstring(country_data)
                            country_name = self._get_text_content(country_tree, './/name')
                            customer_details['country'] = country_name

        return customer_details

    def _fetch_api_data(self, url):
        """Helper method to fetch data from API"""
        try:
            # Use basic authentication instead of ws_key
            response = requests.get(url, auth=(self.TOKEN, ''), timeout=30)
            if response.status_code == 200:
                return response.content
            else:
                _logger.warning("Failed to fetch data from %s (status %s)", url, response.status_code)
                return None
        except Exception as e:
            _logger.exception("Exception fetching data from %s: %s", url, str(e))
            return None

    def _get_customer_name(self, customer_url):
        """Legacy method - kept for compatibility"""
        if not customer_url:
            return "Unknown"

        try:
            # Use basic authentication
            response = requests.get(customer_url, auth=(self.TOKEN, ''), timeout=30)
            if response.status_code == 200:
                tree = ET.fromstring(response.content)
                firstname = tree.find('.//firstname')
                lastname = tree.find('.//lastname')
                firstname_text = firstname.text if firstname is not None else ''
                lastname_text = lastname.text if lastname is not None else ''
                return f"{firstname_text} {lastname_text}".strip()
            else:
                _logger.warning("Failed to fetch customer data at %s (status %s)", customer_url, response.status_code)
                return "Unknown"
        except Exception as e:
            _logger.exception("Exception fetching customer data from %s: %s", customer_url, str(e))
            return "Unknown"

    def _find_or_create_partner(self, customer_details):
        """Find existing partner or create/update based on phone and email matching"""
        email = customer_details.get('email', '').strip().lower()
        phone = customer_details.get('phone', '').strip()
        phone_mobile = customer_details.get('phone_mobile', '').strip()
        firstname = customer_details.get('firstname', '').strip()
        lastname = customer_details.get('lastname', '').strip()
        full_name = f"{firstname} {lastname}".strip()

        partner = None

        # Search for existing partner by phone (mobile or phone) and email
        search_domain = []
        if phone:
            search_domain.append(('phone', '=', phone))
        if phone_mobile:
            if search_domain:
                search_domain = ['|'] + search_domain + [('mobile', '=', phone_mobile)]
            else:
                search_domain.append(('mobile', '=', phone_mobile))

        if email:
            if search_domain:
                search_domain = ['&', ('email', '=', email)] + search_domain
            else:
                search_domain.append(('email', '=', email))

        if search_domain:
            partners = self.env['res.partner'].search(search_domain)

            # If multiple partners found, try to match by name (case insensitive)
            if len(partners) > 1 and full_name:
                for p in partners:
                    if p.name and p.name.lower() == full_name.lower():
                        partner = p
                        break
                # If no exact name match, take the first one
                if not partner:
                    partner = partners[0]
            elif len(partners) == 1:
                partner = partners[0]

        # Prepare partner values with ALL PrestaShop data
        country_id = False
        if customer_details.get('country'):
            country = self.env['res.country'].search([('name', '=', customer_details.get('country'))], limit=1)
            if country:
                country_id = country.id

        partner_vals = {
            'name': full_name,
            'email': email,
            'phone': phone,
            'mobile': phone_mobile,
            'company_name': customer_details.get('company', ''),
            'street': customer_details.get('address1', ''),
            'street2': customer_details.get('address2', ''),
            'city': customer_details.get('city', ''),
            'zip': customer_details.get('postcode', ''),
            'country_id': country_id,
        }

        if partner:
            # Always update existing partner with PrestaShop data (overwrite existing)
            old_address = partner.street
            partner.write(partner_vals)
            _logger.info("UPDATED existing partner: %s", partner.name)
            _logger.info("  - Old Address: '%s'", old_address or 'Empty')
            _logger.info("  - New Address: '%s'", customer_details.get('address1', ''))
            _logger.info("  - Email: %s", email)
            _logger.info("  - Phone: %s", phone)
            _logger.info("  - Mobile: %s", phone_mobile)
            _logger.info("  - Address2: %s", customer_details.get('address2', ''))
            _logger.info("  - City: %s", customer_details.get('city', ''))
            _logger.info("  - PostCode: %s", customer_details.get('postcode', ''))
            _logger.info("  - Country: %s", customer_details.get('country', ''))
        else:
            # Create new partner with all PrestaShop data
            partner = self.env['res.partner'].create(partner_vals)
            _logger.info("Created new partner: %s with all PrestaShop details", partner.name)

        return partner

    def _get_text_content(self, tree, xpath):
        """Helper method to safely extract text content from XML"""
        element = tree.find(xpath)
        return element.text.strip() if element is not None and element.text else ''