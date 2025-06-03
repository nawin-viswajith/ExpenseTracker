import os
import sqlite3
import pandas as pd
import requests
import streamlit as st
import time
from datetime import datetime
from hashlib import sha256
from urllib.parse import urlencode

# ─────────────── OAuth / Per‐User DB Setup ───────────────
GOOGLE_CLIENT_ID     = "YOUR_GOOGLE_CLIENT_ID"
GOOGLE_CLIENT_SECRET = "YOUR_GOOGLE_CLIENT_SECRET"
REDIRECT_URI         = "http://localhost:8501/"

USER_DB_FOLDER = "user_data"
os.makedirs(USER_DB_FOLDER, exist_ok=True)

def build_google_auth_url() -> str:
    params = {
        "client_id":     GOOGLE_CLIENT_ID,
        "redirect_uri":  REDIRECT_URI,
        "response_type": "code",
        "scope":         "openid email profile",
        "access_type":   "offline",
        "prompt":        "select_account",
    }
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)

def exchange_code_for_token(code: str) -> dict:
    token_url = "https://oauth2.googleapis.com/token"
    data = {
        "code":          code,
        "client_id":     GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "redirect_uri":  REDIRECT_URI,
        "grant_type":    "authorization_code",
    }
    resp = requests.post(token_url, data=data)
    resp.raise_for_status()
    return resp.json()

def get_userinfo(access_token: str) -> dict:
    userinfo_endpoint = "https://www.googleapis.com/oauth2/v1/userinfo"
    resp = requests.get(userinfo_endpoint, params={"access_token": access_token})
    resp.raise_for_status()
    return resp.json()

def init_schema_if_missing(conn):
    cursor = conn.cursor()
    # (Optional) store user info in a per‐DB table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_profile (
            google_id TEXT PRIMARY KEY,
            email     TEXT,
            name      TEXT
        )
    """)
    # Create the expenses table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS expenses (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            amount       REAL NOT NULL,
            category     TEXT NOT NULL,
            date         TEXT NOT NULL,
            is_necessary INTEGER NOT NULL,
            description  TEXT
        )
    """)
    conn.commit()

def get_connection():
    user_id = st.session_state.get("google_user_id")
    if not user_id:
        st.error("Not authenticated. Please log in with Google.")
        st.stop()
    db_path = os.path.join(USER_DB_FOLDER, f"{user_id}.db")
    conn = sqlite3.connect(db_path, check_same_thread=False)
    init_schema_if_missing(conn)
    return conn

# ───────────── Utility Functions (re‐written) ─────────────
def add_expense(amount, category, date, is_necessary, description):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO expenses (amount, category, date, is_necessary, description)
        VALUES (?, ?, ?, ?, ?)
    """, (amount, category, date, is_necessary, description))
    conn.commit()
    conn.close()

def get_expenses():
    conn = get_connection()
    df = pd.read_sql_query("SELECT * FROM expenses ORDER BY date DESC", conn)
    conn.close()
    if not df.empty:
        df['date'] = pd.to_datetime(df['date'])
        df['day_of_week'] = df['date'].dt.dayofweek
        df['month'] = df['date'].dt.month
        features = df[['amount', 'day_of_week', 'month', 'is_necessary', 'category']].copy()

        from sklearn.ensemble import IsolationForest
        from sklearn.preprocessing import OneHotEncoder

        encoder = OneHotEncoder(sparse_output=False, handle_unknown='ignore')
        category_encoded = encoder.fit_transform(features[['category']])
        X = pd.concat([
            features[['amount', 'day_of_week', 'month', 'is_necessary']].reset_index(drop=True),
            pd.DataFrame(category_encoded)
        ], axis=1)
        X.columns = X.columns.astype(str)

        model = IsolationForest(contamination=0.05, random_state=42)
        df['Anomaly'] = model.fit_predict(X)
        df['Anomaly'] = df['Anomaly'].map({1: '✅ Normal', -1: '🚨 Anomaly'})
    return df

# ───────────── Streamlit: Authentication & Routing ─────────────
st.set_page_config(page_title="Expense Tracker", layout="centered")

if "google_user_id" not in st.session_state:
    st.session_state.google_user_id = None
if "google_user_info" not in st.session_state:
    st.session_state.google_user_info = {}

# 1) Check for OAuth 'code' from Google
query_params = st.experimental_get_query_params()
if "code" in query_params:
    code = query_params["code"][0]
    try:
        token_data = exchange_code_for_token(code)
        access_token = token_data["access_token"]
        userinfo = get_userinfo(access_token)
        google_id = userinfo["id"]  # or userinfo["sub"]
        # Store both id and email/name if you like
        st.session_state.google_user_id   = google_id
        st.session_state.google_user_info = {
            "email": userinfo.get("email", ""),
            "name":  userinfo.get("name", "")
        }
        # Remove ?code= from the URL
        st.experimental_set_query_params()
        st.experimental_rerun()
    except Exception as e:
        st.error(f"Google OAuth failed: {e}")
        st.stop()

# 2) If not yet signed in, show “Login with Google” button
if not st.session_state.google_user_id:
    st.markdown("## Please sign in with Google to continue")
    if st.button("Login with Google"):
        auth_url = build_google_auth_url()
        st.write(f'<meta http-equiv="refresh" content="0; url={auth_url}" />',
                 unsafe_allow_html=True)
    st.stop()

# From here on, the user _is_ authenticated
google_id   = st.session_state.google_user_id
google_info = st.session_state.google_user_info

# ───────────── Streamlit: Main App UI ─────────────
# You can now copy/paste your existing sidebar/tabs code,
# but replace any `get_expenses(st.session_state.user_id)` with just `get_expenses()`,
# and any `add_expense(st.session_state.user_id, ...)` with `add_expense(...)`.
#
# Also, if you previously showed the “username” from your local users table,
# you can now show:
#
#     st.sidebar.write(f"**Logged in as:** {google_info.get('email')}")

# EXAMPLE: show summary in the sidebar
with st.sidebar:
    df = get_expenses()

    st.markdown("### User Summary")
    st.write(f"**Email:** {google_info.get('email')}")

    if not df.empty:
        from babel.numbers import format_currency
        st.write(f"**Total Spent:** {format_currency(df['amount'].sum(), 'INR', locale='en_IN')}")
        st.write(f"**Entries:** {len(df)}")
        st.write(f"**Avg per Entry:** {format_currency(df['amount'].mean(), 'INR', locale='en_IN')}")
    st.markdown("---")
    if st.button("Logout"):
        for key in ["google_user_id", "google_user_info"]:
            if key in st.session_state:
                del st.session_state[key]
        st.experimental_rerun()

tabs = st.tabs(["Dashboard", "Add Expense", "Reports", "All Entries"])

# ─────────── Tab 0: Dashboard Overview ───────────
with tabs[0]:
    st.subheader("Dashboard Overview")
    st.markdown("### Smart Suggestions")
    df = get_expenses()
    if not df.empty:
        total = df['amount'].sum()
        necessary    = df[df['is_necessary'] == 1]['amount'].sum()
        non_necessary = total - necessary
        ratio = non_necessary / total if total > 0 else 0
        if ratio > 0.4:
            st.warning("You are spending over 40% on non‐necessary expenses. Consider reviewing subscriptions or luxury spending.")
        if df.groupby(df['date'].dt.to_period('M'))['amount'].sum().mean() > 0 \
           and df['amount'].max() > df['amount'].mean() * 3:
            st.info("You've had some unusually high expenses. Make sure they were planned or essential.")

        avg_monthly = df.groupby(df['date'].dt.to_period('M'))['amount'].sum().mean()
        if avg_monthly > 0 and ratio > 0.3:
            est_savings = ratio * avg_monthly * 0.25  # 25% reduction on non‐essential
            st.success(f"Tip: Save around {format_currency(est_savings, 'INR', locale='en_IN')} monthly by cutting luxury spends.")
            st.info("You've had some unusually high expenses. Make sure they were planned or essential.")

    df = get_expenses()
    if not df.empty:
        total_spent = df['amount'].sum()
        avg_spent   = df['amount'].mean()
        max_spent   = df['amount'].max()
        min_spent   = df['amount'].min()

        col1, col2 = st.columns(2)
        with col1:
            st.metric("Total Spent", format_currency(total_spent, 'INR', locale='en_IN'))
            st.metric("Highest Single Expense", format_currency(max_spent, 'INR', locale='en_IN'))
        with col2:
            st.metric("Average per Entry", format_currency(avg_spent, 'INR', locale='en_IN'))
            st.metric("Lowest Single Expense", format_currency(min_spent, 'INR', locale='en_IN'))

        st.markdown("### Category‐wise Breakdown")
        import plotly.express as px
        cat_data = df.groupby("category")["amount"].sum().reset_index()
        cat_data["formatted"] = cat_data["amount"].apply(lambda x: format_currency(x, 'INR', locale='en_IN'))
        pie = px.pie(cat_data, names="category", values="amount", hole=0.3, custom_data=["formatted"])
        pie.update_traces(textinfo='percent+label', hovertemplate='%{label}<br>Total: %{customdata[0]}<extra></extra>')
        st.plotly_chart(pie, use_container_width=True, key='pie_chart')

        st.markdown("### Necessary vs Non‐Necessary")
        necessity_data = df.groupby("is_necessary")["amount"].sum().reset_index()
        necessity_data["label"] = necessity_data["is_necessary"].map({1: "Necessary", 0: "Non‐Necessary"})
        donut = px.pie(necessity_data, names="label", values="amount", hole=0.4)
        donut.update_traces(textinfo='percent+label', hovertemplate='%{label}: ₹%{value:,.2f}')
        st.plotly_chart(donut, use_container_width=True, key='necessity_pie')

        st.markdown("### Top 5 Highest Expenses")
        top_expenses = df.sort_values("amount", ascending=False).head(5)
        st.dataframe(top_expenses[["amount", "category", "date", "description"]])
    else:
        st.info("No expense data available.")

# ─────────── Tab 1: Add Expense ───────────
with tabs[1]:
    st.subheader("Add New Expense")
    with st.form("expense_form"):
        amount       = st.number_input("Amount", min_value=0.0)
        category     = st.selectbox("Category", ["Food", "Transport", "Utilities", "Entertainment", "Miscellaneous"])
        date         = st.date_input("Date", value=datetime.now().date())
        is_necessary = st.checkbox("Is this a necessary expense?", value=True)
        description  = st.text_input("Short Description")
        if st.form_submit_button("Add Expense"):
            add_expense(amount, category, str(date), int(is_necessary), description)
            st.success("Expense added successfully")

# ─────────── Tab 2: Reports ───────────
with tabs[2]:
    st.markdown("### Spending Habit Insight")
    df = get_expenses()
    if not df.empty:
        df['date'] = pd.to_datetime(df['date'])
        habit_summary = df.groupby('category')['amount'].agg(['count', 'sum', 'mean']).reset_index()
        habit_summary.columns = ['Category', 'Entries', 'Total Spent', 'Average Spent']
        for col in ['Total Spent', 'Average Spent']:
            habit_summary[col] = habit_summary[col].apply(lambda x: format_currency(x, 'INR', locale='en_IN'))
        st.dataframe(habit_summary)

    st.subheader("Detailed Monthly Report")
    if not df.empty:
        df['date'] = pd.to_datetime(df['date'])
        df['Month']   = df['date'].dt.strftime('%B %Y')
        df['Weekday'] = df['date'].dt.day_name()

        st.markdown("### Monthly Summary Table")
        st.caption("Includes entry count, totals, and AI‐suggested savings.")
        monthly_summary = df.groupby(df['date'].dt.to_period("M"))['amount'].agg(['count', 'sum', 'mean', 'max', 'min']).reset_index()
        monthly_summary.columns = ['Month', 'Total Entries', 'Total Spent', 'Average', 'Max', 'Min']
        monthly_summary['Month'] = monthly_summary['Month'].dt.strftime('%B %Y')
        for col in ['Total Spent', 'Average', 'Max', 'Min']:
            monthly_summary[col] = monthly_summary[col].apply(lambda x: format_currency(x, 'INR', locale='en_IN'))
        st.dataframe(monthly_summary)

        st.markdown("### Category Distribution per Month")
        monthly_cat = df.groupby([df['date'].dt.to_period('M'), 'category'])['amount'].sum().reset_index()
        monthly_cat['date'] = monthly_cat['date'].dt.to_timestamp()
        cat_fig = px.bar(
            monthly_cat,
            x='date',
            y='amount',
            color='category',
            barmode='group',
            labels={'amount': 'Total Spent', 'date': 'Month'},
            title='Spending per Category Over Time'
        )
        st.plotly_chart(cat_fig, use_container_width=True)

        st.markdown("### Average Spend by Weekday with Necessity Ratio")
        weekday_data = df.groupby('Weekday').agg(
            total_amount=('amount', 'sum'),
            avg_amount=('amount', 'mean'),
            total_necessary=('is_necessary', 'sum'),
            count=('is_necessary', 'count')
        ).reindex(['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'])
        weekday_data['necessity_ratio'] = (weekday_data['total_necessary'] / weekday_data['count']) * 100

        import plotly.graph_objects as go
        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=weekday_data.index,
            y=weekday_data['avg_amount'],
            text=[f"Necessity %: {n:.1f}%" for n in weekday_data['necessity_ratio']],
            hovertemplate="%{x}<br>Avg Spend: ₹%{y:.2f}<br>%{text}<extra></extra>",
            marker_color="#0d6efd"
        ))
        fig.update_layout(
            title="Average Spending by Day of Week",
            xaxis_title="Day",
            yaxis_title="Avg Spend (₹)",
            template="plotly_white"
        )
        st.plotly_chart(fig, use_container_width=True)

        st.markdown("### Monthly Trend of Average Expenses")
        monthly_avg = df.groupby(df['date'].dt.to_period("M"))['amount'].mean().reset_index()
        monthly_avg['month'] = monthly_avg['date'].dt.strftime('%b %Y')
        monthly_avg['date']  = monthly_avg['date'].dt.to_timestamp()
        monthly_avg = monthly_avg.sort_values("date")
        line_fig = px.line(
            monthly_avg,
            x='month',
            y='amount',
            markers=True,
            title='Average Monthly Expense Over Time'
        )
        line_fig.update_layout(
            xaxis_title='Month',
            yaxis_title='Average Expense (₹)',
            template='plotly_white',
            xaxis_rangeslider_visible=True,
            xaxis=dict(
                type='category',
                range=[monthly_avg['month'].iloc[-12], monthly_avg['month'].iloc[-1]],
                rangeselector=dict(
                    buttons=[
                        dict(count=12, label='Last 12M', step='month', stepmode='backward'),
                        dict(step='all', label='All')
                    ]
                )
            )
        )
        st.plotly_chart(line_fig, use_container_width=True)

        st.markdown("### Overall Category‐wise Distribution")
        category_total = df.groupby("category")["amount"].sum().reset_index()
        category_total["formatted"] = category_total["amount"].apply(lambda x: format_currency(x, 'INR', locale='en_IN'))
        pie_fig = px.pie(category_total, names="category", values="amount", hole=0.4, custom_data=["formatted"])
        pie_fig.update_traces(textinfo='percent+label', hovertemplate='%{label}<br>Total: %{customdata[0]}<extra></extra>')
        pie_fig.update_layout(title="Category‐wise Spending Distribution")
        st.plotly_chart(pie_fig, use_container_width=True)
    else:
        st.info("No expense data available.")

# ─────────── Tab 3: All Entries ───────────
with tabs[3]:
    st.subheader("All Expense Entries")
    df = get_expenses()
    if not df.empty:
        st.dataframe(df)  # We drop 'user_id' because it no longer exists
    else:
        st.info("No expenses recorded yet.")
