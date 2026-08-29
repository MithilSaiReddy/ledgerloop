"""Indian GST state codes (2-digit) -> name, and reverse lookup.

Used to normalise `place_of_supply` on an invoice and compare it against the
owner's home state so the ledger can tell intra- from inter-state supplies
(CGST+SGST vs IGST).
"""

# 2-digit GST state code -> full state/UT name
STATE_CODES: dict[str, str] = {
    "01": "Jammu & Kashmir", "02": "Himachal Pradesh", "03": "Punjab",
    "04": "Chandigarh", "05": "Uttarakhand", "06": "Haryana",
    "07": "Delhi", "08": "Rajasthan", "09": "Uttar Pradesh",
    "10": "Bihar", "11": "Sikkim", "12": "Arunachal Pradesh",
    "13": "Nagaland", "14": "Manipur", "15": "Mizoram",
    "16": "Tripura", "17": "Meghalaya", "18": "Assam",
    "19": "West Bengal", "20": "Jharkhand", "21": "Odisha",
    "22": "Chhattisgarh", "23": "Madhya Pradesh", "24": "Gujarat",
    "26": "Dadra & Nagar Haveli and Daman & Diu", "27": "Maharashtra",
    "29": "Karnataka", "30": "Goa", "31": "Lakshadweep",
    "32": "Kerala", "33": "Tamil Nadu", "34": "Puducherry",
    "35": "Andaman & Nicobar", "36": "Telangana", "37": "Andhra Pradesh",
    "38": "Ladakh",
}

# state/UT name (lowercased) -> 2-digit code
_STATE_NAME_TO_CODE: dict[str, str] = {
    name.lower(): code for code, name in STATE_CODES.items()
}
_STATE_NAME_TO_CODE.update({
    "dadra and nagar haveli and daman and diu": "26",
})

# Short/common names sometimes written on invoices -> code
_ALIASES_TO_CODE: dict[str, str] = {
    "jammu & kashmir": "01", "j&k": "01", "jammu": "01",
    "hp": "02", "himachal": "02",
    "punjab": "03", "chandigarh": "04", "uttarakhand": "05",
    "haryana": "06", "delhi": "07", "nct of delhi": "07", "new delhi": "07",
    "rajasthan": "08", "up": "09", "uttar pradesh": "09", "bihar": "10",
    "sikkim": "11", "arunachal pradesh": "12", "arunachal": "12",
    "nagaland": "13", "manipur": "14", "mizoram": "15", "tripura": "16",
    "meghalaya": "17", "assam": "18", "west bengal": "19", "wb": "19",
    "jharkhand": "20", "odisha": "21", "orissa": "21", "chhattisgarh": "22",
    "madhya pradesh": "23", "mp": "23", "gujarat": "24", "guj": "24",
    "maharashtra": "27", "mumbai": "27", "pune": "27",
    "karnataka": "29", "bengaluru": "29", "bangalore": "29", "kar": "29",
    "goa": "30", "lakshadweep": "31", "kerala": "32", "tamil nadu": "33",
    "tamilnadu": "33", "chennai": "33", "tn": "33", "puducherry": "34",
    "pondicherry": "34", "andaman & nicobar": "35", "andaman and nicobar": "35",
    "telangana": "36", "hyderabad": "36", "telangana (new)": "36",
    "andhra pradesh": "37", "ap": "37", "ladakh": "38",
}


def state_code_from(place_of_supply: str | None) -> str | None:
    """Extract a 2-digit GST state code from a free-text place of supply.

    Accepts '27-Maharashtra', 'Maharashtra', 'KA', 'CHENNAI', etc. Returns the
    canonical 2-digit code or None if it can't be resolved.
    """
    if not place_of_supply:
        return None
    pos = str(place_of_supply).strip()
    if not pos:
        return None

    # Leading or embedded 2-digit GST code, e.g. "27" or "27-Maharashtra".
    import re
    m = re.search(r"\b(3[0-8]|0[1-9]|2[0-6])\b", pos)
    if m and m.group(1) in STATE_CODES:
        return m.group(1)

    name = pos.lower()
    if name in _STATE_NAME_TO_CODE:
        return _STATE_NAME_TO_CODE[name]
    if name in _ALIASES_TO_CODE:
        return _ALIASES_TO_CODE[name]
    # Try a single trailing word e.g. "state-code 27" handled above; try
    # matching any contained known state name word.
    for alias, code in _ALIASES_TO_CODE.items():
        if alias in name:
            return code
    return None
