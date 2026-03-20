def clean_onion(onion):
    onion = onion.strip().lower()
    if onion.endswith(".onion"):
        onion = onion[:-6]
    return onion

def ensure_onion_format(onion):
    onion = clean_onion(onion)
    return onion + ".onion"