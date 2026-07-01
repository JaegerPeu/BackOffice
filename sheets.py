import streamlit as st
import gspread
from google.oauth2.service_account import Credentials

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]


@st.cache_resource
def get_gc():
    creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=SCOPES)
    return gspread.authorize(creds)


def get_sheet():
    return get_gc().open_by_key(st.secrets["SHEET_ID"])


def get_ws(nome):
    return get_sheet().worksheet(nome)
