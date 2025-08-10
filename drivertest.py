# driver.py
import os
from datetime import datetime
import streamlit as st
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, firestore, messaging

st.set_page_config(page_title="Driver Dashboard", layout="wide")
st.title("🚚 Driver Dashboard")

# --- Firebase Init ---
load_dotenv()
FIREBASE_KEY_PATH = os.getenv("FIREBASE_KEY_PATH")
if not firebase_admin._apps:
    cred = credentials.Certificate(FIREBASE_KEY_PATH)
    firebase_admin.initialize_app(cred)

db = firestore.client()

# --- FCM Function ---
def send_fcm(token, title, body):
    try:
        message = messaging.Message(
            notification=messaging.Notification(title=title, body=body),
            token=token
        )
        return messaging.send(message)
    except Exception as e:
        st.error(f"FCM error: {e}")

# --- Driver Interface ---
driver_code = st.text_input("Enter Driver Code").strip().lower()
fcm_token = st.text_input("FCM Token").strip()

if not driver_code:
    st.stop()

# Store FCM token
if fcm_token:
    db.collection("drivers").document(driver_code).set({
        "fcm_token": fcm_token,
        "last_seen": datetime.now().isoformat()
    }, merge=True)

deliveries = db.collection("deliveries") \
    .where("driver_code", "==", driver_code) \
    .where("status", "in", ["pending", "accepted", "in_transit"]) \
    .stream()

deliveries = list(deliveries)
if not deliveries:
    st.info("No deliveries assigned.")
    st.stop()

for d in deliveries:
    data = d.to_dict()
    doc_id = d.id
    st.subheader(f"Invoice: {data.get('invoice_number')}")
    st.write(f"Client: {data.get('client_name')}")
    st.write(f"Location: {data.get('location')}")
    st.write(f"Status: {data.get('status')}")

    if data["status"] == "pending":
        if st.button("✅ Accept", key=f"a{doc_id}"):
            db.document(f"deliveries/{doc_id}").update({
                "status": "accepted",
                "timestamps.accepted": datetime.now().isoformat()
            })
            st.success("Accepted. Refreshing...")
            st.experimental_rerun()

        if st.button("❌ Reject", key=f"r{doc_id}"):
            reason = st.text_area("Reason:", key=f"reason_{doc_id}")
            if st.button("Submit", key=f"submit_{doc_id}") and reason.strip():
                db.document(f"deliveries/{doc_id}").update({
                    "status": "rejected",
                    "rejection_reason": reason.strip(),
                    "timestamps.rejected": datetime.now().isoformat()
                })
                st.warning("Rejected. Refreshing...")
                st.experimental_rerun()

    elif data["status"] == "accepted":
        if st.button("📦 In Transit", key=f"t{doc_id}"):
            db.document(f"deliveries/{doc_id}").update({
                "status": "in_transit",
                "timestamps.in_transit": datetime.now().isoformat()
            })
            st.info("Marked in transit.")
            st.experimental_rerun()

    elif data["status"] == "in_transit":
        if st.button("✅ Delivered", key=f"d{doc_id}"):
            db.document(f"deliveries/{doc_id}").update({
                "status": "delivered",
                "timestamps.delivered": datetime.now().isoformat()
            })
            st.success("Marked delivered.")
            st.experimental_rerun()
