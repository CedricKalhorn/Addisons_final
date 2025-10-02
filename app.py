import math
import json
from datetime import datetime, timedelta, time
import pytz
import streamlit as st
import random

# =========================================================
# Addison Sense & Dose — Wearable vitals (smartwatch/polsband)
# =========================================================
st.set_page_config(page_title="Addison Sense & Dose (Wearable)", page_icon="⌚", layout="wide")
st.title("⌚ Addison Sense & Dose — Wearable vitals (Prototype)")
st.caption("Educatief prototype — geen vervanging van medisch advies. Volg je noodplan en artsadvies.")

# -------------------------------
# Helpers / tijdzone
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
        "daily_hc_mg": 20.0,                       # gebruikelijke totale dagdosis
        "usual_schedule": ["08:00 10", "14:00 5", "18:00 5"],  # "HH:MM mg"
        "wakeup_time": "07:30",
        # Doelbereiken voor "verwachte belasting" op basis van dagdeel (kan gebruiken voor future features)
        "targets_info": {
            "morning": "Hoger energieverbruik normaal; hogere drempel voor alarm",
            "afternoon":"Neutraal",
            "evening":"Lagere drempel voor alarmering bij aanhoudende stresssignalen",
            "night":"Tijdens slaap: HR laag, HRV hoger; kleine afwijking is al verdacht"
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

# -------------------------------
# Wearable-bestand inlezen / simuleren
# -------------------------------
def read_vitals_json(path):
    """
    Verwacht JSON met velden:
    {
      "timestamp": "2025-10-02T09:12:00+02:00",
      "hr_bpm": 104,
      "hrv_rmssd_ms": 18,
      "wrist_temp_dev_c": 0.9,   # afwijking t.o.v. persoonlijke baseline
      "resp_bpm": 17,
      "spo2_pct": 97,
      "sbp": null                 # optioneel (systolische BP, als je wearable/databron dat heeft)
    }
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
        return {
            "ts": d.get("timestamp"),
            "hr": d.get("hr_bpm"),
            "hrv": d.get("hrv_rmssd_ms"),
            "temp_dev": d.get("wrist_temp_dev_c"),
            "resp": d.get("resp_bpm"),
            "spo2": d.get("spo2_pct"),
            "sbp": d.get("sbp"),
        }
    except Exception:
        return None

def simulate_vitals(now_dt: datetime):
    """Eenvoudige simulatie met circadiaan ritme + ruis."""
    hour = now_dt.hour + now_dt.minute/60.0
    # HR: iets hoger overdag (workload), lager 's nachts
    hr_base = 60 + 15 * math.exp(-((hour-15.0)/5.0)**2)   # middag hoger
    hr_noise = random.uniform(-5, 8)
    hr = max(45, hr_base + hr_noise)

    # HRV: omgekeerd gedrag: hoger 's nachts, lager bij stress
    hrv_base = 35 + 20 * math.exp(-((hour-3.0)/5.0)**2)   # nacht hoger
    hrv_noise = random.uniform(-8, 6)
    hrv = max(5, hrv_base + hrv_noise)

    # Polstemperatuur-deviatie: normaal ~0, bij koorts/stress omhoog
    temp_dev = max(0.0, random.gauss(0.2, 0.15)) if 6 <= hour <= 23 else max(0.0, random.gauss(0.1, 0.1))
    # Kleinere kans op “koorts-episode”
    if random.random() < 0.05:
        temp_dev += random.uniform(0.5, 1.0)  # koortsachtig

    resp = max(10, random.gauss(15, 2))
    spo2 = min(100, max(93, random.gauss(97.5, 1.0)))
    # sbp optioneel (wearables schatten zelden betrouwbaar); laat op None
    return {
        "ts": now_dt.isoformat(),
        "hr": int(hr),
        "hrv": int(hrv),
        "temp_dev": round(temp_dev, 2),
        "resp": int(resp),
        "spo2": int(spo2),
        "sbp": None
    }

# -------------------------------
# Stressindex & beslislogica
# -------------------------------
def compute_stress_index(vitals, base_hr, base_hr_sd, base_temp_dev):
    """
    Simpele 0–100 score uit HR↑, temp_dev↑ en HRV↓.
    - HR z-score tov baseline (alleen verhoging telt)
    - Temp_dev boven baseline
    - HRV < 20 ms geeft extra punten
    """
    if not vitals:
        return 0.0, []

    score = 0.0
    parts = []

    # HR-component
    hr = vitals.get("hr")
    if hr is not None and base_hr_sd > 0:
        hr_z = (hr - base_hr) / base_hr_sd
        hr_z = max(0.0, hr_z)
        score += min(hr_z * 15, 40)  # max 40 punten uit HR
        parts.append(f"HR↑ (z≈{hr_z:.1f})")

    # Temp_dev component
    tdev = vitals.get("temp_dev")
    if tdev is not None:
        # elke +0.5°C boven baseline ~20 punten
        sc = max(0.0, (tdev - base_temp_dev)) * 40
        sc = min(sc, 40)
        score += sc
        parts.append(f"TempΔ {tdev:+.1f}°C")

    # HRV component (lager = stress)
    hrv = vitals.get("hrv")
    if hrv is not None and hrv < 20:
        score += 10
        parts.append("HRV↓")

    score = max(0.0, min(100.0, score))
    return score, parts

def classify_alert(vomit, severe_flags, vitals, stress_index):
    """Combineer RED-flags + wearable stress tot GREEN/AMBER/RED + redenen."""
    reasons = []
    level = "GREEN"

    # RED flags (klinisch)
    if vomit or severe_flags.get("persistent_diarrhea") or severe_flags.get("cannot_tolerate_oral"):
        level = "RED"; reasons.append("Geen betrouwbare orale opname (braken/diarree).")
    if severe_flags.get("syncope_confusion") or severe_flags.get("very_low_bp"):
        level = "RED"; reasons.append("Ernstige klachten (syncope/verwardheid/hypotensie).")

    # AMBER door vitals / stressindex (alleen als nog niet RED)
    if level != "RED" and vitals:
        hr = vitals.get("hr")
        sbp = vitals.get("sbp")
        tdev = vitals.get("temp_dev")

        if stress_index >= 50:
            level = "AMBER"; reasons.append(f"Wearable stressindex {int(stress_index)} (≥50).")

        if hr is not None and hr >= 100:
            level = "AMBER"; reasons.append(f"Tachycardie (HR {hr}).")

        # Systolische BP (indien beschikbaar uit bron)
        if sbp is not None and sbp < 100:
            level = "AMBER"; reasons.append(f"Lage systolische BP ({sbp} mmHg).")

        # Polstemperatuur-afwijking als koorts-proxy
        if tdev is not None and tdev >= 0.8:
            level = "AMBER"; reasons.append(f"Koortsverdenking (TempΔ +{tdev:.1f} °C).")

    return level, reasons

def sick_day_factor_from_wearable(vitals, stress_index, red: bool):
    """Heuristische factor (×1, ×2, ×3) op basis van wearable-signalen."""
    if red:  # handled upstream: parenterale route
        return 0.0
    if not vitals:
        return 1.0
    hr = vitals.get("hr")
    tdev = vitals.get("temp_dev")

    # sterk verhoogde stress
    if (tdev is not None and tdev >= 1.0) or stress_index >= 70 or (hr is not None and hr >= 110):
        return 3.0
    # matig verhoogde stress
    if (tdev is not None and tdev >= 0.6) or stress_index >= 50 or (hr is not None and hr >= 100):
        return 2.0
    return 1.0

# -------------------------------
# Sidebar — Profiel & Wearable
# -------------------------------
st.sidebar.header("🔧 Profiel & Instellingen")
profile = st.session_state.get("profile", default_profile())

profile["name"] = st.sidebar.text_input("Naam (optioneel)", value=profile.get("name",""))
profile["weight_kg"] = st.sidebar.number_input("Gewicht (kg)", min_value=20.0, max_value=200.0,
                                               value=float(profile["weight_kg"]), step=0.5)
profile["daily_hc_mg"] = st.sidebar.number_input("Gebruikelijke hydrocortison dagdosis (mg/dag)", min_value=5.0,
                                                 max_value=60.0, value=float(profile["daily_hc_mg"]), step=2.5)

st.sidebar.markdown("**Gebruikelijke dosering (tijd en mg, één per regel)** — bv: `08:00 10`")
schedule_str = st.sidebar.text_area("Schema", value="\n".join(profile["usual_schedule"]), height=100)
profile["usual_schedule"] = [s.strip() for s in schedule_str.splitlines() if s.strip()]
profile["wakeup_time"] = st.sidebar.text_input("Wektijd (HH:MM)", value=profile["wakeup_time"])

st.sidebar.divider()
st.sidebar.subheader("⌚ Wearable koppeling")
use_wearable = st.sidebar.checkbox("Vitals automatisch inladen van wearable", value=True)
vitals_path = st.sidebar.text_input("Pad naar vitals.json", value="vitals.json")
# Persoonlijke baselines (kun je later automatisch leren; nu handmatig instelbaar)
base_hr = st.sidebar.number_input("Baseline HR (bpm)", 40, 120, 70, 1)
base_hr_sd = st.sidebar.number_input("HR SD (bpm)", 1, 30, 8, 1)
base_temp_dev = st.sidebar.number_input("Baseline temp. dev (°C)", -1.0, 1.0, 0.0, 0.1)

st.sidebar.divider()
st.sidebar.subheader("⚗️ PK-instellingen (optioneel)")
t_half_h = st.sidebar.slider("t½ eliminatie (uur)", 0.8, 3.0, 1.7, 0.1)
ka_h     = st.sidebar.slider("Ka absorptie (1/uur)", 0.5, 3.0, 1.8, 0.1)
use_schedule_as_taken = st.sidebar.checkbox("Gebruik gebruikelijke schema-doses (vóór nu) automatisch", True)

st.sidebar.button("Profiel opslaan (sessie)", on_click=lambda: st.session_state.update({"profile": profile}))

# -------------------------------
# Huidige status & symptomen
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
    st.write("Wearable vitals")
    if use_wearable:
        vitals = read_vitals_json(vitals_path)
        if not vitals:
            st.warning("Geen vitals.json gevonden of niet leesbaar — schakel simulatie of voer handmatig in.")
    else:
        vitals = None
    # Simulatie toggle (handig voor demo)
    simulate = st.checkbox("Simuleer vitals (overschrijft wearable)", value=False)
    if simulate:
        vitals = simulate_vitals(now)

with colC:
    st.write("Symptomen / RED flags")
    vomit = st.checkbox("Braken of niet binnenhouden")
    persistent_diarrhea = st.checkbox("Aanhoudende diarree")
    cannot_tolerate_oral = st.checkbox("Orale inname niet mogelijk")
    syncope_confusion = st.checkbox("Flauwvallen / verwardheid")
    very_low_bp = st.checkbox("Erg lage bloeddruk / ernstige zwakte")

# Toon vitals / stressindex
st.write("---")
st.subheader("⌚ Wearable-overzicht")
if vitals:
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("HR (bpm)", f"{vitals.get('hr','–')}")
    c2.metric("HRV (RMSSD, ms)", f"{vitals.get('hrv','–')}")
    c3.metric("Temp Δ (°C)", f"{vitals.get('temp_dev','–')}")
    c4.metric("Ademfreq (bpm)", f"{vitals.get('resp','–')}")
    c5.metric("SpO₂ (%)", f"{vitals.get('spo2','–')}")
    c6.metric("Sys BP (mmHg)", f"{vitals.get('sbp','–')}")
    st.caption(f"Laatst gemeten: {vitals.get('ts','onbekend')}")
else:
    st.info("Geen wearable-data → voer simulatie in of lever een vitals.json aan.")

# Stressindex berekenen
stress_index, stress_parts = compute_stress_index(vitals, base_hr, base_hr_sd, base_temp_dev)
st.metric("Stressindex (0–100)", int(stress_index))
if stress_parts:
    st.caption("Componenten: " + ", ".join(stress_parts))

# -------------------------------
# PK (optioneel, voor context) — eenvoudige Bateman-functie
# -------------------------------
def pk_predict_conc(last_doses, t_eval, ka, t_half, Vd=35.0):
    ke = math.log(2)/t_half
    conc = 0.0
    for t_admin, dose in last_doses:
        dt = (t_eval - t_admin).total_seconds()/3600.0
        if dt <= 0:
            continue
        if abs(ka - ke) < 1e-6:
            continue
        term = (dose * ka) / (Vd * (ka - ke)) * (math.exp(-ke*dt) - math.exp(-ka*dt))
        conc += max(term, 0.0)
    return conc

# Build list of doses for PK
last_doses = []
today = now.date()
dt_last = datetime.combine(today, last_dose_time).replace(tzinfo=TZ)
if dt_last <= now and last_dose_mg > 0:
    last_doses.append((dt_last, float(last_dose_mg)))

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

if use_schedule_as_taken:
    for line in profile["usual_schedule"]:
        try:
            tstr, mgstr = line.split()
            ti = parse_time_str(tstr)
            mg = float(mgstr)
            if ti:
                dt_sched = datetime.combine(today, ti).replace(tzinfo=TZ)
                if dt_sched <= now and mg > 0:
                    last_doses.append((dt_sched, mg))
        except Exception:
            pass

# optioneel: laatste avonddosis van gisteren meenemen (staart)
try:
    last_evening_candidates = []
    for line in profile["usual_schedule"]:
        tstr, mgstr = line.split()
        ti = parse_time_str(tstr)
        mg = float(mgstr)
        if ti and ti >= time(17,0):
            last_evening_candidates.append((ti, mg))
    if last_evening_candidates:
        ti_e, mg_e = sorted(last_evening_candidates)[-1]
        dt_yesterday = datetime.combine(today - timedelta(days=1), ti_e).replace(tzinfo=TZ)
        if (now - dt_yesterday).total_seconds()/3600.0 < 12:
            last_doses.append((dt_yesterday, mg_e))
except Exception:
    pass

conc_now = pk_predict_conc(last_doses, now, ka=ka_h, t_half=t_half_h)
conc_in_1h = pk_predict_conc(last_doses, now + timedelta(hours=1), ka=ka_h, t_half=t_half_h)
conc_in_2h = pk_predict_conc(last_doses, now + timedelta(hours=2), ka=ka_h, t_half=t_half_h)

with st.expander("📈 Interne PK-schatting (relatieve conc.)"):
    st.write({
        "nu": round(conc_now, 3),
        "+1h": round(conc_in_1h, 3),
        "+2h": round(conc_in_2h, 3),
        "Ka (1/h)": round(ka_h, 2),
        "t½ (h)": round(t_half_h, 2)
    })
    st.caption("Relatieve eenheden; trendmodel voor context bij dosisbesluiten.")

# -------------------------------
# Alarmstatus + dosisadvies
# -------------------------------
severe_flags = {
    "persistent_diarrhea": persistent_diarrhea,
    "cannot_tolerate_oral": cannot_tolerate_oral,
    "syncope_confusion": syncope_confusion,
    "very_low_bp": very_low_bp,
}

alert_level, reasons = classify_alert(vomit, severe_flags, vitals, stress_index)

st.subheader("🔔 Alarmstatus")
if alert_level == "RED":
    st.error("RED — **Onmiddellijke actie vereist**")
elif alert_level == "AMBER":
    st.warning("AMBER — **Verhoogde waakzaamheid / stressdosering**")
else:
    st.success("GREEN — **Geen directe actie** (blijf monitoren)")

if reasons:
    st.write("**Redenen:** " + " ".join([f"• {r}" for r in reasons]))

# Dosisadvies op basis van wearable
usual_daily = profile["daily_hc_mg"]
factor = sick_day_factor_from_wearable(vitals, stress_index, red=(alert_level=="RED"))

if alert_level == "RED":
    st.markdown("### 💉 Dosisadvies (noodsituatie)")
    st.write(
        "- **Parenterale toediening aanbevolen**: overweeg hydrocortison **100 mg IM/IV** en **zoek direct medische hulp**.",
        "- Vermijd orale tabletten tot klachten (braken/diarree) onder controle zijn en arts akkoord geeft."
    )
else:
    st.markdown("### 💊 Dosisadvies (oraal)")
    if factor <= 1.0:
        st.write("**Geen extra stressdosis** nodig op basis van huidige wearable-gegevens. Blijf monitoren en volg je gebruikelijke schema.")
    else:
        extra_today = (factor - 1.0) * usual_daily
        # onmiddellijke bolus om binnen ~60–90 min te corrigeren
        immediate_bolus = min(20.0, max(5.0, round(0.4 * extra_today / 2.5) * 2.5))
        follow_up = max(0.0, extra_today - immediate_bolus)
        st.write(f"- Aanbevolen **stressfactor**: ×{factor:.1f} (t.o.v. je dagdosis {usual_daily:.1f} mg).")
        st.write(f"- **Neem nu**: **{immediate_bolus:.1f} mg** hydrocortison.")
        if follow_up > 0:
            st.write(f"- **Rest van extra dosis vandaag**: **{follow_up:.1f} mg** verspreid over de dag.")
        st.caption("Heuristische verdeling — personaliseer met je arts en ervaring.")

# -------------------------------
# Logboek
# -------------------------------
st.write("---")
st.subheader("📒 Logboek (sessie)")
if "events" not in st.session_state:
    st.session_state["events"] = []

if st.button("✚ Log: advies toevoegen aan logboek"):
    dose_text = "IM/IV 100 mg (RED)" if alert_level=="RED" else "Geen extra dosis"
    try:
        immediate_bolus
    except NameError:
        immediate_bolus = 0.0
    try:
        follow_up
    except NameError:
        follow_up = 0.0
    if alert_level != "RED" and factor > 1.0:
        dose_text = f"Orale bolus nu: {immediate_bolus:.1f} mg; rest vandaag: {max(0.0, follow_up):.1f} mg"

    event = {
        "time": now.strftime("%Y-%m-%d %H:%M"),
        "alert": alert_level,
        "stress_index": int(stress_index),
        "hr": None if not vitals else vitals.get("hr"),
        "hrv": None if not vitals else vitals.get("hrv"),
        "temp_dev": None if not vitals else vitals.get("temp_dev"),
        "sbp": None if not vitals else vitals.get("sbp"),
        "dose_advice": dose_text,
        "reasons": reasons,
    }
    st.session_state["events"].append(event)

if st.session_state["events"]:
    st.table(st.session_state["events"])

st.write("---")
st.caption("⚠️ Disclaimer: Dit is een educatief hulpmiddel. Geen medisch advies. Volg altijd je persoonlijke noodplan en de instructies van je behandelaar.")
