import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

BASE="https://elcidinvestments.com"
URL=f"{BASE}/investors/"

def search_elcid():
    r=requests.get(URL,headers={"User-Agent":"Mozilla/5.0"},timeout=20)
    r.raise_for_status()
    soup=BeautifulSoup(r.text,"html.parser")
    hits=[]
    for a in soup.find_all("a",href=True):
        text=a.get_text(" ",strip=True)
        href=urljoin(BASE,a["href"])
        if any(x in text.lower() for x in ["2025-26","annual report","consolidated report"]):
            hits.append((text,href))
    return list(dict.fromkeys(hits))

print("="*90)
print("PEREZ AI — OFFICIAL ELCID WEB RESEARCH")
print("="*90)
for i,(text,url) in enumerate(search_elcid(),1):
    print(f"[{i}] {text}")
    print(url)
