import streamlit as st

# Titel van de app
st.title("Is Fransje dom?")

# Vraag weergeven
keuze = st.radio("Maak een keuze:", ("Ja", "Nee"))

# Antwoord tonen gebaseerd op de keuze
if keuze == "Ja":
    st.write(
        "Hee dat is niet lief, want ze is ook niet dom, alleen minder slim dan haar broer"
    )
else:
    st.write(
        "Inderdaad, Fransje is niet dom, ze is alleen minder slim dan haar broer"
    )
