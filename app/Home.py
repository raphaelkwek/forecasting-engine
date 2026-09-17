"""App entrypoint: sidebar navigation.

Run with: uv run streamlit run app/Home.py
"""

import streamlit as st

st.set_page_config(page_title="Forecasting Engine", page_icon=":material/monitoring:")

pg = st.navigation(
    [
        st.Page("app_pages/0_Home.py", title="Home", icon=":material/home:", default=True),
        st.Page("app_pages/1_Data.py", title="Data", icon=":material/database:"),
        st.Page("app_pages/4_Models.py", title="Models", icon=":material/functions:"),
        st.Page(
            "app_pages/3_Model_Metrics.py",
            title="Model Metrics",
            icon=":material/table_chart:",
        ),
    ]
)
pg.run()
