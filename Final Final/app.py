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

# Display all current products
st.subheader(f"📋 All Products ({len(df)})")
st.write(
    df[['Title', 'SKU', 'Sale_Price', 'Regular_Price', 'Availability', 'Product Link']]
    .rename(columns={'Sale_Price':'Sale Price', 'Regular_Price':'Regular Price'})
    .sort_values(by='Title')
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
    needed_cols = {'Link', 'Sale_Price', 'Regular_Price'}
    if needed_cols.issubset(prev_df.columns):
        prev_prices = prev_df[list(needed_cols)]
    else:
        prev_prices = prev_df[['Link']].copy()
        prev_prices['Sale_Price'] = ""
        prev_prices['Regular_Price'] = ""
    merged = pd.merge(df, prev_prices, on='Link', how='left', suffixes=('', '_old'))
else:
    merged = df.copy()
    merged['Sale_Price_old'] = ""
    merged['Regular_Price_old'] = ""

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

st.sidebar.header("Filters")
keyword = st.sidebar.text_input("Search Title Keyword")
availability_filter = st.sidebar.selectbox("Availability", options=["All", "Available", "Sold Out", "Unknown"])
min_price = st.sidebar.number_input("Min Sale Price", min_value=0.0, value=0.0, step=1.0)
max_price = st.sidebar.number_input("Max Sale Price", min_value=0.0, value=100000.0, step=1.0)

def price_to_float(p):
    if not p or pd.isna(p):
        return 0.0
    try:
        return float(str(p).replace('$','').replace('₹','').replace(',','').strip())
    except:
        return 0.0

merged['Sale_Price_num'] = merged['Sale_Price'].apply(price_to_float)

if show_price_changes:
    # Filter changed prices and apply sidebar filters
    changed = merged[merged['Price Changes'] != "-"]
    filtered = changed[
        (changed['Sale_Price_num'] >= min_price) & (changed['Sale_Price_num'] <= max_price)
    ]

    if keyword:
        filtered = filtered[filtered['Title'].str.contains(keyword, case=False, na=False)]

    if availability_filter != "All" and 'Availability' in merged.columns:
        filtered = filtered[filtered['Availability'] == availability_filter]

    # Show price changed products
    st.subheader(f"📦 Products with Price Changes ({len(filtered)})")
    if not filtered.empty:
        st.write(
            filtered[['Title', 'SKU', 'Price_Display', 'Price Changes', 'Availability', 'Product Link']]
            .rename(columns={'Price_Display': 'Price'})
            .sort_values(by='Title')
            .to_html(escape=False, index=False),
            unsafe_allow_html=True
        )
    else:
        st.info("No products have changed prices.")
else:
    st.subheader("📦 Products with Price Changes")
    st.info("Price change comparison unavailable until baseline data is saved.")

# Detect new products
if not prev_df.empty and 'Link' in prev_df.columns:
    old_links = set(prev_df['Link'])
    new_products = merged[~merged['Link'].isin(old_links)]
else:
    new_products = merged.copy()

# Show new products below
st.subheader(f"🆕 New Products ({len(new_products)})")
if not new_products.empty:
    st.write(
        new_products[['Title', 'SKU', 'Price_Display', 'Availability', 'Product Link']]
        .rename(columns={'Price_Display': 'Price'})
        .sort_values(by='Title')
        .to_html(escape=False, index=False),
        unsafe_allow_html=True
    )
else:
    st.info("No new products found.")

if st.button("📥 Save current data for next comparison"):
    df[['Link', 'Sale_Price', 'Regular_Price']].to_csv(PREV_CSV_FILENAME, index=False)
    st.success("Saved current prices for future comparison!")
