import requests

url = "http://127.0.0.1:8000/api/upload/"

files_with_types = [
    ("sap_data.csv",     "SAP"),
    ("travel_data.csv",  "TRAVEL"),
    ("utility_data.csv", "UTILITY"),
]

for filepath, source_type in files_with_types:
    with open(filepath, 'rb') as f:
        response = requests.post(
            url,
            files={'file': f},
            data={'source_type': source_type}   # <-- this was missing
        )
        print("FILE:", filepath)
        print("STATUS:", response.status_code)
        print("RESPONSE:", response.text)
        print("---------------------")