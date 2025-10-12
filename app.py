# =========================================================
# Addison Sense & Dose — CGM × Hydrocortisone Dashboard (EU Prototype)
# =========================================================
# Educational prototype – not for clinical or diagnostic use (EU MDR Annex I)
# Author: Cedric Kalhorn — TU Delft / TM12004 Drug Sensing & Delivery

import math, random, json
from datetime import datetime, timedelta, time
import pytz, streamlit as st
import pandas as pd
import plotly.graph_objects as go

# ------------------------------------
# CONFIG
# ------------------------------------
st.set_page_config(page_title="Addison Sense & Dose — CGM Dashboard", page_icon="🩸", layout="wide")
st.title("🩸 Addison Sense & Dose — CGM × Hydrocortisone Dashboard")
st.caption("Educatief prototype – niet bedoeld als medisch hulpmiddel (EU MDR 2017/745 Annex I).")

TZ = pytz.timezone("Europe/Amsterdam")
def now_local(): return datetime.now(TZ)

# ------------------------------------
# PROFIEL
# ------------------------------------
@st.cache_data(show_spinner=False)
def default_profile():
    return {
        "name": "",
        "weight_kg": "",
        "daily_hc_mg": "",
        "usual_schedule": ["08:00 10", "14:00 5", "18:00 5"],
        "baseline_glucose": 5.5,
        "baseline_sd": 0.4
    }
    
profile = st.session_state.get("profile", default_profile())
st.sidebar.header("👤 Profiel")
profile["name"] = st.sidebar.text_input("Naam", value=profile.get("name",""))
profile["weight_kg"] = st.sidebar.number_input("Gewicht (kg)",20.0,200.0,profile["weight_kg"],0.5)
profile["daily_hc_mg"] = st.sidebar.number_input("Dagelijkse hydrocortison (mg)",5.0,60.0,profile["daily_hc_mg"],2.5)
profile["baseline_glucose"] = st.sidebar.number_input("Basale glucose (mmol/L)",3.0,10.0,profile["baseline_glucose"],0.1)
profile["baseline_sd"] = st.sidebar.number_input("SD glucose (mmol/L)",0.1,2.0,profile["baseline_sd"],0.1)
st.sidebar.button("Opslaan in sessie",on_click=lambda: st.session_state.update({"profile":profile}))

# ------------------------------------
# GLUCOSE INVOER / SIMULATIE
# ------------------------------------
def read_glucose_json(path:str):
    """JSON: {"timestamp":"2025-10-12T09:30:00+02:00","glucose_mmol":5.6}"""
    try:
        with open(path,"r",encoding="utf-8") as f:
            d=json.load(f)
        return {"ts":d.get("timestamp"),"glucose":d.get("glucose_mmol")}
    except Exception:
        return None

def simulate_glucose(now_dt:datetime):
    hour = now_dt.hour + now_dt.minute/60
    base = 5.2 + 1.2*math.sin((hour-8)/6*math.pi)
    noise = random.gauss(0,0.3)
    if 7<=hour<=9 or 12<=hour<=14 or 18<=hour<=20:
        base += random.uniform(0.8,2.0)
    if random.random()<0.05: base -= random.uniform(1.0,2.0)
    return {"ts":now_dt.isoformat(),"glucose":round(max(2.5,base+noise),1)}

st.subheader("📊 Glucosemeting")
colA,colB=st.columns(2)
with colA:
    use_sensor = st.checkbox("Automatisch uitlezen CGM-bestand",True)
    path = st.text_input("Pad naar glucose.json","glucose.json")
with colB:
    simulate = st.checkbox("Simuleer CGM-waarden (demo)",True)

now = now_local()
if use_sensor:
    data = read_glucose_json(path)
else:
    data=None
if simulate or not data:
    data = simulate_glucose(now)

glucose = data["glucose"]
st.metric("Glucose (mmol/L)",glucose)
st.caption(f"Laatste meting: {data['ts']}")

# ------------------------------------
# GLUCOSE ANALYSE
# ------------------------------------
def classify_glucose(glu:float, base:float, sd:float):
    """EU clinical guidance: target 4.0–7.8 mmol/L (ISO 15197 / EASD 2023)"""
    if glu < 3.5:
        return "RED","Hypoglycemie – risico op Addison’s crisis door tekort aan cortisol."
    elif glu < 4.5:
        return "AMBER","Lage glucose – mogelijke relatieve hydrocortison-deficiëntie."
    elif glu > 9:
        return "AMBER","Hoge glucose – stressrespons of voeding."
    elif glu > 12:
        return "RED","Zeer hoge glucose – metabole dysregulatie, contact arts."
    else:
        return "GREEN","Glucose binnen fysiologisch bereik."

alert,recommend = classify_glucose(glucose,profile["baseline_glucose"],profile["baseline_sd"])
if alert=="RED": st.error(f"RED — {recommend}")
elif alert=="AMBER": st.warning(f"AMBER — {recommend}")
else: st.success(f"GREEN — {recommend}")

# ------------------------------------
# HYDROCORTISON PK-MODEL
# ------------------------------------
def pk_predict_conc(doses,t_eval,ka,t_half,Vd=35.0):
    ke=math.log(2)/t_half; conc=0.0
    for t_admin,dose in doses:
        dt=(t_eval-t_admin).total_seconds()/3600
        if dt<=0: continue
        term=(dose*ka)/(Vd*(ka-ke))*(math.exp(-ke*dt)-math.exp(-ka*dt))
        conc+=max(term,0.0)
    return conc

st.subheader("⚗️ Hydrocortison-concentratie (relatief)")
ka=st.slider("Ka absorptie (1/h)",0.5,3.0,1.8,0.1)
t_half=st.slider("Halfwaardetijd (h)",0.8,3.0,1.7,0.1)
schedule=[("08:00",10),("14:00",5),("18:00",5)]
today=now.date()
doses=[(datetime.combine(today,time.fromisoformat(t)).replace(tzinfo=TZ),mg)
        for t,mg in schedule if datetime.combine(today,time.fromisoformat(t)).replace(tzinfo=TZ)<=now]

conc_now=pk_predict_conc(doses,now,ka,t_half)
conc_1h=pk_predict_conc(doses,now+timedelta(hours=1),ka,t_half)
st.write(f"Relatieve conc.: nu {conc_now:.3f}, +1h {conc_1h:.3f}")
st.caption("Model gebaseerd op orale hydrocortison (bioavail. 95%, Tmax ≈ 1 h).")

# ------------------------------------
# ADVIES
# ------------------------------------
st.subheader("💊 Dosisadvies")
usual=profile["daily_hc_mg"]
if alert=="RED":
    st.write("- **Neem direct 100 mg hydrocortison intramusculair of IV** en bel medische hulp (EU-richtlijn BijnierNET).")
elif alert=="AMBER":
    st.write(f"- **Neem nu extra orale stressdosis:** ca. **{0.5*usual:.1f} mg** (halve dagdosis).")
    st.write("- Hermeet glucose binnen 30 min; stabilisatie = adequaat effect.")
else:
    st.write("- Geen extra dosis vereist. Blijf CGM-waarden volgen.")

# ------------------------------------
# DAGELIJKSE TRENDGRAFIEK
# ------------------------------------
st.subheader("📈 Dagelijkse trends (simulatie)")

# Simuleer 24h glucose + hydrocortisonprofiel
times=[datetime.combine(today,time(0,0,tzinfo=TZ))+timedelta(minutes=15*i) for i in range(96)]
hc_conc=[]; glu=[]
for t in times:
    c=pk_predict_conc(doses,t,ka,t_half)
    hc_conc.append(c)
    g=profile["baseline_glucose"] + 0.25*c + random.gauss(0,0.15)
    if c<0.3 and random.random()<0.2: g-=random.uniform(0.8,1.5)
    glu.append(max(2.5,round(g,2)))
df=pd.DataFrame({"tijd":times,"glucose":glu,"hydrocortison":hc_conc})

# Plotly grafiek
fig=go.Figure()
fig.add_trace(go.Scatter(x=df["tijd"],y=df["glucose"],mode="lines",name="Glucose (mmol/L)",line=dict(color="royalblue")))
fig.add_hrect(y0=4,y1=8,fillcolor="green",opacity=0.1,line_width=0)
fig.add_trace(go.Scatter(x=df["tijd"],y=df["hydrocortison"],mode="lines",name="Hydrocortison (rel.)",yaxis="y2",line=dict(color="orange")))
fig.update_layout(
    xaxis_title="Tijd",
    yaxis=dict(title="Glucose (mmol/L)",range=[2,12]),
    yaxis2=dict(title="Relatieve [HC]",overlaying="y",side="right"),
    title="Dagelijkse glucose- en hydrocortisontrends",
    legend=dict(x=0.01,y=0.99)
)
st.plotly_chart(fig,use_container_width=True)

# ------------------------------------
# LOGBOEK
# ------------------------------------
st.subheader("📒 Logboek")
if "log" not in st.session_state: st.session_state["log"]=[]
if st.button("✚ Voeg meting toe aan logboek"):
    st.session_state["log"].append({
        "tijd":now.strftime("%Y-%m-%d %H:%M"),
        "glucose":glucose,
        "alert":alert,
        "advies":recommend
    })
if st.session_state["log"]:
    st.table(st.session_state["log"])

st.caption("⚠️ Educatief hulpmiddel – geen medisch hulpmiddel volgens Verordening (EU) 2017/745 (MDR).")
