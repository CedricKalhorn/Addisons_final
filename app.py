import math
import json
from datetime import datetime, timedelta, time
import pytz
import streamlit as st
import os
import random

# -------------------------------
# App metadata & disclaimer
# -------------------------------
st.set_page_config(page_title="Addison Sense & Dose (Lab-on-Chip)", page_icon="🩺", layout="wide")
st.title("🩺 Addison Sense & Dose — Lab-on-Chip cortisol (Prototype)")
st.caption("Educatief prototype — geen vervanging van medisch advies. Neem bij twijfel contact op met je arts / 112.")

# -------------------------------
# Helpers
# -------------------------------
TZ = pytz.timezone("Europe/Amsterdam")

def now_local():
    return datetime.now(TZ)

def parse_time_str(tstr: str):
    try:
        h, m = tstr.split(":")
        return time(int(h), int(m))
    except Exception:
        return None

@st.cache_data(show_spinner=False)
def default_profile():
    return {
        "name": "",
        "weight_kg": 75.0,
        "daily_hc_mg": 20.0,
        "usual_schedule": ["08:00 10", "14:00 5", "18:00 5"],
        "wakeup_time": "07:30",
        "targets_nmol": {
            "morning": [12, 25],
            "afternoon": [5, 12],
            "evening": [2, 7],
            "night": [0.5, 4]
        }
    }

def time_of_day_bucket(t: time):
    if t >= time(5,0) and t < time(12,0):
        return "morning"
    if t >= time(12,0) and t < time(17,0):
        return "afternoon"
    if t >= time(17,0) and t < time(23,0):
        return "evening"
    return "night"

def sick_day_factor(temp_c: float, hr: int, has_fever: bool, severe: bool):
    if severe:
        return 0.0
    if has_fever or (temp_c is not None and temp_c >= 38.0):
        if temp_c is not None and temp_c >= 39.0:
            return 3.0
        return 2.0
    if hr is not None and hr >= 100:
        return 2.0
    return 1.0

def pk_predict_conc(last_doses, t_eval, ka=1.8, ke=math.log(2)/1.7, Vd=35.0):
    conc = 0.0
    for t_admin, dose in last_doses:
        dt = (t_eval - t_admin).total_seconds()/3600.0
        if dt <= 0:
            continue
        try:
            term = (dose * ka)/(Vd*(ka - ke)) * (math.exp(-ke*dt) - math.exp(-ka*dt))
        except ZeroDivisionError:
            term = 0.0
        conc += max(term, 0.0)
    return conc

def classify_alert(vomit, severe_flags, temp_c, hr, systolic_bp, sensor_value, tgt_range):
    reasons = []
    level = "GREEN"
    if vomit or severe_flags.get("persistent_diarrhea") or severe_flags.get("cannot_tolerate_oral"):
        level = "RED"
        reasons.append("Geen betrouwbare orale opname (braken/diarree).")
    if severe_flags.get("syncope_confusion") or severe_flags.get("very_low_bp"):
        level = "RED"
        reasons.append("Ernstige klachten (syncope/verwardheid/hypotensie).")
    if level != "RED":
        if (temp_c is not None and temp_c >= 38.0) or (hr is not None and hr >= 100):
            level = "AMBER"
            if temp_c is not None and temp_c >= 38.0:
                reasons.append(f"Koorts {temp_c:.1f} °C.")
            if hr is not None and hr >= 100:
                reasons.append(f"Tachycardie (HR {hr}).")
        if sensor_value is not None and tgt_range is not None:
            low, high = tgt_range
            if sensor_value < low:
                level = "AMBER" if level != "RED" else level
                reasons.append(f"Sensor onder doel ({sensor_value:.1f} < {low:.1f} nmol/L).")
    return level, reasons

# -------------------------------
# Sidebar — profile & sensor setup
# -------------------------------
st.sidebar.header("🔧 Profiel & Instellingen")
profile = st.session_state.get("profile", default_profile())

profile["name"] = st.sidebar.text_input("Naam (optioneel)", value=profile.get("name",""))
profile["weight_kg"] = st.sidebar.number_input("Gewicht (kg)", min_value=20.0, max_value=200.0, value=float(profile["weight_kg"]), step=0.5)
profile["daily_hc_mg"] = st.sidebar.number_input("Gebruikelijke hydrocortison dagdosis (mg/dag)", min_value=5.0, max_value=60.0, value=float(profile["daily_hc_mg"]), step=2.5)

st.sidebar.markdown("**Gebruikelijke dosering (tijd en mg, één per regel)** — bv: `08:00 10`")
schedule_str = st.sidebar.text_area("Schema", value="\n".join(profile["usual_schedule"]), height=100)
profile["usual_schedule"] = [s.strip() for s in schedule_str.splitlines() if s.strip()]

profile["wakeup_time"] = st.sidebar.text_input("Wektijd (HH:MM)", value=profile["wakeup_time"])

st.sidebar.markdown("**Doelbereiken sensor (nmol/L) — personaliseer**")
cols = st.sidebar.columns(2)
t_m_lo = cols[0].number_input("Ochtend min", value=float(profile["targets_nmol"]["morning"][0]), step=0.5)
t_m_hi = cols[1].number_input("Ochtend max", value=float(profile["targets_nmol"]["morning"][1]), step=0.5)
t_a_lo = cols[0].number_input("Middag min", value=float(profile["targets_nmol"]["afternoon"][0]), step=0.5)
t_a_hi = cols[1].number_input("Middag max", value=float(profile["targets_nmol"]["afternoon"][1]), step=0.5)
t_e_lo = cols[0].number_input("Avond min", value=float(profile["targets_nmol"]["evening"][0]), step=0.5)
t_e_hi = cols[1].number_input("Avond max", value=float(profile["targets_nmol"]["evening"][1]), step=0.5)
t_n_lo = cols[0].number_input("Nacht min", value=float(profile["targets_nmol"]["night"][0]), step=0.5)
t_n_hi = cols[1].number_input("Nacht max", value=float(profile["targets_nmol"]["night"][1]), step=0.5)
profile["targets_nmol"] = {
    "morning": [t_m_lo, t_m_hi],
    "afternoon": [t_a_lo, t_a_hi],
    "evening": [t_e_lo, t_e_hi],
    "night": [t_n_lo, t_n_hi],
}

st.sidebar.divider()
st.sidebar.subheader("🧪 Biosensor op de tand")
sensor_mode = st.sidebar.selectbox(
    "Kies bron",
    ["Biosensor op de tand (bestand)", "Biosensor op de tand (simulatie)", "Handmatig (error modus)"],
    index=0
)
sensor_path = st.sidebar.text_input("Bestandspad voor sensor.json", value="sensor.json")

# -------------------------------
# Main — current status input
# -------------------------------
st.subheader("Huidige status")
colA, colB, colC = st.columns(3)

with colA:
    now = now_local()
    st.write(f"🕒 Lokale tijd: {now.strftime('%Y-%m-%d %H:%M')}")
    last_dose_time = st.time_input("Laatste inname (tijd)", value=now.time().replace(minute=(now.minute//5)*5))
    last_dose_mg = st.number_input("Laatste inname (mg)", min_value=0.0, max_value=100.0, value=0.0, step=2.5)
    additional_recent = st.text_input("Extra recente innames (optioneel, CSV: 'HH:MM mg; HH:MM mg')", value="")

with colB:
    temp_c = st.number_input("Lichaamstemperatuur (°C)", min_value=34.0, max_value=42.5, value=37.0, step=0.1)
    hr = st.number_input("Hartslag (bpm)", min_value=30, max_value=220, value=70, step=1)
    sbp = st.number_input("Systolische bloeddruk (mmHg) (optioneel)", min_value=60, max_value=220, value=120, step=1)

with colC:
    st.write("Symptomen")
    vomit = st.checkbox("Braken of niet kunnen binnenhouden")
    persistent_diarrhea = st.checkbox("Aanhoudende diarree")
    cannot_tolerate_oral = st.checkbox("Orale inname niet mogelijk")
    syncope_confusion = st.checkbox("Flauwvallen / verwardheid")
    very_low_bp = st.checkbox("Erg lage bloeddruk / ernstige zwakte")
    has_fever = st.checkbox("Ziek gevoel met koorts")

st.write("---")
st.subheader("Sensor — vrij cortisol (nmol/L)")

def read_sensor_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
        val = float(d.get("free_cortisol_nmol", None))
        ts = d.get("timestamp", None)
        return val, ts
    except Exception:
        return None, None

def simulate_sensor_value(now_dt: datetime, fever: bool):
    hour = now_dt.hour + now_dt.minute/60.0
    baseline = 6 + 10 * math.exp(-((hour-8.0)/3.0)**2)
    trough = 2.0 + 1.0 * math.exp(-((hour-23.0)/3.0)**2)
    value = max(trough, baseline)
    if fever:
        value *= 1.2
    noise = random.uniform(-1.0, 1.0)
    return max(0.0, value + noise)

sensor_value = None
sensor_ts = None

if sensor_mode == "Lab-on-chip (bestand)":
    sensor_value, sensor_ts = read_sensor_file(sensor_path)
    st.caption(f"Bron: bestand • {sensor_path}")
elif sensor_mode == "Lab-on-chip (simulatie)":
    sensor_value = simulate_sensor_value(now, has_fever)
    sensor_ts = now.isoformat()
    st.caption("Bron: simulatie (circadiaan + ruis)")
else:
    sensor_value = st.number_input("Handmatige invoer (nmol/L)", min_value=0.0, max_value=200.0, value=0.0, step=0.5)
    sensor_ts = now.isoformat()
    st.caption("Bron: handmatig")

if sensor_value is not None:
    st.metric("Vrij cortisol (nmol/L)", f"{sensor_value:.1f}", help=f"Laatste meting: {sensor_ts}")

# Determine target range by current time of day
bucket = time_of_day_bucket(now.time())
tgt_range = profile["targets_nmol"][bucket]
st.info(f"Doelbereik ({bucket}): {tgt_range[0]:.1f}–{tgt_range[1]:.1f} nmol/L (instelbaar in de zijbalk)")

# Build list of doses for PK
last_doses = []
today = now.date()
dt_last = datetime.combine(today, last_dose_time).replace(tzinfo=TZ)
if dt_last <= now and last_dose_mg > 0:
    last_doses.append((dt_last, last_dose_mg))

if additional_recent.strip():
    for chunk in additional_recent.split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            tpart, mgpart = chunk.split()
            ti = parse_time_str(tpart)
            mg = float(mgpart)
            if ti:
                dt_i = datetime.combine(today, ti).replace(tzinfo=TZ)
                if dt_i <= now and mg > 0:
                    last_doses.append((dt_i, mg))
        except Exception:
            st.warning(f"Kon invoer niet parsen: '{chunk}' (verwacht 'HH:MM mg')")

# Compute simple PK trend (arbitrary units)
conc_now = pk_predict_conc(last_doses, now)
conc_in_1h = pk_predict_conc(last_doses, now + timedelta(hours=1))
conc_in_2h = pk_predict_conc(last_doses, now + timedelta(hours=2))

with st.expander("📈 Interne PK-schatting (relatieve conc.)"):
    st.write({"nu": round(conc_now,3), "+1h": round(conc_in_1h,3), "+2h": round(conc_in_2h,3)})
    st.caption("Relatieve eenheden — bedoeld voor trend, niet voor absolute diagnose.")

# -------------------------------
# Decision logic
# -------------------------------
severe_flags = {
    "persistent_diarrhea": persistent_diarrhea,
    "cannot_tolerate_oral": cannot_tolerate_oral,
    "syncope_confusion": syncope_confusion,
    "very_low_bp": very_low_bp,
}

alert_level, reasons = classify_alert(vomit, severe_flags, temp_c, hr, sbp, sensor_value, tuple(tgt_range))

st.subheader("🔔 Alarmstatus")
if alert_level == "RED":
    st.error("RED — **Onmiddellijke actie vereist**")
elif alert_level == "AMBER":
    st.warning("AMBER — **Verhoogde waakzaamheid / stressdosering**")
else:
    st.success("GREEN — **Geen directe actie** (blijf monitoren)")

if reasons:
    st.write("**Redenen:** " + " ".join([f"• {r}" for r in reasons]))

# Dosing suggestion
factor = sick_day_factor(temp_c, hr, has_fever, (alert_level=="RED"))
usual_daily = profile["daily_hc_mg"]

if alert_level == "RED" or vomit or cannot_tolerate_oral:
    st.markdown("### 💉 Dosisadvies (noodsituatie)")
    st.write(
        "- **Parenterale toediening aanbevolen**: overweeg hydrocortison **100 mg IM/IV** en **zoek direct medische hulp**.",
        "- Blijf orale tabletten vermijden totdat braken/diarree onder controle is en arts akkoord geeft."
    )
else:
    st.markdown("### 💊 Dosisadvies (oraal)")
    if factor <= 1.0:
        st.write("**Geen extra stressdosis** nodig op basis van huidige gegevens. Blijf monitoren en volg je gebruikelijke schema.")
    else:
        extra_today = (factor - 1.0) * usual_daily
        immediate_bolus = min(20.0, max(5.0, round(0.4 * extra_today / 2.5) * 2.5))
        follow_up = max(0.0, extra_today - immediate_bolus)
        st.write(f"- Aanbevolen **stressfactor**: ×{factor:.1f} (t.o.v. je gebruikelijke dagdosis {usual_daily:.1f} mg).")
        st.write(f"- **Neem nu**: **{immediate_bolus:.1f} mg** hydrocortison.")
        if follow_up > 0:
            st.write(f"- **Rest van extra dosis vandaag**: **{follow_up:.1f} mg** verspreid over de dag.")
        st.caption("Heuristische verdeling — pas aan op artsadvies en persoonlijke ervaring.")

    if sensor_value is not None:
        low, high = tgt_range
        if sensor_value < low:
            st.info("Sensorsignaal ligt **onder** doel. Hercontroleer over 60–90 min na inname.")
        elif sensor_value > high:
            st.info("Sensorsignaal is **boven** doelbereik; overleg met je arts bij aanhoudend hoge waarden.")

st.write("---")
st.subheader("📒 Logboek (sessie)")
if "events" not in st.session_state:
    st.session_state["events"] = []

if st.button("✚ Log: advies toevoegen aan logboek"):
    dose_text = "IM/IV 100 mg (RED)" if alert_level=="RED" or vomit or cannot_tolerate_oral else "Geen extra dosis"
    try:
        immediate_bolus
    except NameError:
        immediate_bolus = 0.0
    try:
        follow_up
    except NameError:
        follow_up = 0.0
    if alert_level != "RED" and not (vomit or cannot_tolerate_oral) and factor>1.0:
        dose_text = f"Orale bolus nu: {immediate_bolus:.1f} mg; rest vandaag: {max(0.0, follow_up):.1f} mg"

    event = {
        "time": now.strftime("%Y-%m-%d %H:%M"),
        "alert": alert_level,
        "temp": temp_c,
        "hr": int(hr),
        "sensor": None if sensor_value is None else round(float(sensor_value),1),
        "dose_advice": dose_text,
        "reasons": reasons,
    }
    st.session_state["events"].append(event)

if st.session_state["events"]:
    st.table(st.session_state["events"])

st.write("---")
st.caption("⚠️ Disclaimer: Dit is een educatief hulpmiddel. Het geeft geen medisch advies. Volg altijd je persoonlijke noodplan en de instructies van je behandelaar.")
