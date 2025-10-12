# =========================================================
# Addison Sense & Dose — CGM × Hydrocortisone Dashboard (EU Prototype)
# =========================================================
# Educational prototype – not for clinical or diagnostic use (EU MDR Annex I)
# Author: Cedric Kalhorn — TU Delft / TM12004 Drug Sensing & Delivery

import math, random, json
from datetime import datetime, timedelta, time
import pytz, streamlit as st
import pandas as pd
import matplotlib.pyplot as plt

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
    return {"daily_hc_mg":20.0,"baseline_glucose":5.5,"baseline_sd":0.4}

profile = st.session_state.get("profile", default_profile())
col1,col2,col3 = st.columns(3)
profile["daily_hc_mg"] = col1.number_input("Dagdosis hydrocortison (mg)",5.0,60.0,profile["daily_hc_mg"],2.5)
profile["baseline_glucose"] = col2.number_input("Basale glucose (mmol/L)",3.0,10.0,profile["baseline_glucose"],0.1)
profile["baseline_sd"] = col3.number_input("SD glucose (mmol/L)",0.1,2.0,profile["baseline_sd"],0.1)
st.session_state["profile"] = profile

# ------------------------------------
# HYDROCORTISON PK-MODEL
# ------------------------------------
def pk_predict_conc(doses,t_eval,ka,t_half,Vd=35.0):
    ke=math.log(2)/t_half; conc=0
    for t_admin,dose in doses:
        dt=(t_eval-t_admin).total_seconds()/3600
        if dt<=0: continue
        term=(dose*ka)/(Vd*(ka-ke))*(math.exp(-ke*dt)-math.exp(-ka*dt))
        conc+=max(term,0)
    return conc

# standaarddosering
schedule=[("08:00",10),("14:00",5),("18:00",5)]
today=now_local().date()
doses=[(datetime.combine(today,time.fromisoformat(t)).replace(tzinfo=TZ),mg) for t,mg in schedule]
ka=1.8; t_half=1.7

# ------------------------------------
# 24 UURS SIMULATIE
# ------------------------------------
times=[datetime.combine(today,time(0,0,tzinfo=TZ))+timedelta(minutes=15*i) for i in range(96)]
hc_conc=[]; glu=[]
for t in times:
    c=pk_predict_conc(doses,t,ka,t_half)
    hc_conc.append(c)
    # Glucose = basale waarde + correlatie met cortisol concentratie + ruis
    g = profile["baseline_glucose"] + 0.25*c + random.gauss(0,0.15)
    # Lage glucose wanneer hydrocortison lager dan 0.3 → Addison-episode
    if c<0.3 and random.random()<0.2: g -= random.uniform(0.8,1.5)
    glu.append(max(2.5,round(g,2)))

df=pd.DataFrame({"tijd":times,"glucose":glu,"hydrocortison":hc_conc})

# ------------------------------------
# GRAFIEKEN
# ------------------------------------
st.subheader("📈 Dagelijkse trends")
fig, (ax1, ax2) = plt.subplots(2,1,figsize=(8,6),sharex=True)

# Glucose
ax1.plot(df["tijd"],df["glucose"],label="Glucose (mmol/L)")
ax1.axhspan(4,8,color="green",alpha=0.1,label="Doelbereik 4–8 mmol/L")
ax1.set_ylabel("Glucose (mmol/L)")
ax1.legend(loc="upper right")
ax1.grid(True,alpha=0.3)

# Hydrocortison
ax2.plot(df["tijd"],df["hydrocortison"],color="orange",label="Hydrocortison (rel.)")
for t,mg in doses:
    ax2.axvline(t,color="gray",linestyle="--",alpha=0.3)
ax2.set_ylabel("Relatieve [HC]")
ax2.set_xlabel("Tijd (vandaag)")
ax2.legend(loc="upper right")
ax2.grid(True,alpha=0.3)

st.pyplot(fig)

# ------------------------------------
# HUIDIGE STATUS & ADVIES
# ------------------------------------
latest=df.iloc[-1]
glu_now=latest["glucose"]
alert="GREEN"; msg="Glucose binnen normaal bereik."
if glu_now<3.5: alert,msg="RED","Hypoglycemie – neem extra stressdosis en raadpleeg arts."
elif glu_now<4.5: alert,msg="AMBER","Lage glucose – mogelijke hydrocortison-deficiëntie."
elif glu_now>9: alert,msg="AMBER","Hoge glucose – stress of voeding."
elif glu_now>12: alert,msg="RED","Zeer hoog – contacteer arts."

st.subheader("🔔 Huidige alarmstatus")
if alert=="RED": st.error(msg)
elif alert=="AMBER": st.warning(msg)
else: st.success(msg)

# ------------------------------------
# DISCLAIMER
# ------------------------------------
st.caption("⚠️ Educatief hulpmiddel – geen medisch hulpmiddel volgens Verordening (EU) 2017/745 (MDR).")
