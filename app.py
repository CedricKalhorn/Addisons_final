# =========================================================
# Addison Sense & Dose — Multimodale CGM × HRV × EDA × Hydrocortisone Dashboard
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
st.set_page_config(page_title="Addison Sense & Dose — Multimodal Dashboard", page_icon="🩸", layout="wide")
st.title("🩸 Addison Sense & Dose — Multimodal CGM × HRV × EDA × Hydrocortisone Dashboard")
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
        "weight_kg": 75.0,
        "daily_hc_mg": 20.0,
        "usual_schedule": ["08:00 10", "14:00 5", "18:00 5"],
        "baseline_glucose": 5.5,
        "baseline_sd": 0.4
    }

profile = st.session_state.get("profile", default_profile())
for key, default in default_profile().items():
    if key not in profile:
        profile[key] = default

st.sidebar.header("👤 Profiel")
profile["name"] = st.sidebar.text_input("Naam", value=profile.get("name",""))
profile["weight_kg"] = st.sidebar.number_input("Gewicht (kg)",20.0,200.0,float(profile["weight_kg"]),0.5)
profile["daily_hc_mg"] = st.sidebar.number_input("Dagelijkse hydrocortison (mg)",5.0,60.0,float(profile["daily_hc_mg"]),2.5)
profile["baseline_glucose"] = st.sidebar.number_input("Basale glucose (mmol/L)",3.0,10.0,float(profile["baseline_glucose"]),0.1)
profile["baseline_sd"] = st.sidebar.number_input("SD glucose (mmol/L)",0.1,2.0,float(profile["baseline_sd"]),0.1)
st.sidebar.button("Opslaan in sessie",on_click=lambda: st.session_state.update({"profile":profile}))

# ------------------------------------
# MULTIMODALE METING (CGM + HRV + EDA)
# ------------------------------------
def simulate_wearables(now_dt: datetime):
    hour = now_dt.hour + now_dt.minute/60
    # glucose
    base_g = 5.2 + 1.2 * math.sin((hour-8)/6*math.pi)
    g = round(max(2.5, base_g + random.gauss(0,0.3)),1)
    # HRV
    base_hrv = 45 - 15*math.cos((hour-3)/6*math.pi)
    hrv = max(5, base_hrv + random.uniform(-6,5))
    # EDA
    base_eda = 0.6 + 0.3*math.sin((hour-10)/8*math.pi)
    eda = round(max(0.2, base_eda + random.gauss(0,0.1)),2)
    # stress-episode
    if random.random()<0.05:
        g -= random.uniform(0.8,1.2)
        hrv -= random.uniform(8,12)
        eda += random.uniform(0.3,0.6)
    return {"glucose":g,"hrv":hrv,"eda":eda,"ts":now_dt.isoformat()}

st.subheader("⌚ Multimodale meting")
simulate = st.checkbox("Simuleer CGM + HRV + EDA (demo)", True)
now = now_local()
if simulate:
    data = simulate_wearables(now)
else:
    data = {"glucose":5.6,"hrv":40,"eda":0.5,"ts":now.isoformat()}

st.metric("Glucose (mmol/L)", data["glucose"])
st.metric("HRV (RMSSD, ms)", int(data["hrv"]))
st.metric("EDA (µS)", round(data["eda"],2))
st.caption(f"Laatst gemeten: {data['ts']}")

# ------------------------------------
# STRESS-INDEX
# ------------------------------------
def compute_stress_index(glu, hrv, eda, base_glu, base_sd):
    score = 0; reasons = []
    if glu < base_glu - 0.5:
        score += min(40, (base_glu - glu)/base_sd*20)
        reasons.append("Glucose↓")
    if hrv < 25:
        score += 30; reasons.append("HRV↓")
    elif hrv < 35:
        score += 15; reasons.append("HRV licht ↓")
    if eda > 0.8:
        score += 20; reasons.append("EDA↑")
    score = max(0,min(100,score))
    return score, reasons

stress_index, reasons = compute_stress_index(
    data["glucose"], data["hrv"], data["eda"],
    profile["baseline_glucose"], profile["baseline_sd"]
)
st.subheader("🧠 Samengevoegde stress-index")
st.metric("Stress-index (0–100)", int(stress_index))
if reasons:
    st.caption("Componenten: " + ", ".join(reasons))
if stress_index>=70:
    st.error("RED — ernstige stressrespons, mogelijk Addison-deficiëntie")
elif stress_index>=45:
    st.warning("AMBER — verhoogde stressrespons, controleer waarden")
else:
    st.success("GREEN — binnen normale grenzen")

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
if stress_index>=70:
    st.write("- **Neem direct 100 mg hydrocortison IM/IV** en bel medische hulp (BijnierNET).")
elif stress_index>=45:
    st.write(f"- **Neem nu extra orale stressdosis:** ca. **{0.5*usual:.1f} mg** (halve dagdosis).")
    st.write("- Hermeet glucose/HRV binnen 30 min; stabilisatie = adequaat effect.")
else:
    st.write("- Geen extra dosis vereist. Blijf waarden monitoren.")

# ------------------------------------
# DAGELIJKSE TRENDGRAFIEK
# ------------------------------------
st.subheader("📈 Dagelijkse trends (simulatie)")
times=[datetime.combine(today,time(0,0,tzinfo=TZ))+timedelta(minutes=15*i) for i in range(96)]
hc_conc=[]; glu=[]; hrv_list=[]; eda_list=[]; stress_list=[]
for t in times:
    c=pk_predict_conc(doses,t,ka,t_half)
    hc_conc.append(c)
    # simulatie glucose/hrv/eda
    sim=simulate_wearables(t)
    glu.append(sim["glucose"]); hrv_list.append(sim["hrv"]); eda_list.append(sim["eda"])
    s,_=compute_stress_index(sim["glucose"],sim["hrv"],sim["eda"],profile["baseline_glucose"],profile["baseline_sd"])
    stress_list.append(s)
df=pd.DataFrame({"tijd":times,"glucose":glu,"hrv":hrv_list,"eda":eda_list,"stress":stress_list,"hydrocortison":hc_conc})

fig=go.Figure()
fig.add_trace(go.Scatter(x=df["tijd"],y=df["glucose"],mode="lines",name="Glucose (mmol/L)",line=dict(color="royalblue")))
fig.add_trace(go.Scatter(x=df["tijd"],y=df["hrv"],mode="lines",name="HRV (ms)",yaxis="y2",line=dict(color="purple",dash="dot")))
fig.add_trace(go.Scatter(x=df["tijd"],y=df["eda"],mode="lines",name="EDA (µS)",yaxis="y3",line=dict(color="teal",dash="dot")))
fig.add_trace(go.Scatter(x=df["tijd"],y=df["hydrocortison"],mode="lines",name="Hydrocortison (rel.)",yaxis="y4",line=dict(color="orange")))
fig.add_trace(go.Scatter(x=df["tijd"],y=df["stress"],mode="lines",name="Stress-index (0-100)",yaxis="y5",line=dict(color="red",width=2)))

fig.update_layout(
    title="Dagelijkse trends: Glucose, HRV, EDA, Hydrocortison & Stress-index",
    xaxis_title="Tijd",
    yaxis=dict(title="Glucose (mmol/L)",side="left",range=[2,12]),
    yaxis2=dict(title="HRV (ms)",overlaying="y",side="right",range=[0,80],showgrid=False),
    yaxis3=dict(title="EDA (µS)",anchor="free",overlaying="y",side="right",position=0.95,range=[0,1.5],showgrid=False),
    yaxis4=dict(title="Relatieve [HC]",anchor="free",overlaying="y",side="left",position=0.05,range=[0,1.5],showgrid=False),
    yaxis5=dict(title="Stress-index",anchor="x",overlaying="y",side="right",position=1.05,range=[0,100],showgrid=False),
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
        "glucose":data["glucose"],
        "hrv":data["hrv"],
        "eda":data["eda"],
        "stress_index":stress_index
    })
if st.session_state["log"]:
    st.table(st.session_state["log"])

st.caption("⚠️ Educatief hulpmiddel – geen medisch hulpmiddel volgens Verordening (EU) 2017/745 (MDR).")
