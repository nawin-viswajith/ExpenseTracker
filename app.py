from babel.numbers import format_currency
import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime
from hashlib import sha256
import time

DB = "expense_tracker.db"

# ------------------------ Utility Functions ------------------------
def get_connection():
    return sqlite3.connect(DB, check_same_thread=False)

def create_user(username, password, email):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO users (username, password_hash, email) VALUES (?, ?, ?)",
                       (username, sha256(password.encode()).hexdigest(), email))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def login_user(identifier, password):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM users WHERE (username=? OR email=?) AND password_hash=?",
                   (identifier, identifier, sha256(password.encode()).hexdigest()))
    user = cursor.fetchone()
    conn.close()
    return user[0] if user else None

def add_expense(user_id, amount, category, date, is_necessary, description):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO expenses (user_id, amount, category, date, is_necessary, description)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (user_id, amount, category, date, is_necessary, description))
    conn.commit()
    conn.close()

def get_expenses(user_id):
    conn = get_connection()
    df = pd.read_sql_query("SELECT * FROM expenses WHERE user_id=? ORDER BY date DESC", conn, params=(user_id,))
    conn.close()
    return df

# ------------------------ Streamlit UI ------------------------
st.set_page_config(page_title="Expense Tracker", layout="centered")

st.markdown("""
    <style>
    body {
        background-color: #f0f2f6;
    }
    .stTextInput>div>div>input, .stTextArea>div>textarea {
        border-radius: 10px;
        border: 1px solid #ced4da;
        padding: 10px;
    }
    .stButton>button {
        border-radius: 8px;
        background-color: #0d6efd;
        color: white;
        padding: 10px 20px;
        font-weight: 500;
        margin-top: 10px;
    }
    .stButton>button:hover {
        background-color: #0b5ed7;
    }
    .auth-box {
        background-color: white;
        padding: 30px;
        border-radius: 12px;
        box-shadow: 0 4px 10px rgba(0, 0, 0, 0.1);
        max-width: 500px;
        margin: auto;
    }
    .dashboard {
        padding-top: 30px;
    }
    </style>
""", unsafe_allow_html=True)

if "user_id" not in st.session_state:
    st.session_state.user_id = None
if "page" not in st.session_state:
    st.session_state.page = "auth"
if "show_register" not in st.session_state:
    st.session_state.show_register = False

def reroute(page):
    st.session_state.page = page
    st.rerun()

if st.session_state.page == "auth":
    st.markdown("### Welcome to your personal expense tracker\nTrack, analyze, and manage your spending efficiently")

    if not st.session_state.show_register:
        st.markdown("#### Login")
        identifier = st.text_input("Username or Email")
        password = st.text_input("Password", type="password")
        if st.button("Login"):
            uid = login_user(identifier, password)
            if uid:
                st.session_state.user_id = uid
                reroute("main")
            else:
                st.error("Invalid credentials")
        if st.button("Register here"):
            st.session_state.show_register = True
            st.rerun()
        
        

    else:
        st.markdown("#### Register")
        st.markdown("""
        **Registration Rules:**
        - Username is required and must be unique.
        - Password must be at least 6 characters long.
        - Email is optional, but recommended for recovery.
        """)
        with st.form("register_form"):
            new_username = st.text_input("Username")
            new_email = st.text_input("Email")
            new_password = st.text_input("Password", type="password")
            if st.form_submit_button("Register"):
                import re
                email_regex = r"^[\w\.-]+@[\w\.-]+\.\w+$"
                if not new_username:
                    st.error("Username is required.")
                elif len(new_password) < 6:
                    st.error("Password must be at least 6 characters long.")
                elif new_email and not re.match(email_regex, new_email):
                    st.error("Please enter a valid email address.")
                else:
                    success = create_user(new_username, new_password, new_email)
                    if success:
                        st.success("Registered successfully")
                        time.sleep(2)
                        st.session_state.show_register = False
                    else:
                        st.error("Username or Email already exists")
        if st.button("Back to Login"):
            st.session_state.show_register = False
            st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)

elif st.session_state.page == "main":
    with st.sidebar:
        df = get_expenses(st.session_state.user_id)
        st.markdown("### User Summary")
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT username FROM users WHERE id=?", (st.session_state.user_id,))
        user_row = cursor.fetchone()
        conn.close()
        if user_row:
            st.write(f"**Username:** {user_row[0]}")
        if not df.empty:
            st.write(f"**Total Spent:** {format_currency(df['amount'].sum(), 'INR', locale='en_IN')}")
            st.write(f"**Entries:** {len(df)}")
            st.write(f"**Avg Spend/Entry:** {format_currency(df['amount'].mean(), 'INR', locale='en_IN')}")
        st.markdown("---")
        if st.button("Logout"):
            st.session_state.user_id = None
            reroute("auth")

    tabs = st.tabs(["Dashboard", "Add Expense", "Reports", "All Entries"])

    with tabs[0]:
        st.subheader("Dashboard Overview")
        df = get_expenses(st.session_state.user_id)
        if not df.empty:
            total_spent = df['amount'].sum()
            avg_spent = df['amount'].mean()
            max_spent = df['amount'].max()
            min_spent = df['amount'].min()

            col1, col2 = st.columns(2)
            with col1:
                st.metric("Total Spent", format_currency(total_spent, 'INR', locale='en_IN'))
                st.metric("Highest Single Expense", format_currency(max_spent, 'INR', locale='en_IN'))
            with col2:
                st.metric("Average per Entry", format_currency(avg_spent, 'INR', locale='en_IN'))
                st.metric("Lowest Single Expense", format_currency(min_spent, 'INR', locale='en_IN'))

            st.markdown("### Category-wise Breakdown")
            import plotly.express as px
            cat_data = df.groupby("category")["amount"].sum().reset_index()
            cat_data["formatted"] = cat_data["amount"].apply(lambda x: format_currency(x, 'INR', locale='en_IN'))
            pie = px.pie(cat_data, names="category", values="amount", hole=0.3, custom_data=["formatted"])
            pie.update_traces(textinfo='percent+label', hovertemplate='%{label}<br>Total: %{customdata[0]}<extra></extra>')
            st.plotly_chart(pie, use_container_width=True, key='pie_chart')

            # Add necessary vs non-necessary breakdown
            st.markdown("### Necessary vs Non-Necessary")
            necessity_data = df.groupby("is_necessary")["amount"].sum().reset_index()
            necessity_data["label"] = necessity_data["is_necessary"].map({1: "Necessary", 0: "Non-Necessary"})
            donut = px.pie(necessity_data, names="label", values="amount", hole=0.4)
            donut.update_traces(textinfo='percent+label', hovertemplate='%{label}: ₹%{value:,.2f}')
            st.plotly_chart(donut, use_container_width=True, key='necessity_pie')

            # Add top 5 highest expenses table
            st.markdown("### Top 5 Highest Expenses")
            top_expenses = df.sort_values("amount", ascending=False).head(5)
            st.dataframe(top_expenses[["amount", "category", "date", "description"]])
        else:
            st.info("No expense data available.")

    with tabs[1]:
        st.subheader("Add New Expense")
        with st.form("expense_form"):
            amount = st.number_input("Amount", min_value=0.0)
            category = st.selectbox("Category", ["Food", "Transport", "Utilities", "Entertainment", "Miscellaneous"])
            date = st.date_input("Date", value=datetime.now().date())
            is_necessary = st.checkbox("Is this a necessary expense?", value=True)
            description = st.text_input("Short Description")
            if st.form_submit_button("Add Expense"):
                add_expense(st.session_state.user_id, amount, category, str(date), is_necessary, description)
                st.success("Expense added successfully")

    with tabs[2]:
        st.subheader("Detailed Monthly Report")
        if not df.empty:
            df['date'] = pd.to_datetime(df['date'])
            df['Month'] = df['date'].dt.strftime('%B %Y')
            df['Weekday'] = df['date'].dt.day_name()

            st.markdown("### Monthly Summary Table")
            monthly_summary = df.groupby(df['date'].dt.to_period("M"))['amount'].agg(['count', 'sum', 'mean', 'max', 'min']).reset_index()
            monthly_summary.columns = ['Month', 'Total Entries', 'Total Spent', 'Average', 'Max', 'Min']
            monthly_summary['Month'] = monthly_summary['Month'].dt.strftime('%B %Y')
            for col in ['Total Spent', 'Average', 'Max', 'Min']:
                monthly_summary[col] = monthly_summary[col].apply(lambda x: format_currency(x, 'INR', locale='en_IN'))
            st.dataframe(monthly_summary)

            st.markdown("### Category Distribution per Month")
            monthly_cat = df.groupby([df['date'].dt.to_period('M'), 'category'])['amount'].sum().reset_index()
            monthly_cat['date'] = monthly_cat['date'].dt.to_timestamp()
            import plotly.express as px
            cat_fig = px.bar(monthly_cat, x='date', y='amount', color='category', barmode='group',
                             labels={'amount': 'Total Spent', 'date': 'Month'},
                             title='Spending per Category Over Time')
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
            monthly_avg = df.copy()
            monthly_avg = monthly_avg.groupby(monthly_avg['date'].dt.to_period("M"))['amount'].mean().reset_index()
            monthly_avg['month'] = monthly_avg['date'].dt.strftime('%b %Y')
            monthly_avg['date'] = monthly_avg['date'].dt.to_timestamp()
            monthly_avg = monthly_avg.sort_values("date")
            line_fig = px.line(monthly_avg, x='month', y='amount', markers=True, title='Average Monthly Expense Over Time')
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

            st.markdown("### Overall Category-wise Distribution")
            category_total = df.groupby("category")["amount"].sum().reset_index()
            category_total["formatted"] = category_total["amount"].apply(lambda x: format_currency(x, 'INR', locale='en_IN'))
            pie_fig = px.pie(category_total, names="category", values="amount", hole=0.4, custom_data=["formatted"])
            pie_fig.update_traces(textinfo='percent+label', hovertemplate='%{label}<br>Total: %{customdata[0]}<extra></extra>')
            pie_fig.update_layout(title="Category-wise Spending Distribution")
            st.plotly_chart(pie_fig, use_container_width=True)
        else:
            st.info("No expense data available.")
            
    with tabs[3]:
        st.subheader("All Expense Entries")
        if not df.empty:
            st.dataframe(df.drop(columns=["user_id"]))
        else:
            st.info("No expenses recorded yet.")
    
