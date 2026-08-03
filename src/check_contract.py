from src.option_chain import load_instruments

for item in load_instruments():

    if item.get("token") == "1138612":
        print(item)
        break
