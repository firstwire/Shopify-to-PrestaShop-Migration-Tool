#!/usr/bin/env python3
"""
Shopify -> PrestaShop CSV Converter (Import-module templates)
===============================================================
Converts Shopify exported CSV files into CSV files that match PrestaShop's
official back-office "Import" module templates - the same layouts as the
categories_import.csv / customers_import.csv / addresses_import.csv /
products_import.csv sample files supplied with this request.

This is a from-scratch re-target of the earlier version of this script,
which matched a different set of demo files (PrestaShop back-office LIST
EXPORTS). Those two formats are not interchangeable - see the previous
version's docstring if you still need that output shape. This version:
  - Writes semicolon-delimited CSVs (";"), matching the Import templates.
  - Adds a brand-new CategoryConverter. Shopify has no separate "category
    export" - categories are derived from every product's Product Category
    (or Type) column, deduplicated into a tree, and written out with
    Parent category names so they can be imported *before* products.
  - Leaves store-specific fields that can't be safely guessed blank
    (Tax rules ID, Default group ID, Warehouse, etc.) rather than
    fabricating IDs - see KNOWN LIMITATIONS below.
  - Still has no PrestaShop-import equivalent for orders in this pass,
    since no orders_import.csv template was supplied. The previous
    prestashop_orders.csv (back-office list export format) is left as-is;
    tell us if you'd like a real order-import mapping added.

Author: AI Assistant
Version: 2.0.0
Python: 3.8+
"""

import csv
import logging
import os
import re
import sys
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
import hashlib

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('converter.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


class Config:
    """Configuration class for the converter."""

    INPUT_DIR = "input"
    OUTPUT_DIR = "prestashop_output"
    REFERENCE_DIR = "output"
    SHOPIFY_PRODUCT_FILE = "shopify_products.csv"
    SHOPIFY_ORDER_FILE = "shopify_orders.csv"
    SHOPIFY_CUSTOMER_FILE = "shopify_customers.csv"

    # The Import-module templates are semicolon-delimited.
    DELIMITER = ';'

    DEFAULT_CURRENCY_SYMBOL = '$'
    DEFAULT_TAX_RATE = 0.0
    DEFAULT_QUANTITY = 999
    DEFAULT_CUSTOMER_GROUP = 'Customer'
    DEFAULT_ADDRESS_ALIAS = 'My address'
    DEFAULT_CATEGORY = 'Uncategorized'
    DEFAULT_ROOT_CATEGORY = 'Home'   # matches the sample categories_import.csv

    DATE_FORMAT_ORDERS = '%d-%m-%Y %H:%M'
    DATE_FORMAT_DAY = '%Y-%m-%d'          # Birthday / Registration date / dates below

    COUNTRY_NAME_MAP = {
        'IN': 'India', 'US': 'United States', 'GB': 'United Kingdom',
        'CA': 'Canada', 'AU': 'Australia', 'DE': 'Germany', 'FR': 'France',
        'ES': 'Spain', 'IT': 'Italy', 'NL': 'Netherlands', 'AE': 'United Arab Emirates',
        'SG': 'Singapore', 'JP': 'Japan', 'CN': 'China', 'BR': 'Brazil',
        'MX': 'Mexico', 'ZA': 'South Africa', 'NZ': 'New Zealand', 'IE': 'Ireland',
        'CH': 'Switzerland', 'SE': 'Sweden', 'NO': 'Norway', 'DK': 'Denmark',
    }

    PAYMENT_METHOD_MAP = {
        'cash_on_delivery': 'Cash on delivery (COD)',
        'cod': 'Cash on delivery (COD)',
        'manual': 'Cash on delivery (COD)',
        'bogus': 'Cash on delivery (COD)',
        'credit_card': 'Card',
        'shopify_payments': 'Card',
        'paypal': 'PayPal',
        'razorpay': 'Card',
        'bank_deposit': 'Bank wire',
        'gift_card': 'Gift card',
    }


class CSVReader:
    """Handles reading and parsing CSV files with robust error handling."""

    @staticmethod
    def read_csv(file_path: str, encoding: str = 'utf-8') -> List[Dict[str, str]]:
        data = []
        if not os.path.exists(file_path):
            logger.error(f"File not found: {file_path}")
            return data
        try:
            with open(file_path, 'r', encoding=encoding, errors='ignore') as file:
                sample = file.read(4096)
                file.seek(0)
                delimiter = ','
                try:
                    sniffed = csv.Sniffer().sniff(sample)
                    if sniffed.delimiter in (',', ';', '\t', '|'):
                        delimiter = sniffed.delimiter
                    else:
                        logger.warning(
                            f"Sniffed delimiter {sniffed.delimiter!r} for {file_path} looks "
                            f"implausible, falling back to comma-delimited dialect"
                        )
                except csv.Error:
                    logger.warning(
                        f"Could not sniff CSV dialect for {file_path}, "
                        f"falling back to default comma-delimited dialect"
                    )

                reader = csv.DictReader(file, delimiter=delimiter, quotechar='"', doublequote=True)
                for row in reader:
                    cleaned_row = {}
                    for key, value in row.items():
                        if key is None:
                            continue
                        cleaned_row[key.strip()] = '' if value is None else value.strip()
                    data.append(cleaned_row)
                logger.info(f"Successfully read {len(data)} rows from {file_path}")
                return data
        except Exception as e:
            logger.error(f"Error reading CSV file {file_path}: {e}")
            return data


class CSVWriter:
    """Writes semicolon-delimited CSVs matching PrestaShop's Import templates."""

    @staticmethod
    def write_csv(file_path: str, headers: List[str], data: List[Dict[str, Any]],
                  delimiter: str = Config.DELIMITER):
        try:
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            with open(file_path, 'w', newline='', encoding='utf-8') as file:
                writer = csv.DictWriter(file, fieldnames=headers, delimiter=delimiter,
                                         quoting=csv.QUOTE_MINIMAL, lineterminator='\n')
                writer.writeheader()
                for row in data:
                    row_data = {}
                    for header in headers:
                        value = row.get(header, '')
                        row_data[header] = '' if value is None else value
                    writer.writerow(row_data)
            logger.info(f"Successfully wrote {len(data)} rows to {file_path}")
        except Exception as e:
            logger.error(f"Error writing CSV file {file_path}: {e}")
            raise


class DataNormalizer:
    """Data normalization and transformation helpers."""

    @staticmethod
    def clean_title(title: str) -> str:
        if not title:
            return ''
        clean = re.sub(r'<[^>]+>', '', title)
        clean = re.sub(r'\s+', ' ', clean).strip()
        if not re.search(r'[a-zA-Z0-9]', clean):
            return ''
        return clean[:255]

    @staticmethod
    def is_valid_title(title: str) -> bool:
        if not title:
            return False
        clean_title = DataNormalizer.clean_title(title)
        if not clean_title:
            return False
        if title.startswith('<') and len(clean_title) < 3:
            return False
        if len(clean_title) < 2:
            return False
        return True

    @staticmethod
    def parse_price(price_str: str) -> float:
        if not price_str or str(price_str).strip() == '':
            return 0.0
        try:
            cleaned = re.sub(r'[^0-9.]', '', str(price_str).strip())
            return float(cleaned) if cleaned else 0.0
        except (ValueError, TypeError):
            return 0.0

    @staticmethod
    def format_money(amount: float) -> str:
        return f"{amount:.2f}"

    @staticmethod
    def parse_shopify_datetime(raw: str) -> Optional[datetime]:
        if not raw:
            return None
        raw = raw.strip()
        raw_no_tz = re.sub(r'\s*[+-]\d{2}:?\d{2}$', '', raw).strip()
        for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d'):
            try:
                return datetime.strptime(raw_no_tz, fmt)
            except (ValueError, TypeError):
                continue
        return None

    @staticmethod
    def format_date(dt: Optional[datetime], fmt: str) -> str:
        if dt is None:
            dt = datetime.now()
        return dt.strftime(fmt)

    @staticmethod
    def country_code_to_name(code_or_name: str) -> str:
        if not code_or_name:
            return ''
        raw = code_or_name.strip()
        if len(raw) == 2:
            return Config.COUNTRY_NAME_MAP.get(raw.upper(), raw)
        return raw

    @staticmethod
    def format_customer_display(name: str) -> str:
        name = DataNormalizer.clean_title(name)
        if not name:
            return ''
        parts = name.split()
        if len(parts) == 1:
            return parts[0]
        return f"{parts[0][0].upper()}. {parts[-1]}"

    @staticmethod
    def generate_ps_reference(seed: str) -> str:
        if not seed:
            seed = 'order'
        digest = hashlib.sha256(seed.encode()).hexdigest().upper()
        alnum = re.sub(r'[^A-Z0-9]', '', digest)
        return alnum[:9] if len(alnum) >= 9 else alnum.ljust(9, '0')

    @staticmethod
    def generate_temp_password(email: str) -> str:
        """
        Shopify never exports real passwords. A short, deterministic
        placeholder is generated per customer so the Password* column
        (required by the Import template) isn't left blank; customers
        will still need to reset their password after import - see
        KNOWN LIMITATIONS / conversion_report.txt.
        """
        if not email:
            email = 'customer'
        salt = "prestashop_temp_pw"
        return hashlib.sha256(f"{email}{salt}".encode()).hexdigest()[:10]

    @staticmethod
    def split_category_path(category_str: str) -> List[str]:
        if not category_str:
            return []
        if '>' in category_str:
            segments = [c.strip() for c in category_str.split('>')]
        elif '/' in category_str:
            segments = [c.strip() for c in category_str.split('/')]
        else:
            segments = [category_str.strip()]
        return [s for s in segments if s]


class CategoryConverter:
    """
    Builds a deduplicated category tree from every product's Product
    Category (or Type) column, since Shopify has no separate category
    export. Each unique path (e.g. "Home > Electronics > iPods") becomes
    one row per unique node, linked to its parent by name, matching the
    categories_import.csv template. Import this file before products.
    """

    def __init__(self, start_id: int = 1):
        self.current_category_id = start_id
        self.path_to_id: Dict[Tuple[str, ...], int] = {}
        self.path_to_name: Dict[Tuple[str, ...], str] = {}
        self.categories: "OrderedDict[Tuple[str, ...], Dict]" = OrderedDict()
        self.stats = {'total_categories': 0}
        logger.info(f"CategoryConverter initialized: start_id={self.current_category_id}")

    def register_path(self, segments: List[str]) -> Optional[str]:
        """Ensure every node along `segments` exists; returns the leaf category name."""
        if not segments:
            return None
        path: Tuple[str, ...] = tuple()
        for segment in segments:
            path = path + (segment,)
            if path not in self.categories:
                parent_name = Config.DEFAULT_ROOT_CATEGORY if len(path) == 1 else self.path_to_name[path[:-1]]
                category_id = self.current_category_id
                self.current_category_id += 1
                self.categories[path] = {
                    'Category ID': category_id,
                    'Active (0/1)': 1,
                    'Name *': segment,
                    'Parent category': parent_name,
                    'Root category (0/1)': 0,
                    'Description': '',
                    'Meta title': '',
                    'Meta keywords': '',
                    'Meta description': '',
                    'URL rewritten': self._slugify(segment),
                    'Image URL': '',
                }
                self.path_to_id[path] = category_id
                self.path_to_name[path] = segment
        return segments[-1]

    @staticmethod
    def _slugify(text: str) -> str:
        slug = re.sub(r'[^a-zA-Z0-9]+', '-', text.strip().lower()).strip('-')
        return slug or 'category'

    def get_categories(self) -> List[Dict]:
        self.stats['total_categories'] = len(self.categories)
        return list(self.categories.values())


class ProductConverter:
    """
    Converts Shopify products (one row per variant, grouped by Handle) to
    rows matching PrestaShop's products_import.csv template. Fields with
    no Shopify source (Tax rules ID, dimensions, SEO meta, etc.) are left
    blank rather than guessed - see KNOWN LIMITATIONS.
    """

    def __init__(self, category_converter: CategoryConverter, start_id: int = 1):
        self.category_converter = category_converter
        self.current_product_id = start_id
        self.sku_to_product_id = {}
        self.stats = {
            'total_products': 0, 'total_rows': 0, 'successful_conversions': 0,
            'failed_conversions': 0, 'skipped_products': 0,
            'failed_handles': [], 'skipped_handles': []
        }
        logger.info(f"ProductConverter initialized: start_id={self.current_product_id}")

    def convert_products(self, shopify_rows: List[Dict]) -> List[Dict]:
        self.stats['total_rows'] = len(shopify_rows)
        groups = self._group_rows_by_handle(shopify_rows)
        self.stats['total_products'] = len(groups)
        logger.info(f"Converting {len(shopify_rows)} rows grouped into {len(groups)} products...")

        products = []
        for idx, (handle, rows) in enumerate(groups.items(), 1):
            try:
                parent_row = self._find_parent_row(rows)
                if not self._is_valid_product(parent_row, handle):
                    logger.warning(f"Skipping product with invalid data: {handle}")
                    self.stats['skipped_products'] += 1
                    self.stats['skipped_handles'].append(handle)
                    continue
                product = self._convert_product_group(handle, parent_row, rows)
                products.append(product)
                self.stats['successful_conversions'] += 1
                if idx % 50 == 0:
                    logger.info(f"Processed {idx}/{len(groups)} products...")
            except Exception as e:
                logger.error(f"Error converting product {handle}: {e}")
                self.stats['failed_conversions'] += 1
                self.stats['failed_handles'].append(handle)
                continue

        logger.info(f"Product conversion complete: {self.stats['successful_conversions']} successful, "
                    f"{self.stats['failed_conversions']} failed, {self.stats['skipped_products']} skipped")
        return products

    def _group_rows_by_handle(self, rows: List[Dict]) -> "OrderedDict[str, List[Dict]]":
        groups = OrderedDict()
        blank_handle_counter = 0
        for row in rows:
            handle = row.get('Handle', '').strip()
            if not handle:
                blank_handle_counter += 1
                handle = f"__no_handle_{blank_handle_counter}"
            groups.setdefault(handle, []).append(row)
        return groups

    def _find_parent_row(self, rows: List[Dict]) -> Dict:
        for row in rows:
            if row.get('Title', '').strip():
                return row
        return rows[0]

    def _is_valid_product(self, parent_row: Dict, handle: str) -> bool:
        title = parent_row.get('Title', '')
        if not DataNormalizer.is_valid_title(title):
            return False
        if not handle or len(handle) < 2 or handle.startswith('__no_handle_'):
            return False
        return True

    def _convert_product_group(self, handle: str, parent_row: Dict, rows: List[Dict]) -> Dict:
        raw_title = parent_row.get('Title', '')
        title = DataNormalizer.clean_title(raw_title)
        if not title:
            title = handle.replace('-', ' ').title() if handle else f"Product {self.current_product_id}"

        display_product_id = self.current_product_id
        self.current_product_id += 1

        base_sku, base_price, compare_at_price, weight_kg, barcode = self._extract_base_variant(rows)
        if base_sku:
            self.sku_to_product_id[base_sku] = display_product_id

        image_urls, image_alts = self._extract_images(rows)
        category_path = DataNormalizer.split_category_path(parent_row.get('Product Category', '')) \
            or DataNormalizer.split_category_path(parent_row.get('Type', '')) \
            or [Config.DEFAULT_CATEGORY]
        leaf_category = self.category_converter.register_path(category_path)

        on_sale = 1 if (compare_at_price and compare_at_price > base_price) else 0
        discount_amount = DataNormalizer.format_money(compare_at_price - base_price) if on_sale else ''

        published = parent_row.get('Published', '').strip().lower()
        active = 0 if published == 'false' else 1

        quantity = self._get_quantity(rows)
        vendor = DataNormalizer.clean_title(parent_row.get('Vendor', ''))
        body_html = parent_row.get('Body (HTML)', '')
        tags = parent_row.get('Tags', '')

        return {
            'Product ID': display_product_id,
            'Active (0/1)': active,
            'Name *': title,
            'Categories (x,y,z...)': leaf_category or Config.DEFAULT_CATEGORY,
            'Price tax excluded': DataNormalizer.format_money(base_price),
            'Tax rules ID': '',
            'Wholesale price': '',
            'On sale (0/1)': on_sale,
            'Discount amount': discount_amount,
            'Discount percent': '',
            'Discount from (yyyy-mm-dd)': '',
            'Discount to (yyyy-mm-dd)': '',
            'Reference #': base_sku or self._generate_model(handle, display_product_id),
            'Supplier reference #': '',
            'Supplier': vendor,
            'Manufacturer': vendor,
            'EAN13': barcode,
            'UPC': '',
            'Ecotax': '',
            'Width': '',
            'Height': '',
            'Depth': '',
            'Weight': weight_kg,
            'Delivery time of in-stock products': '',
            'Delivery time of out-of-stock products with allowed orders': '',
            'Quantity': quantity,
            'Minimal quantity': 1,
            'Low stock level': '',
            'Receive a low stock alert by email': 0,
            'Visibility': 'both',
            'Additional shipping cost': '',
            'Unity': '',
            'Unit price': '',
            'Summary': '',
            'Description': body_html,
            'Tags (x,y,z...)': tags,
            'Meta title': '',
            'Meta keywords': '',
            'Meta description': '',
            'URL rewritten': handle,
            'Text when in stock': '',
            'Text when backorder allowed': '',
            'Available for order (0 = No, 1 = Yes)': 1,
            'Product available date': '',
            'Product creation date': '',
            'Show price (0 = No, 1 = Yes)': 1,
            'Image URLs (x,y,z...)': image_urls,
            'Image alt texts (x,y,z...)': image_alts,
            'Delete existing images (0 = No, 1 = Yes)': 0,
            'Feature(Name:Value:Position)': '',
            'Available online only (0 = No, 1 = Yes)': 0,
            'Condition': 'new',
            'Customizable (0 = No, 1 = Yes)': 0,
            'Uploadable files (0 = No, 1 = Yes)': 0,
            'Text fields (0 = No, 1 = Yes)': 0,
            'Out of stock action': '',
            'Virtual product': 0,
            'File URL': '',
            'Number of allowed downloads': '',
            'Expiration date': '',
            'Number of days': '',
            'ID / Name of shop': '',
            'Advanced stock management': '',
            'Depends On Stock': '',
            'Warehouse': '',
            'Acessories  (x,y,z...)': '',
        }

    def _extract_base_variant(self, rows: List[Dict]):
        for row in rows:
            option1 = row.get('Option1 Value', '').strip()
            option2 = row.get('Option2 Value', '').strip()
            option3 = row.get('Option3 Value', '').strip()
            sku = row.get('Variant SKU', '').strip()
            price_raw = row.get('Variant Price', '').strip()
            if not (option1 or option2 or option3 or sku or price_raw):
                continue
            price = DataNormalizer.parse_price(price_raw)
            compare_at = DataNormalizer.parse_price(row.get('Variant Compare At Price', ''))
            grams = row.get('Variant Grams', '').strip()
            weight_kg = ''
            if grams:
                try:
                    weight_kg = DataNormalizer.format_money(float(grams) / 1000.0)
                except ValueError:
                    weight_kg = ''
            barcode = row.get('Variant Barcode', '').strip()
            return sku, price, compare_at, weight_kg, barcode
        return '', 0.0, 0.0, '', ''

    def _get_quantity(self, rows: List[Dict]) -> Any:
        for row in rows:
            qty = row.get('Variant Inventory Qty', '').strip()
            if qty:
                try:
                    return int(float(qty))
                except ValueError:
                    continue
        return Config.DEFAULT_QUANTITY

    def _generate_model(self, handle: str, product_id: int) -> str:
        if handle:
            clean_handle = re.sub(r'[^a-zA-Z0-9]', '', handle)[:10].upper()
            return f"REF-{product_id}-{clean_handle}"
        return f"REF-{product_id}"

    def _extract_images(self, rows: List[Dict]) -> Tuple[str, str]:
        entries = []
        seen = set()
        for row in rows:
            src = row.get('Image Src', '').strip()
            if src and len(src) > 10 and src not in seen:
                seen.add(src)
                pos_raw = row.get('Image Position', '').strip()
                try:
                    pos = int(pos_raw)
                except (ValueError, TypeError):
                    pos = len(entries) + 1
                alt = row.get('Image Alt Text', '').strip()
                entries.append((pos, src, alt))
        entries.sort(key=lambda e: e[0])
        urls = ','.join(e[1] for e in entries)
        alts = ','.join(e[2] for e in entries)
        return urls, alts


class CustomerConverter:
    """Converts Shopify customers to rows matching customers_import.csv."""

    def __init__(self, start_id: int = 1):
        self.current_customer_id = start_id
        self.customer_id_map = {}
        self.stats = {'total_customers': 0, 'successful_conversions': 0,
                       'failed_conversions': 0, 'skipped_customers': 0}
        logger.info(f"CustomerConverter initialized: start_id={self.current_customer_id}")

    def convert_customers(self, shopify_customers: List[Dict]) -> List[Dict]:
        logger.info(f"Converting {len(shopify_customers)} customers...")
        self.stats['total_customers'] = len(shopify_customers)
        ps_customers = []
        for customer_data in shopify_customers:
            try:
                ps_customer = self._convert_single_customer(customer_data)
                if ps_customer:
                    ps_customers.append(ps_customer)
                    self.stats['successful_conversions'] += 1
                else:
                    self.stats['skipped_customers'] += 1
            except Exception as e:
                email = customer_data.get('Email', 'unknown')
                logger.error(f"Error converting customer {email}: {e}")
                self.stats['failed_conversions'] += 1
                continue
        logger.info(f"Customer conversion complete: {self.stats['successful_conversions']} successful, "
                   f"{self.stats['failed_conversions']} failed, {self.stats['skipped_customers']} skipped")
        return ps_customers

    def _convert_single_customer(self, customer_data: Dict) -> Optional[Dict]:
        email = customer_data.get('Email', '').strip()
        if not email:
            logger.warning("Skipping customer with no email")
            return None

        first_name = DataNormalizer.clean_title(customer_data.get('First Name', ''))
        last_name = DataNormalizer.clean_title(customer_data.get('Last Name', ''))

        active = 1
        tags = customer_data.get('Tags', '')
        if 'disabled' in tags.lower() or 'inactive' in tags.lower():
            active = 0

        newsletter = 1 if customer_data.get('Accepts Email Marketing', '').lower() == 'yes' else 0
        accepts_sms = customer_data.get('Accepts SMS Marketing', '').lower() == 'yes'
        accepts_whatsapp = customer_data.get('Accepts WhatsApp Marketing', '').lower() == 'yes'
        opt_in = 1 if (accepts_sms or accepts_whatsapp) else 0

        now_str = DataNormalizer.format_date(None, Config.DATE_FORMAT_DAY)
        customer_id = self.current_customer_id

        ps_customer = {
            'Customer ID': customer_id,
            'Active (0/1)': active,
            'Titles ID (Mr = 1, Ms = 2, else 0)': 0,
            'Email *': email[:96],
            'Password *': DataNormalizer.generate_temp_password(email),
            'Birthday (yyyy-mm-dd)': '',
            'Last Name *': last_name[:32],
            'First Name *': first_name[:32],
            'Newsletter (0/1)': newsletter,
            'Opt-in (0/1)': opt_in,
            'Registration date (yyyy-mm-dd)': now_str,
            'Groups (x,y,z...)': Config.DEFAULT_CUSTOMER_GROUP,
            'Default group ID': '',
        }
        self.customer_id_map[email] = customer_id
        self.current_customer_id += 1
        return ps_customer


class AddressConverter:
    """
    Converts each customer's Default Address into a row matching
    addresses_import.csv. Unlike the ps_address DB-table format, this
    template links by both Customer ID and Customer e-mail, and takes
    Country/State as plain text - no numeric FK guessing required.
    """

    def __init__(self, customer_id_map: Dict, start_id: int = 1):
        self.customer_id_map = customer_id_map
        self.current_address_id = start_id
        self.stats = {'total_customers': 0, 'successful_conversions': 0,
                       'skipped_no_address': 0, 'skipped_no_customer': 0}
        logger.info(f"AddressConverter initialized: start_id={self.current_address_id}")

    def convert_addresses(self, shopify_customers: List[Dict]) -> List[Dict]:
        logger.info(f"Converting addresses for {len(shopify_customers)} customers...")
        self.stats['total_customers'] = len(shopify_customers)
        addresses = []
        for customer_data in shopify_customers:
            try:
                address = self._convert_single_address(customer_data)
                if address:
                    addresses.append(address)
                    self.stats['successful_conversions'] += 1
            except Exception as e:
                email = customer_data.get('Email', 'unknown')
                logger.error(f"Error converting address for {email}: {e}")
                continue
        logger.info(f"Address conversion complete: {self.stats['successful_conversions']} successful, "
                    f"{self.stats['skipped_no_address']} skipped (no address data), "
                    f"{self.stats['skipped_no_customer']} skipped (no matching customer)")
        return addresses

    def _convert_single_address(self, customer_data: Dict) -> Optional[Dict]:
        email = customer_data.get('Email', '').strip()
        customer_id = self.customer_id_map.get(email)
        if customer_id is None:
            self.stats['skipped_no_customer'] += 1
            return None

        address1 = customer_data.get('Default Address Address1', '').strip()
        city = customer_data.get('Default Address City', '').strip()
        if not address1 and not city:
            self.stats['skipped_no_address'] += 1
            return None

        first_name = DataNormalizer.clean_title(customer_data.get('First Name', ''))
        last_name = DataNormalizer.clean_title(customer_data.get('Last Name', ''))
        company = DataNormalizer.clean_title(customer_data.get('Default Address Company', ''))
        phone = customer_data.get('Default Address Phone', '') or customer_data.get('Phone', '')
        country = DataNormalizer.country_code_to_name(customer_data.get('Default Address Country', ''))
        state = customer_data.get('Default Address Province', '').strip()

        address_id = self.current_address_id
        self.current_address_id += 1

        return {
            'Address ID': address_id,
            'Alias*': Config.DEFAULT_ADDRESS_ALIAS,
            'Active (0/1)': 1,
            'Customer e-mail*': email,
            'Customer ID': customer_id,
            'Manufacturer': '',
            'Supplier': '',
            'Company': company,
            'Lastname*': last_name,
            'Firstname*': first_name,
            'Address 1*': address1[:128],
            'Address 2': DataNormalizer.clean_title(customer_data.get('Default Address Address2', ''))[:128],
            'Zipcode*': customer_data.get('Default Address Zip', ''),
            'City*': city[:64],
            'Country*': country,
            'State': state,
            'Other': '',
            'Phone': phone,
            'Mobile Phone': '',
            'VAT number': '',
            'DNI': '',
        }


class OrderConverter:
    """
    Converts Shopify orders. No orders_import.csv template was supplied
    with this request, so this keeps the previous back-office LIST EXPORT
    column layout (ID, Reference, New client, Delivery, Customer, Total,
    Payment, Status, Date). Tell us if you'd like a real order-import
    mapping (ps_orders / ps_order_detail) added to match the other files.
    """

    def __init__(self, start_id: int = 1):
        self.current_order_id = start_id
        self.stats = {'total_orders': 0, 'successful_conversions': 0, 'failed_conversions': 0}
        logger.info(f"OrderConverter initialized: start_id={self.current_order_id}")

    def convert_orders(self, shopify_orders: List[Dict]) -> List[Dict]:
        logger.info(f"Converting {len(shopify_orders)} orders...")
        self.stats['total_orders'] = len(shopify_orders)
        first_order_index = self._find_first_order_per_email(shopify_orders)
        orders = []
        for idx, order_data in enumerate(shopify_orders):
            try:
                order = self._convert_single_order(order_data, idx, first_order_index)
                orders.append(order)
                self.stats['successful_conversions'] += 1
            except Exception as e:
                logger.error(f"Error converting order {order_data.get('Name', 'unknown')}: {e}")
                self.stats['failed_conversions'] += 1
                continue
        logger.info(f"Order conversion complete: {self.stats['successful_conversions']} successful, "
                    f"{self.stats['failed_conversions']} failed")
        return orders

    def _find_first_order_per_email(self, shopify_orders: List[Dict]) -> set:
        earliest_idx_per_email = {}
        earliest_dt_per_email = {}
        for idx, order_data in enumerate(shopify_orders):
            email = order_data.get('Email', '').strip().lower()
            if not email:
                continue
            dt = DataNormalizer.parse_shopify_datetime(order_data.get('Created at', ''))
            if email not in earliest_dt_per_email:
                earliest_dt_per_email[email] = dt
                earliest_idx_per_email[email] = idx
                continue
            existing_dt = earliest_dt_per_email[email]
            if dt is not None and (existing_dt is None or dt < existing_dt):
                earliest_dt_per_email[email] = dt
                earliest_idx_per_email[email] = idx
        return set(earliest_idx_per_email.values())

    def _convert_single_order(self, order_data: Dict, row_index: int, first_order_index: set) -> Dict:
        order_id = self.current_order_id
        self.current_order_id += 1
        order_name = order_data.get('Name', '') or order_data.get('Id', '') or f'order-{order_id}'
        reference = DataNormalizer.generate_ps_reference(order_data.get('Id', '') or order_name)
        email = order_data.get('Email', '').strip()
        new_client = 1 if (not email or row_index in first_order_index) else 0
        shipping_country_code = order_data.get('Shipping Country', '').strip() or order_data.get('Billing Country', '').strip()
        delivery = DataNormalizer.country_code_to_name(shipping_country_code) or 'Unknown'
        customer_name = order_data.get('Shipping Name', '').strip() or order_data.get('Billing Name', '').strip()
        customer_display = DataNormalizer.format_customer_display(customer_name)
        total = DataNormalizer.parse_price(order_data.get('Total', '0'))
        payment = self._get_payment_label(order_data.get('Payment Method', ''))
        status = self._get_order_status_label(order_data)
        created_dt = DataNormalizer.parse_shopify_datetime(order_data.get('Created at', ''))
        date_str = DataNormalizer.format_date(created_dt, Config.DATE_FORMAT_ORDERS)
        return {
            'ID': order_id, 'Reference': reference, 'New client': new_client,
            'Delivery': delivery, 'Customer': customer_display,
            'Total': f"{Config.DEFAULT_CURRENCY_SYMBOL}{total:.2f}",
            'Payment': payment, 'Status': status, 'Date': date_str,
        }

    def _get_payment_label(self, raw_method: str) -> str:
        if not raw_method:
            return 'Cash on delivery (COD)'
        key = raw_method.strip().lower().replace(' ', '_')
        for pattern, label in Config.PAYMENT_METHOD_MAP.items():
            if pattern in key:
                return label
        return DataNormalizer.clean_title(raw_method)

    def _get_order_status_label(self, order_data: Dict) -> str:
        financial_status = order_data.get('Financial Status', '').strip().lower()
        fulfillment_status = order_data.get('Fulfillment Status', '').strip().lower()
        if order_data.get('Cancelled at', '').strip():
            return 'Canceled'
        if financial_status == 'refunded':
            return 'Refunded'
        if 'partially' in fulfillment_status:
            return 'Partially Shipped'
        if fulfillment_status == 'fulfilled':
            return 'Shipped'
        if financial_status == 'paid':
            return 'Payment accepted'
        if financial_status == 'pending':
            payment_label = self._get_payment_label(order_data.get('Payment Method', ''))
            if 'cash on delivery' in payment_label.lower():
                return 'Awaiting Cash On Delivery validation'
            return 'Awaiting payment'
        return 'Awaiting payment'


class ShopifyToPrestaShopConverter:
    """Main converter class that orchestrates the entire conversion process."""

    def get_start_id(self, filename: str, id_column: str) -> int:
        filepath = os.path.join(Config.REFERENCE_DIR, filename)
        if not os.path.exists(filepath):
            return 1
        max_id = 0
        try:
            with open(filepath, 'r', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f, delimiter=Config.DELIMITER)
                for row in reader:
                    val = row.get(id_column, '0')
                    if val and val.isdigit():
                        max_id = max(max_id, int(val))
        except Exception as e:
            logger.error(f'Error reading {filepath} for max ID: {e}')
        return max(max_id + 1, 1)

    def __init__(self):
        self.csv_reader = CSVReader()
        self.csv_writer = CSVWriter()

        start_category = self.get_start_id('categories_import.csv', 'Category ID')
        self.category_converter = CategoryConverter(start_id=start_category)

        start_product = self.get_start_id('products_import.csv', 'Product ID')
        self.product_converter = ProductConverter(self.category_converter, start_id=start_product)

        start_customer = self.get_start_id('customers_import.csv', 'Customer ID')
        self.customer_converter = CustomerConverter(start_id=start_customer)

        start_address = self.get_start_id('addresses_import.csv', 'Address ID')
        self.address_converter = None
        self._start_address = start_address

        start_order = self.get_start_id('prestashop_orders.csv', 'ID')
        self.order_converter = OrderConverter(start_id=start_order)

    def run(self):
        logger.info("=" * 60)
        logger.info("Shopify -> PrestaShop CSV Converter (Import templates)")
        logger.info("=" * 60)
        try:
            products_data = self._read_input_file('product')
            customers_data = self._read_input_file('customer')
            orders_data = self._read_input_file('order')

            if not products_data and not customers_data and not orders_data:
                logger.warning("No input data found. Exiting.")
                return

            os.makedirs(Config.OUTPUT_DIR, exist_ok=True)

            ps_products = []
            if products_data:
                logger.info("Starting product conversion...")
                ps_products = self.product_converter.convert_products(products_data)
                # Categories must be written after products are converted
                # (that's what populates the category tree) but imported
                # into PrestaShop BEFORE products.
                ps_categories = self.category_converter.get_categories()
                if ps_categories:
                    self.csv_writer.write_csv(
                        os.path.join(Config.OUTPUT_DIR, 'categories_import.csv'),
                        ['Category ID', 'Active (0/1)', 'Name *', 'Parent category',
                         'Root category (0/1)', 'Description', 'Meta title',
                         'Meta keywords', 'Meta description', 'URL rewritten', 'Image URL'],
                        ps_categories
                    )
                if ps_products:
                    self.csv_writer.write_csv(
                        os.path.join(Config.OUTPUT_DIR, 'products_import.csv'),
                        ['Product ID', 'Active (0/1)', 'Name *', 'Categories (x,y,z...)',
                         'Price tax excluded', 'Tax rules ID', 'Wholesale price',
                         'On sale (0/1)', 'Discount amount', 'Discount percent',
                         'Discount from (yyyy-mm-dd)', 'Discount to (yyyy-mm-dd)',
                         'Reference #', 'Supplier reference #', 'Supplier', 'Manufacturer',
                         'EAN13', 'UPC', 'Ecotax', 'Width', 'Height', 'Depth', 'Weight',
                         'Delivery time of in-stock products',
                         'Delivery time of out-of-stock products with allowed orders',
                         'Quantity', 'Minimal quantity', 'Low stock level',
                         'Receive a low stock alert by email', 'Visibility',
                         'Additional shipping cost', 'Unity', 'Unit price', 'Summary',
                         'Description', 'Tags (x,y,z...)', 'Meta title', 'Meta keywords',
                         'Meta description', 'URL rewritten', 'Text when in stock',
                         'Text when backorder allowed',
                         'Available for order (0 = No, 1 = Yes)', 'Product available date',
                         'Product creation date', 'Show price (0 = No, 1 = Yes)',
                         'Image URLs (x,y,z...)', 'Image alt texts (x,y,z...)',
                         'Delete existing images (0 = No, 1 = Yes)',
                         'Feature(Name:Value:Position)',
                         'Available online only (0 = No, 1 = Yes)', 'Condition',
                         'Customizable (0 = No, 1 = Yes)', 'Uploadable files (0 = No, 1 = Yes)',
                         'Text fields (0 = No, 1 = Yes)', 'Out of stock action',
                         'Virtual product', 'File URL', 'Number of allowed downloads',
                         'Expiration date', 'Number of days', 'ID / Name of shop',
                         'Advanced stock management', 'Depends On Stock', 'Warehouse',
                         'Acessories  (x,y,z...)'],
                        ps_products
                    )
            else:
                logger.info("No products to convert.")

            ps_customers = []
            if customers_data:
                logger.info("Starting customer conversion...")
                ps_customers = self.customer_converter.convert_customers(customers_data)
                if ps_customers:
                    self.csv_writer.write_csv(
                        os.path.join(Config.OUTPUT_DIR, 'customers_import.csv'),
                        ['Customer ID', 'Active (0/1)', 'Titles ID (Mr = 1, Ms = 2, else 0)',
                         'Email *', 'Password *', 'Birthday (yyyy-mm-dd)', 'Last Name *',
                         'First Name *', 'Newsletter (0/1)', 'Opt-in (0/1)',
                         'Registration date (yyyy-mm-dd)', 'Groups (x,y,z...)', 'Default group ID'],
                        ps_customers
                    )

                logger.info("Starting address conversion...")
                self.address_converter = AddressConverter(
                    customer_id_map=self.customer_converter.customer_id_map,
                    start_id=self._start_address
                )
                ps_addresses = self.address_converter.convert_addresses(customers_data)
                if ps_addresses:
                    self.csv_writer.write_csv(
                        os.path.join(Config.OUTPUT_DIR, 'addresses_import.csv'),
                        ['Address ID', 'Alias*', 'Active (0/1)', 'Customer e-mail*',
                         'Customer ID', 'Manufacturer', 'Supplier', 'Company', 'Lastname*',
                         'Firstname*', 'Address 1*', 'Address 2', 'Zipcode*', 'City*',
                         'Country*', 'State', 'Other', 'Phone', 'Mobile Phone',
                         'VAT number', 'DNI'],
                        ps_addresses
                    )
            else:
                logger.info("No customers to convert.")

            ps_orders = []
            if orders_data:
                logger.info("Starting order conversion...")
                ps_orders = self.order_converter.convert_orders(orders_data)
                if ps_orders:
                    self.csv_writer.write_csv(
                        os.path.join(Config.OUTPUT_DIR, 'prestashop_orders.csv'),
                        ['ID', 'Reference', 'New client', 'Delivery', 'Customer',
                         'Total', 'Payment', 'Status', 'Date'],
                        ps_orders, delimiter=','
                    )
            else:
                logger.info("No orders to convert.")

            self._generate_summary_report(products_data, customers_data, orders_data)

            logger.info("=" * 60)
            logger.info("Conversion completed successfully!")
            logger.info(f"Output directory: {os.path.abspath(Config.OUTPUT_DIR)}")
            logger.info("=" * 60)
        except Exception as e:
            logger.error(f"Fatal error during conversion: {e}")
            raise

    def _read_input_file(self, file_type: str) -> List[Dict]:
        file_map = {
            'product': Config.SHOPIFY_PRODUCT_FILE,
            'customer': Config.SHOPIFY_CUSTOMER_FILE,
            'order': Config.SHOPIFY_ORDER_FILE
        }
        if file_type not in file_map:
            logger.error(f"Unknown file type: {file_type}")
            return []
        file_path = os.path.join(Config.INPUT_DIR, file_map[file_type])
        if not os.path.exists(file_path):
            logger.warning(f"Input file not found: {file_path}")
            return []
        logger.info(f"Reading {file_type} data from: {file_path}")
        return self.csv_reader.read_csv(file_path)

    def _generate_summary_report(self, products: List, customers: List, orders: List):
        report_path = os.path.join(Config.OUTPUT_DIR, 'conversion_report.txt')
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write("=" * 60 + "\n")
            f.write("Shopify -> PrestaShop Conversion Report (Import templates)\n")
            f.write("=" * 60 + "\n\n")
            f.write(f"Conversion Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")

            f.write("Input Data Summary:\n" + "-" * 40 + "\n")
            f.write(f"Product rows read: {len(products)}\n")
            f.write(f"Products (after grouping by Handle): {self.product_converter.stats['total_products']}\n")
            f.write(f"Categories discovered: {self.category_converter.stats.get('total_categories', 0)}\n")
            f.write(f"Customers: {len(customers)}\n")
            f.write(f"Orders: {len(orders)}\n\n")

            f.write("Product Conversion Statistics:\n" + "-" * 40 + "\n")
            f.write(f"Products successfully converted: {self.product_converter.stats['successful_conversions']}\n")
            f.write(f"Products failed: {self.product_converter.stats['failed_conversions']}\n")
            f.write(f"Products skipped (invalid data): {self.product_converter.stats['skipped_products']}\n")

            f.write("\nCustomer Conversion Statistics:\n" + "-" * 40 + "\n")
            f.write(f"Customers successfully converted: {self.customer_converter.stats['successful_conversions']}\n")
            f.write(f"Customers failed: {self.customer_converter.stats['failed_conversions']}\n")
            f.write(f"Customers skipped: {self.customer_converter.stats['skipped_customers']}\n")

            if self.address_converter:
                f.write("\nAddress Conversion Statistics:\n" + "-" * 40 + "\n")
                f.write(f"Addresses successfully converted: {self.address_converter.stats['successful_conversions']}\n")
                f.write(f"Skipped (no address data): {self.address_converter.stats['skipped_no_address']}\n")
                f.write(f"Skipped (no matching customer): {self.address_converter.stats['skipped_no_customer']}\n")

            f.write("\nOrder Conversion Statistics:\n" + "-" * 40 + "\n")
            f.write(f"Orders successfully converted: {self.order_converter.stats['successful_conversions']}\n")
            f.write(f"Orders failed: {self.order_converter.stats['failed_conversions']}\n")

            f.write("\nKNOWN LIMITATIONS:\n" + "-" * 40 + "\n")
            f.write("- categories_import.csv, customers_import.csv, addresses_import.csv, and\n")
            f.write("  products_import.csv now match PrestaShop's official Import-module\n")
            f.write("  templates (semicolon-delimited). Import order matters: categories,\n")
            f.write("  then customers, then addresses/products.\n")
            f.write("- prestashop_orders.csv is UNCHANGED from the previous back-office LIST\n")
            f.write("  EXPORT format - no orders_import.csv template was supplied. Ask if you\n")
            f.write("  want a real order-import mapping added.\n")
            f.write("- Password * is a random per-customer placeholder (Shopify never exports\n")
            f.write("  real passwords). Customers will need to reset their password after\n")
            f.write("  import, or you should force a password-reset email on first login.\n")
            f.write("- Tax rules ID and Default group ID are store-specific numeric IDs and are\n")
            f.write("  left blank rather than guessed - map these to your store's real IDs\n")
            f.write("  before importing.\n")
            f.write("- Quantity uses Variant Inventory Qty when present in your export,\n")
            f.write("  otherwise falls back to Config.DEFAULT_QUANTITY.\n")
            f.write("- Categories are derived from each product's Product Category (or Type)\n")
            f.write("  column and assigned to their leaf category only; multi-category\n")
            f.write("  assignment isn't attempted since Shopify has one category per product.\n")
            f.write("- Meta title/keywords/description, dimensions (Width/Height/Depth), and\n")
            f.write("  Tax rules ID have no Shopify source field and are left blank.\n")

            f.write("\nOutput Files Generated:\n" + "-" * 40 + "\n")
            output_dir = Path(Config.OUTPUT_DIR)
            for file_path in sorted(output_dir.glob('*.csv')):
                with open(file_path, 'r', encoding='utf-8') as csv_file:
                    row_count = sum(1 for _ in csv_file) - 1
                f.write(f"  {file_path.name}: {row_count} rows\n")
            f.write("\n" + "=" * 60 + "\n")
        logger.info(f"Summary report generated: {report_path}")


def main():
    try:
        if sys.version_info < (3, 8):
            print("Error: Python 3.8 or higher is required.")
            sys.exit(1)

        os.makedirs(Config.INPUT_DIR, exist_ok=True)

        print("=" * 60)
        print("Shopify -> PrestaShop CSV Converter (Import templates)")
        print("=" * 60)
        print(f"\nPlease ensure your Shopify export files are placed in:")
        print(f"  {os.path.abspath(Config.INPUT_DIR)}/")
        print(f"\nRequired files:")
        print(f"  - {Config.SHOPIFY_PRODUCT_FILE}")
        print(f"  - {Config.SHOPIFY_CUSTOMER_FILE}")
        print(f"  - {Config.SHOPIFY_ORDER_FILE}")
        print("\nPress Enter to continue or Ctrl+C to cancel...")

        try:
            input()
        except KeyboardInterrupt:
            print("\nOperation cancelled by user.")
            sys.exit(0)

        converter = ShopifyToPrestaShopConverter()
        converter.run()

    except KeyboardInterrupt:
        print("\n\nOperation interrupted by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\nFatal error: {e}")
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()