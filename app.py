import streamlit as st
import pandas as pd
import subprocess
import os

CSV_FILENAME = "nidhi_prices.csv"
PREV_CSV_FILENAME = "nidhi_prices_prev.csv"

st.set_page_config(page_title="Nidhiratna Product Tracker", layout="wide")

st.title("🛍️ Nidhiratna Product Tracker Dashboard")

if st.button("🔄 Run Scraper and Refresh Data"):
    with st.spinner("Running scraper..."):
        result = subprocess.run(["python", "scraper.py"], capture_output=True, text=True)
        if result.returncode == 0:
            st.success("Scraper finished successfully!")
        else:
            st.error(f"Scraper failed:\n{result.stderr}")

@st.cache_data(ttl=600)
def load_data(file):
    if os.path.exists(file):
        try:
            return pd.read_csv(file)
        except Exception as e:
            st.error(f"Error reading {file}: {e}")
            return pd.DataFrame()
    return pd.DataFrame()

df = load_data(CSV_FILENAME)
prev_df = load_data(PREV_CSV_FILENAME)

if df.empty:
    st.warning("No product data available. Please run the scraper.")
    st.stop()

def make_clickable(url):
    if not url or not isinstance(url, str):
        return ""
    return f'<a href="{url}" target="_blank">View Product</a>'

# Normalize URLs and fill missing prices for current df
if 'Link' in df.columns:
    df['Link'] = df['Link'].str.lower().str.rstrip('/')
else:
    st.error("Current data missing 'Link' column!")
    st.stop()

if not prev_df.empty and 'Link' in prev_df.columns:
    prev_df['Link'] = prev_df['Link'].str.lower().str.rstrip('/')
else:
    prev_df = pd.DataFrame()  # Treat as empty for safety

for col in ['Sale_Price', 'Regular_Price']:
    if col not in df.columns:
        df[col] = ""
    else:
        df[col] = df[col].fillna("")
    if prev_df.empty or col not in prev_df.columns:
        if not prev_df.empty:
            prev_df[col] = ""
    else:
        prev_df[col] = prev_df[col].fillna("")

df['Product Link'] = df['Link'].apply(make_clickable)

# Pagination setup for all tables
rows_per_page = 20  # Number of rows per page

def paginate(df, page):
    start_row = (page - 1) * rows_per_page
    end_row = start_row + rows_per_page
    return df.iloc[start_row:end_row]

# Display all current products with pagination
num_pages_all = (len(df) // rows_per_page) + (1 if len(df) % rows_per_page > 0 else 0)
page_all = st.selectbox(f"Select Page for All Products (Total Pages: {num_pages_all})", range(1, num_pages_all + 1))

st.subheader(f"📋 All Products ({len(df)}) - Page {page_all} of {num_pages_all}")
st.write(
    paginate(df[['Title', 'SKU', 'Sale_Price', 'Regular_Price', 'Availability', 'Product Link']].rename(columns={'Sale_Price':'Sale Price', 'Regular_Price':'Regular Price'}).sort_values(by='Title'), page_all)
    .to_html(escape=False, index=False),
    unsafe_allow_html=True
)

# Decide if we have baseline data for price comparison
if prev_df.empty or 'Link' not in prev_df.columns:
    st.info("ℹ️ No baseline data found for previous prices.\n"
            "Please click the '📥 Save current data for next comparison' button below to save current prices as baseline.\n"
            "Price change comparisons will be available on subsequent runs.")
    show_price_changes = False
else:
    show_price_changes = True

# Prepare for merging and comparison
if show_price_changes:
    needed_cols = {'Link', 'Sale_Price', 'Regular_Price', 'Title'}
    if needed_cols.issubset(prev_df.columns):
        prev_prices = prev_df[list(needed_cols)]
    else:
        prev_prices = prev_df[['Link']].copy()
        prev_prices['Sale_Price'] = ""
        prev_prices['Regular_Price'] = ""
        prev_prices['Title'] = ""
    merged = pd.merge(df, prev_prices, on='Link', how='left', suffixes=('', '_old'))
else:
    merged = df.copy()
    merged['Sale_Price_old'] = ""
    merged['Regular_Price_old'] = ""
    merged['Title_old'] = ""

def safe_float(p):
    try:
        val = float(str(p).replace('$', '').replace('₹', '').replace(',', '').strip())
        return round(val, 2)
    except:
        return None

def format_prices(row):
    reg = safe_float(row.get("Regular_Price"))
    sale = safe_float(row.get("Sale_Price"))
    regular = f"Regular: ${reg:,.2f}" if reg is not None else "Regular: N/A"
    sale = f"Sale: ${sale:,.2f}" if sale is not None else "Sale: N/A"
    return f"{regular}<br>{sale}"

def format_price_changes(row):
    changes = []
    reg_new = safe_float(row.get("Regular_Price"))
    reg_old = safe_float(row.get("Regular_Price_old"))
    if reg_new is not None and reg_old is not None and reg_new != reg_old:
        changes.append(f"Regular Price: ${reg_old:,.2f} → <b style='color:red;'>{reg_new:,.2f}</b>")
    sale_new = safe_float(row.get("Sale_Price"))
    sale_old = safe_float(row.get("Sale_Price_old"))
    if sale_new is not None and sale_old is not None and sale_new != sale_old:
        changes.append(f"Sale Price: ${sale_old:,.2f} → <b style='color:red;'>{sale_new:,.2f}</b>")
    return "<br>".join(changes) if changes else "-"

merged['Price_Display'] = merged.apply(format_prices, axis=1)
merged['Price Changes'] = merged.apply(format_price_changes, axis=1)
merged['Product Link'] = merged['Link'].apply(make_clickable)

# Pagination for Products with Price Changes
num_pages_changes = (len(merged) // rows_per_page) + (1 if len(merged) % rows_per_page > 0 else 0)
page_changes = st.selectbox(f"Select Page for Products with Price Changes (Total Pages: {num_pages_changes})", range(1, num_pages_changes + 1))

st.subheader(f"📦 Products with Price Changes - Page {page_changes} of {num_pages_changes}")
filtered_changes = merged[merged['Price Changes'] != "-"]
st.write(
    paginate(filtered_changes[['Title', 'SKU', 'Price_Display', 'Price Changes', 'Availability', 'Product Link']].rename(columns={'Price_Display': 'Price'}), page_changes)
    .to_html(escape=False, index=False),
    unsafe_allow_html=True
)

# Count the number of price changes
price_changes_count = len(filtered_changes)
st.write(f"**Total Price Changes Found: {price_changes_count}**")

# Detect new products
if not prev_df.empty and 'Link' in prev_df.columns:
    old_links = set(prev_df['Link'])
    new_products = merged[~merged['Link'].isin(old_links)]
else:
    new_products = merged.copy()

# Pagination for New Products
num_pages_new = (len(new_products) // rows_per_page) + (1 if len(new_products) % rows_per_page > 0 else 0)
page_new = st.selectbox(f"Select Page for New Products (Total Pages: {num_pages_new})", range(1, num_pages_new + 1))

st.subheader(f"🆕 New Products - Page {page_new} of {num_pages_new}")
st.write(
    paginate(new_products[['Title', 'SKU', 'Price_Display', 'Availability', 'Product Link']].rename(columns={'Price_Display': 'Price'}), page_new)
    .to_html(escape=False, index=False),
    unsafe_allow_html=True
)

# Count the number of new products
st.write(f"**Total New Products Found: {len(new_products)}**")

if st.button("📥 Save current data for next comparison"):
    df[['Link', 'Sale_Price', 'Regular_Price']].to_csv(PREV_CSV_FILENAME, index=False)
    st.success("Saved current prices for future comparison!")
