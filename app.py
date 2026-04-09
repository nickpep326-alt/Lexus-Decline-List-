import streamlit as st
import pandas as pd
import re
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials

# --- PAGE CONFIG ---
st.set_page_config(page_title="Lexus CRM Dashboard", layout="wide")
st.title("Lexus Declined Repair Follow-Up Dashboard")
st.markdown("Team workspace for BDC, Advisors, and Management to track and follow up on declined services.")

# --- GOOGLE SHEETS CLOUD DATABASE SETUP ---
@st.cache_resource
def init_connection():
    try:
        creds = Credentials.from_service_account_info(
            st.secrets["gcp_service_account"],
            scopes=['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
        )
        client = gspread.authorize(creds)
        sheet = client.open_by_url(st.secrets["private"]["google_sheet_url"]).sheet1
        return sheet
    except Exception as e:
        return None

sheet = init_connection()

# Fetch already contacted ROs from the cloud
@st.cache_data(ttl=10) 
def get_contacted_ros(_sheet):
    if _sheet is None: return []
    try:
        records = _sheet.get_all_records()
        return [str(row['RO Number']) for row in records if 'RO Number' in row]
    except:
        return []

contacted_ros = get_contacted_ros(sheet)

# --- DATA PROCESSING ---
def extract_total_amount(text):
    if pd.isna(text): return 0.0
    matches = re.findall(r'\$([0-9,]+(?:\.\d{2})?)', str(text))
    total = 0.0
    for match in matches:
        try: total += float(match.replace(',', ''))
        except: pass
    return total

def categorize_repair(text):
    if pd.isna(text) or str(text).strip() == '': return 'Manager Review'
    text_lower = str(text).lower()
    categories = []
    
    # Expanded Tire Dictionary
    tire_brands = ['tire', 'alignment', 'michelin', 'goodyear', 'yokohama', 'bridgestone', 'pirelli', 'continental', 'dunlop', 'firestone', 'hankook', 'kumho', 'falken', 'toyo']
    if any(brand in text_lower for brand in tire_brands): categories.append('Tires')
    
    # Expanded Brake Dictionary
    brake_keywords = ['brake', 'rotor', 'pad', 'caliper', 'resurface', 'shoe']
    if any(kw in text_lower for kw in brake_keywords): categories.append('Brakes')
    
    # Expanded Service Dictionary
    service_keywords = ['service', 'fluid', 'filter', 'maintenance', 'flush', 'spark plug', 'battery', 'wiper', 'bulb', 'oil', 'synthetic', 'coolant']
    if any(kw in text_lower for kw in service_keywords): categories.append('Services')
    
    if not categories: return 'Other'
    
    # Join multiple categories together (e.g., "Tires, Brakes")
    return ', '.join(categories)

# CACHE REMOVED HERE: Ensures the data is processed fresh every single time you upload!
def process_data(df):
    internal_names = ["RAY CATENA LEXUS OF MONMOUTH", "RAY CATENA LEXUS OF FREEHOLD"]
    df = df[~df['FULL-NAME-DV'].isin(internal_names)].copy()
    
    df['Extracted_Amount'] = df['RO-RECOM'].apply(extract_total_amount)
    df['Category'] = df['RO-RECOM'].apply(categorize_repair)
    df['Needs_Recheck'] = df['RO-RECOM'].str.lower().str.contains('recheck', na=False)
    
    df['RO-DATE-DT'] = pd.to_datetime(df['RO-DATE'], errors='coerce')
    today = pd.to_datetime('today').normalize()
    df['Days_Since'] = (today - df['RO-DATE-DT']).dt.days
    
    if 'ADVISOR' not in df.columns:
        if 'ADVISOR NAME' in df.columns: df['ADVISOR'] = df['ADVISOR NAME']
        elif 'ADVISOR-NAME' in df.columns: df['ADVISOR'] = df['ADVISOR-NAME']
        else: df['ADVISOR'] = 'Unknown'
        
    df['ADVISOR'] = df['ADVISOR'].fillna('Unknown').astype(str).str.strip().str.title()
    df['ADVISOR'] = df['ADVISOR'].replace({'Nan': 'Unknown', '': 'Unknown'})
        
    if 'EMAIL' not in df.columns:
        if 'EMAIL-ADDRESS' in df.columns: df['EMAIL'] = df['EMAIL-ADDRESS']
        else: df['EMAIL'] = 'No Email Provided'
    
    def assign_tier(amt):
        if amt >= 5000: return "Ultra-Ticket (>$5000)"
        elif amt >= 1000: return "High-Ticket ($1000-$4999)"
        elif amt >= 300: return "Mid-Ticket ($300-$999)"
        elif amt > 0: return "Low-Ticket (<$300)"
        else: return "Unpriced / Zero"
        
    df['Dollar Tier'] = df['Extracted_Amount'].apply(assign_tier)
    df['FULL-NAME-DV'] = df['FULL-NAME-DV'].astype(str).str.title()
    
    rename_cols = {
        'FULL-NAME-DV': 'Customer Name', 'PH-CELL-FMT-DV': 'Phone Number',
        'Extracted_Amount': 'Declined Work Total', 'Days_Since': 'Last Serviced',
        'MODEL': 'Model', 'YEAR': 'Year', 'SER-NO': 'VIN',
        'RO-DATE': 'RO Date', 'RECID': 'RO Number', 'RO-RECOM': 'Original Notes'
    }
    df.rename(columns=rename_cols, inplace=True)
    return df

# --- SIDEBAR IDENTIFIER ---
st.sidebar.markdown("### 👤 User Login")
agent_name = st.sidebar.text_input("Your Name (Required to log calls)", placeholder="e.g., John D.")
st.sidebar.divider()

# --- FILE UPLOADER ---
uploaded_file = st.sidebar.file_uploader("Upload Reynolds Export (CSV)", type=['csv'])

if uploaded_file:
    raw_df = pd.read_csv(uploaded_file)
    df = process_data(raw_df)
    
    # FILTER OUT CLOUD-CONTACTED LEADS
    df = df[~df['RO Number'].astype(str).isin(contacted_ros)]
    
    # --- SIDEBAR FILTERS ---
    st.sidebar.header("Filter Pipeline")
    tier_filter = st.sidebar.selectbox("Dollar Tier", ["All", "Ultra-Ticket (>$5000)", "High-Ticket ($1000-$4999)", "Mid-Ticket ($300-$999)", "Low-Ticket (<$300)", "Unpriced / Zero"])
    
    # --- UPGRADED MULTI-SELECT CATEGORY FILTER ---
    category_options = ["Tires", "Brakes", "Services", "Manager Review", "Other"]
    category_filter = st.sidebar.multiselect(
        "Repair Category (Select one or multiple)", 
        options=category_options,
        default=category_options  # Starts with all selected
    )
    
    advisor_list = ["All"] + sorted(list(df['ADVISOR'].unique()))
    advisor_filter = st.sidebar.selectbox("Advisor Name (Scroll or Type)", advisor_list)
    stage_filter = st.sidebar.radio("Follow-Up Stage", ["7-Day (Soft Touch)", "30-Day (Check-in)", "60-Day (Offer)", "90-Day (Re-engage/Audit)"])
    
    # Apply Filters & Reset Index
    filtered_df = df.copy()
    
    # Filter Dollar Tier
    if tier_filter != "All": 
        filtered_df = filtered_df[filtered_df['Dollar Tier'] == tier_filter]
        
    # Filter Category (Multi-Select Logic)
    if not category_filter:
        # If they uncheck everything, show an empty list instead of crashing
        filtered_df = filtered_df.iloc[0:0] 
    elif len(category_filter) < len(category_options):
        # Create a search pattern that looks for ANY of the selected categories
        pattern = '|'.join(category_filter)
        filtered_df = filtered_df[filtered_df['Category'].str.contains(pattern, case=False, na=False)]
        
    # Filter Advisor
    if advisor_filter != "All": 
        filtered_df = filtered_df[filtered_df['ADVISOR'] == advisor_filter]
        
    filtered_df = filtered_df.reset_index(drop=True) 
        
    # --- METRICS BOARD ---
    col1, col2, col3 = st.columns(3)
    col1.metric("Customers in Queue", len(filtered_df))
    col2.metric("Pipeline Value", f"${filtered_df['Declined Work Total'].sum():,.2f}")
    col3.metric("Already Contacted (Cloud)", len(contacted_ros))
    st.divider()

    # --- INTERACTIVE QUEUE TABLE ---
    st.subheader("Customer Queue (Click a row to select)")
    display_cols = ['Customer Name', 'Phone Number', 'EMAIL', 'Model', 'Category', 'Declined Work Total', 'Last Serviced']
    
    selection_event = st.dataframe(
        filtered_df[display_cols].style.format({'Declined Work Total': '${:,.2f}', 'Last Serviced': '{:.0f} days'}),
        use_container_width=True,
        on_select="rerun",
        selection_mode="single-row"
    )
    st.divider()
    
    # --- ACTION PANEL ---
    st.subheader("Action & Outreach Panel")
    selected_rows = selection_event.selection.rows

    if len(selected_rows) > 0:
        selected_index = selected_rows[0]
        customer = filtered_df.iloc[selected_index]
        days_ago = int(customer['Last Serviced']) if pd.notna(customer['Last Serviced']) else "Unknown"
        
        c1, c2 = st.columns([1, 1])
        with c1:
            st.write(f"**Name:** {customer['Customer Name']}")
            st.write(f"**Phone:** {customer['Phone Number']}")
            st.write(f"**Email:** {customer['EMAIL']}")
            st.write(f"**Vehicle:** {customer['Year']} {customer['Model']}")
            st.markdown(f"**RO Date:** {customer['RO Date']} <span style='color:#e63946; font-weight:bold;'>({days_ago} days ago)</span> | RO #: {customer['RO Number']}", unsafe_allow_html=True)
            st.write(f"**Advisor:** {customer['ADVISOR']}")
            
            st.markdown("---")
            st.write("**VIN (Hover to right of box to copy):**")
            st.code(customer['VIN'], language="text")
            st.markdown("[🔍 Open Lexus Drivers History Portal](https://drivers.lexus.com/lexusdrivers/history)")
            st.markdown("---")
            
        with c2:
            st.error(f"**Declined Value:** ${customer['Declined Work Total']:,.2f}")
            st.warning(f"**Original Advisor Notes:**\n{customer['Original Notes']}")
            
            # --- CLOUD TRACKING BUTTON ---
            st.markdown("---")
            st.markdown("### ☁️ Lead Tracking")
            if sheet is None:
                st.warning("⚠️ Google Sheets database not connected yet. Tracking is disabled.")
            else:
                if st.button("✅ Mark as Contacted & Remove from Queue", type="primary", use_container_width=True):
                    if not agent_name:
                        st.error("🚨 Please enter your name in the top left sidebar before marking a lead!")
                    else:
                        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        try:
                            # Append to Google Sheet
                            sheet.append_row([str(customer['RO Number']), customer['Customer Name'], agent_name, timestamp, stage_filter])
                            st.success("Lead securely logged to Cloud Database! Refreshing queue...")
                            st.cache_data.clear()
                            st.rerun()
                        except Exception as e:
                            st.error(f"Failed to log: {e}")
        
        # RECHECK FLAG WARNING
        if customer['Needs_Recheck']:
            st.info("ℹ️ **RECHECK ITEM DETECTED:** The technician flagged this to be 'rechecked' rather than replaced immediately. **DO NOT push for a sale today.** Frame this follow-up as a reminder to monitor the item and to get their next regular service scheduled so we can keep an eye on it.")

        st.markdown("### Message Templates")
        
        name = str(customer['Customer Name']).split()[0] if pd.notna(customer['Customer Name']) else "Valued Client"
        model = str(customer['Model'])
        cat = str(customer['Category'])
        
        sms_draft = ""
        email_subj = ""
        email_body = ""

        if cat == 'Manager Review':
            sms_draft = "⚠️ DO NOT CONTACT. Flagged for Manager Review. No advisor recommendations found."
            email_body = sms_draft
        else:
            # Priority formatting check
            if 'Tires' in cat:
                if "7-Day" in stage_filter:
                    sms_draft = f"Hi {name}, this is {customer['ADVISOR']} from Ray Catena Lexus. Just a quick check-in on your {model}! Let us know if you have any questions regarding the tire quote we provided."
                    email_subj = f"Following up on your {model} visit - Ray Catena Lexus"
                    email_body = f"Hi {name},\n\nThank you for trusting us with your {model}. I wanted to follow up regarding the tire recommendations we provided last week. Ensuring you have proper tread is critical for safety and performance. Let us know if you'd like to get those scheduled!"
                elif "30-Day" in stage_filter:
                    sms_draft = f"Hi {name}, following up from Ray Catena Lexus. We want to make sure your {model} is safe for the road. Are you still considering replacing those tires? We'd be happy to check availability."
                    email_subj = f"Safety Reminder: {model} Tires - Ray Catena Lexus"
                    email_body = f"Hi {name},\n\nWe noticed you haven't had a chance to replace the tires on your {model} yet. As traction and stopping distance are vital for your safety, we highly recommend getting this taken care of soon."
                elif "60-Day" in stage_filter:
                    sms_draft = f"Hi {name}, Ray Catena Lexus here! We'd love to help get the tires sorted on your {model}. Let me know if you are still in the market and I'll see if we have any current tire rebates available!"
                    email_subj = f"Special Check on Tires for your {model} - Ray Catena Lexus"
                    email_body = f"Hi {name},\n\nWe want to earn your business back on the tire replacement for your {model}. Lexus frequently runs manufacturer rebates on premium tires—please let me know if you are ready to move forward and I will check what specials we can apply."
                elif "90-Day" in stage_filter:
                    sms_draft = f"Hi {name}, Ray Catena Lexus checking in! Just updating our records on your {model}. If you already had those tires replaced, let us know! If not, we'd love to see how we can help."
                    email_subj = f"Checking in on your {model} - Ray Catena Lexus"
                    email_body = f"Hi {name},\n\nWe certainly don't want to be a bother, but we are currently updating our vehicle service records. It's been about 3 months since we recommended tires for your {model}.\n\nIf you've already had this taken care of elsewhere, please let us know so we can update your vehicle's history! If not, we'd love the opportunity to earn your business back."

            elif 'Brakes' in cat:
                if "7-Day" in stage_filter:
                    sms_draft = f"Hi {name}, this is {customer['ADVISOR']} from Ray Catena Lexus. Just doing a courtesy check-in on your {model}. Let us know if you have any questions about the brake service quoted during your recent visit!"
                    email_subj = f"Following up on your {model} visit - Ray Catena Lexus"
                    email_body = f"Hi {name},\n\nI am following up on the brake recommendations from your recent service. Your safety is our top priority, and we want to ensure you have all the information you need. Please reply or call if you'd like to schedule."
                elif "30-Day" in stage_filter:
                    sms_draft = f"Hi {name}, from Ray Catena Lexus. A quick safety reminder regarding the brakes on your {model}. Please let us know if you'd like to schedule an appointment to get them taken care of."
                    email_subj = f"Important Safety Notice: {model} Brakes - Ray Catena Lexus"
                    email_body = f"Hi {name},\n\nWe wanted to reach out regarding the brake service recommended for your {model}. Delaying brake maintenance can sometimes lead to more costly repairs down the road. We'd love to get you on the schedule."
                elif "60-Day" in stage_filter:
                    sms_draft = f"Hi {name}, Ray Catena Lexus here. We want to help ensure your {model} is safe to drive. Is there anything holding you back from completing your recommended brake service that we can assist with?"
                    email_subj = f"Let's get your {model} brakes taken care of - Ray Catena Lexus"
                    email_body = f"Hi {name},\n\nWe are concerned about the brake wear on your {model}. Is there anything we can do to help facilitate this repair for you? Let us know if we can arrange a loaner vehicle to make the process easier."
                elif "90-Day" in stage_filter:
                    sms_draft = f"Hi {name}, Ray Catena Lexus here. We're just updating our service records. Were you able to get the brakes serviced on your {model}? We want to make sure you're driving safely!"
                    email_subj = f"Service Audit: Safety update for your {model} - Ray Catena Lexus"
                    email_body = f"Hi {name},\n\nI'm reaching out because we are doing a routine safety audit on our recent service visits. We noticed the brake service recommended for your {model} is still pending in our system.\n\nWe don't want to pester you, but since brakes are a critical safety component, we wanted to check if you had this completed elsewhere so we can close out our safety log."

            else:
                if "7-Day" in stage_filter:
                    sms_draft = f"Hi {name}, this is {customer['ADVISOR']} from Ray Catena Lexus. Just a quick courtesy follow-up on your {model}. Let us know if you have any questions about the recommended maintenance!"
                    email_subj = f"Following up on your {model} maintenance - Ray Catena Lexus"
                    email_body = f"Hi {name},\n\nI'm checking in to see if you had any questions regarding the factory maintenance we recommended during your visit. We're here to help keep your {model} running perfectly."
                elif "30-Day" in stage_filter:
                    sms_draft = f"Hi {name}, from Ray Catena Lexus. A quick reminder about the recommended services for your {model} to ensure it stays in top condition. Let us know if you'd like to schedule!"
                    email_subj = f"Maintenance Reminder for your {model} - Ray Catena Lexus"
                    email_body = f"Hi {name},\n\nWe noticed you haven't yet completed the recommended services for your {model}. Staying on top of routine maintenance is the best way to protect your vehicle's longevity and warranty."
                elif "60-Day" in stage_filter:
                    sms_draft = f"Hi {name}, Ray Catena Lexus here. We'd love to help get your {model} up to date on its maintenance. Please let me know if there's anything we can do to earn your business back on this visit!"
                    email_subj = f"Update on your {model} maintenance - Ray Catena Lexus"
                    email_body = f"Hi {name},\n\nWe want to ensure your {model} continues to deliver the luxury performance you expect. Let us know what we can do to help you get your recommended services completed. We'd be happy to check for any applicable service specials."
                elif "90-Day" in stage_filter:
                    sms_draft = f"Hi {name}, from Ray Catena Lexus! Just touching base on your {model}. If you already took care of that recommended maintenance, let us know so we can update your file!"
                    email_subj = f"Updating your {model} records - Ray Catena Lexus"
                    email_body = f"Hi {name},\n\nWe know how easily routine maintenance can slip down the to-do list! It's been a few months since your last visit with your {model}.\n\nIf there's anything we can do—like reserving a loaner car or applying a current service special—just let us know. If you've already handled the service, simply reply to let us know so we can update your history!"

        col_sms, col_email = st.columns(2)
        with col_sms:
            st.text_area("📱 Text Message Draft (Copy/Paste to Reynolds)", value=sms_draft, height=250)
        with col_email:
            email_combined = f"Subject: {email_subj}\n\n{email_body}"
            st.text_area("📧 Email Draft", value=email_combined, height=250)

        # --- DEALER TIRE & DEALERSHIP OBJECTION HANDLING SECTION ---
        st.markdown("---")
        with st.expander(f"💬 High-Conversion Dealership Rebuttals for: {cat}", expanded=True):
            
            st.markdown("""
            ### 🤝 "I need to talk to my spouse/partner about it."
            * **The Rebuttal:** "I completely understand wanting to make that decision together. Let me text or email you a copy of the multi-point inspection report so they can actually see the measurements and safety notes for themselves."
            * **The Close:** *"Since we sometimes have to order parts, can I pencil you in for next week? We can always move or cancel the appointment if your spouse decides against it once they see the report."*
            
            ### 📄 "I'm turning my lease in / trading it in soon."
            * **The Rebuttal (Lease):** "That’s actually why I'm bringing it up. Lexus Financial requires at least 4/32” of tread on tires and specific brake pad thickness. If you return it below that, they will charge you a wear-and-tear penalty that is almost always higher than the cost of replacing them here today."
            * **The Rebuttal (Trade-In):** "Our appraisers deduct heavily for worn safety items. Having these replaced now usually increases your trade-in value, so you end up recouping the money anyway, while staying safe in the meantime."
            * **The Close:** *"Would it make sense to protect your wallet from lease penalties and get this done now so you can drive safely until you turn it in?"*
            
            ### ⏱️ "I don't have time to wait today."
            * **The Rebuttal:** "I respect your time, and you don't have to wait here at all. We can set you up with a complimentary Lexus loaner car so you can run your errands, or you can relax in our customer lounge with Wi-Fi and coffee."
            * **The Close:** *"If we provide the loaner so your schedule isn't impacted, what day next week works best to drop it off?"*
            """)
            
            if 'Tires' in cat:
                st.markdown("""
                ### 🛑 TIRES: "I'll just wait until winter/bad weather." or "I don't need them right now."
                * **The Rebuttal:** "I hear you, but tires are the only thing touching the road. Even on dry pavement, bald tires drastically increase your stopping distance. Don't wait for a rainy day to find out you don't have enough traction to stop safely."
                * **The Close:** *"Since your tires are already below safety standards, let's look at getting them replaced so you aren't risking an accident. Should I check our current tire rebates?"*
                
                ### 🛑 TIRES: "I can get them cheaper at Costco / Mavis."
                * **The Rebuttal:** "I totally get wanting the best price. That is exactly why we offer a Tire Price Match Guarantee. Make sure they are giving you an 'apples-to-apples' quote—our tires include complimentary 24-month Road Hazard coverage, factory-trained installation, a car wash, and a loaner vehicle."
                * **The Close:** *"If I can match the price of the tires you found, would you prefer to have our Lexus Master Technicians handle the installation today?"*
                """)
            if 'Brakes' in cat:
                st.markdown("""
                ### 🛑 BRAKES: "They aren't squeaking or vibrating yet, I'll wait until my next service."
                * **The Rebuttal:** "I'm glad you aren't experiencing any noise or steering wheel vibrations yet! Our primary concern right now is your safety. As brake pads get this low, they lose their ability to dissipate heat. This significantly increases your emergency stopping distance, and the excess heat can warp your rotors. Because we strictly follow Lexus safety standards, we do not cut or resurface warped rotors—they must be completely replaced."
                * **The Close:** *"For your safety and to prevent any performance loss or vibration on the highway, would you like us to get these pads swapped out today?"*
                """)
            if 'Services' in cat or cat == 'Other':
                st.markdown("""
                ### 🛑 SERVICES: "I'll just take it to my local independent mechanic."
                * **The Rebuttal:** "You absolutely have that right. Just keep in mind that doing your maintenance with us ensures your Lexus warranty stays fully intact. Local shops don't have our proprietary diagnostic software, and they cannot perform the open factory safety recall checks we do during every single visit."
                * **The Close:** *"For the peace of mind knowing it was done to exact factory specs by Master Certified techs, plus the complimentary loaner, doesn't it make sense to keep your Lexus with Lexus?"*
                """)

    else:
        st.info("👆 Click on any customer row in the table above to open their file and generate follow-up templates.")

else:
    st.info("👋 Welcome! Please upload your Reynolds CSV export using the sidebar on the left to begin.")
