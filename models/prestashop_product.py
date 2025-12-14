from odoo import models, fields, api,_
from odoo.exceptions import UserError
import requests
import base64
from datetime import datetime, timedelta
import time
import json
import xml.etree.ElementTree as ET
from lxml import etree
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
    def _delete_product_from_prestashop(self, id_prestashop):
        """Delete a single product from PrestaShop by ID"""
        try:
            response = requests.delete(
                f"https://outletna.com/api/products/{id_prestashop}",
                auth=("86TN4NX1QDTBJC2XS9HUHL9RI53ANB3N", ""),
                timeout=60
            )

            if response.status_code in [200, 204, 404]:
                _logger.info(f"Successfully deleted product ID {id_prestashop} from PrestaShop")
                return True
            else:
                _logger.error(
                    f"Failed to delete product {id_prestashop}: "
                    f"{response.status_code} - {response.text}"
                )
                return False

        except Exception as e:
            _logger.error(f"Exception deleting product {id_prestashop}: {str(e)}")
            return False

    def action_delete_product_prestashop(self):
        """Delete selected products from PrestaShop and Odoo"""
        if not self:
            raise UserError(_("No product selected."))

        success_products = []
        failed_products = []

        for product in self:
            product_name = product.display_name

            if not product.id_prestashop:
                _logger.warning(f"Product {product_name} has no PrestaShop ID, skipping")
                failed_products.append(product_name)
                continue

            success = product._delete_product_from_prestashop(product.id_prestashop)

            if success:
                success_products.append(product_name)
                # Also remove from Odoo
                product.unlink()
            else:
                failed_products.append(product_name)

        # Build detailed notification message
        message_parts = []

        if success_products:
            message_parts.append(f"Successfully deleted ({len(success_products)}):")
            message_parts.append(", ".join(success_products[:10]))
            if len(success_products) > 10:
                message_parts.append(f"... and {len(success_products) - 10} more")

        if failed_products:
            if message_parts:
                message_parts.append("\n\n")
            message_parts.append(f"Failed to delete ({len(failed_products)}):")
            message_parts.append(", ".join(failed_products[:10]))
            if len(failed_products) > 10:
                message_parts.append(f"... and {len(failed_products) - 10} more")

        message = "\n".join(message_parts)

        _logger.info(message)

        # Redirect to product template list and show confirmation notification
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Deletion Summary'),
                'message': message,
                'type': 'success' if not failed_products else 'warning',
                'sticky': False,
                'next': {
                    'type': 'ir.actions.act_window',
                    'res_model': 'product.template',
                    'view_mode': 'tree,form',
                    'views': [(False, 'tree'), (False, 'form')],
                    'domain': [],
                    'target': 'current',
                }
            }
        }

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
                root = ET.fromstring(response.content)
                category_id = root.find('.//category/id')
                if category_id is not None:
                    _logger.info(f"Category '{category_name}' created with ID: {category_id.text}")
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

    def _prepare_product_xml(self, product):
        """Prepare XML data for a single product"""
        # default brand
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
        if manufacturer_id > 0:
            manufacturer_xml = f'<id_manufacturer xlink:href="https://outletna.com/api/manufacturers/{manufacturer_id}"><![CDATA[{manufacturer_id}]]></id_manufacturer>'
        else:
            manufacturer_xml = '<id_manufacturer><![CDATA[0]]></id_manufacturer>'
        ean_value = product.barcode or ''
        link_rewrite = product.name.lower().replace(' ', '-')

        # Return product XML fragment
        return f"""      <product>
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
      </product>"""

    def _job_export_products_batch(self, product_ids):
        """Background job to export a batch of products"""
        products = self.browse(product_ids)

        if not products:
            return

        _logger.info(f"JOB: Exporting batch of {len(products)} products...")

        # Build XML for all products
        products_xml = '\n'.join([self._prepare_product_xml(p) for p in products])

        xml_data = f"""<?xml version="1.0" encoding="UTF-8"?>
    <prestashop xmlns:xlink="http://www.w3.org/1999/xlink">
{products_xml}
    </prestashop>"""

        try:
            response = requests.post(
                "https://outletna.com/api/products",
                auth=("86TN4NX1QDTBJC2XS9HUHL9RI53ANB3N", ""),
                headers={"Content-Type": "application/xml"},
                data=xml_data.encode('utf-8'),
                timeout=60
            )

            if response.status_code in [200, 201]:
                root = ET.fromstring(response.content)

                # Parse response and map IDs back to products
                for idx, product_elem in enumerate(root.findall('.//product')):
                    prestashop_id_elem = product_elem.find('id')
                    if prestashop_id_elem is not None and idx < len(products):
                        product = products[idx]
                        prestashop_id = int(prestashop_id_elem.text)
                        product.id_prestashop = prestashop_id

                        _logger.info(f"JOB: Exported {product.name} (ID: {prestashop_id})")

                        # Post message to product
                        category_names = []
                        if product.categ_id:
                            current = product.categ_id
                            while current and current.name not in ['All', 'All / Saleable']:
                                category_names.append(current.name)
                                current = current.parent_id

                        categories_display = ' > '.join(reversed(category_names)) if category_names else 'Home'

                _logger.info(f"JOB: Batch completed successfully")

            else:
                _logger.error(f"JOB: Batch export failed: {response.status_code} - {response.text}")

        except Exception as e:
            _logger.error(f"JOB: Exception during batch export: {e}", exc_info=True)
            raise

    def action_export_to_prestashop(self):
        """Export products in background using queue jobs"""
        if not self:
            raise UserError("No product selected.")

        BATCH_SIZE = 30  # Products per job

        # Filter products that need export
        products_to_export = []
        skipped_count = 0

        for product in self:
            if product.id_prestashop and product.id_prestashop != 0:
                skipped_count += 1
                _logger.info(f"Skipped: {product.name} (already exported)")
                continue

            if not product.x_studio_item_id:
                _logger.warning(f"Skipped: {product.name} (missing reference)")
                skipped_count += 1
                continue

            products_to_export.append(product)

        if not products_to_export:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'No Products to Export',
                    'message': f'{skipped_count} products skipped.',
                    'type': 'warning',
                    'sticky': False,
                }
            }

        # Create background jobs for each batch
        total_products = len(products_to_export)
        total_batches = (total_products + BATCH_SIZE - 1) // BATCH_SIZE

        _logger.info(f"Creating {total_batches} background jobs for {total_products} products")

        for i in range(0, total_products, BATCH_SIZE):
            batch = products_to_export[i:i + BATCH_SIZE]
            batch_ids = [p.id for p in batch]

            # Create a background job for this batch
            self.with_delay(
                description=f"Export PrestaShop Products (Batch {(i // BATCH_SIZE) + 1}/{total_batches})"
            )._job_export_products_batch(batch_ids)

        _logger.info(f"Created {total_batches} background jobs")

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Export Started!',
                'message': f'{total_products} products queued for export in {total_batches} batch(es). Check Queue Jobs menu for progress.',
                'type': 'success',
                'sticky': True,
            }
        }

    def cron_export_new_products_to_prestashop(self):
        """Cron job: Export new products using queue jobs"""
        _logger.info("CRON: Starting automatic PrestaShop export")
        try:
            # Find products that need to be exported
            products_to_export = self.search([
                '|',
                ('id_prestashop', '=', False),
                ('id_prestashop', '=', 0),
                ('x_studio_item_id', '!=', False),
            ], limit=100)

            if not products_to_export:
                _logger.info("CRON: No new products to export")
                return

            _logger.info(f"CRON: Found {len(products_to_export)} product(s) to export")
            products_to_export.action_export_to_prestashop()
            _logger.info("CRON: Jobs created successfully")

        except Exception as e:
            _logger.error(f"CRON ERROR: {str(e)}")

class ProductProductPrest(models.Model):
    _inherit = "product.product"

    id_prestashop_variant = fields.Integer(
        string='PrestaShop Combination ID',
        help='Stores the PrestaShop variant ID after export',
        copy=False,
        readonly=True
    )

    def action_export_variant_images(self):
        """Export images for multiple variant/combination to PrestaShop"""

        if not self:
            raise UserError("No variant selected.")

        total_uploaded = 0
        total_failed = 0
        all_associated_ids = []

        for variant in self:
            # Validation 1: Check combination ID
            if not variant.id_prestashop_variant or variant.id_prestashop_variant == 0:
                _logger.warning(f"Skipped {variant.display_name}: id_prestashop_variant missing")
                total_failed += 1
                continue

            # Validation 2: Check template PrestaShop ID
            if not variant.product_tmpl_id.id_prestashop or variant.product_tmpl_id.id_prestashop == 0:
                _logger.warning(f"Skipped {variant.display_name}: product_tmpl_id.id_prestashop missing")
                total_failed += 1
                continue

            # Validation 3: Check image URLs
            if not variant.x_studio_image1:
                _logger.warning(f"Skipped {variant.display_name}: no images in x_studio_image1")
                total_failed += 1
                continue

            image_urls = [url.strip() for url in variant.x_studio_image1.split(';') if url.strip()]
            if not image_urls:
                _logger.warning(f"Skipped {variant.display_name}: no valid image URLs")
                total_failed += 1
                continue

            uploaded_image_ids = []
            uploaded_count = 0
            failed_count = 0

            # Upload images
            for idx, image_url in enumerate(image_urls, 1):
                try:
                    response = requests.get(image_url, timeout=30)
                    if response.status_code != 200:
                        _logger.error(f"{variant.display_name}: failed to download {image_url}")
                        failed_count += 1
                        continue

                    image_data = response.content
                    files = {'image': (f'variant_{variant.id_prestashop_variant}_{idx}.jpg', image_data, 'image/jpeg')}
                    upload_response = requests.post(
                        f"https://outletna.com/api/images/products/{variant.product_tmpl_id.id_prestashop}",
                        auth=("86TN4NX1QDTBJC2XS9HUHL9RI53ANB3N", ""),
                        files=files,
                        timeout=60
                    )

                    if upload_response.status_code in [200, 201]:
                        root = ET.fromstring(upload_response.content)
                        image_id_elem = root.find('.//image/id')
                        if image_id_elem is not None:
                            image_id = int(image_id_elem.text)
                            uploaded_image_ids.append(image_id)
                            uploaded_count += 1
                    else:
                        _logger.error(f"{variant.display_name}: upload failed {upload_response.status_code}")
                        failed_count += 1
                except Exception as e:
                    _logger.error(f"{variant.display_name}: error {str(e)}")
                    failed_count += 1

            # Associate images with variant
            if uploaded_image_ids:
                try:
                    get_response = requests.get(
                        f"https://outletna.com/api/combinations/{variant.id_prestashop_variant}",
                        auth=("86TN4NX1QDTBJC2XS9HUHL9RI53ANB3N", ""),
                        params={'display': 'full'},
                        timeout=30
                    )
                    if get_response.status_code == 200:
                        root = ET.fromstring(get_response.content)
                        combination = root.find('.//combination')
                        associations = combination.find('associations')
                        if associations is None:
                            associations = ET.SubElement(combination, 'associations')
                        old_images = associations.find('images')
                        if old_images is not None:
                            associations.remove(old_images)
                        images_elem = ET.SubElement(associations, 'images')
                        for img_id in uploaded_image_ids:
                            image_elem = ET.SubElement(images_elem, 'image')
                            id_elem = ET.SubElement(image_elem, 'id')
                            id_elem.text = str(img_id)
                        updated_xml = ET.tostring(root, encoding='utf-8', method='xml')
                        update_response = requests.put(
                            f"https://outletna.com/api/combinations/{variant.id_prestashop_variant}",
                            auth=("86TN4NX1QDTBJC2XS9HUHL9RI53ANB3N", ""),
                            headers={"Content-Type": "application/xml"},
                            data=updated_xml,
                            timeout=30
                        )
                        if update_response.status_code == 200:
                            all_associated_ids.extend(uploaded_image_ids)
                except Exception as e:
                    _logger.error(f"{variant.display_name}: failed to associate images: {str(e)}")

            total_uploaded += uploaded_count
            total_failed += failed_count

        message = f"Total Uploaded: {total_uploaded}\n Total Failed: {total_failed}"
        if all_associated_ids:
            message += f"\n Associated Image IDs: {', '.join(map(str, all_associated_ids))}"

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Variant Image Export',
                'message': message,
                'type': 'success' if total_failed == 0 else 'warning',
                'sticky': True,
            }
        }

    def _job_export_variant_images_batch(self, variant_ids):
        """Background job to export images for a batch of variants"""
        variants = self.browse(variant_ids)
        if not variants:
            return

        for variant in variants:
            try:
                variant.action_export_variant_images()
            except Exception as e:
                _logger.error(f"JOB: Failed to export images for {variant.display_name}: {str(e)}")

        _logger.info(f"JOB: Batch completed for {len(variants)} variant(s)")

    def action_export_variant_images_batch(self):
        """Queue jobs to export variant images for multiple products"""
        if not self:
            raise UserError(_("No variant selected."))

        BATCH_SIZE = 20  # Adjust batch size as needed
        variants_to_export = []

        for variant in self:
            if not variant.id_prestashop_variant:
                _logger.warning(f"Skipped {variant.display_name}: no PrestaShop variant ID")
                continue
            if not variant.x_studio_image1:
                _logger.warning(f"Skipped {variant.display_name}: no image URLs")
                continue
            variants_to_export.append(variant)

        if not variants_to_export:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'No Variants to Export',
                    'message': 'No valid variant images found for export.',
                    'type': 'warning',
                    'sticky': False,
                }
            }

        total_variants = len(variants_to_export)
        total_batches = (total_variants + BATCH_SIZE - 1) // BATCH_SIZE
        _logger.info(f"Creating {total_batches} background jobs for {total_variants} variants")

        for i in range(0, total_variants, BATCH_SIZE):
            batch = variants_to_export[i:i + BATCH_SIZE]
            batch_ids = [v.id for v in batch]
            self.with_delay(
                description=f"Export PrestaShop Variant Images (Batch {(i // BATCH_SIZE) + 1}/{total_batches})"
            )._job_export_variant_images_batch(batch_ids)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Export Started!',
                'message': f'{total_variants} variant(s) queued for image export in {total_batches} batch(es). Check Queue Jobs menu for progress.',
                'type': 'success',
                'sticky': True,
            }
        }

    def cron_export_variant_images_to_prestashop(self):
        """Cron job: export variant images automatically in batches"""
        _logger.info("CRON: Starting automatic variant image export")
        try:
            variants_to_export = self.search([
                ('id_prestashop_variant', '!=', False),
                ('x_studio_image1', '!=', False)
            ], limit=100)

            if not variants_to_export:
                _logger.info("CRON: No variant images to export")
                return

            _logger.info(f"CRON: Found {len(variants_to_export)} variant(s) for export")
            variants_to_export.action_export_variant_images_batch()
            _logger.info("CRON: Queue jobs created successfully")

        except Exception as e:
            _logger.error(f"CRON ERROR: {str(e)}")

    def _delete_combination_from_prestashop(self, id_prestashop_variant):
        """Delete a single combination from PrestaShop by ID"""
        try:
            response = requests.delete(
                f"https://outletna.com/api/combinations/{id_prestashop_variant}",
                auth=("86TN4NX1QDTBJC2XS9HUHL9RI53ANB3N", ""),
                timeout=60
            )

            if response.status_code in [200, 204, 404]:
                _logger.info(f"Successfully deleted combination ID {id_prestashop_variant} from PrestaShop")
                return True
            else:
                _logger.error(
                    f"Failed to delete combination {id_prestashop_variant}: "
                    f"{response.status_code} - {response.text}"
                )
                return False

        except Exception as e:
            _logger.error(f"Exception deleting combination {id_prestashop_variant}: {str(e)}")
            return False

    def action_delete_combination_prestashop(self):
        """Delete selected variants (combinations) from PrestaShop and Odoo"""
        if not self:
            raise UserError(_("No variant selected."))

        success_variants = []
        failed_variants = []

        for variant in self:
            variant_name = variant.display_name

            if not variant.id_prestashop_variant:
                _logger.warning(f"Variant {variant_name} has no PrestaShop combination ID, skipping")
                failed_variants.append(variant_name)
                continue

            success = variant._delete_combination_from_prestashop(variant.id_prestashop_variant)

            if success:
                success_variants.append(variant_name)
                # Also remove from Odoo
                variant.unlink()
            else:
                failed_variants.append(variant_name)

        # Build detailed notification message
        message_parts = []

        if success_variants:
            message_parts.append(f"Successfully deleted ({len(success_variants)}):")
            message_parts.append(", ".join(success_variants[:10]))
            if len(success_variants) > 10:
                message_parts.append(f"... and {len(success_variants) - 10} more")

        if failed_variants:
            if message_parts:
                message_parts.append("\n\n")
            message_parts.append(f"Failed to delete ({len(failed_variants)}):")
            message_parts.append(", ".join(failed_variants[:10]))
            if len(failed_variants) > 10:
                message_parts.append(f"... and {len(failed_variants) - 10} more")

        message = "\n".join(message_parts)

        _logger.info(message)

        # Show confirmation dialog and redirect to product variants page
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Deletion Summary'),
                'message': message,
                'type': 'success' if not failed_variants else 'warning',
                'sticky': False,
                'next': {
                    'type': 'ir.actions.act_window',
                    'res_model': 'product.product',
                    'view_mode': 'tree,form',
                    'views': [(False, 'tree'), (False, 'form')],
                    'domain': [],
                    'target': 'current',
                }
            }
        }

    def _get_prestashop_attribute_id(self, attribute_name):
        """Get PrestaShop attribute ID by name (Color, Size, etc.)"""
        try:
            response = requests.get(
                "https://outletna.com/api/product_options",
                auth=("86TN4NX1QDTBJC2XS9HUHL9RI53ANB3N", ""),
                params={'filter[name]': attribute_name, 'display': 'full'},
                timeout=30
            )

            if response.status_code == 200:
                root = ET.fromstring(response.content)
                attribute_id = root.find('.//product_option/id')
                if attribute_id is not None:
                    return int(attribute_id.text)

            return None
        except Exception as e:
            _logger.error(f"Error getting attribute {attribute_name}: {str(e)}")
            return None

    def _get_or_create_prestashop_attribute_value(self, attribute_id, value_name):
        """Get or create PrestaShop attribute value ID"""
        try:
            # Search for existing value
            response = requests.get(
                "https://outletna.com/api/product_option_values",
                auth=("86TN4NX1QDTBJC2XS9HUHL9RI53ANB3N", ""),
                params={'filter[id_attribute_group]': attribute_id, 'display': 'full'},
                timeout=300
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
                timeout=300
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
                timeout=300
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

    # ==================== HELPER METHODS ====================
    def _prepare_combination_data(self, variant):
        """Prepare XML data for a single combination"""
        try:
            template = variant.product_tmpl_id

            # Get variant attributes
            variant_attributes = variant._get_variant_attribute_values()

            if not variant_attributes:
                return None

            # Get or create attribute values in PrestaShop
            option_value_ids = []
            for attr in variant_attributes:
                ps_attr_id = variant._get_prestashop_attribute_id(attr['prestashop_name'])

                if not ps_attr_id:
                    _logger.error(f"Attribute '{attr['prestashop_name']}' not found in PrestaShop")
                    return None

                ps_value_id = variant._get_or_create_prestashop_attribute_value(ps_attr_id, attr['value'])

                if ps_value_id:
                    option_value_ids.append(ps_value_id)

            if not option_value_ids:
                return None

            # Build XML with dynamic option values
            option_values_xml = '\n        '.join([
                f'<product_option_value><id><![CDATA[{vid}]]></id></product_option_value>'
                for vid in option_value_ids
            ])

            # Price difference from base template price
            price_diff = variant.lst_price - template.list_price

            xml_data = f"""<?xml version="1.0" encoding="UTF-8"?>
<prestashop xmlns:xlink="http://www.w3.org/1999/xlink">
  <combination>
    <id_product><![CDATA[{template.id_prestashop}]]></id_product>
    <reference><![CDATA[{variant.default_code}]]></reference>
    <ean13><![CDATA[{variant.default_code}]]></ean13>
    <price><![CDATA[{price_diff:.2f}]]></price>
    <minimal_quantity><![CDATA[1]]></minimal_quantity>
    <associations>
      <product_option_values>
        {option_values_xml}
      </product_option_values>
    </associations>
  </combination>
</prestashop>"""

            return xml_data

        except Exception as e:
            _logger.error(f"Error preparing data for {variant.display_name}: {str(e)}")
            return None

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
                timeout=300
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
            if 'color' in attribute_name.lower():
                prestashop_attr = 'Color'
            elif 'size' in attribute_name.lower():
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
                timeout=300
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
                timeout=300
            )

            if update_response.status_code == 200:
                return category_ids

            return None

        except Exception as e:
            # Log error but don't fail the combination export
            self.message_post(body=f"Warning: Could not update categories: {str(e)}")
            return None

    def action_export_combination_to_prestashop(self):
        """Export product variants (combinations) in background using queue jobs"""
        if not self:
            raise UserError("No variant selected.")

        BATCH_SIZE = 30  # Variants per job

        # Filter variants that need export
        variants_to_export = []
        skipped_count = 0

        for variant in self:
            # Skip if already exported
            if variant.id_prestashop_variant and variant.id_prestashop_variant != 0:
                skipped_count += 1
                _logger.info(f"Skipped: {variant.display_name} (already exported)")
                continue

            # Skip if missing template PrestaShop ID
            if not variant.product_tmpl_id.id_prestashop:
                _logger.warning(f"Skipped: {variant.display_name} (missing template id_prestashop)")
                skipped_count += 1
                continue

            # Skip if missing reference
            if not variant.default_code:
                _logger.warning(f"Skipped: {variant.display_name} (missing reference)")
                skipped_count += 1
                continue

            # Skip if no attributes
            if not variant.product_template_attribute_value_ids:
                _logger.warning(f"Skipped: {variant.display_name} (no attributes)")
                skipped_count += 1
                continue

            variants_to_export.append(variant)

        if not variants_to_export:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'No Variants to Export',
                    'message': f'{skipped_count} variants skipped.',
                    'type': 'warning',
                    'sticky': False,
                }
            }

        # Create background jobs for each batch
        total_variants = len(variants_to_export)
        total_batches = (total_variants + BATCH_SIZE - 1) // BATCH_SIZE

        _logger.info(f"Creating {total_batches} background jobs for {total_variants} variants")

        for i in range(0, total_variants, BATCH_SIZE):
            batch = variants_to_export[i:i + BATCH_SIZE]
            batch_ids = [v.id for v in batch]

            # Create a background job for this batch
            self.with_delay(
                description=f"Export PrestaShop Combinations (Batch {(i // BATCH_SIZE) + 1}/{total_batches})"
            )._job_export_combinations_batch(batch_ids)

        _logger.info(f"Created {total_batches} background jobs")

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Export Started!',
                'message': f'{total_variants} variants queued for export in {total_batches} batch(es). Check Queue Jobs menu for progress.',
                'type': 'success',
                'sticky': True,
            }
        }

    def _job_export_combinations_batch(self, variant_ids):
        """Background job to export a batch of combinations"""
        variants = self.browse(variant_ids)

        if not variants:
            return

        _logger.info(f"JOB: Exporting batch of {len(variants)} combinations...")

        success_count = 0
        failed_count = 0

        for variant in variants:
            try:
                # Prepare combination data
                combination_data = self._prepare_combination_data(variant)

                if not combination_data:
                    _logger.warning(f"JOB: Skipped {variant.display_name} - no valid data")
                    failed_count += 1
                    continue

                # Create combination in PrestaShop
                response = requests.post(
                    "https://outletna.com/api/combinations",
                    auth=("86TN4NX1QDTBJC2XS9HUHL9RI53ANB3N", ""),
                    headers={"Content-Type": "application/xml"},
                    data=combination_data.encode('utf-8'),
                    timeout=60
                )

                if response.status_code in [200, 201]:
                    root = ET.fromstring(response.content)
                    prestashop_variant_id = root.find('.//combination/id')

                    if prestashop_variant_id is not None:
                        variant.id_prestashop_variant = int(prestashop_variant_id.text)
                        success_count += 1
                        _logger.info(f"JOB: Exported {variant.display_name} (ID: {prestashop_variant_id.text})")
                    else:
                        failed_count += 1
                        _logger.error(f"JOB: No ID in response for {variant.display_name}")
                else:
                    failed_count += 1
                    _logger.error(f"JOB: Failed {variant.display_name}: {response.status_code} - {response.text}")

            except Exception as e:
                failed_count += 1
                _logger.error(f"JOB: Exception for {variant.display_name}: {str(e)}")

        _logger.info(f"JOB: Batch completed - Success: {success_count}, Failed: {failed_count}")

    def cron_export_combinations_to_prestashop(self):
        """Cron job: Export new combinations using queue jobs"""
        _logger.info("CRON: Starting automatic combination export")
        try:
            # Find variants that need to be exported
            variants_to_export = self.search([
                '|',
                ('id_prestashop_variant', '=', False),
                ('id_prestashop_variant', '=', 0),
                ('product_tmpl_id.id_prestashop', '!=', False),
                ('default_code', '!=', False),
            ], limit=100)

            if not variants_to_export:
                _logger.info("CRON: No new combinations to export")
                return

            _logger.info(f"CRON: Found {len(variants_to_export)} combination(s) to export")
            variants_to_export.action_export_combination_to_prestashop()
            _logger.info("CRON: Jobs created successfully")

        except Exception as e:
            _logger.error(f"CRON ERROR: {str(e)}")
    '''Stock update'''

    @api.model
    def cron_monitor_stock_changes(self):
        """
        Cron job function that runs every 5 minutes to monitor stock changes
        This is the main entry point for the scheduled action
        """
        try:
            _logger.info("CRON: Starting stock change monitor")

            # Monitor stock move lines in the last 10 minutes
            affected_products = self.get_products_from_stock_move_lines(minutes_ago=10)

            if affected_products:
                _logger.info(f"CRON: Found {len(affected_products)} affected products, creating queue jobs")

                # Create background jobs for stock sync
                self._create_stock_sync_jobs(affected_products)
            else:
                _logger.info("CRON: No products affected by stock moves in the last 10 minutes")

        except Exception as e:
            _logger.error(f"CRON: Error in stock change monitor: {e}")

        _logger.info("=== CRON: Stock Change Monitor Completed ===")
        return True

    # ==================== JOB CREATION ====================
    @api.model
    def _create_stock_sync_jobs(self, affected_products):
        """Create queue jobs for stock synchronization in batches"""
        BATCH_SIZE = 30  # Products per job

        total_products = len(affected_products)
        total_batches = (total_products + BATCH_SIZE - 1) // BATCH_SIZE

        _logger.info(f"Creating {total_batches} background jobs for {total_products} products")

        for i in range(0, total_products, BATCH_SIZE):
            batch = affected_products[i:i + BATCH_SIZE]

            # Create a background job for this batch
            self.with_delay(
                description=f"Sync PrestaShop Stock (Batch {(i // BATCH_SIZE) + 1}/{total_batches})"
            )._job_sync_stock_batch(batch)

        _logger.info(f"Created {total_batches} stock sync jobs")

    # ==================== BACKGROUND JOB METHOD ====================
    @api.model
    def _job_sync_stock_batch(self, products_batch):
        """Background job to sync stock for a batch of products"""
        if not products_batch:
            return

        _logger.info(f"JOB: Starting stock sync for batch of {len(products_batch)} products")

        BASE_URL = "https://outletna.com/api"
        WS_KEY = "86TN4NX1QDTBJC2XS9HUHL9RI53ANB3N"

        # Create basic auth header
        auth_string = f"{WS_KEY}:"
        auth_bytes = auth_string.encode('ascii')
        auth_b64 = base64.b64encode(auth_bytes).decode('ascii')
        headers = {
            'Authorization': f'Basic {auth_b64}',
            'Content-Type': 'application/xml'
        }

        sync_success = 0
        sync_failed = 0

        for product_info in products_batch:
            try:
                ean13 = product_info['ean13']
                new_qty = product_info['qty_available']
                product_name = product_info['name']

                _logger.info(f"JOB: Processing {product_name} (EAN13: {ean13}) - Stock: {new_qty}")

                # Search and update combination stock
                success = self._search_and_update_combination_stock(
                    ean13, new_qty, BASE_URL, headers
                )

                if success:
                    sync_success += 1
                    _logger.info(f"JOB: ✔ Successfully synced {product_name}")
                else:
                    sync_failed += 1
                    _logger.warning(f"JOB: ✘ Failed to sync {product_name}")

                # Small delay between products
                time.sleep(0.2)

            except Exception as e:
                sync_failed += 1
                _logger.error(f"JOB: Error processing {product_info.get('ean13', 'unknown')}: {e}")

        _logger.info(f"JOB: Batch completed - Success: {sync_success}, Failed: {sync_failed}")

    # ==================== HELPER METHODS ====================
    @api.model
    def _search_and_update_combination_stock(self, ean13, new_quantity, base_url, headers):
        """Search for combination by EAN13 and update its stock directly"""
        try:
            # Step 1: Search for combinations by EAN13
            search_url = f"{base_url}/combinations?filter[ean13]={ean13}&display=full"
            _logger.info(f"Searching combinations: {search_url}")

            combinations_root = self._get_xml(search_url, headers)
            if combinations_root is None:
                _logger.warning(f"Failed to get combinations response for EAN13 {ean13}")
                return False

            # Check if any combinations were found
            combinations = combinations_root.findall('.//combination')
            if not combinations:
                _logger.warning(f"No combinations found for EAN13 {ean13}")
                return False

            # Get the first combination
            combination = combinations[0]

            # Extract the combination ID
            combination_id_elem = combination.find('.//id')
            if combination_id_elem is None:
                _logger.warning(f"No combination ID found for EAN13 {ean13}")
                return False

            combination_id = combination_id_elem.text.strip()

            # Step 2: Get stock_available by combination ID
            stock_search_url = f"{base_url}/stock_availables?filter[id_product_attribute]={combination_id}&display=full"
            stock_root = self._get_xml(stock_search_url, headers)

            if stock_root is None:
                _logger.warning(f"Failed to get stock_availables for combination ID {combination_id}")
                return False

            # Find stock_available elements
            stock_availables = stock_root.findall('.//stock_available')
            if not stock_availables:
                _logger.warning(f"No stock_availables found for combination ID {combination_id}")
                return False

            updated_count = 0

            # Step 3: Update each stock_available
            for stock_available_elem in stock_availables:
                stock_id_elem = stock_available_elem.find('.//id')
                if stock_id_elem is None:
                    continue

                stock_id = stock_id_elem.text.strip()

                # Get current quantity for logging
                current_qty_elem = stock_available_elem.find('.//quantity')
                old_qty = current_qty_elem.text if current_qty_elem is not None else "unknown"

                _logger.info(f"Updating stock_available ID {stock_id} for combination {combination_id}")

                # Get the full stock_available details for update
                stock_detail_url = f"{base_url}/stock_availables/{stock_id}"
                stock_detail = self._get_xml(stock_detail_url, headers)

                if stock_detail is None:
                    _logger.warning(f"Failed to get stock_available details for ID {stock_id}")
                    continue

                stock_available_node = stock_detail.find('stock_available')
                if stock_available_node is None:
                    continue

                # Update quantity
                quantity_node = stock_available_node.find('quantity')
                if quantity_node is not None:
                    quantity_node.text = str(int(new_quantity))

                    # Prepare update XML
                    updated_doc = ET.Element('prestashop', xmlns_xlink="http://www.w3.org/1999/xlink")
                    updated_doc.append(stock_available_node)
                    updated_data = ET.tostring(updated_doc, encoding='utf-8', xml_declaration=True)

                    # Send update
                    response = self._put_xml(stock_detail_url, updated_data, headers)

                    if response and response.status_code in (200, 201):
                        _logger.info(
                            f"✔ PRESTASHOP SYNC: Updated stock_available {stock_id} for EAN13 {ean13} "
                            f"(combination {combination_id}): {old_qty} → {int(new_quantity)}"
                        )
                        updated_count += 1
                    else:
                        _logger.warning(f"Failed to update stock_available {stock_id}")

                # Small delay between updates
                time.sleep(0.1)

            return updated_count > 0

        except Exception as e:
            _logger.error(f"Error processing combination for EAN13 {ean13}: {e}")
            return False

    @api.model
    def _get_xml(self, url, headers):
        """Helper method to GET XML from PrestaShop"""
        try:
            resp = requests.get(url, headers=headers, timeout=60)
            if resp.status_code != 200:
                _logger.warning(f"GET failed: {url} | Status: {resp.status_code}")
                return None
            return ET.fromstring(resp.content)
        except Exception as e:
            _logger.warning(f"Exception during GET: {url} | Error: {e}")
            return None

    @api.model
    def _put_xml(self, url, data, headers):
        """Helper method to PUT XML to PrestaShop"""
        try:
            resp = requests.put(url, data=data, headers=headers, timeout=30)
            if resp.status_code not in (200, 201):
                _logger.warning(f"PUT failed: {url} | Status: {resp.status_code}")
                return None
            return resp
        except Exception as e:
            _logger.warning(f"Exception during PUT: {url} | Error: {e}")
            return None

    # ==================== STOCK MONITORING ====================
    @api.model
    def get_products_from_stock_move_lines(self, minutes_ago=10):
        """
        Get products affected by stock move lines in the last X minutes
        Returns list of products with their current stock quantities
        """
        # Calculate the time threshold
        time_threshold = datetime.now() - timedelta(minutes=minutes_ago)

        # Search for stock move lines that were updated in the last X minutes
        recent_move_lines = self.env['stock.move.line'].search([
            '|',
            ('create_date', '>=', time_threshold),
            ('write_date', '>=', time_threshold),
            ('product_id.default_code', '!=', False),
            ('product_id.default_code', '!=', ''),
            ('state', '=', 'done'),
        ], order='write_date desc')

        if not recent_move_lines:
            _logger.info("No stock move lines found in the specified time period")
            return []

        # Get unique products from the move lines
        product_ids = set()
        for move_line in recent_move_lines:
            product_ids.add(move_line.product_id.id)

        # Get current stock quantities for these products
        affected_products = []
        for product_id in product_ids:
            product = self.env['product.product'].browse(product_id)
            if product and product.default_code:
                affected_products.append({
                    'id': product.id,
                    'name': product.name,
                    'ean13': product.default_code,
                    'qty_available': product.qty_available,
                    'write_date': product.write_date
                })
                _logger.info(
                    f"Product affected: {product.name} (EAN13: {product.default_code}) - "
                    f"Current Stock: {product.qty_available}"
                )

        _logger.info(f"=== Found {len(affected_products)} products to sync ===")
        return affected_products

    # ==================== UTILITY METHODS ====================
    @api.model
    def log_stock_move_lines_for_product(self, ean13, minutes_ago=10):
        """Log stock move lines for a specific product by EAN13"""
        time_threshold = datetime.now() - timedelta(minutes=minutes_ago)

        # Find the product
        product = self.env['product.product'].search([
            ('default_code', '=', ean13)
        ], limit=1)

        if not product:
            _logger.info(f"Product with EAN13 {ean13} not found")
            return False

        # Check recent move lines for this product
        recent_move_lines = self.env['stock.move.line'].search([
            ('product_id', '=', product.id),
            '|',
            ('create_date', '>=', time_threshold),
            ('write_date', '>=', time_threshold),
        ], order='write_date desc')

        if recent_move_lines:
            _logger.info(f"Recent move lines for {product.name} (EAN13: {ean13}):")
            for move_line in recent_move_lines:
                _logger.info(
                    f"  - Qty: {move_line.qty_done} | "
                    f"{move_line.location_id.name} → {move_line.location_dest_id.name}"
                )
                _logger.info(f"    Date: {move_line.write_date} | State: {move_line.state}")
        else:
            _logger.info("No recent move lines found for this product")

        return True

    # ==================== MANUAL SYNC ACTION ====================
    def action_sync_stock_to_prestashop(self):
        """Manual action to sync selected products' stock to PrestaShop"""
        if not self:
            raise UserError("No product selected.")

        # Filter products with EAN13
        products_to_sync = []
        skipped_count = 0

        for product in self:
            if not product.default_code:
                skipped_count += 1
                _logger.warning(f"Skipped: {product.display_name} (missing EAN13)")
                continue

            products_to_sync.append({
                'id': product.id,
                'name': product.name,
                'ean13': product.default_code,
                'qty_available': product.qty_available,
                'write_date': product.write_date
            })

        if not products_to_sync:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'No Products to Sync',
                    'message': f'{skipped_count} products skipped (missing EAN13).',
                    'type': 'warning',
                    'sticky': False,
                }
            }

        # Create queue jobs
        self._create_stock_sync_jobs(products_to_sync)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Stock Sync Started!',
                'message': f'{len(products_to_sync)} products queued for stock sync. Check Queue Jobs menu for progress.',
                'type': 'success',
                'sticky': True,
            }
        }

class pickingmaximum(models.Model):
    _name ='picking.maximum'
    _description = 'maiximum number for create order'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    number_max = fields.Integer(string="Number max")

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
    pays = fields.Char(string="Pays")
    status = fields.Selection([
        ('en_cours_traitement', 'En cours de traitement'),
        ('en_cours_preparation', 'En cours de préparation'),
        ('commande_prepare', 'Commande préparée'),
        ('ready_to_delivery', 'Prêt à être livré'),
        ('en_cours_de_livraison', 'En cours de Livraison'),
        ('delivered', 'Livré'),
        ('annuler', 'Annulé'),
    ], string="Statut", default='en_cours_traitement', tracking=True)

    batch_number = fields.Char(
        string="Numéro de Batch",
        readonly=True,
        help="Numéro de lot pour grouper les commandes (ex: S000001)"
    )

    total_qty = fields.Float(
        string="Quantité Totale",
        compute="_compute_total_qty",
        store=True
    )

    # Shipment fields
    shipment_number = fields.Char(
        string="Numéro de Colis",
        readonly=True,
        tracking=True,
        help="Numéro de suivi du colis"
    )

    label_url = fields.Char(
        string="URL Étiquette",
        readonly=True,
        help="URL pour imprimer l'étiquette du colis"
    )

    shipment_created = fields.Boolean(
        string="Colis Créé",
        default=False,
        readonly=True
    )
    sale_order_id = fields.Many2one(
        'sale.order',
        string="Bon de Commande",
        readonly=True,
        ondelete='set null',
        help="Bon de commande lié à cette commande website"
    )
    # Champ texte pour afficher la référence en lecture (safe)
    sale_order_ref = fields.Char(
        string="Ref. Bon de Commande",
        readonly=True,
        help="Nom / référence du bon de commande (copie textuelle pour affichage sécurisé)"
    )
    BASE_URL = "https://outletna.com/api"
    WS_KEY = "86TN4NX1QDTBJC2XS9HUHL9RI53ANB3N"

    @api.depends('line_ids.quantity')
    def _compute_total_qty(self):
        """Calculate total quantity of all lines"""
        for order in self:
            order.total_qty = sum(order.line_ids.mapped('quantity'))

    def _get_next_batch_number(self):
        """Generate next batch number (S000001, S000002, etc.)"""
        last_batch = self.search([('batch_number', '!=', False)], order='batch_number desc', limit=1)
        if not last_batch or not last_batch.batch_number:
            return 'S000001'
        try:
            last_number = int(last_batch.batch_number[1:])
            return f'S{last_number + 1:06d}'
        except:
            return 'S000001'
    '''pour deploiement'''
    def action_create_shipment(self):
        """Create shipment via PostShipping API"""
        self.ensure_one()

        if self.status != 'ready_to_delivery':
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Erreur',
                    'message': 'Le colis ne peut être créé que pour les commandes avec le statut "Prêt à être livré".',
                    'type': 'warning'
                }
            }

        if self.shipment_created:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Info',
                    'message': f'Un colis a déjà été créé pour cette commande (N°: {self.shipment_number}).',
                    'type': 'info'
                }
            }

        # Prepare API request
        url = "https://api.postshipping.com/api2/shipments"
        headers = {
            'Content-Type': 'application/json',
            'Token': '45E6880FBAD104CFA6BBCF9407154187'
        }

        # Calculate total weight (1kg per item as default)
        total_weight = self.total_qty or 1

        payload = [{
            "ThirdPartyToken": "",
            "SenderDetails": {
                "SenderName": "TEST Outletna",
                "SenderCompanyName": "TEST Outletna",
                "SenderCountryCode": "MA",
                "SenderAdd1": "Casablanca",
                "SenderAdd2": "Casablanca",
                "SenderAdd3": "",
                "SenderAddCity": "Casablanca",
                "SenderAddState": "Casablanca",
                "SenderAddPostcode": "20000",
                "SenderPhone": "99999999",
                "SenderEmail": "test@outletna.com",
                "SenderFax": "",
                "SenderKycType": "Passport",
                "SenderKycNumber": "P00001",
                "SenderReceivingCountryTaxID": ""
            },
            "ReceiverDetails": {
                "ReceiverName": self.client_name or "Client",
                "ReceiverCompanyName": self.client_name or "Client",
                "ReceiverCountryCode": "MA",
                "ReceiverAdd1": self.adresse or "Address",
                "ReceiverAdd2": self.second_adresse or "",
                "ReceiverAdd3": "",
                "ReceiverAddCity": self.city or "Casablanca",
                "ReceiverAddState": self.city or "Casablanca",
                "ReceiverAddPostcode": self.postcode or "20000",
                "ReceiverMobile": self.mobile or self.phone or "0600000000",
                "ReceiverPhone": self.phone or self.mobile or "0600000000",
                "ReceiverEmail": self.email or "client@example.com",
                "ReceiverAddResidential": "N",
                "ReceiverFax": "",
                "ReceiverKycType": "Passport",
                "ReceiverKycNumber": "P00005"
            },
            "PackageDetails": {
                "GoodsDescription": f"Commande {self.reference}",
                "CustomValue": 100.00,
                "CustomCurrencyCode": "MAD",
                "InsuranceValue": "0.00",
                "InsuranceCurrencyCode": "MAD",
                "ShipmentTerm": "",
                "GoodsOriginCountryCode": "MA",
                "DeliveryInstructions": "Livraison commande e-commerce",
                "Weight": total_weight,
                "WeightMeasurement": "KG",
                "NoOfItems": int(self.total_qty),
                "CubicL": 30,
                "CubicW": 30,
                "CubicH": 30,
                "CubicWeight": 0.0,
                "ServiceTypeName": "EN",
                "BookPickUP": False,
                "AlternateRef": "",
                "SenderRef1": self.reference or self.ticket_id,
                "SenderRef2": "",
                "SenderRef3": "",
                "DeliveryAgentCode": "",
                "DeliveryRouteCode": "",
                "BusinessType": "B2C",
                "ShipmentResponseItem": [{
                    "ItemAlt": "",
                    "ItemNoOfPcs": 1,
                    "ItemCubicL": 30,
                    "ItemCubicW": 30,
                    "ItemCubicH": 30,
                    "ItemWeight": total_weight,
                    "ItemCubicWeight": 0,
                    "ItemDescription": "Produits divers",
                    "ItemCustomValue": 100.00,
                    "ItemCustomCurrencyCode": "MAD",
                    "Notes": f"Commande {self.reference or self.ticket_id}",
                    "Pieces": [{
                        "HarmonisedCode": "hs001",
                        "GoodsDescription": "Produits e-commerce",
                        "Content": "Divers",
                        "Notes": "Articles commande",
                        "SenderRef1": self.reference,
                        "Quantity": int(self.total_qty),
                        "Weight": total_weight,
                        "ManufactureCountryCode": "MA",
                        "OriginCountryCode": "MA",
                        "CurrencyCode": "MAD",
                        "CustomsValue": 100.00
                    }]
                }],
                "CODAmount": 0.0,
                "CODCurrencyCode": "MAD",
                "Bag": 0,
                "Notes": f"Commande Website",
                "OriginLocCode": "",
                "BagNumber": 0,
                "DeadWeight": total_weight,
                "ReasonExport": "",
                "DestTaxes": 0.0,
                "Security": 0.0,
                "Surcharge": 0.0,
                "ReceiverTaxID": "",
                "OrderNumber": self.ticket_id,
                "Incoterms": "CIF",
                "ClearanceReference": ""
            },
            "PickupDetails": {
                "ReadyTime": fields.Datetime.now().strftime("%Y/%m/%d 09:00:00"),
                "CloseTime": fields.Datetime.now().strftime("%Y/%m/%d 18:00:00"),
                "SpecialInstructions": "TEST Pickup commande e-commerce",
                "Address1": "Casablanca",
                "Address2": "Casablanca",
                "Address3": "",
                "AddressState": "Casablanca",
                "AddressCity": "Casablanca",
                "AddressPostalCode": "20000",
                "AddressCountryCode": "MA"
            }
        }]

        try:
            _logger.info(f"Creating shipment for order {self.ticket_id}")
            _logger.debug(f"Payload: {json.dumps(payload, indent=2)}")

            response = requests.post(url, headers=headers, json=payload, timeout=30)
            response.raise_for_status()

            result = response.json()
            _logger.info(f"Shipment API response: {result}")

            if result and len(result) > 0:
                shipment_data = result[0]

                if shipment_data.get('ShipmentNumber'):
                    # Update order with shipment info
                    self.write({
                        'shipment_number': shipment_data.get('ShipmentNumber'),
                        'label_url': shipment_data.get('LabelURL'),
                        'shipment_created': True,
                        'status': 'en_cours_de_livraison'
                    })

                    # Post message in chatter
                    self.message_post(
                        body=f"Colis créé avec succès<br/>"
                             f"Numéro de colis: <b>{shipment_data.get('ShipmentNumber')}</b><br/>"
                             f"Référence: {shipment_data.get('SenderRef')}<br/>"
                             f"<a href='{shipment_data.get('LabelURL')}' target='_blank'>Voir l'étiquette</a>"
                    )

                    _logger.info(f"Shipment created successfully: {shipment_data.get('ShipmentNumber')}")

                    return {
                        'type': 'ir.actions.client',
                        'tag': 'display_notification',
                        'params': {
                            'title': 'Succès',
                            'message': f"Colis créé avec succès!<br/>Numéro: {shipment_data.get('ShipmentNumber')}",
                            'type': 'success',
                            'sticky': True
                        }
                    }
                else:
                    error_msg = shipment_data.get('ErrMessage', 'Erreur inconnue')
                    _logger.error(f"Shipment creation failed: {error_msg}")

                    self.message_post(
                        body=f"Erreur lors de la création du colis: {error_msg}"
                    )

                    return {
                        'type': 'ir.actions.client',
                        'tag': 'display_notification',
                        'params': {
                            'title': 'Erreur',
                            'message': f"Erreur API: {error_msg}",
                            'type': 'danger'
                        }
                    }

        except requests.exceptions.RequestException as e:
            _logger.error(f"Error calling PostShipping API: {str(e)}")

            self.message_post(
                body=f"Erreur de connexion à l'API: {str(e)}"
            )

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Erreur',
                    'message': f"Erreur de connexion: {str(e)}",
                    'type': 'danger'
                }
            }
        except Exception as e:
            _logger.error(f"Unexpected error creating shipment: {str(e)}")

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Erreur',
                    'message': f"Erreur inattendue: {str(e)}",
                    'type': 'danger'
                }
            }

    def action_print_label(self):
        """Open label URL in new window"""
        self.ensure_one()

        if not self.label_url:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Erreur',
                    'message': "Aucune étiquette disponible. Veuillez d'abord créer le colis.",
                    'type': 'warning'
                }
            }

        return {
            'type': 'ir.actions.act_url',
            'url': self.label_url,
            'target': 'new',
        }
    '''pour deploiement'''
    def action_open_tracking(self):
        self.ensure_one()

        if not self.shipment_number:
            raise UserError("Aucun numéro de colis disponible.")
        '''
        tracking_url = f"https://www.aftership.com/track?t={self.shipment_number}&c=medafrica" '''
        tracking_url = f"https://medafrica-log.com/tracking/?lang=fr&fusion_privacy_store_ip_ua=false&fusion_privacy_expiration_interval=48&privacy_expiration_action=anonymize"
        return {
            "type": "ir.actions.act_url",
            "url": tracking_url,
            "target": "new",
        }

    def action_create_batch_sale_orders_dynamic(self):
        """
        Create sale orders from website orders.
        - Remove maximum quantity restriction.
        - Keep the same batch number for all orders processed in this run.
        - Do NOT create stock picking batches.
        """
        # Get all orders with status 'en_cours_traitement' ordered by date
        orders_to_process = self.search([
            ('status', '=', 'en_cours_traitement')
        ], order='date_commande, id')

        if not orders_to_process:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Info',
                    'message': 'Aucune commande à traiter.',
                    'type': 'info'
                }
            }

        batches_created = 0
        processed_ids = []

        _logger.info(f"Starting processing {len(orders_to_process)} website orders")

        # Main loop: process each order
        for order in orders_to_process:
            if order.id in processed_ids:
                continue

            self._create_sale_orders_for_batch([order])
            processed_ids.append(order.id)
            batches_created += 1

        final_message = (
            f'{batches_created} batch(es) traité(s)<br/>'
            f'{len(processed_ids)}/{len(orders_to_process)} commandes traitées'
        )

        _logger.info(f"Website order processing completed: {batches_created} batch(es)")

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Traitement Terminé',
                'message': final_message,
                'type': 'success',
                'sticky': True
            }
        }
    def _create_sale_orders_for_batch(self, orders):
        """Create sale orders for a batch of website orders without picking batch"""
        if not orders:
            return

        # Generate batch number (keep same for all orders in this call)
        batch_number = self._get_next_batch_number()
        _logger.info(f"Creating sale orders for batch {batch_number} with {len(orders)} order(s)")

        for order in orders:
            # Find or create partner
            partner = self.env['res.partner'].search([('name', 'ilike', order.client_name)], limit=1)
            if not partner:
                partner = self.env['res.partner'].create({
                    'name': order.client_name or "Client Website",
                    'email': order.email or False,
                    'phone': order.phone or order.mobile or False,
                    'street': order.adresse or '',
                    'street2': order.second_adresse or '',
                    'city': order.city or '',
                    'zip': order.postcode or '',
                })
                _logger.info(f"New partner created: {partner.name}")

            # Create sale order
            sale_order_vals = {
                'partner_id': partner.id,
                'date_order': order.date_commande or fields.Datetime.now(),
                'client_order_ref': order.reference,
                'origin': f"{order.reference or order.ticket_id} - Batch: {batch_number}",
                'note': f"Commande Website\nRéférence: {order.reference or order.ticket_id}\nBatch: {batch_number}",
            }

            sale_order = self.env['sale.order'].create(sale_order_vals)
            _logger.info(f"Sale order {sale_order.name} created for website order {order.ticket_id}")

            # Create order lines
            for line in order.line_ids:
                if not line.product_id:
                    _logger.warning(f"Product missing for line (Barcode: {line.code_barre})")
                    continue

                line_vals = {
                    'order_id': sale_order.id,
                    'product_id': line.product_id.id,
                    'product_uom_qty': line.quantity,
                    'price_unit': line.price,
                    'discount': line.discount if hasattr(line, 'discount') else 0,
                }
                self.env['sale.order.line'].create(line_vals)

            # Confirm the sale order
            try:
                sale_order.action_confirm()
                _logger.info(f"Sale order {sale_order.name} confirmed successfully")
            except Exception as e:
                _logger.error(f"Error confirming sale order {sale_order.name}: {str(e)}")

            # Update website order status, batch number and link to sale order
            try:
                order.write({
                    'status': 'en_cours_preparation',
                    'batch_number': batch_number,
                    'sale_order_id': sale_order.id,
                    'sale_order_ref': sale_order.name or False,
                })
            except Exception as e:
                _logger.exception(f"Failed to write sale_order_id for website order {order.id}: {e}")
                order.write({
                    'status': 'en_cours_preparation',
                    'batch_number': batch_number,
                    'sale_order_ref': sale_order.name or False,
                    'sale_order_id': False,
                })

            # Post message in chatter
            '''
            order.message_post(
                body=f"Commande de vente créée: {sale_order.name}<br/>"
                     f"Batch: {batch_number}<br/>"
                     f"Quantité totale: {order.total_qty}"
            )
            '''
            _logger.info(
                f"Website order {order.ticket_id} updated - Status: en_cours_preparation, Batch: {batch_number}"
            )

    '''
    def action_create_batch_sale_orders_dynamic(self):
        """
        Create batches with maximum quantity of 10.
        Process orders with status 'en_cours_traitement' and fill batch up to 10 units.
        """
        config = self.env['picking.maximum'].search([], limit=1)
        MAX_QTY = config.number_max if config and config.number_max > 0 else 10
        current_max = MAX_QTY

        # Get all orders with status 'en_cours_traitement' ordered by date
        orders_to_process = self.search([
            ('status', '=', 'en_cours_traitement')
        ], order='date_commande, id')

        if not orders_to_process:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Info',
                    'message': 'Aucune commande à traiter.',
                    'type': 'info'
                }
            }

        batches_created = 0
        current_batch = []
        processed_ids = []

        _logger.info(f"Starting batch processing with MAX_QTY={MAX_QTY}")
        _logger.info(f"Found {len(orders_to_process)} orders to process")

        # Main loop: go through each order
        for order in orders_to_process:
            # Skip if already processed
            if order.id in processed_ids:
                continue

            order_qty = order.total_qty
            _logger.info(f"Checking order {order.ticket_id}: qty={order_qty}, current_max={current_max}")

            # Check if order fits in current max
            if order_qty <= current_max:
                # Take this order
                current_batch.append(order)
                processed_ids.append(order.id)
                current_max -= order_qty
                _logger.info(f"Order {order.ticket_id} added to batch. New max: {current_max}")

                # If current_max reaches 0, create batch immediately
                if current_max == 0:
                    _logger.info(f"Max reached 0! Creating batch with {len(current_batch)} orders")
                    self._create_sale_orders_for_batch(current_batch)
                    batches_created += 1
                    current_batch = []
                    current_max = MAX_QTY
                    _logger.info(f"Batch created. Reset max to {MAX_QTY}")

            else:
                # Order doesn't fit in current max, search for smaller orders
                _logger.info(f"Order {order.ticket_id} (qty={order_qty}) doesn't fit in current_max={current_max}")
                _logger.info(f"Searching for smaller orders that fit...")

                # Look for other orders that fit in remaining capacity
                remaining_orders = [
                    o for o in orders_to_process
                    if o.id not in processed_ids and o.total_qty <= current_max
                ]

                if remaining_orders:
                    _logger.info(f"Found {len(remaining_orders)} smaller orders that fit")

                    # Add all fitting orders
                    for small_order in remaining_orders:
                        if small_order.total_qty <= current_max:
                            current_batch.append(small_order)
                            processed_ids.append(small_order.id)
                            current_max -= small_order.total_qty
                            _logger.info(
                                f"Added order {small_order.ticket_id} (qty={small_order.total_qty}). New max: {current_max}")

                            if current_max == 0:
                                break

                # If we have orders in batch, create it
                if current_batch:
                    _logger.info(f"Creating batch with {len(current_batch)} orders. Remaining max: {current_max}")
                    self._create_sale_orders_for_batch(current_batch)
                    batches_created += 1
                    current_batch = []
                    current_max = MAX_QTY
                    _logger.info(f"Batch created. Reset max to {MAX_QTY}")

                # Now check if the original order (that didn't fit) can fit in new max
                if order.id not in processed_ids and order_qty <= current_max:
                    current_batch.append(order)
                    processed_ids.append(order.id)
                    current_max -= order_qty
                    _logger.info(f"Order {order.ticket_id} now added to new batch. New max: {current_max}")

                    if current_max == 0:
                        _logger.info(f"Max reached 0! Creating batch")
                        self._create_sale_orders_for_batch(current_batch)
                        batches_created += 1
                        current_batch = []
                        current_max = MAX_QTY
                        _logger.info(f"Reset max to {MAX_QTY}")

        # Process any remaining orders in the last batch
        if current_batch:
            _logger.info(f"Creating final batch with {len(current_batch)} remaining orders")
            self._create_sale_orders_for_batch(current_batch)
            batches_created += 1

        final_message = (
            f'{batches_created} batch(es) créé(s)<br/>'
            f'{len(processed_ids)}/{len(orders_to_process)} commandes traitées'
        )
        
        final_message = (
            f'{batches_created} batch(es) créé(s)<br/>'
            f'Capacité restante: {current_max}/{MAX_QTY}<br/>'
            f'{len(processed_ids)}/{len(orders_to_process)} commandes traitées'
        )
        
        _logger.info(f"Batch processing completed: {batches_created} batches created")

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Traitement Terminé',
                'message': final_message,
                'type': 'success',
                'sticky': True
            }
        }

    def _create_sale_orders_for_batch(self, orders):
        """Create sale orders for a batch of website orders"""
        if not orders:
            return

        # Generate batch number
        batch_number = self._get_next_batch_number()
        _logger.info(f"Creating sale orders for batch {batch_number} with {len(orders)} order(s)")

        created_pickings = []  # List to store all created pickings

        for order in orders:
            # Find or create partner
            partner = self.env['res.partner'].search([('name', 'ilike', order.client_name)], limit=1)
            if not partner:
                partner = self.env['res.partner'].create({
                    'name': order.client_name or "Client Website",
                    'email': order.email or False,
                    'phone': order.phone or order.mobile or False,
                    'street': order.adresse or '',
                    'street2': order.second_adresse or '',
                    'city': order.city or '',
                    'zip': order.postcode or '',
                })
                _logger.info(f"New partner created: {partner.name}")

            # Create sale order
            sale_order_vals = {
                'partner_id': partner.id,
                'date_order': order.date_commande or fields.Datetime.now(),
                'client_order_ref' : order.reference,
                'origin': f"{order.reference or order.ticket_id} - Batch: {batch_number}",
                'note': f"Commande Website\nRéférence: {order.reference or order.ticket_id}\nBatch: {batch_number}",
            }

            sale_order = self.env['sale.order'].create(sale_order_vals)
            _logger.info(f"Sale order {sale_order.name} created for website order {order.ticket_id}")

            # Create order lines
            for line in order.line_ids:
                if not line.product_id:
                    _logger.warning(f"Product missing for line (Barcode: {line.code_barre})")
                    continue

                line_vals = {
                    'order_id': sale_order.id,
                    'product_id': line.product_id.id,
                    'product_uom_qty': line.quantity,
                    'price_unit': line.price,
                    'discount': line.discount if hasattr(line, 'discount') else 0,
                }
                self.env['sale.order.line'].create(line_vals)

            # Confirm the sale order
            try:
                sale_order.action_confirm()
                _logger.info(f"Sale order {sale_order.name} confirmed successfully")

                # Collect the delivery pickings created from the sale order
                pickings = sale_order.picking_ids.filtered(lambda p: p.state not in ('done', 'cancel'))
                if pickings:
                    created_pickings.extend(pickings.ids)
                    _logger.info(f"Found {len(pickings)} picking(s) for sale order {sale_order.name}")

            except Exception as e:
                _logger.error(f"Error confirming sale order {sale_order.name}: {str(e)}")

            # Update website order status, batch number and link to sale order
            try:
                order.write({
                    'status': 'en_cours_preparation',
                    'batch_number': batch_number,
                    'sale_order_id': sale_order.id,
                    'sale_order_ref': sale_order.name or False,
                })
            except Exception as e:
                _logger.exception(f"Failed to write sale_order_id for website order {order.id}: {e}")
                order.write({
                    'status': 'en_cours_preparation',
                    'batch_number': batch_number,
                    'sale_order_ref': sale_order.name or False,
                    'sale_order_id': False,
                })

            # Post message in chatter
            order.message_post(
                body=f"Commande de vente créée: {sale_order.name}<br/>"
                     f"Batch: {batch_number}<br/>"
                     f"Quantité totale: {order.total_qty}"
            )

            _logger.info(
                f"Website order {order.ticket_id} updated - Status: en_cours_preparation, Batch: {batch_number}"
            )

        # Create batch picking for all created pickings
        if created_pickings:
            try:
                self._create_picking_batch(created_pickings, batch_number)
                _logger.info(f"Batch picking created for batch {batch_number} with {len(created_pickings)} picking(s)")
            except Exception as e:
                _logger.error(f"Error creating batch picking for batch {batch_number}: {str(e)}")
    
    def _create_picking_batch(self, picking_ids, batch_number):
        """Create a batch picking for the given pickings"""
        if not picking_ids:
            return

        pickings = self.env['stock.picking'].browse(picking_ids)

        # Check if all pickings belong to the same company
        companies = pickings.mapped('company_id')
        if len(companies) > 1:
            _logger.warning(f"Pickings belong to multiple companies. Creating separate batches.")
            # Group by company
            for company in companies:
                company_pickings = pickings.filtered(lambda p: p.company_id == company)
                self._create_single_batch(company_pickings, batch_number)
        else:
            self._create_single_batch(pickings, batch_number)
    
    def _create_single_batch(self, pickings, batch_number):
        """Create a single batch for the given pickings"""
        if not pickings:
            return

        # Get the first picking's company and picking type
        company = pickings[0].company_id
        picking_type = pickings[0].picking_type_id

        # Create the batch picking
        batch_vals = {
            'user_id': self.env.user.id,  # Current user
            'company_id': company.id,
            'picking_type_id': picking_type.id,
        }

        batch = self.env['stock.picking.batch'].create(batch_vals)
        _logger.info(f"Batch picking {batch.name} created")

        # Attach pickings to the batch
        pickings.write({'batch_id': batch.id})
        _logger.info(f"Attached {len(pickings)} picking(s) to batch {batch.name}")

        # Confirm the batch (not draft)
        try:
            batch.action_confirm()
            _logger.info(f"Batch {batch.name} confirmed successfully")
        except Exception as e:
            _logger.error(f"Error confirming batch {batch.name}: {str(e)}")

        # Post message to all related website orders
        for picking in pickings:
            # Find related website order through sale order
            website_order = self.search([('sale_order_id', '=', picking.sale_id.id)], limit=1)
            if website_order:
                website_order.message_post(
                    body=f"Batch de préparation créé: <b>{batch.name}</b><br/>"
                         f"Bon de livraison: {picking.name}<br/>"
                         f"Responsable: {self.env.user.name}"
                )

        return batch
    '''
    '''pour depoloiement'''
    @api.model
    def cron_check_sale_order_ref_status(self):
        """Cron to check status in stock picking model."""

        # Only take orders in 'en_cours_preparation'
        orders = self.search([
            ('status', '=', 'en_cours_preparation'),
            ('sale_order_ref', '!=', False),
        ])

        if not orders:
            _logger.info("[CRON] No orders found in en_cours_preparation.")
            return True

        _logger.info(f"[CRON] Checking status for {len(orders)} orders...")

        Picking = self.env['stock.picking']

        for order in orders:
            picking = Picking.search([
                ('origin', '=', order.sale_order_ref)
            ], limit=1)

            if not picking:
                _logger.info(f"[CRON] No picking found for order {order.sale_order_ref}")
                continue

            # If picking is done → only update orders that are still in en_cours_preparation
            if picking.state == 'done':

                if order.status == 'en_cours_preparation':
                    order.status = 'commande_prepare'
                    _logger.info(
                        f"[CRON] Order {order.ticket_id}: picking done → status changed to commande_prepare"
                    )
                else:
                    # Should not happen because we filtered, but safe check
                    _logger.info(
                        f"[CRON] Order {order.ticket_id} picking done but status is '{order.status}', not updated."
                    )

            else:
                _logger.info(
                    f"[CRON] Order {order.ticket_id} still not ready (picking state: {picking.state})"
                )

        return True

    @api.model
    def cron_check_sale_order_invoice_status(self):
        """Cron to check if related sale order is fully invoiced."""

        _logger.info("[CRON] Checking sale order invoice status...")

        # Get orders to check
        orders = self.search([
            ('status', '=', 'commande_prepare'),
            ('sale_order_ref', '!=', False),
        ])

        if not orders:
            _logger.info("[CRON] No orders found in commande_prepare.")
            return True

        SaleOrder = self.env['sale.order']

        _logger.info(f"[CRON] Checking invoice status for {len(orders)} orders...")

        for order in orders:

            sale = SaleOrder.search([
                ('name', '=', order.sale_order_ref)
            ], limit=1)

            if not sale:
                _logger.info(f"[CRON] No sale order found for ref {order.sale_order_ref}")
                continue

            _logger.info(
                f"[CRON] Order {order.ticket_id} → sale {sale.name} "
                f"→ invoice_status = {sale.invoice_status}"
            )

            # ONLY update invoiced orders
            if sale.invoice_status == 'invoiced':

                if order.status not in ['en_cours_de_livraison', 'delivered', 'annuler']:
                    order.status = 'ready_to_delivery'
                    _logger.info(
                        f"[CRON] Order {order.ticket_id} updated to ready_to_delivery"
                    )
                else:
                    _logger.info(
                        f"[CRON] Order {order.ticket_id} already in final state ({order.status})"
                    )

            else:
                # Just skip and continue, DO NOT STOP the cron
                _logger.info(
                    f"[CRON] Order {order.ticket_id} skipped "
                    f"(invoice_status = {sale.invoice_status})"
                )

        # RETURN ONLY AFTER LOOP FINISHES
        _logger.info("[CRON] Invoice status check finished.")
        return True

    @api.model
    def sync_status_to_prestashop(self):
        _logger.info("Starting PrestaShop status synchronization...")

        # Sync only the supported statuses
        orders_to_sync = self.search([
            ('status', 'in', ['en_cours_de_livraison','ready_to_delivery', 'delivered','annuler']),
            ('reference', '!=', False),
        ])

        _logger.info(f"Found {len(orders_to_sync)} orders to sync")

        synced_count = 0
        error_count = 0

        for order in orders_to_sync:
            try:
                if self._update_prestashop_order_status(order):
                    synced_count += 1
                    _logger.info(f"Successfully synced order {order.reference} with status {order.status}")
                else:
                    error_count += 1
                    _logger.error(f"Failed to sync order {order.reference}")
            except Exception as e:
                error_count += 1
                _logger.error(f"Error syncing order {order.reference}: {str(e)}")

        _logger.info(f"Sync completed. Synced: {synced_count}, Errors: {error_count}")
        return {
            'synced': synced_count,
            'errors': error_count,
            'total': len(orders_to_sync)
        }

    def _find_prestashop_order_by_reference(self, reference):
        """
        Find PrestaShop order ID by reference using basic authentication
        """
        try:
            url = f"{self.BASE_URL}/orders"
            params = {
                'filter[reference]': reference,
            }

            response = requests.get(url, auth=(self.WS_KEY, ''), params=params, timeout=30)
            response.raise_for_status()

            root = ET.fromstring(response.content)
            order_elem = root.find('.//order')

            if order_elem is not None and 'id' in order_elem.attrib:
                order_id = order_elem.attrib['id']
                _logger.info(f"Found PrestaShop order ID {order_id} for reference {reference}")
                return order_id
            else:
                _logger.warning(f"No order found in PrestaShop with reference {reference}")
                return None

        except requests.exceptions.RequestException as e:
            _logger.error(f"HTTP error while searching for order: {str(e)}")
            return None
        except ET.ParseError as e:
            _logger.error(f"XML parsing error: {str(e)}")
            return None
        except Exception as e:
            _logger.error(f"Unexpected error while searching for order: {str(e)}")
            return None

    def _update_prestashop_order_status(self, order):
        """
        Update PrestaShop order status based on Odoo order status
        """
        try:
            prestashop_order_id = self._find_prestashop_order_by_reference(order.reference)

            if not prestashop_order_id:
                _logger.warning(f"Order with reference '{order.reference}' not found in PrestaShop")
                return False

            # Mapping Odoo status to PrestaShop current_state ID
            status_mapping = {
                'en_cours_de_livraison': 20,
                'delivered': 5,
                'annuler':6,
            }

            prestashop_status_id = status_mapping.get(order.status)

            if not prestashop_status_id:
                _logger.warning(f"No PrestaShop status mapping for Odoo status '{order.status}'")
                return False

            return self._update_prestashop_order_status_by_id(prestashop_order_id, prestashop_status_id)

        except Exception as e:
            _logger.error(f"Error updating PrestaShop order status: {str(e)}")
            return False

    def _update_prestashop_order_status_by_id(self, order_id, status_id):
        """
        Update the current_state of a PrestaShop order
        """
        try:
            url = f"{self.BASE_URL}/orders/{order_id}"
            response = requests.get(url, auth=(self.WS_KEY, ''))
            response.raise_for_status()

            root = ET.fromstring(response.content)

            current_state = root.find('.//current_state')
            if current_state is not None:
                current_state.text = str(status_id)
            else:
                _logger.error(f"Could not find current_state field in order {order_id}")
                return False

            xml_data = ET.tostring(root, encoding='utf-8', method='xml')

            headers = {'Content-Type': 'application/xml'}

            update_response = requests.put(
                url,
                auth=(self.WS_KEY, ''),
                data=xml_data,
                headers=headers
            )
            update_response.raise_for_status()

            _logger.info(f"Successfully updated PrestaShop order {order_id} to status {status_id}")
            return True

        except requests.exceptions.RequestException as e:
            _logger.error(f"HTTP error while updating order status: {str(e)}")
            return False
        except ET.ParseError as e:
            _logger.error(f"XML parsing error: {str(e)}")
            return False
        except Exception as e:
            _logger.error(f"Unexpected error while updating order status: {str(e)}")
            return False
    @api.model
    def _create_shippement_number_to_prestashop(self):
        """Send shipment_number to Prestashop (Basic Auth + XML)."""
        _logger.info("[CRON] Sync shipping_number → Prestashop started...")
        orders = self.search([
            ('status', '=', 'en_cours_de_livraison'),
            ('shipment_number', '!=', False),
            ('reference', '!=', False),
        ])
        if not orders:
            _logger.info("[CRON] No orders needing sync.")
            return True
        for order in orders:
            try:
                # ---- 1) FIND ORDER ID BY REFERENCE ----
                filter_url = (
                    f"{order.BASE_URL}/orders/"
                    f"?filter[reference]={order.reference}"
                )
                _logger.info(f"[CRON] Searching Prestashop order with reference {order.reference}")
                response = requests.get(
                    filter_url,
                    auth=(order.WS_KEY, ''),  # Basic Auth
                    timeout=20
                )
                response.raise_for_status()

                xml = etree.fromstring(response.content)

                ps_order_nodes = xml.findall(".//order")
                if not ps_order_nodes:
                    _logger.error(f"[CRON] No Prestashop order found for reference {order.reference}")
                    continue

                ps_order_id = ps_order_nodes[0].get("id")

                _logger.info(f"[CRON] Prestashop order ID found: {ps_order_id}")

                # ---- 2) GET FULL ORDER DATA ----
                order_url = f"{order.BASE_URL}/orders/{ps_order_id}"

                response = requests.get(
                    order_url,
                    auth=(order.WS_KEY, ''),
                    timeout=120,
                )
                response.raise_for_status()

                order_xml = etree.fromstring(response.content)

                # ---- 3) UPDATE SHIPPING NUMBER ----
                shipping_node = order_xml.find(".//shipping_number")
                if shipping_node is not None:
                    shipping_node.text = order.shipment_number
                else:
                    _logger.error(f"[CRON] Could not find <shipping_number> node for order {order.reference}")
                    continue

                updated_xml = etree.tostring(order_xml, encoding='utf-8', xml_declaration=True)

                # ---- 4) PUT BACK TO PRESTASHOP ----
                put_response = requests.put(
                    order_url,
                    data=updated_xml,
                    headers={'Content-Type': 'application/xml'},
                    auth=(order.WS_KEY, ''),
                    timeout=120,
                )
                put_response.raise_for_status()

                _logger.info(f"[CRON] Shipping number updated successfully for {order.reference}")

                order.message_post(
                    body=f"Numéro de colis : {order.shipment_number})."
                )

            except Exception as e:
                _logger.error(
                    f"[CRON] ERROR while syncing order {order.reference}: {e}"
                )

        return True

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
        yesterday = today - timedelta(days=2)
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
            response = requests.get(order_url, auth=(self.TOKEN, ''), timeout=300)
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
                try:
                    order_rec.action_create_sale_order()
                    _logger.info("✅ Sale order automatically created for website order %s", order_id)
                except Exception as e:
                    _logger.error("Failed to auto-create sale order for website order %s: %s", order_id, str(e))
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
            response = requests.get(url, auth=(self.TOKEN, ''), timeout=300)
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
            response = requests.get(customer_url, auth=(self.TOKEN, ''), timeout=300)
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
        else:
            # Create new partner with all PrestaShop data
            partner = self.env['res.partner'].create(partner_vals)
        return partner

    def _get_text_content(self, tree, xpath):
        """Helper method to safely extract text content from XML"""
        element = tree.find(xpath)
        return element.text.strip() if element is not None and element.text else ''