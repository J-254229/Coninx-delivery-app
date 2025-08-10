import os
import json
import requests
import threading
from datetime import datetime

import streamlit as st
from dotenv import load_dotenv

import pandas as pd
import firebase_admin
from firebase_admin import credentials, firestore

# -------------------- Setup --------------------
load_dotenv()

FIREBASE_KEY_PATH = os.getenv("FIREBASE_KEY_PATH")
SERVER_KEY = os.getenv("FCM_SERVER_KEY")  # FCM Server Key, store securely in .env

if not FIREBASE_KEY_PATH or not os.path.exists(FIREBASE_KEY_PATH):
    st.error(f"Firebase key file not found at: {FIREBASE_KEY_PATH}")
    st.stop()

if not SERVER_KEY:
    st.error("FCM Server Key (FCM_SERVER_KEY) missing in .env")
    st.stop()

if not firebase_admin._apps:
    cred = credentials.Certificate(FIREBASE_KEY_PATH)
    firebase_admin.initialize_app(cred)

db = firestore.client()

# -------------------- Helper Functions --------------------
def send_push_notification_async(token, title, body, data=None):
    """Send FCM push notification asynchronously."""
    def worker():
        url = "https://fcm.googleapis.com/fcm/send"
        headers = {
            "Authorization": f"key={SERVER_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "to": token,
            "notification": {"title": title, "body": body},
            "data": data or {}
        }
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=5)
            print("Push response:", resp.text)
        except Exception as e:
            print("Push error:", e)
    threading.Thread(target=worker, daemon=True).start()

# -------------------- Streamlit Pages --------------------
def manage_drivers():
    st.header("Manage Drivers")
    
    name = st.text_input("Driver Name").strip()
    code = st.text_input("Driver Code (unique)").strip().lower()
    phone = st.text_input("Phone Number").strip()
    fcm_token = st.text_area("FCM Token").strip()

    if st.button("Save Driver"):
        if not name or not code:
            st.warning("Driver Name and Code are required.")
            return
        
        db.collection("drivers").document(code).set({
            "name": name,
            "code": code,
            "phone": phone,
            "fcm_token": fcm_token
        })
        st.success("Driver saved successfully!")

    st.subheader("Current Drivers")
    drivers = db.collection("drivers").stream()
    for doc in drivers:
        d = doc.to_dict()
        st.write(f"**{d['name']}** ({d['code']}) - {d.get('phone','')}")

def assign_delivery():
    st.header("Assign Delivery")
    drivers = {doc.id: doc.to_dict() for doc in db.collection("drivers").stream()}

    if not drivers:
        st.warning("No drivers available. Please add drivers first.")
        return

    client_name = st.text_input("Client Name")
    delivery_location = st.text_input("Delivery Location")
    invoice_number = st.text_input("Invoice Number").strip()
    driver_choice = st.selectbox("Select Driver", options=list(drivers.keys()))

    if st.button("Assign Delivery"):
        if not client_name or not delivery_location or not invoice_number:
            st.warning("Please fill all delivery details.")
            return

        # Check for duplicate invoice
        existing = db.collection("deliveries").where("invoice", "==", invoice_number).stream()
        if any(existing):
            st.error(f"Invoice number '{invoice_number}' already exists! Please use a unique one.")
            return

        delivery_data = {
            "client": client_name,
            "location": delivery_location,
            "invoice": invoice_number,
            "driver_code": driver_choice,
            "status": "Assigned",
            "time": datetime.now().isoformat()
        }
        db.collection("deliveries").add(delivery_data)

        token = drivers[driver_choice].get("fcm_token")
        if token:
            send_push_notification_async(
                token,
                "New Delivery Assigned",
                f"{client_name} - {delivery_location}",
                data={"invoice": invoice_number}
            )

        st.success("Delivery assigned!")

    # Collapsible section for audit view with filtering, search, export
    with st.expander("📦 Current Orders (Audit & Export)", expanded=False):
        deliveries = db.collection("deliveries").order_by("time", direction=firestore.Query.DESCENDING).stream()
        orders = [doc.to_dict() for doc in deliveries]
        if not orders:
            st.info("No current orders.")
            return

        df = pd.DataFrame(orders)
        # Convert 'time' to datetime
        if "time" in df.columns:
            df["time"] = pd.to_datetime(df["time"], errors='coerce')

        # Status filter: always include these fixed statuses
        fixed_statuses = ["Pending", "In Transit", "Delivered"]
        data_statuses = df["status"].dropna().unique().tolist()

        def normalize_status(s):
            return s.strip().title() if isinstance(s, str) else s

        normalized_data_statuses = list(set(normalize_status(s) for s in data_statuses))
        all_statuses = sorted(set(fixed_statuses + normalized_data_statuses))
        statuses = ["All"] + all_statuses

        selected_status = st.selectbox("Filter by Status", statuses)

        drivers_list = ["All"] + sorted(df["driver_code"].dropna().unique().tolist())
        selected_driver = st.selectbox("Filter by Driver", drivers_list)

        date_min = df["time"].min() if not df["time"].isnull().all() else None
        date_max = df["time"].max() if not df["time"].isnull().all() else None

        date_range = st.date_input(
            "Filter by Date Range",
            value=(date_min.date() if date_min else datetime.today(), date_max.date() if date_max else datetime.today()),
            min_value=date_min.date() if date_min else None,
            max_value=date_max.date() if date_max else None,
        )

        search_text = st.text_input("Search Client or Invoice (partial, case-insensitive)").strip().lower()

        # Apply filters
        if selected_status != "All":
            df = df[df["status"].str.strip().str.title() == selected_status]

        if selected_driver != "All":
            df = df[df["driver_code"] == selected_driver]

        if len(date_range) == 2:
            start_date, end_date = date_range
            df = df[(df["time"].dt.date >= start_date) & (df["time"].dt.date <= end_date)]

        if search_text:
            df = df[
                df["client"].str.lower().str.contains(search_text, na=False) |
                df["invoice"].str.lower().str.contains(search_text, na=False)
            ]

        if df.empty:
            st.info("No deliveries match the filter criteria.")
            return

        # Show filtered dataframe with selected columns
        st.dataframe(df[["client", "location", "invoice", "driver_code", "status", "time"]])

        # Export filtered data to CSV
        csv = df.to_csv(index=False).encode("utf-8")
        st.download_button(
            label="Export Filtered Deliveries to CSV",
            data=csv,
            file_name="filtered_deliveries.csv",
            mime="text/csv",
        )

# -------------------- Main --------------------
def main():
    st.sidebar.title("Delivery App Menu")
    tab = st.sidebar.radio("Select Page", ["Manage Drivers", "Assign Delivery"])

    if tab == "Manage Drivers":
        manage_drivers()
    elif tab == "Assign Delivery":
        assign_delivery()

if __name__ == "__main__":
    main()
