import streamlit as st
import pandas as pd
import re
from datetime import datetime

# --- PAGE CONFIG ---
st.set_page_config(page_title="Lexus CRM Dashboard", layout="wide")
st.title("Lexus Declined Repair Follow-Up Dashboard")
st.markdown("Team workspace for BDC, Advisors, and Management to track and follow up on declined services.")

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
    if 'tire' in text_lower or 'alignment' in text_lower: categories.append('Tires')
    if 'brake' in text_lower or 'rotor' in text_lower or 'pad' in text_lower: categories.append('Brakes')
    if 'service' in text_lower or 'fluid' in text_lower or 'filter' in text_lower or 'maintenance' in text_lower: categories.append('Services')
    
    if not categories: return 'Other'
    return categories[0]

@st.cache_data
def process_data(df):
    internal_names = ["RAY CATENA LEXUS OF MONMOUTH", "RAY CATENA LEXUS OF FREEHOLD"]
    df = df[~df['FULL-NAME-DV'].isin(internal_names)].copy()
    
    df['Extracted_Amount'] = df['RO-RECOM'].apply(extract_total_amount)
    df['Category'] = df['RO-RECOM'].apply(categorize_repair)
    
    # Calculate Days Since Visit
    df['RO-DATE-DT'] = pd.to_datetime(df['RO-DATE'], errors='coerce')
    today = pd.to_datetime('today').normalize()
    df['Days_Since'] = (today - df['RO-DATE-DT']).dt.days
    
    # Updated Tiers with $5000+ category
    def assign_tier(amt):
        if amt >= 5000: return "Ultra-Ticket (>$5000)"
        elif amt >= 1000: return "High-Ticket ($1000-$4999)"
        elif amt >= 300: return "Mid-Ticket ($300-$999)"
        elif amt > 0: return "Low-Ticket (<$300)"
        else: return "Unpriced / Zero"
        
    df['Dollar Tier'] = df['Extracted_Amount'].apply(assign_tier)
    df['FULL-NAME-DV'] = df['FULL-NAME-DV'].astype(str).str.title()
    return df

# --- FILE UPLOADER ---
uploaded_file = st.sidebar.file_uploader("Upload Reynolds Export (CSV)", type=['csv'])

if uploaded_file:
    raw_df = pd.read_csv(uploaded_file)
    df = process_data(raw_df)
    
    # --- SIDEBAR FILTERS ---
    st.sidebar.header("Filter Pipeline")
    tier_filter = st.sidebar.selectbox("Dollar Tier", ["All", "Ultra-Ticket (>$5000)", "High-Ticket ($1000-$4999)", "Mid-Ticket ($300-$999)", "Low-Ticket (<$300)", "Unpriced / Zero"])
    category_filter = st.sidebar.selectbox("Repair Category", ["All", "Tires", "Brakes", "Services", "Manager Review", "Other"])
    stage_filter = st.sidebar.radio("Follow-Up Stage", ["7-Day (Soft Touch)", "30-Day (Check-in)", "60-Day (Offer)", "90-Day (Re-engage/Audit)"])
    
    # Apply Filters & Reset Index
    filtered_df = df.copy()
    if tier_filter != "All": filtered_df = filtered_df[filtered_df['Dollar Tier'] == tier_filter]
    if category_filter != "All": filtered_df = filtered_df[filtered_df['Category'].str.contains(category_filter, na=False)]
    filtered_df = filtered_df.reset_index(drop=True) 
        
    # --- METRICS BOARD ---
    col1, col2, col3 = st.columns(3)
    col1.metric("Customers in Queue", len(filtered_df))
    col2.metric("Pipeline Value", f"${filtered_df['Extracted_Amount'].sum():,.2f}")
    col3.metric("Flagged for Review", len(df[df['Category'] == 'Manager Review']))
    st.divider()

    # --- INTERACTIVE QUEUE TABLE ---
    st.subheader("Customer Queue (Click a row to select)")
    display_cols = ['FULL-NAME-DV', 'PH-CELL-FMT-DV', 'MODEL', 'Category', 'Extracted_Amount', 'Days_Since']
    
    selection_event = st.dataframe(
        filtered_df[display_cols].style.format({'Extracted_Amount': '${:,.2f}', 'Days_Since': '{:.0f} days'}),
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
        days_ago = int(customer['Days_Since']) if pd.notna(customer['Days_Since']) else "Unknown"
        
        c1, c2 = st.columns([1, 1])
        with c1:
            st.write(f"**Name:** {customer['FULL-NAME-DV']}")
            st.write(f"**Phone:** {customer['PH-CELL-FMT-DV']}")
            st.write(f"**Vehicle:** {customer['YEAR']} {customer['MODEL']}")
            st.markdown(f"**RO Date:** {customer['RO-DATE']} <span style='color:#e63946; font-weight:bold;'>({days_ago} days ago)</span> | RO #: {customer['RECID']}", unsafe_allow_html=True)
        with c2:
            st.error(f"**Declined Value:** ${customer['Extracted_Amount']:,.2f}")
            st.warning(f"**Original Advisor Notes:**\n{customer['RO-RECOM']}")
            
        st.markdown("---")
        st.markdown("### Message Templates")
        
        name = str(customer['FULL-NAME-DV']).split()[0] if pd.notna(customer['FULL-NAME-DV']) else "Valued Client"
        model = str(customer['MODEL'])
        cat = str(customer['Category'])
        
        sms_draft = ""
        email_subj = ""
        email_body = ""

        if cat == 'Manager Review':
            sms_draft = "⚠️ DO NOT CONTACT. Flagged for Manager Review. No advisor recommendations found."
            email_body = sms_draft
        else:
            if 'Tires' in cat:
                if "7-Day" in stage_filter:
                    sms_draft = f"Hi {name}, this is Ray Catena Lexus. Just a quick check-in on your {model}! Let us know if you have any questions regarding the tire quote we provided during your visit."
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
                    email_body = f"Hi {name},\n\nWe certainly don't want to be a bother, but we are currently updating our vehicle service records. It's been about 3 months since we recommended tires for your {model}.\n\nIf you've already had this taken care of elsewhere, please let us know so we can update your vehicle's history! If not, we'd love the opportunity to earn your business back. Let me know if you'd like me to check our current tire promos for you."

            elif 'Brakes' in cat:
                if "7-Day" in stage_filter:
                    sms_draft = f"Hi {name}, Ray Catena Lexus here. Just doing a courtesy check-in on your {model}. Let us know if you have any questions about the brake service quoted during your recent visit!"
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
                    email_body = f"Hi {name},\n\nI'm reaching out because we are doing a routine safety audit on our recent service visits. We noticed the brake service recommended for your {model} is still pending in our system.\n\nWe don't want to pester you, but since brakes are a critical safety component, we wanted to check if you had this completed elsewhere so we can close out our safety log. Please hit reply and let us know, or let us know if we can set up a loaner for you to bring it in!"

            else:
                if "7-Day" in stage_filter:
                    sms_draft = f"Hi {name}, this is Ray Catena Lexus. Just a quick courtesy follow-up on your {model}. Let us know if you have any questions about the recommended maintenance!"
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
                    email_body = f"Hi {name},\n\nWe know how easily routine maintenance can slip down the to-do list! It's been a few months since your last visit with your {model}.\n\nIf there's anything we can do—like reserving a loaner car or applying a current service special—just let us know. If you've already handled the service, simply reply to let us know so we can update your vehicle's service history so you stop getting these reminders!"

        col_sms, col_email = st.columns(2)
        with col_sms:
            st.text_area("📱 Text Message Draft (Copy/Paste to Reynolds)", value=sms_draft, height=250)
        with col_email:
            email_combined = f"Subject: {email_subj}\n\n{email_body}"
            st.text_area("📧 Email Draft", value=email_combined, height=250)

        # --- OBJECTION HANDLING SECTION ---
        st.markdown("---")
        with st.expander(f"💬 Overcoming Objections: Talk Tracks for {cat}", expanded=True):
            if cat == 'Tires':
                st.markdown("""
                ### 🛑 Objection: Price ("I can get them cheaper somewhere else.")
                * **The Rebuttal:** "I completely understand wanting the best price. We actually offer a Tire Price Match Guarantee. Plus, purchasing through us includes complimentary 24-month Road Hazard coverage, which most discount shops charge extra for."
                * **The Close:** *"If I can match the price of the tires you found, would you prefer to have our Lexus Master Technicians handle the installation today?"*
                
                ### 🛑 Objection: Time ("I don't have time to sit and wait at the dealership.")
                * **The Rebuttal:** "I completely respect your time. You don't have to wait here at all. We can reserve a complimentary Lexus loaner vehicle for you. You just drop your car off, take the loaner to work or run your errands, and come back when it's ready."
                * **The Close:** *"What day this week works best for you to pick up your loaner vehicle?"*
                """)
            elif cat == 'Brakes':
                st.markdown("""
                ### 🛑 Objection: Price / Delaying ("They aren't squeaking yet, I'll wait.")
                * **The Rebuttal:** "I'm glad you aren't hearing noise yet! However, we actually want to replace the pads *before* they grind. Here at Lexus, we do not cut or resurface damaged rotors—they must be completely replaced. If the pads wear down to the metal and score the rotors, it easily doubles or triples the cost of your repair."
                * **The Close:** *"Since replacing just the pads right now will save you the cost of a full rotor replacement later, would you like to get this taken care of?"*
                
                ### 🛑 Objection: Time ("I need my car for work, I can't leave it.")
                * **The Rebuttal:** "We don't want this to interrupt your day at all. Brake safety is a priority, so we will set you up with a complimentary Lexus loaner car. You can seamlessly continue your day while we get your vehicle safe for the road."
                * **The Close:** *"Would morning or afternoon be easier for you to swap into the loaner?"*
                """)
            elif cat == 'Services':
                st.markdown("""
                ### 🛑 Objection: Price ("I'll just take it to my local mechanic / Jiffy Lube.")
                * **The Rebuttal:** "You absolutely have that right. Just keep in mind that our service includes Lexus-specific diagnostic checks, factory-grade fluids, and ensures your Lexus warranty stays fully intact. Local shops also can't perform the software updates and recall checks we do during your visit."
                * **The Close:** *"For the peace of mind knowing it was done to factory specs, plus the complimentary car wash, doesn't it make sense to keep your Lexus with Lexus?"*
                
                ### 🛑 Objection: Time ("I'm too busy this month to deal with maintenance.")
                * **The Rebuttal:** "We know life gets incredibly busy. That's exactly why we offer complimentary Lexus loaner vehicles. We want this to be zero hassle for you. Drop it off, take our car, and we'll let you know when yours is ready."
                * **The Close:** *"If we provide the loaner so your schedule isn't impacted, what day next week works to get this maintenance knocked out?"*
                """)
            else:
                st.markdown("*Review the specific technician notes above to formulate the best value proposition for this repair.*")

    else:
        st.info("👆 Click on any customer row in the table above to open their file and generate follow-up templates.")

else:
    st.info("👋 Welcome! Please upload your Reynolds CSV export using the sidebar on the left to begin.")