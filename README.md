We have created a free tool to convert Shopify data into PrestaShop-compatible CSV files.

You can use this tool to convert your product, customer, and address data into CSV files that match PrestaShop's own official **Import module templates** — the same semicolon-delimited layouts you'd use under Back Office → All Shops → Import in PrestaShop — plus a brand-new categories file, since Shopify has no separate category export of its own. Order data is still converted too, but into a different, older format — see Step 5 below for why.

Please see the detailed instructions at: **https://firstwireapp.com/blog/shopify-to-prestashop-migration-free-tool/**

See the code and guide below.

**Step 1 — Install Python (one-time setup)**

Python is the free program that runs the script. If you already have Python installed, skip to Step 2.
1. Go to python.org/downloads in your web browser.
2. Click the yellow "Download Python" button.
3. Open the downloaded file and run the installer.

**Important**

On the first install screen, tick the box that says
"Add Python to PATH" before clicking Install.

4. Click Install Now and wait for it to finish.

To check it worked, open your terminal (Command Prompt on Windows, Terminal on Mac) and type:
`python --version`

If you see a version number like "Python 3.12.0", you are ready for Step 2.


**Step 2 — Install the Required Add-ons**

This script only uses Python's own built-in libraries (for reading and writing CSV files, hashing, logging, and so on). There is nothing extra to install with pip — once Python itself is installed, you're ready to run the script.


**Step 3 — Save Your Files in One Folder**

Create a new folder on your Desktop (for example, "Shopify-To-PrestaShop").
Inside it, create another folder called "input" — this is where all your Shopify export files will go.
Your folder structure should look like this:
```
Shopify-To-PrestaShop/
  shopify_to_prestashop.py
  input/
    shopify_products.csv
    shopify_customers.csv
    shopify_orders.csv
```

Place the script file directly inside "Shopify-To-PrestaShop", and place your Shopify CSV exports inside the "input" folder:

- input/shopify_products.csv  (your Shopify product export — if migrating products; Shopify Admin → Products → Export)
- input/shopify_customers.csv  (your Shopify customer export — if migrating customers and addresses; Shopify Admin → Customers → Export)
- input/shopify_orders.csv  (your Shopify order export — if migrating orders; Shopify Admin → Orders → Export)

Important: the file names must match exactly as shown above (shopify_products.csv, shopify_customers.csv, shopify_orders.csv) — the script looks for these specific names inside the input folder, not any file with "product" or "order" somewhere in the name.

You do not need all three files, and none of them is required to unlock the others — each is read and converted independently. The script only stops without converting anything if none of the three files is present in the input folder.


**Step 4 — Run the Script**

5. Open your terminal.
6. Navigate to the folder you created. For example:
`cd Desktop/Shopify-To-PrestaShop`
7. Run the script by typing:

`python shopify_to_prestashop.py`

The script will print a short summary of what it expects, then wait for you to press Enter before it starts. It automatically looks for shopify_products.csv, shopify_customers.csv, and shopify_orders.csv inside the input folder and converts whichever of those are present, all in one run.

There is currently no option to convert a single file on its own by typing a path — the script always reads from the input folder as described above.

A note on IDs: by default, generated Category IDs, Product IDs, Customer IDs, Address IDs, and Order IDs all start at 1. If you place a previous run's output files (categories_import.csv, products_import.csv, customers_import.csv, addresses_import.csv, prestashop_orders.csv) inside a folder named "output" next to the input folder, the script will read the highest existing ID from each and continue numbering from there instead — useful for re-running the conversion without colliding with IDs you've already used.


**Step 5 — Find Your Converted Files**

Once the script finishes, it creates a new folder called "prestashop_output" inside your project folder, along with a converter.log file and a conversion_report.txt summary. Inside prestashop_output you'll find:

**categories_import.csv** — a category tree built automatically from every product's Product Category (or Type) column, since Shopify has no separate category export. Each unique level of the category path (e.g. "Home > Electronics > iPods") becomes its own row, linked to its parent by name via the Parent category column. Import this file *before* products_import.csv, since products refer to these category names.

**products_import.csv** — one row per product (Shopify's variant rows are grouped by Handle first), matching PrestaShop's official product Import template: Product ID, Active, Name, Categories, Price tax excluded, Reference, Supplier/Manufacturer (from Vendor), EAN13 (from Variant Barcode), Weight (converted from Variant Grams), Quantity (from Variant Inventory Qty if present, otherwise a fixed default), on-sale/discount fields (derived from Variant Compare At Price), Description (Body HTML), Tags, and image URLs/alt texts — plus a number of columns PrestaShop supports but Shopify has no equivalent for (Tax rules ID, dimensions, SEO meta fields, and so on), which are left blank.

**customers_import.csv** — created only if shopify_customers.csv was supplied, matching PrestaShop's customer Import template: Customer ID, Active, Email, Password, Last/First Name, Newsletter, Opt-in, Registration date, and Group. Since Shopify never exports real passwords, each customer gets a random placeholder password — see Troubleshooting below.

**addresses_import.csv** — created only if shopify_customers.csv was supplied, one address per customer built from each customer's default Shopify address, matching PrestaShop's address Import template. Linked to the right customer via *both* Customer ID and Customer e-mail. Country and State are plain text here (e.g. "United States", "New York") — no numeric ID guessing needed, unlike some other import formats.

**prestashop_orders.csv** — created only if shopify_orders.csv was supplied. This one is **not** in the Import-module format — no orders_import.csv template exists for this converter yet, so orders still export in PrestaShop's Orders back-office *list-export* style (reference, new-client flag, delivery country, customer display name, total, payment label, status label, date). See Step 6.

conversion_report.txt lists exactly how many categories, products, customers, and orders were converted, which ones (if any) were skipped or failed and why, plus a recap of the known limitations below.


**Step 6 — What To Do With Your Converted Files**

**categories_import.csv, products_import.csv, customers_import.csv, and addresses_import.csv** are built to match PrestaShop's real Import-module templates (Back Office → All Shops → Import), semicolon-delimited, so they're designed to be imported through that screen directly. Import them in this order, since later files reference IDs/names from earlier ones:
1. categories_import.csv
2. customers_import.csv
3. addresses_import.csv and products_import.csv (either order)

Before importing, double-check the fields this tool couldn't safely fill in from Shopify data alone:
- **Tax rules ID** and **Default group ID** are store-specific numeric IDs and are left blank — map these to your store's actual IDs, or set them in the Import module's column-mapping screen.
- **Password** is a random placeholder for every customer — plan to force a password reset (or send a "set your password" email) after import rather than sharing these values with customers.

**prestashop_orders.csv** is the exception — it still matches PrestaShop's Orders back-office *list-export* format, not the Import module, because no orders_import.csv template has been supplied for this converter yet. That means:
- It cannot be loaded through the Import module — the column names don't match (Import expects things like line items, carrier, and tax details this list format doesn't have).
- It's best used for review — checking order counts, totals, and statuses migrated correctly — while your developer (or FirstWire) handles order import a different way, e.g. a direct MySQL load into `ps_orders` / `ps_order_detail`.

If you'd like a real orders_import.csv mapping added so all four entities import the same way, just let us know — the script's order-grouping logic can be extended to produce it.

If you're not comfortable working with PrestaShop's Import module or database directly, ask your developer or hosting provider to take it from here — or see the FirstWire contact details below.


**Troubleshooting — Common Questions**

"python is not recognized" — Reinstall Python and make sure to tick "Add Python to PATH".

File not found — Make sure your CSV files are named exactly shopify_products.csv, shopify_customers.csv, and shopify_orders.csv, and are placed inside the input folder as described in Step 3.

Some products are missing from the output — A product is skipped if its first row has no readable Title, or if its Handle is blank/too short (or blank entirely). Check conversion_report.txt for a list of skipped and failed product handles.

Some customers are missing from the output — A customer row is skipped if it has no Email value.

A customer is missing from addresses_import.csv — The address is skipped if that customer's default address has neither an Address1 nor a City value, or if no matching customer record was created (e.g. because that customer had no email).

Quantity always shows the same number (999) — Only happens if your product export has no Variant Inventory Qty column; when that column is present, its value is used instead. Edit Config.DEFAULT_QUANTITY in the script if you want a different fallback.

On sale / Discount amount are always blank for a product — This is filled in only when Variant Compare At Price is present and higher than Variant Price; otherwise there's nothing to base a discount on.

Tax rules ID / Default group ID are blank in the output — These are store-specific numeric IDs tied to your PrestaShop installation and can't be safely guessed; fill them in by hand or via the Import module's mapping screen.

Every customer has the same-looking Password — Shopify's customer export has no password field at all, so a random placeholder is generated per customer. Force a password reset after import rather than relying on these values.

Country / State look wrong in addresses_import.csv — These are taken directly from Shopify's Default Address Country / Default Address Province fields (with 2-letter country codes expanded to full names); if your Shopify store used unusual naming, double-check against PrestaShop's own Countries/States list before importing.

Importing prestashop_orders.csv into PrestaShop's Import module fails — This is expected; see Step 6. Unlike the other three files, orders still use the older back-office list-export format, not the Import template.


**Quick Reference — Every Time You Run It**

1. Make sure input/shopify_products.csv (and shopify_customers.csv / shopify_orders.csv if needed) are up to date
2. Open terminal in your project folder
3. Type: `python shopify_to_prestashop.py`
4. Find your results in the prestashop_output folder, and check conversion_report.txt for a summary

That's it — no coding required. If you run into any issue not listed above, check converter.log for details and confirm your CSV files were exported correctly from Shopify.

At FirstWire, we can do the complete migration and make sure that your new PrestaShop store is set up properly and optimized for Design, User Experience, Performance, SEO and CRO.

Please Contact Us for a custom proposal at **https://firstwireapp.com/get-a-quotation/**

You can also check our other Shopify Services at **https://firstwireapp.com/e-commerce/prestashop/**
